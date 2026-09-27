"""Parrainage — BlackTurf.

Règles (décision de l'exploitant, 2026-09-27) :

- le FILLEUL s'inscrit par le lien d'un parrain : pas d'essai gratuit, mais 5 €
  de remise sur sa première facture payante (mensuelle ou annuelle) ;
- le PARRAIN reçoit 5 € de crédit dès que le filleul a réellement payé. Rien
  n'est jamais versé : le crédit est posé sur le solde client Stripe du parrain,
  et Stripe le déduit seul de l'abonnement qu'il prend ou de sa prochaine
  mensualité. Stripe n'impute jamais plus que le montant d'une facture : au-delà,
  le reste est reporté au mois suivant (plafond « un mois offert au plus ») ;
- tout compte à l'adresse confirmée peut parrainer, abonné ou non.

Pourquoi c'est inexploitable par construction : la récompense n'existe qu'après
un paiement réel du filleul d'au moins « prix − 5 € », toujours supérieur aux
5 € de crédit. Se parrainer soi-même avec un faux compte coûte donc plus cher
que ce que cela rapporte. Les deux seules façons de récupérer l'argent — le
remboursement et la contestation bancaire — reprennent le crédit
(`sur_remboursement`). S'y ajoutent les verrous d'usage : parrain fixé à la
création du compte seulement, un seul parrain par compte, pas d'auto-parrainage,
carte du filleul déjà vue sur un autre compte = récompense refusée.

Comme `services.abonnements`, rien ici ne doit faire échouer un webhook Stripe :
les erreurs sont consignées, et la récompense restée `en_attente` est retentée
au paiement suivant du filleul.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
import stripe
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.config import get_settings
from db.models import CarteConnue, Parrainage, User

settings = get_settings()
log = structlog.get_logger()

REMISE_CENTS = 500
# Identifiant FIXE : le coupon est créé une fois chez Stripe, au premier besoin,
# puis réutilisé. Aucune manipulation dans le tableau de bord Stripe.
COUPON_FILLEUL_ID = "BLACKTURF_PARRAINAGE_5"
# Sans voyelles ni caractères ambigus (0/O, 1/I/L) : le code se dicte et ne forme
# pas de mot par hasard.
ALPHABET = "BCDFGHJKMNPQRSTVWXZ23456789"
LONGUEUR_CODE = 8
# Au-delà, un remboursement sans facture identifiable n'est plus rattaché au
# parrainage (cf. `sur_remboursement`).
FENETRE_REPRISE = timedelta(days=60)


def normaliser_code(code: Optional[str]) -> str:
    return "".join(ch for ch in (code or "").upper() if ch.isalnum())[:12]


def _nouveau_code() -> str:
    return "".join(secrets.choice(ALPHABET) for _ in range(LONGUEUR_CODE))


def lien_parrainage(code: str) -> str:
    return f"{settings.frontend_url}/inscription?parrain={code}"


def _peut_parrainer(user: Optional[User]) -> bool:
    from services.email_verification import email_confirme
    return bool(user and user.is_active and email_confirme(user))


async def code_de(user: User, db: AsyncSession) -> str:
    """Code du parrain, créé au premier appel. Commit inclus."""
    if user.code_parrain:
        return user.code_parrain
    for _ in range(10):
        code = _nouveau_code()
        pris = (await db.execute(select(User.user_id).where(User.code_parrain == code))).first()
        if pris is None:
            user.code_parrain = code
            await db.commit()
            return code
    raise RuntimeError("code de parrainage : génération impossible")


async def parrain_du_code(code: Optional[str], db: AsyncSession) -> Optional[User]:
    code = normaliser_code(code)
    if not code:
        return None
    parrain = (await db.execute(select(User).where(User.code_parrain == code))).scalar_one_or_none()
    return parrain if _peut_parrainer(parrain) else None


class CodeInvalide(ValueError):
    pass


async def rattacher_filleul(filleul: User, code: Optional[str], db: AsyncSession) -> Optional[Parrainage]:
    """Rattache un compte NEUF à son parrain. N'appelle pas `commit`.

    À n'appeler qu'à la création du compte (ou à la reprise d'une inscription
    jamais confirmée) : c'est ce qui interdit à un client existant de se faire
    parrainer après coup pour décrocher la remise.
    """
    if not normaliser_code(code):
        return None
    if filleul.parraine_par_id:
        return None  # un seul parrain, le premier
    parrain = await parrain_du_code(code, db)
    if parrain is None or parrain.user_id == filleul.user_id:
        raise CodeInvalide("Code de parrainage inconnu ou expiré.")
    filleul.parraine_par_id = parrain.user_id
    lien = Parrainage(parrain_id=parrain.user_id, filleul_id=filleul.user_id, statut="en_attente")
    db.add(lien)
    log.info("parrainage.rattache", parrain=parrain.user_id, filleul=filleul.user_id)
    return lien


async def _lien_du_filleul(filleul_id: str, db: AsyncSession) -> Optional[Parrainage]:
    return (await db.execute(
        select(Parrainage).where(Parrainage.filleul_id == filleul_id)
    )).scalar_one_or_none()


async def remise_filleul_due(user: User, db: AsyncSession) -> Optional[Parrainage]:
    """Le parrainage qui ouvre droit aux −5 € au prochain checkout, sinon None.

    Une fois la première facture payante réglée (`remise_filleul_at`), plus
    jamais : résilier puis se réabonner ne rouvre pas la remise.
    """
    if not user.parraine_par_id:
        return None
    lien = await _lien_du_filleul(user.user_id, db)
    if lien is None or lien.remise_filleul_at is not None or lien.statut != "en_attente":
        return None
    return lien


def coupon_filleul() -> str:
    """Identifiant du coupon « 5 € sur la première facture », créé s'il manque."""
    try:
        stripe.Coupon.retrieve(COUPON_FILLEUL_ID)
    except stripe.error.InvalidRequestError:
        stripe.Coupon.create(
            id=COUPON_FILLEUL_ID,
            amount_off=REMISE_CENTS,
            currency="eur",
            duration="once",
            name="Parrainage : 5 € offerts",
        )
        log.info("parrainage.coupon_cree", coupon=COUPON_FILLEUL_ID)
    return COUPON_FILLEUL_ID


