"""Revenus lus DIRECTEMENT chez Stripe — la source de vérité comptable.

Pourquoi ce module (2026-09-25) : l'écran « Revenus » lisait le journal interne
`subscription_events.paiement_recu`. L'exploitant y voyait 19 € quand deux
abonnés avaient payé. Deux trous, prouvés dans le code :

  1. avant le 2026-08-27 (commit 15309ab), le webhook ne journalisait un
     paiement que s'il RÉTABLISSAIT un accès coupé : premiers paiements et
     renouvellements ordinaires n'ont jamais laissé de trace ;
  2. Stripe ne garantit pas l'ordre des webhooks : un `invoice.payment_succeeded`
     reçu avant `customer.subscription.created` ne trouvait pas l'abonnement et
     repartait sans rien écrire (corrigé dans `stripe_routes` le même jour).

Un chiffre qui sert à une déclaration de revenus ne peut pas dépendre d'un
journal à trous. On interroge donc Stripe :

  · `Charge`             — chaque encaissement réussi, avec sa transaction de
                           solde (frais Stripe et net réellement crédité) ;
  · `Refund`             — les remboursements, datés du jour où ils ont eu lieu ;
  · `Payout`             — les virements vers le compte bancaire.

Tous les montants sont en CENTIMES, TTC tels qu'encaissés. Les mois sont ceux
de Paris : une carte débitée le 31 à 23 h 30 appartient au mois du 31.

Les appels Stripe sont synchrones (bibliothèque officielle) : le module expose
une fonction pure `collecter()` que l'API exécute dans un thread, et un cache
court en mémoire pour qu'un écran rafraîchi toutes les 30 s ne déclenche pas
une pagination complète à chaque fois.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

import stripe

# Durée de vie du cache. Un paiement Stripe apparaît donc au plus 60 s après
# avoir été encaissé ; le bouton « Actualiser » de l'écran force la relecture.
TTL_CACHE_S = 60


def _g(obj: Any, *chemin: str, defaut: Any = None) -> Any:
    """Lecture tolérante d'un objet Stripe (dict) ou d'un identifiant non déplié."""
    cur = obj
    for cle in chemin:
        if cur is None:
            return defaut
        if isinstance(cur, dict):
            cur = cur.get(cle)
        else:
            cur = getattr(cur, cle, None)
    return defaut if cur is None else cur


def _id(v: Any) -> Optional[str]:
    if isinstance(v, str):
        return v
    return _g(v, "id")


@dataclass
class Encaissement:
    charge_id: str
    cree_le: datetime
    montant_cents: int
    rembourse_cents: int
    frais_cents: int
    net_cents: int
    devise: str
    client_id: Optional[str]
    email: Optional[str]
    facture_id: Optional[str]
    recu_url: Optional[str]
    description: Optional[str]


@dataclass
class Remboursement:
    refund_id: str
    charge_id: Optional[str]
    cree_le: datetime
    montant_cents: int
    net_cents: int
    email: Optional[str]


@dataclass
class Virement:
    payout_id: str
    arrivee_le: datetime
    montant_cents: int
    statut: str


@dataclass
class Grand_livre:
    encaissements: list[Encaissement] = field(default_factory=list)
    remboursements: list[Remboursement] = field(default_factory=list)
    virements: list[Virement] = field(default_factory=list)
    lu_le: float = 0.0


def _date(ts: Any) -> datetime:
    return datetime.fromtimestamp(int(ts or 0), tz=timezone.utc)


def _pages(ressource: Any, **params: Any) -> Iterable[Any]:
    """Toutes les pages d'une liste Stripe (pagination automatique)."""
    return ressource.list(limit=100, **params).auto_paging_iter()


