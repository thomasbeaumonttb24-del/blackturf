"""Parrainage — BlackTurf.

Règles (décision de l'exploitant, 2026-09-27) :

- le FILLEUL s'inscrit par le lien d'un parrain : pas d'essai gratuit, mais 5 €
  de remise sur sa première facture payante (mensuelle ou annuelle) ;
- le PARRAIN reçoit 5 € de crédit dès que le filleul a réellement payé. Rien
  n'est jamais versé : le crédit est posé sur le solde client Stripe du parrain,
  et Stripe le déduit seul de l'abonnement qu'il prend ou de sa prochaine
  mensualité. Stripe n'impute jamais plus que le montant d'une facture : au-delà,
  le reste est reporté au mois suivant (plafond « un mois offert au plus ») ;
- tout compte à l'adresse confirmée peut parrainer, abonné ou non ;
- PLAFOND par mois de facturation : autant de crédits qu'il en faut pour rendre
  la mensualité gratuite, pas plus — 4 en Expert (4 × 5 € ≥ 19 €), 3 en Standard
  (3 × 5 € ≥ 12 €). Au-delà, le crédit est gagné mais REPORTÉ : il est posé au
  mois suivant (`liberer_credits`), jamais perdu.

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
# Prix mensuel de chaque formule : fixe le plafond de crédits par mois
# (le nombre de parrainages qui rend la mensualité gratuite).
PRIX_MENSUEL_CENTS = {"standard": 1200, "expert": 1900}
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


async def sur_facture_reglee_par_credit(filleul: User, invoice: dict, db: AsyncSession) -> None:
    """Facture du filleul soldée par son propre crédit (il est lui-même parrain) :
    aucun argent n'a été encaissé, donc rien pour son parrain — mais sa remise
    est bel et bien consommée, sinon il la retrouverait au prochain abonnement.
    Le parrain sera crédité au premier paiement réel suivant. Ne lève jamais."""
    try:
        if not filleul.parraine_par_id or int(invoice.get("total") or 0) <= 0:
            return
        lien = await _lien_du_filleul(filleul.user_id, db)
        if lien is not None and lien.statut == "en_attente" and lien.remise_filleul_at is None:
            lien.remise_filleul_at = datetime.now(timezone.utc)
    except Exception as e:  # noqa: BLE001
        log.error("parrainage.facture_credit_erreur", filleul=filleul.user_id, error=str(e)[:200])


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
    lignes = ((invoice.get("lines") or {}).get("data") or [])
    if any(l.get("proration") or ((l.get("parent") or {}).get("subscription_item_details") or {})
           .get("proration") for l in lignes):
        # Différence au prorata d'un changement de formule : pas un premier mois
        # payé, ne valide rien (sinon 4,61 € payés créditaient 5 € au parrain).
        return
    if int(invoice.get("amount_paid") or 0) < REMISE_CENTS:
        # Facture réglée surtout par un crédit : le filleul n'a pas encore payé
        # de quoi financer la récompense ; la facture suivante validera.
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

    # Le filleul a payé avec sa carte : les 5 € sont GAGNÉS. Ils sont posés sur
    # le solde Stripe tout de suite si le plafond du mois le permet, sinon au
    # mois suivant (`liberer_credits`).
    lien.statut = "valide"
    lien.motif = None
    lien.valide_at = maintenant
    lien.stripe_invoice_id = invoice.get("id")
    lien.credit_cents = REMISE_CENTS
    await db.flush()
    await liberer_credits(parrain, db)
    reporte = lien.credit_pose_at is None
    await journaliser(db, "parrainage_valide", parrain, None, montant_cents=REMISE_CENTS,
                      detail={"filleul": filleul.email, "facture": invoice.get("id"),
                              "reporte": reporte, "motif_report": lien.motif})
    log.info("parrainage.valide", parrain=parrain.user_id, filleul=filleul.user_id, reporte=reporte)
    await _prevenir_parrain(parrain, filleul, db, reporte)


# ── Passes sans abonnement (2026-10-04) ──────────────────────────────────────
# Le parrainage vaut pour les Pass Semaine et Mois, PAS pour le Pass Jour :
# 5 € − 5 € de remise = un pass gratuit, et deux comptes qui se renverraient la
# balle obtiendraient l'accès gratuit en boucle. Un Pass Jour n'applique donc
# aucune remise, ne valide aucun parrainage et ne consomme pas la remise du
# filleul (elle reste pour un Pass Semaine, Mois ou un abonnement).
DUREES_PASS_PARRAINAGE = ("semaine", "mois")


def cartes_du_paiement(payment_intent_id: Optional[str]) -> list[dict]:
    """Carte qui a réellement payé (empreinte Stripe), lue sur le paiement.

    Un pass est un paiement unique : la carte n'est PAS enregistrée sur le
    client Stripe, `_cartes_du_client` ne la verrait pas — et le contrôle
    « carte du parrain / d'un autre compte » serait aveugle. Liste vide si
    Stripe ne répond pas (on ne tranche pas alors)."""
    if not payment_intent_id or not settings.stripe_secret_key:
        return []
    try:
        pi = stripe.PaymentIntent.retrieve(payment_intent_id, expand=["latest_charge"])
        charge = pi.get("latest_charge") or {}
        carte = ((charge.get("payment_method_details") or {}).get("card") or {})
        if not carte.get("fingerprint"):
            return []
        return [{"empreinte": carte["fingerprint"], "pm": charge.get("payment_method"),
                 "marque": carte.get("brand"), "dernier4": carte.get("last4"),
                 "financement": carte.get("funding")}]
    except Exception as e:  # noqa: BLE001
        log.warning("parrainage.carte_paiement_illisible", pi=payment_intent_id, error=str(e)[:150])
        return []


async def sur_paiement_pass(filleul: User, duree: str, montant_paye: int, remise_appliquee: bool,
                            session_id: str, cartes: list[dict], db: AsyncSession) -> None:
    """Pass payé par `filleul` (déjà accordé). N'appelle pas `commit`. Ne lève jamais."""
    try:
        await _sur_paiement_pass(filleul, duree, montant_paye, remise_appliquee, session_id, cartes, db)
    except Exception as e:  # noqa: BLE001
        log.error("parrainage.pass_erreur", filleul=filleul.user_id, error=str(e)[:200])