def _mouvement_existant(customer: str, cle: str) -> Optional[str]:
    """Mouvement de solde déjà posé sous cette clé, s'il existe.

    La clé d'idempotence de Stripe n'est gardée que 24 h : un crédit parti chez
    Stripe mais jamais enregistré ici (coupure juste après l'appel) serait
    reposé au retry suivant, un mois plus tard. On relit donc le solde du client
    avant d'écrire. Lève si Stripe ne répond pas : dans le doute, on n'écrit rien.
    """
    for txn in stripe.Customer.list_balance_transactions(customer, limit=100).auto_paging_iter():
        if (txn.get("metadata") or {}).get("cle") == cle:
            return txn["id"]
    return None


def _crediter(client: User, montant_cents: int, cle: str, description: str, metadata: dict) -> str:
    """Écrit sur le solde client Stripe (négatif = crédit, positif = reprise).

    Jamais deux fois : relecture du solde (`_mouvement_existant`) + clé
    d'idempotence pour deux webhooks simultanés.
    """
    deja = _mouvement_existant(client.stripe_customer_id, cle)
    if deja:
        return deja
    txn = stripe.Customer.create_balance_transaction(
        client.stripe_customer_id,
        amount=montant_cents,
        currency="eur",
        description=description,
        metadata={**metadata, "cle": cle},
        idempotency_key=cle,
    )
    return txn["id"]


async def _client_stripe(user: User, db: AsyncSession) -> str:
    """Client Stripe du parrain, créé s'il n'en a pas encore (compte gratuit) :
    le crédit l'attend et sera déduit de l'abonnement qu'il prendra."""
    if not user.stripe_customer_id:
        client = stripe.Customer.create(
            email=user.email,
            name=f"{user.prenom or ''} {user.nom or ''}".strip() or user.email,
            metadata={"user_id": user.user_id},
        )
        user.stripe_customer_id = client["id"]
    return user.stripe_customer_id


async def _verdict_cartes(filleul: User, lien: Parrainage, db: AsyncSession) -> Optional[str]:
    """None si la carte du filleul est bien la sienne, sinon le motif du refus.

    Lève `LookupError` si Stripe ne renvoie aucune carte : on ne tranche pas,
    la récompense reste en attente jusqu'au paiement suivant.
    """
    from api.routes.stripe_routes import _cartes_du_client, _memoriser_cartes

    cartes = _cartes_du_client({"customer": filleul.stripe_customer_id})
    if not cartes:
        raise LookupError("cartes indisponibles")
    await _memoriser_cartes(filleul, cartes, db)
    for carte in cartes:
        connue = await db.get(CarteConnue, carte["empreinte"])
        if connue is not None and connue.user_id and connue.user_id != filleul.user_id:
            return "carte_du_parrain" if connue.user_id == lien.parrain_id else "carte_autre_compte"
    return None