def _encaissement(ch: Any) -> Optional[Encaissement]:
    # Seul un débit RÉUSSI et CAPTURÉ est de l'argent encaissé : un échec, une
    # autorisation non capturée ou un litige en cours ne le sont pas.
    if _g(ch, "status") != "succeeded" or not _g(ch, "paid") or _g(ch, "captured") is False:
        return None
    bt = _g(ch, "balance_transaction")
    montant = int(_g(ch, "amount_captured", defaut=None) or _g(ch, "amount", defaut=0))
    frais = int(_g(bt, "fee", defaut=0)) if isinstance(bt, dict) else 0
    net = int(_g(bt, "net", defaut=montant - frais)) if isinstance(bt, dict) else montant - frais
    client = _g(ch, "customer")
    email = (
        _g(ch, "billing_details", "email")
        or _g(ch, "receipt_email")
        or (_g(client, "email") if isinstance(client, dict) else None)
    )
    return Encaissement(
        charge_id=_g(ch, "id"),
        cree_le=_date(_g(ch, "created")),
        montant_cents=montant,
        rembourse_cents=int(_g(ch, "amount_refunded", defaut=0)),
        frais_cents=frais,
        net_cents=net,
        devise=str(_g(ch, "currency", defaut="eur")).lower(),
        client_id=_id(client),
        email=email,
        facture_id=_id(_g(ch, "invoice")),
        recu_url=_g(ch, "receipt_url"),
        description=_g(ch, "description"),
    )


def collecter(cle: str, depuis_ts: Optional[int] = None) -> Grand_livre:
    """Lit chez Stripe tout ce qui a été encaissé, remboursé et viré.

    `depuis_ts` borne la lecture des remboursements et virements. Les débits sont
    lus depuis l'ouverture du compte : c'est ce qui permet de savoir si un
    paiement est le PREMIER d'un client (« nouveau ») ou une échéance suivante.
    Le volume d'un abonnement à quelques euros reste de quelques centaines de
    lignes par an — une pagination complète coûte quelques appels.
    """
    stripe.api_key = cle
    livre = Grand_livre(lu_le=time.time())

    for ch in _pages(stripe.Charge, expand=["data.balance_transaction", "data.customer"]):
        e = _encaissement(ch)
        if e is not None:
            livre.encaissements.append(e)

    params = {"created": {"gte": depuis_ts}} if depuis_ts else {}
    for rf in _pages(stripe.Refund, expand=["data.balance_transaction", "data.charge"], **params):
        if _g(rf, "status") not in ("succeeded", "pending"):
            continue
        bt = _g(rf, "balance_transaction")
        montant = int(_g(rf, "amount", defaut=0))
        charge = _g(rf, "charge")
        livre.remboursements.append(Remboursement(
            refund_id=_g(rf, "id"),
            charge_id=_id(charge),
            cree_le=_date(_g(rf, "created")),
            montant_cents=montant,
            # Le net d'un remboursement est négatif côté solde (argent rendu).
            net_cents=int(_g(bt, "net", defaut=-montant)) if isinstance(bt, dict) else -montant,
            email=_g(charge, "billing_details", "email") if isinstance(charge, dict) else None,
        ))

    for po in _pages(stripe.Payout, **({"arrival_date": {"gte": depuis_ts}} if depuis_ts else {})):
        if _g(po, "status") in ("canceled", "failed"):
            continue
        livre.virements.append(Virement(
            payout_id=_g(po, "id"),
            arrivee_le=_date(_g(po, "arrival_date")),
            montant_cents=int(_g(po, "amount", defaut=0)),
            statut=str(_g(po, "status", defaut="")),
        ))

    livre.encaissements.sort(key=lambda e: e.cree_le)
    return livre


# ─────────────────────────── cache en mémoire ────────────────────────────
_verrou = threading.Lock()
_cache: dict[Any, Grand_livre] = {}


def lire(cle: str, depuis_ts: Optional[int], forcer: bool = False) -> Grand_livre:
    """`collecter` avec un cache de `TTL_CACHE_S` secondes par fenêtre."""
    k = (cle[-6:], depuis_ts)
    with _verrou:
        en_cache = _cache.get(k)
        if en_cache and not forcer and time.time() - en_cache.lu_le < TTL_CACHE_S:
            return en_cache
    livre = collecter(cle, depuis_ts)
    with _verrou:
        _cache[k] = livre
    return livre


def vider_cache() -> None:
    with _verrou:
        _cache.clear()