async def _sur_paiement_pass(filleul: User, duree: str, montant_paye: int, remise_appliquee: bool,
                             session_id: str, cartes: list[dict], db: AsyncSession) -> None:
    from services.abonnements import journaliser

    if not filleul.parraine_par_id:
        return
    lien = await _lien_du_filleul(filleul.user_id, db)
    if lien is None:
        return

    if remise_appliquee:
        if lien.remise_filleul_at is not None:
            # Deux paiements avec remise ouverts en parallèle (deux onglets) : la
            # remise ne vaut qu'une fois — la seconde est refacturée (solde positif,
            # prélevé sur sa prochaine facture d'abonnement).
            if filleul.stripe_customer_id and settings.stripe_secret_key:
                try:
                    _crediter(filleul, REMISE_CENTS, f"parrainage-remise-double-{session_id}",
                              "Remise de parrainage déjà utilisée sur un autre paiement",
                              {"parrainage_id": lien.parrainage_id, "session": session_id})
                except Exception as e:  # noqa: BLE001
                    log.error("parrainage.remise_double_reprise_echouee", filleul=filleul.user_id, error=str(e)[:200])
            log.warning("parrainage.remise_double", filleul=filleul.user_id, session=session_id)
        else:
            lien.remise_filleul_at = datetime.now(timezone.utc)

    # Pass Jour, ou paiement trop faible pour financer 5 € : ne valide rien.
    if duree not in DUREES_PASS_PARRAINAGE or montant_paye < REMISE_CENTS or lien.statut != "en_attente":
        return
    if lien.remise_filleul_at is None:
        lien.remise_filleul_at = datetime.now(timezone.utc)

    parrain = await db.get(User, lien.parrain_id) if lien.parrain_id else None
    motif: Optional[str] = None
    if not _peut_parrainer(parrain):
        motif = "parrain_inactif"
    else:
        if not cartes:
            lien.motif = "cartes_indisponibles"
            log.warning("parrainage.cartes_indisponibles", filleul=filleul.user_id, pass_session=session_id)
            return
        from api.routes.stripe_routes import _memoriser_cartes
        await _memoriser_cartes(filleul, cartes, db)
        for carte in cartes:
            connue = await db.get(CarteConnue, carte["empreinte"])
            if connue is not None and connue.user_id and connue.user_id != filleul.user_id:
                motif = "carte_du_parrain" if connue.user_id == lien.parrain_id else "carte_autre_compte"
                break

    if motif:
        lien.statut = "refuse"
        lien.motif = motif
        if remise_appliquee and motif != "parrain_inactif" and filleul.stripe_customer_id and settings.stripe_secret_key:
            try:
                _crediter(filleul, REMISE_CENTS, f"parrainage-remise-reprise-{lien.parrainage_id}",
                          "Remise de parrainage non applicable : carte déjà utilisée sur un autre compte",
                          {"parrainage_id": lien.parrainage_id})
            except Exception as e:  # noqa: BLE001
                log.error("parrainage.reprise_remise_echouee", filleul=filleul.user_id, error=str(e)[:200])
        await journaliser(db, "parrainage_refuse", parrain, None,
                          detail={"filleul": filleul.email, "motif": motif, "pass": duree})
        log.warning("parrainage.refuse", parrain=lien.parrain_id, filleul=filleul.user_id, motif=motif, pass_=duree)
        return

    if not settings.stripe_secret_key:
        return
    maintenant = datetime.now(timezone.utc)
    lien.statut = "valide"
    lien.motif = None
    lien.valide_at = maintenant
    lien.credit_cents = REMISE_CENTS
    await db.flush()
    await liberer_credits(parrain, db)
    reporte = lien.credit_pose_at is None
    await journaliser(db, "parrainage_valide", parrain, None, montant_cents=REMISE_CENTS,
                      detail={"filleul": filleul.email, "pass": duree, "session": session_id,
                              "reporte": reporte, "motif_report": lien.motif})
    log.info("parrainage.valide_par_pass", parrain=parrain.user_id, filleul=filleul.user_id, pass_=duree)
    await _prevenir_parrain(parrain, filleul, db, reporte)