async def sur_paiement(filleul: User, invoice: dict, db: AsyncSession) -> None:
    """Facture payante réglée par `filleul` : valide son parrainage s'il y en a un.

    N'appelle pas `commit` (transaction du webhook). Ne lève jamais.
    """
    try:
        await _sur_paiement(filleul, invoice, db)
    except Exception as e:  # noqa: BLE001
        log.error("parrainage.paiement_erreur", filleul=filleul.user_id, error=str(e)[:200])


async def _sur_paiement(filleul: User, invoice: dict, db: AsyncSession) -> None:
    from services.abonnements import journaliser

    if not filleul.parraine_par_id or (invoice.get("amount_paid") or 0) <= 0:
        return
    lien = await _lien_du_filleul(filleul.user_id, db)
    if lien is None or lien.statut != "en_attente":
        return

    maintenant = datetime.now(timezone.utc)
    # La remise ne vaut que pour la toute première facture payante, quoi qu'il
    # advienne ensuite de la récompense du parrain.
    if lien.remise_filleul_at is None:
        lien.remise_filleul_at = maintenant

    parrain = await db.get(User, lien.parrain_id) if lien.parrain_id else None
    motif: Optional[str] = None
    if not _peut_parrainer(parrain):
        motif = "parrain_inactif"
    else:
        try:
            motif = await _verdict_cartes(filleul, lien, db)
        except LookupError:
            lien.motif = "cartes_indisponibles"
            log.warning("parrainage.cartes_indisponibles", filleul=filleul.user_id)
            return

    if motif:
        lien.statut = "refuse"
        lien.motif = motif
        # Carte déjà connue ailleurs : c'est un ancien client qui a rouvert un
        # compte pour la remise. Elle lui est refacturée sur sa facture suivante
        # (solde positif), sinon on pourrait l'obtenir en boucle, un compte par mois.
        if motif != "parrain_inactif" and filleul.stripe_customer_id and settings.stripe_secret_key:
            try:
                _crediter(filleul, REMISE_CENTS, f"parrainage-remise-reprise-{lien.parrainage_id}",
                          "Remise de parrainage non applicable : carte déjà utilisée sur un autre compte",
                          {"parrainage_id": lien.parrainage_id})
            except Exception as e:  # noqa: BLE001
                log.error("parrainage.reprise_remise_echouee", filleul=filleul.user_id, error=str(e)[:200])
        await journaliser(db, "parrainage_refuse", parrain, None,
                          detail={"filleul": filleul.email, "motif": motif})
        log.warning("parrainage.refuse", parrain=lien.parrain_id, filleul=filleul.user_id, motif=motif)
        return

    if not settings.stripe_secret_key:
        return
    try:
        await _client_stripe(parrain, db)
        txn = _crediter(
            parrain, -REMISE_CENTS, f"parrainage-credit-{lien.parrainage_id}",
            "Parrainage BlackTurf : 5 € déduits de votre prochain abonnement",
            {"parrainage_id": lien.parrainage_id, "filleul_id": filleul.user_id},
        )
    except Exception as e:  # noqa: BLE001
        # Crédit non posé : le parrainage reste en attente et sera retenté au
        # prochain paiement du filleul. La clé d'idempotence garantit qu'un
        # crédit parti malgré l'erreur ne sera pas doublé.
        lien.motif = "credit_en_echec"
        log.error("parrainage.credit_echoue", parrain=parrain.user_id, error=str(e)[:200])
        return

    lien.statut = "valide"
    lien.motif = None
    lien.valide_at = maintenant
    lien.stripe_invoice_id = invoice.get("id")
    lien.credit_cents = REMISE_CENTS
    lien.stripe_credit_txn_id = txn
    await journaliser(db, "parrainage_valide", parrain, None, montant_cents=REMISE_CENTS,
                      detail={"filleul": filleul.email, "facture": invoice.get("id")})
    log.info("parrainage.valide", parrain=parrain.user_id, filleul=filleul.user_id)
    await _prevenir_parrain(parrain, filleul)


