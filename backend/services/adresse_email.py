"""Une adresse saisie à l'inscription doit pouvoir RECEVOIR du courrier.

Le contrôle de forme (`EmailStr`) dit seulement que la chaîne ressemble à une
adresse : « testturf@yopmail.com » et « jean@gmial.com » le passent tous les
deux. Le premier est une boîte jetable que personne ne relève, le second un
domaine qui n'existe pas. Dans les deux cas le lien de confirmation part dans le
vide, et le compte reste là — c'est exactement la ligne « TEST TEST » constatée
en admin le 04/09.

Trois filtres, posés AVANT la création du compte :

1. **boîtes jetables** — liste de domaines connus (`data/domaines_jetables.txt`).
   Elles s'ouvrent sans mot de passe et expirent en quelques minutes : le mail de
   confirmation y meurt, et l'essai Stripe s'y rouvre à volonté, une adresse
   bidon par compte ;
2. **fautes de frappe sur les grands fournisseurs** — « gmial.com » répond au
   DNS (c'est un domaine squatté) et passerait donc le filtre suivant, alors
   qu'aucune inscription légitime ne s'y termine. Refus avec la correction ;
   les domaines réels mais mal choisis (laposte.fr au lieu de laposte.net) sont,
   eux, seulement suggérés — jamais refusés ;
3. **domaine capable de relever du courrier** — interrogation DNS des MX (repli
   sur A/AAAA, RFC 5321 §5.1). Un domaine inexistant ou déclarant explicitement
   n'accepter aucun mail (« null MX », RFC 7505) est refusé sur-le-champ.

Le contrôle DNS échoue OUVERT : si notre propre résolveur ne répond pas, on
laisse passer plutôt que de fermer l'inscription à tout le monde le temps d'une
panne — le mail de confirmation reste, lui, obligatoire pour ouvrir le compte.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Optional

import structlog

log = structlog.get_logger()

_FICHIER_JETABLES = Path(__file__).parent / "data" / "domaines_jetables.txt"

# Le DNS est interrogé au clavier du visiteur : au-delà de 3 s il vaut mieux
# laisser passer que faire attendre devant un formulaire figé.
TIMEOUT_DNS = float(os.getenv("BT_TIMEOUT_DNS", "3"))
# Une zone MX ne bouge pas d'une heure à l'autre ; ce cache évite une requête DNS
# par tentative d'inscription (et absorbe le bourrage d'un robot).
TTL_CACHE_DNS = 6 * 3600

_jetables: Optional[frozenset[str]] = None
_cache_mx: dict[str, tuple[float, bool]] = {}

# Fautes de frappe qui ne désignent AUCUN fournisseur : « gmial.com » est un
# domaine squatté, pas une boîte. Il répond au DNS — le contrôle MX plus bas le
# laisserait donc passer — mais aucune inscription légitime ne s'y termine, et
# l'adresse visée, elle, ne recevra jamais rien. Refus direct, avec la correction.
_FAUTES_BLOQUANTES = {
    "gmial.com": "gmail.com", "gmai.com": "gmail.com", "gmil.com": "gmail.com",
    "gmaill.com": "gmail.com", "gnail.com": "gmail.com", "gmail.con": "gmail.com",
    "gmail.cm": "gmail.com", "gmail.co": "gmail.com", "gamil.com": "gmail.com",
    "gmail.fr": "gmail.com",
    "hotmial.com": "hotmail.com", "hotmai.com": "hotmail.com",
    "hotmil.com": "hotmail.com", "hotmail.con": "hotmail.com",
    "hotmail.co": "hotmail.com", "hotmaill.com": "hotmail.com",
    "outlok.com": "outlook.com", "outloo.com": "outlook.com",
    "outlook.con": "outlook.com", "outlook.co": "outlook.com",
    "yaho.fr": "yahoo.fr", "yahho.fr": "yahoo.fr", "yahou.fr": "yahoo.fr",
    "yahoo.con": "yahoo.com", "yaoo.com": "yahoo.com",
    "orang.fr": "orange.fr", "oranges.fr": "orange.fr",
    "wanado.fr": "wanadoo.fr", "wanadoo.com": "wanadoo.fr",
    "fre.fr": "free.fr", "fee.fr": "free.fr",
}

# Domaines BIEN RÉELS, mais qui ne distribuent pas de boîte grand public : La
# Poste et SFR relèvent leur courrier d'entreprise sur ceux-là. On ne refuse donc
# rien ; la correction n'est proposée que si le DNS a déjà tranché contre eux.
_SUGGESTIONS_SEULES = {
    "laposte.fr": "laposte.net",
    "laposte.com": "laposte.net",
    "sfr.com": "sfr.fr",
}


class AdresseRefusee(ValueError):
    """Adresse rejetée à la saisie. `message` est écrit pour être affiché tel quel."""

    def __init__(self, message: str, motif: str):
        super().__init__(message)
        self.message = message
        self.motif = motif  # « jetable » / « domaine_injoignable » — pour les logs


def normaliser(adresse: str) -> str:
    """Blancs retirés, casse abaissée.

    Le domaine est insensible à la casse par la norme ; la partie locale ne l'est
    en théorie pas, mais aucun fournisseur grand public ne distingue Jean@ de
    jean@. Normaliser évite deux comptes pour une seule boîte.
    """
    return (adresse or "").strip().lower()


def domaine_de(adresse: str) -> str:
    return normaliser(adresse).rpartition("@")[2]


def _charger_jetables() -> frozenset[str]:
    global _jetables
    if _jetables is not None:
        return _jetables
    domaines: set[str] = set()
    try:
        for ligne in _FICHIER_JETABLES.read_text(encoding="utf-8").splitlines():
            ligne = ligne.split("#", 1)[0].strip().lower()
            if ligne:
                domaines.add(ligne)
    except OSError as e:  # fichier absent d'une image mal construite : on n'écroule rien
        log.warning("adresse_email.liste_jetables_illisible", error=str(e))
    extra = os.getenv("BT_DOMAINES_JETABLES_EXTRA", "")
    domaines.update(d.strip().lower() for d in extra.split(",") if d.strip())
    _jetables = frozenset(domaines)
    return _jetables


def est_jetable(domaine: str) -> bool:
    """Vrai pour le domaine listé ET pour ses sous-domaines.

    Plusieurs services distribuent des adresses en « n'importe.quoi.domaine » :
    ne comparer que la chaîne entière laisserait passer toute la famille.
    """
    domaine = normaliser(domaine)
    if not domaine:
        return False
    listes = _charger_jetables()
    morceaux = domaine.split(".")
    return any(".".join(morceaux[i:]) in listes for i in range(len(morceaux)))


def suggestion_orthographe(domaine: str) -> Optional[str]:
    domaine = normaliser(domaine)
    return _FAUTES_BLOQUANTES.get(domaine) or _SUGGESTIONS_SEULES.get(domaine)


def controle_dns_actif() -> bool:
    """Lu à CHAQUE appel : la suite de tests et l'exploitation doivent pouvoir
    l'éteindre sans réimporter le module."""
    return os.getenv("BT_CONTROLE_DNS", "1").strip().lower() not in ("0", "false", "no")