async def periode_du_parrain(parrain: User, db: AsyncSession) -> dict:
    """Mois de facturation en cours du parrain et son plafond de crédits.

    Abonné au mois : la période Stripe en cours (du dernier renouvellement au
    prochain). Sinon — annuel, offert, gratuit — le mois civil. Plafond = nombre
    de crédits qui rend la mensualité de SA formule gratuite ; sans formule
    payante, celle d'Expert (la plus chère), pour ne jamais brider à tort.
    """
    from api.routes.stripe_routes import STATUT_SANS_CARTE, _normalize_plan, _subs_vivantes

    subs = [s for s in await _subs_vivantes(parrain.user_id, db) if s.statut != STATUT_SANS_CARTE]
    maintenant = datetime.now(timezone.utc)
    mensuel = next((s for s in subs if s.periodicite == "monthly" and s.periode_debut), None)
    if mensuel is not None:
        debut = mensuel.periode_debut
        debut = debut if debut.tzinfo else debut.replace(tzinfo=timezone.utc)
        fin = mensuel.periode_fin
    else:
        debut = maintenant.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        fin = (debut + timedelta(days=32)).replace(day=1)
    plan = _normalize_plan(subs[0].plan if subs else (parrain.plan or "free"))
    prix = PRIX_MENSUEL_CENTS.get(plan, PRIX_MENSUEL_CENTS["expert"])
    return {
        "debut": debut,
        "fin": fin if fin is None or fin.tzinfo else fin.replace(tzinfo=timezone.utc),
        "formule": plan if plan in PRIX_MENSUEL_CENTS else None,
        "prix_cents": prix,
        "plafond": -(-prix // REMISE_CENTS),  # arrondi supérieur : 19 € → 4, 12 € → 3
    }


async def _poses_dans_la_periode(parrain_id: str, debut: datetime, db: AsyncSession) -> int:
    return len((await db.execute(
        select(Parrainage.parrainage_id).where(
            Parrainage.parrain_id == parrain_id,
            Parrainage.statut == "valide",
            Parrainage.credit_pose_at.is_not(None),
            Parrainage.credit_pose_at >= debut,
        )
    )).all())


async def liberer_credits(parrain: User, db: AsyncSession) -> int:
    """Pose sur le solde Stripe les crédits gagnés et pas encore posés, dans la
    limite du plafond du mois, du plus ancien au plus récent. Renvoie le nombre
    posé. Idempotent : à appeler aussi souvent qu'on veut (paiement du filleul,
    facture du parrain, tâche quotidienne, affichage du suivi). Ne lève jamais.
    N'appelle pas `commit`."""
    try:
        if not settings.stripe_secret_key or not _peut_parrainer(parrain):
            return 0
        a_poser = list((await db.execute(
            select(Parrainage).where(
                Parrainage.parrain_id == parrain.user_id,
                Parrainage.statut == "valide",
                Parrainage.credit_pose_at.is_(None),
            ).order_by(Parrainage.valide_at, Parrainage.created_at)
        )).scalars().all())
        if not a_poser:
            return 0
        periode = await periode_du_parrain(parrain, db)
        place = periode["plafond"] - await _poses_dans_la_periode(parrain.user_id, periode["debut"], db)
        poses = 0
        for lien in a_poser:
            if poses >= place:
                lien.motif = "plafond_atteint"
                continue
            try:
                await _client_stripe(parrain, db)
                lien.stripe_credit_txn_id = _crediter(
                    parrain, -(lien.credit_cents or REMISE_CENTS), f"parrainage-credit-{lien.parrainage_id}",
                    "Parrainage BlackTurf : 5 € déduits de votre prochaine facture",
                    {"parrainage_id": lien.parrainage_id, "filleul_id": lien.filleul_id or ""},
                )
            except Exception as e:  # noqa: BLE001
                # Stripe injoignable : le crédit reste gagné, reposé au prochain
                # passage. Jamais doublé (relecture du solde + idempotence).
                lien.motif = "credit_en_echec"
                log.error("parrainage.credit_echoue", parrain=parrain.user_id, error=str(e)[:200])
                break
            lien.credit_pose_at = datetime.now(timezone.utc)
            lien.motif = None
            poses += 1
        if poses:
            log.info("parrainage.credits_poses", parrain=parrain.user_id, poses=poses,
                     plafond=periode["plafond"])
        return poses
    except Exception as e:  # noqa: BLE001
        log.error("parrainage.liberation_erreur", parrain=parrain.user_id, error=str(e)[:200])
        return 0


async def liberer_tous_les_credits(db: AsyncSession) -> int:
    """Tâche quotidienne : pose les crédits reportés de tous les parrains dont
    un nouveau mois a commencé. Commit par parrain."""
    ids = (await db.execute(
        select(Parrainage.parrain_id).where(
            Parrainage.statut == "valide",
            Parrainage.credit_pose_at.is_(None),
            Parrainage.parrain_id.is_not(None),
        ).distinct()
    )).scalars().all()
    total = 0
    for parrain_id in ids:
        parrain = await db.get(User, parrain_id)
        if parrain is not None:
            total += await liberer_credits(parrain, db)
            await db.commit()
    return total


async def _prevenir_parrain(parrain: User, filleul: User, db: AsyncSession, reporte: bool = False) -> None:
    try:
        from services.alerts import send_email
        from services.email_compte import parrainage_credite
        situation = "reporte" if reporte else (await situation_credit(parrain, None, db))["situation"]
        html, texte = parrainage_credite(parrain.prenom, filleul.prenom,
                                         f"{settings.frontend_url}/profil#parrainage", situation)
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
    # Crédit encore reporté (jamais posé) : rien à reprendre chez Stripe.
    if (lien.credit_pose_at is not None and parrain is not None
            and parrain.stripe_customer_id and settings.stripe_secret_key):
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


def _apercu_facture(customer: str) -> Optional[dict]:
    """Prochaine facture du client, telle que Stripe la calculera (remises et
    crédit compris). None s'il n'y en a pas ou si Stripe ne répond pas.

    `create_preview` est l'appel actuel ; `upcoming` (retiré des versions
    récentes de l'API) reste en secours pour un compte épinglé sur une ancienne.
    """
    for appel in ("create_preview", "upcoming"):
        fonction = getattr(stripe.Invoice, appel, None)
        if fonction is None:
            continue
        try:
            facture = fonction(customer=customer)
        except Exception:  # noqa: BLE001 — pas de facture à venir, ou appel refusé
            continue
        quand = facture.get("next_payment_attempt") or facture.get("period_end")
        return {
            "date": datetime.fromtimestamp(quand, tz=timezone.utc) if quand else None,
            "total_cents": int(facture.get("total") or 0),
            "a_payer_cents": int(facture.get("amount_due") or 0),
        }
    return None


async def situation_credit(user: User, credit_cents: Optional[int], db: AsyncSession) -> dict:
    """Où et quand le crédit du parrain sera déduit — dit précisément.

    - `facture` : une facture payante arrive ; montant avant / après crédit ;
    - `abonne` : abonné, mais Stripe n'a pas pu détailler la facture ;
    - `offert` : abonnement offert (plan accordé à la main, ou code promo à 100 %) :
      aucune facture à payer, le crédit attend en réserve ;
    - `resilie` : abonnement qui s'arrête à l'échéance, crédit en réserve ;
    - `sans_abonnement` : compte gratuit, déduit de l'abonnement qu'il prendra.
    """
    from api.routes.stripe_routes import STATUT_SANS_CARTE, _subs_vivantes

    vivants = [s for s in await _subs_vivantes(user.user_id, db) if s.statut != STATUT_SANS_CARTE]
    en_cours = [s for s in vivants if s.statut != "cancel_at_period_end"]
    if vivants and not en_cours:
        fin = max((s.periode_fin for s in vivants if s.periode_fin), default=None)
        return {"situation": "resilie", "date": fin}
    if en_cours:
        apercu = (_apercu_facture(user.stripe_customer_id)
                  if user.stripe_customer_id and settings.stripe_secret_key else None)
        if apercu is not None and apercu["total_cents"] > 0:
            return {"situation": "facture", **apercu}
        if apercu is not None:
            return {"situation": "offert"}
        sub = en_cours[0]
        return {"situation": "abonne", "date": sub.essai_fin or sub.periode_fin}
    if user.plan not in ("free", "decouverte"):
        return {"situation": "offert"}
    return {"situation": "sans_abonnement"}


# Étape fine d'un parrainage, pour le suivi affiché au parrain. Le `statut` en
# base ne connaît que quatre états ; le parrain, lui, veut savoir ce qui manque.
ETAPES = {
    "email_a_confirmer": "Inscrit — doit confirmer son adresse e-mail",
    "attente_paiement": "En attente du premier paiement de votre filleul",
    "paiement_en_cours": "Abonnement en cours de paiement",
    "verification": "Paiement reçu — vos 5 € arrivent sous peu",
    "credite": "Abonné — 5 € crédités sur votre compte",
    "reporte": "Abonné — 5 € reportés au mois suivant (plafond du mois atteint)",
    "refuse": "Non éligible — carte déjà utilisée sur un autre compte",
    "parrain_inactif": "Non éligible",
    "annule": "Paiement remboursé ou contesté — crédit annulé",
}


# Mêmes étapes, vues par l'exploitant (console d'administration) : ni « votre
# compte » ni « votre filleul », qui n'ont de sens que pour le parrain.
ETAPES_ADMIN = {
    "email_a_confirmer": "Inscrit — adresse e-mail à confirmer",
    "attente_paiement": "Inscrit — en attente du premier paiement",
    "paiement_en_cours": "Abonnement en cours de paiement",
    "verification": "A payé — crédit du parrain en cours de pose",
    "credite": "Abonné — parrain crédité de 5 €",
    "reporte": "Abonné — crédit du parrain reporté (plafond du mois)",
    "refuse": "Non éligible",
    "parrain_inactif": "Non éligible — parrain inactif",
    "annule": "Annulé — paiement remboursé ou contesté",
}


def _etape(lien: Parrainage, filleul: Optional[User], abonne: bool) -> str:
    from services.email_verification import email_confirme
    if lien.statut == "valide":
        if lien.credit_pose_at is not None:
            return "credite"
        return "reporte" if lien.motif == "plafond_atteint" else "verification"
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
    # Un nouveau mois a pu commencer depuis le dernier passage : les crédits
    # reportés sont posés avant d'afficher quoi que ce soit.
    if await liberer_credits(user, db):
        await db.commit()
    periode = await periode_du_parrain(user, db)
    poses_mois = await _poses_dans_la_periode(user.user_id, periode["debut"], db)
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
            "credite_le": lien.credit_pose_at,
        })
    valides = sum(1 for lien, _ in liens if lien.statut == "valide")

    remise = await remise_filleul_due(user, db)
    credit = _credit_stripe(user)
    return {
        "code": code,
        "lien": lien_parrainage(code),
        "remise_cents": REMISE_CENTS,
        "filleuls": filleuls,
        "en_attente": sum(1 for lien, _ in liens if lien.statut == "en_attente"),
        "annules": sum(1 for lien, _ in liens if lien.statut in ("refuse", "annule")),
        "valides": valides,
        "gagne_cents": valides * REMISE_CENTS,
        "credit_disponible_cents": credit,
        "deduction": await situation_credit(user, credit, db),
        # Plafond du mois : combien de crédits posés sur la période de facturation
        # en cours, sur combien possibles, et combien attendent le mois suivant.
        "mois": {
            "debut": periode["debut"],
            "fin": periode["fin"],
            "formule": periode["formule"],
            "prix_cents": periode["prix_cents"],
            "plafond": periode["plafond"],
            "poses": poses_mois,
            "reportes": sum(1 for lien, _ in liens if lien.statut == "valide" and lien.credit_pose_at is None),
        },
        "remise_filleul_disponible": remise is not None,
    }