async def _prevenir_parrain(parrain: User, filleul: User) -> None:
    try:
        from services.alerts import send_email
        from services.email_compte import parrainage_credite
        html, texte = parrainage_credite(parrain.prenom, filleul.prenom, f"{settings.frontend_url}/profil#parrainage")
        await send_email(to=parrain.email, subject="BlackTurf — 5 € offerts grâce à votre parrainage",
                         html=html, text=texte)
    except Exception as e:  # noqa: BLE001
        log.warning("parrainage.email_echoue", parrain=parrain.user_id, error=str(e)[:120])


async def sur_remboursement(charge: dict, db: AsyncSession, motif: str) -> None:
    """Le paiement qui a validé un parrainage est remboursé ou contesté : le
    crédit du parrain est repris. N'appelle pas `commit`. Ne lève jamais."""
    try:
        await _sur_remboursement(charge, db, motif)
    except Exception as e:  # noqa: BLE001
        log.error("parrainage.reprise_erreur", charge=charge.get("id"), error=str(e)[:200])


async def _sur_remboursement(charge: dict, db: AsyncSession, motif: str) -> None:
    from services.abonnements import journaliser

    if charge.get("object") == "dispute":
        # Une contestation porte l'identifiant du paiement, pas le paiement.
        cible = charge.get("charge")
        if isinstance(cible, str):
            if not settings.stripe_secret_key:
                return
            cible = stripe.Charge.retrieve(cible)
        charge = cible or {}

    lien: Optional[Parrainage] = None
    facture = charge.get("invoice")
    if isinstance(facture, dict):
        facture = facture.get("id")
    if facture:
        lien = (await db.execute(
            select(Parrainage).where(Parrainage.stripe_invoice_id == facture)
        )).scalar_one_or_none()
    if lien is None and charge.get("customer"):
        # Versions récentes de l'API : la facture n'est plus portée par le
        # paiement. On retombe sur le client, dans une fenêtre courte.
        filleul = (await db.execute(
            select(User).where(User.stripe_customer_id == charge["customer"])
        )).scalar_one_or_none()
        if filleul is not None:
            lien = await _lien_du_filleul(filleul.user_id, db)
            if lien is not None and lien.valide_at is not None:
                valide = lien.valide_at if lien.valide_at.tzinfo else lien.valide_at.replace(tzinfo=timezone.utc)
                # Seul le PREMIER paiement compte : un remboursement d'une
                # mensualité ultérieure ne touche pas au crédit du parrain.
                cree = charge.get("created")
                premier = cree is None or (
                    datetime.fromtimestamp(cree, tz=timezone.utc) <= valide + timedelta(hours=6))
                if datetime.now(timezone.utc) - valide > FENETRE_REPRISE or not premier:
                    lien = None
    if lien is None or lien.statut != "valide":
        return

    parrain = await db.get(User, lien.parrain_id) if lien.parrain_id else None
    if parrain is not None and parrain.stripe_customer_id and settings.stripe_secret_key:
        try:
            _crediter(parrain, lien.credit_cents or REMISE_CENTS,
                      f"parrainage-reprise-{lien.parrainage_id}",
                      "Parrainage annulé : paiement du filleul remboursé",
                      {"parrainage_id": lien.parrainage_id})
        except Exception as e:  # noqa: BLE001
            log.error("parrainage.reprise_echouee", parrain=parrain.user_id, error=str(e)[:200])
            return  # le webhook suivant (ou un rejeu) retentera
    lien.statut = "annule"
    lien.motif = motif
    await journaliser(db, "parrainage_annule", parrain, None, montant_cents=lien.credit_cents,
                      detail={"motif": motif, "charge": charge.get("id")})
    log.warning("parrainage.annule", parrain=lien.parrain_id, filleul=lien.filleul_id, motif=motif)