async def _interroger_mx(domaine: str) -> Optional[bool]:
    """True = le domaine relève du courrier, False = non, None = indécidable.

    None couvre tout ce qui ne prouve rien contre le visiteur : dnspython absent,
    résolveur muet, délai dépassé.
    """
    try:
        import dns.asyncresolver
        import dns.exception
        import dns.resolver
    except ImportError:  # pragma: no cover - dnspython est dans requirements.txt
        log.warning("adresse_email.dnspython_absent")
        return None

    resolveur = dns.asyncresolver.Resolver()
    resolveur.lifetime = TIMEOUT_DNS
    resolveur.timeout = TIMEOUT_DNS

    try:
        reponse = await resolveur.resolve(domaine, "MX")
        # « null MX » (RFC 7505) : un MX unique à « . » déclare que ce domaine
        # n'accepte AUCUN e-mail. C'est un refus explicite, pas une absence.
        cibles = [str(r.exchange).rstrip(".") for r in reponse]
        return any(cibles)
    except dns.resolver.NXDOMAIN:
        return False  # le domaine n'existe pas du tout
    except dns.resolver.NoAnswer:
        pass  # pas de MX : repli légitime sur l'adresse du domaine (RFC 5321)
    except (dns.exception.Timeout, dns.resolver.NoNameservers, dns.resolver.LifetimeTimeout):
        return None
    except dns.exception.DNSException as e:
        log.warning("adresse_email.dns_erreur", domaine=domaine, error=str(e))
        return None

    for type_enreg in ("A", "AAAA"):
        try:
            await resolveur.resolve(domaine, type_enreg)
            return True
        except (dns.resolver.NoAnswer, dns.resolver.NXDOMAIN):
            continue
        except dns.exception.DNSException:
            return None
    return False


async def domaine_recoit_du_courrier(domaine: str) -> Optional[bool]:
    """Même réponse que `_interroger_mx`, mais mise en cache le temps de TTL_CACHE_DNS.

    Les verdicts incertains (None) ne sont jamais mémorisés : une panne de
    résolveur ne doit pas se figer en autorisation pour six heures.
    """
    domaine = normaliser(domaine)
    if not domaine:
        return False
    fige = _cache_mx.get(domaine)
    if fige and (time.monotonic() - fige[0]) < TTL_CACHE_DNS:
        return fige[1]
    verdict = await _interroger_mx(domaine)
    if verdict is not None:
        _cache_mx[domaine] = (time.monotonic(), verdict)
    return verdict


def vider_cache() -> None:
    """Utilisé par les tests, et disponible en console si une zone DNS vient de changer."""
    _cache_mx.clear()
    global _jetables
    _jetables = None


async def controler(adresse: str) -> str:
    """Renvoie l'adresse normalisée, ou lève `AdresseRefusee`."""
    adresse = normaliser(adresse)
    domaine = domaine_de(adresse)
    if not domaine or "." not in domaine:
        raise AdresseRefusee("Adresse e-mail invalide.", "forme")

    if est_jetable(domaine):
        raise AdresseRefusee(
            "Les adresses e-mail jetables ne sont pas acceptées. Indiquez l'adresse "
            "que vous relevez vraiment : c'est là que partent la confirmation, vos "
            "alertes et vos factures.",
            "jetable",
        )

    correction = _FAUTES_BLOQUANTES.get(domaine)
    if correction:
        raise AdresseRefusee(
            f"« {domaine} » ressemble à une faute de frappe : vouliez-vous écrire "
            f"« {correction} » ? Cette adresse ne recevrait jamais votre lien de "
            "confirmation.",
            "faute_de_frappe",
        )

    if controle_dns_actif():
        recoit = await domaine_recoit_du_courrier(domaine)
        if recoit is False:
            propose = suggestion_orthographe(domaine)
            precision = f" Vouliez-vous écrire « {propose} » ?" if propose else ""
            raise AdresseRefusee(
                f"Le domaine « {domaine} » ne reçoit pas d'e-mail : vérifiez "
                f"l'orthographe de votre adresse.{precision}",
                "domaine_injoignable",
            )

    return adresse