async def filleul_confirme(filleul: User, db: AsyncSession) -> None:
    """Le filleul vient de confirmer son adresse : le parrain est prévenu qu'un
    ami l'a rejoint, et de ce qui reste à faire pour que ses 5 € tombent.
    Ne lève jamais : la confirmation d'adresse ne doit pas en dépendre."""
    try:
        if not filleul.parraine_par_id:
            return
        lien = await _lien_du_filleul(filleul.user_id, db)
        parrain = await db.get(User, filleul.parraine_par_id)
        if lien is None or lien.statut != "en_attente" or not _peut_parrainer(parrain):
            return
        from services.alerts import send_email
        from services.email_compte import parrainage_inscrit
        html, texte = parrainage_inscrit(parrain.prenom, filleul.prenom, f"{settings.frontend_url}/profil#parrainage")
        await send_email(to=parrain.email, subject="BlackTurf — Un ami a rejoint BlackTurf grâce à vous",
                         html=html, text=texte)
    except Exception as e:  # noqa: BLE001
        log.warning("parrainage.email_inscription_echoue", filleul=filleul.user_id, error=str(e)[:120])


def _credit_stripe(user: User) -> Optional[int]:
    """Crédit restant sur le solde Stripe, en centimes. None si illisible."""
    if not user.stripe_customer_id or not settings.stripe_secret_key:
        return 0
    try:
        solde = stripe.Customer.retrieve(user.stripe_customer_id).get("balance") or 0
        return max(0, -int(solde))
    except Exception as e:  # noqa: BLE001
        log.warning("parrainage.solde_illisible", user_id=user.user_id, error=str(e)[:120])
        return None


# Étape fine d'un parrainage, pour le suivi affiché au parrain. Le `statut` en
# base ne connaît que quatre états ; le parrain, lui, veut savoir ce qui manque.
ETAPES = {
    "email_a_confirmer": "Inscrit — doit confirmer son adresse e-mail",
    "attente_paiement": "En attente du premier paiement de votre filleul",
    "paiement_en_cours": "Abonnement en cours de paiement",
    "verification": "Paiement reçu — vos 5 € arrivent sous peu",
    "credite": "Abonné — 5 € déduits de votre prochaine facture",
    "refuse": "Non éligible — carte déjà utilisée sur un autre compte",
    "parrain_inactif": "Non éligible",
    "annule": "Paiement remboursé ou contesté — crédit annulé",
}


def _etape(lien: Parrainage, filleul: Optional[User], abonne: bool) -> str:
    from services.email_verification import email_confirme
    if lien.statut == "valide":
        return "credite"
    if lien.statut == "annule":
        return "annule"
    if lien.statut == "refuse":
        return "parrain_inactif" if lien.motif == "parrain_inactif" else "refuse"
    if lien.remise_filleul_at is not None:
        return "verification"
    if filleul is not None and not email_confirme(filleul):
        return "email_a_confirmer"
    return "paiement_en_cours" if abonne else "attente_paiement"


async def resume(user: User, db: AsyncSession) -> dict:
    """Tout ce qu'affiche le bloc « Parrainage » du profil."""
    from db.models import Subscription

    code = await code_de(user, db)
    liens = (await db.execute(
        select(Parrainage, User)
        .join(User, User.user_id == Parrainage.filleul_id, isouter=True)
        .where(Parrainage.parrain_id == user.user_id)
        .order_by(Parrainage.created_at.desc())
    )).all()
    ids = [lien.filleul_id for lien, _ in liens if lien.filleul_id]
    abonnes = set((await db.execute(
        select(Subscription.user_id).where(Subscription.user_id.in_(ids))
    )).scalars().all()) if ids else set()

    filleuls = []
    for lien, filleul in liens:
        etape = _etape(lien, filleul, lien.filleul_id in abonnes)
        filleuls.append({
            # Prénom seulement : jamais l'e-mail d'un tiers.
            "prenom": ((filleul.prenom if filleul else None) or "Un ami").split(" ")[0][:20],
            "statut": lien.statut,
            "etape": etape,
            "etape_libelle": ETAPES[etape],
            "depuis": lien.created_at,
            "credite_le": lien.valide_at,
        })
    valides = sum(1 for lien, _ in liens if lien.statut == "valide")

    remise = await remise_filleul_due(user, db)
    return {
        "code": code,
        "lien": lien_parrainage(code),
        "remise_cents": REMISE_CENTS,
        "filleuls": filleuls,
        "en_attente": sum(1 for lien, _ in liens if lien.statut == "en_attente"),
        "annules": sum(1 for lien, _ in liens if lien.statut in ("refuse", "annule")),
        "valides": valides,
        "gagne_cents": valides * REMISE_CENTS,
        "credit_disponible_cents": _credit_stripe(user),
        "remise_filleul_disponible": remise is not None,
    }

