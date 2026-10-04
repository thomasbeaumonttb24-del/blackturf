"""
Stripe routes — BlackTurf.
Checkout, webhooks, portail client.
"""
import os
import structlog
import stripe
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from api.config import get_settings
from api.routes.auth import get_current_user, require_verified_email
from db.database import get_db
from db.models import CarteConnue, Subscription, User
from services import parrainage
from services.abonnements import journaliser

settings = get_settings()
log = structlog.get_logger()
router = APIRouter()

stripe.api_key = settings.stripe_secret_key

PRICE_MAP = {
    # v3 names (standard/expert) + backwards compat (starter/pro)
    "standard_monthly": settings.stripe_price_starter_monthly,
    "standard_annual":  settings.stripe_price_starter_annual,
    "expert_monthly":   settings.stripe_price_pro_monthly,
    "expert_annual":    settings.stripe_price_pro_annual,
    # backwards compat
    "starter_monthly": settings.stripe_price_starter_monthly,
    "starter_annual":  settings.stripe_price_starter_annual,
    "pro_monthly":     settings.stripe_price_pro_monthly,
    "pro_annual":      settings.stripe_price_pro_annual,
}

# Normalize plan names from Stripe price_id
PLAN_FROM_PRICE = {
    settings.stripe_price_starter_monthly: "standard",
    settings.stripe_price_starter_annual:  "standard",
    settings.stripe_price_pro_monthly:     "expert",
    settings.stripe_price_pro_annual:      "expert",
}

def _normalize_plan(plan: str) -> str:
    """Anciens noms de plans -> noms canoniques.

    "pro" a été supprimé du produit le 2026-08-16 (aucun compte, aucun prix
    Stripe) : il ne reste QUE ce point de normalisation, volontairement, pour
    qu'un client ou un lien de checkout périmé qui enverrait encore "pro"
    aboutisse sur "expert" au lieu d'échouer. Ne pas réintroduire "pro" dans les
    contrôles d'accès — le plan stocké doit toujours être canonique.
    """
    return {"starter": "standard", "pro": "expert"}.get(plan, plan)


# Essai ouvert sans moyen de paiement enregistré : l'abonnement EXISTE chez
# Stripe (il empêche donc d'en ouvrir un second) mais il ne donne AUCUN accès
# tant que la carte n'est pas là. Statut maison, introduit le 2026-08-20 sur
# demande de l'exploitant.
STATUT_SANS_CARTE = "essai_sans_carte"

# Statuts pour lesquels un abonnement existe chez Stripe — donc pour lesquels on
# refuse d'en créer un second.
STATUTS_VIVANTS = ("active", "trialing", "past_due", "cancel_at_period_end",
                   STATUT_SANS_CARTE)

# Statuts qui interdisent d'ouvrir un NOUVEL abonnement sans en être vivants au
# sens de l'accès : un premier paiement en cours de finalisation (`incomplete`,
# cas de l'essai refusé) ou un impayé clos côté Stripe (`unpaid`). Sans eux, un
# clic pendant cette fenêtre ouvrait un second abonnement payant.
STATUTS_EN_ATTENTE_PAIEMENT = ("incomplete", "unpaid")

# Statuts qui DONNENT ACCÈS au produit. `cancel_at_period_end` est notre statut
# maison — résilié, mais payé jusqu'à l'échéance. `essai_sans_carte` n'en fait
# volontairement PAS partie.
#
# `past_due` en a été RETIRÉ le 2026-08-27 (décision de l'exploitant). Il y était
# au motif que Stripe retente le paiement plusieurs jours et qu'une carte expirée
# ne méritait pas une coupure immédiate — sauf que la fenêtre de relance dure
# jusqu'à trois semaines : c'était trois semaines de produit livré à qui n'avait
# rien payé, exactement le scénario de la carte prépayée vidée après l'essai.
# Le paiement qui finit par passer rend l'accès immédiatement, cf.
# `_handle_payment_succeeded`.
STATUTS_ACCES = ("active", "cancel_at_period_end")

# Ordre des plans, pour choisir lequel accorder quand il en reste plusieurs.
RANG_PLAN = {"free": 0, "standard": 1, "expert": 2}


def _stripe_joignable() -> bool:
    """Faux sous pytest (aucun appel réseau réel) ou sans clé : les appels de
    vérification Stripe sont alors sautés, jamais bloquants."""
    return bool(stripe.api_key) and "PYTEST_CURRENT_TEST" not in os.environ


def _abonnements_stripe_vivants(customer_id: Optional[str]) -> list[dict]:
    """Abonnements NON terminés chez Stripe pour ce client, lus en direct : la
    base peut être en retard d'un webhook (quelques secondes à quelques minutes)."""
    if not customer_id or not _stripe_joignable():
        return []
    try:
        return [s for s in stripe.Subscription.list(customer=customer_id, status="all", limit=20)
                .auto_paging_iter()
                if s.get("status") not in ("canceled", "incomplete_expired")]
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.lecture_abonnements_echouee", customer=customer_id, error=str(e)[:120])
        return []


def _expirer_sessions_ouvertes(customer_id: Optional[str]) -> None:
    """Ferme les pages de paiement Stripe encore ouvertes de ce client. Sans ça,
    un onglet Checkout resté ouvert (valable 24 h) pouvait être payé APRÈS un
    autre : deux abonnements, deux prélèvements."""
    if not customer_id or not _stripe_joignable():
        return
    try:
        for sess in stripe.checkout.Session.list(customer=customer_id, status="open", limit=20):
            try:
                stripe.checkout.Session.expire(sess["id"])
            except Exception as e:  # noqa: BLE001
                log.warning("stripe.expiration_session_echouee", session=sess.get("id"), error=str(e)[:120])
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.lecture_sessions_echouee", customer=customer_id, error=str(e)[:120])


async def _subs_vivantes(user_id: str, db: AsyncSession,
                         sauf_stripe_id: str | None = None) -> list[Subscription]:
    """Abonnements qui donnent encore accès, du plus récent au plus ancien."""
    res = await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user_id,
               Subscription.statut.in_(STATUTS_VIVANTS))
        .order_by(Subscription.created_at.desc())
    )
    subs = list(res.scalars().all())
    if sauf_stripe_id:
        subs = [s for s in subs if s.stripe_subscription_id != sauf_stripe_id]
    return subs


async def _plan_effectif(user_id: str, db: AsyncSession,
                         sauf_stripe_id: str | None = None) -> str:
    """Plan réellement dû à l'utilisateur au vu de TOUS ses abonnements vivants.

    Corrige une rétrogradation prématurée : `_handle_subscription_deleted` posait
    `plan = "free"` dès la fin du PREMIER abonnement, même quand un autre courait
    encore (cas réel du 2026-08-20 : 3 essais simultanés expirant à 24 h d'écart,
    le compte perdait l'accès un jour trop tôt).
    """
    subs = [s for s in await _subs_vivantes(user_id, db, sauf_stripe_id=sauf_stripe_id)
            if s.statut in STATUTS_ACCES]
    plans = [s.plan for s in subs]
    plans += await _plans_offerts(user_id, db)
    if not plans:
        return "free"
    return max(plans, key=lambda p: RANG_PLAN.get(p, 0))


async def _plans_offerts(user_id: str, db: AsyncSession) -> list[str]:
    """Formules données hors Stripe et encore en vigueur.

    · récompense du Défi du mois : un webhook (essai ouvert, paiement…) ne doit
      pas retirer au gagnant les jours offerts avant leur échéance ;
    · accès offert à la main (geste commercial…) : sans lui, le premier
      événement Stripe du compte effaçait le cadeau.
    """
    from db.models import DefiRecompense
    from services.acces_offert import plan_offert_actif
    from services.passes import plan_pass_actif
    plans = list((await db.execute(select(DefiRecompense.plan_offert).where(
        DefiRecompense.user_id == user_id, DefiRecompense.statut == "applique",
        DefiRecompense.expire_at > datetime.now(timezone.utc),
    ))).scalars().all())
    offert = await plan_offert_actif(db, user_id)
    if offert:
        plans.append(offert)
    # Pass payé une fois (jour / semaine / mois) en cours : même logique, un
    # webhook d'abonnement ne doit pas l'effacer avant son échéance.
    du_pass = await plan_pass_actif(db, user_id)
    if du_pass:
        plans.append(du_pass)
    return plans


async def _avec_offert(user_id: str, plan: str, db: AsyncSession) -> str:
    """`plan` d'un abonnement, relevé par un éventuel accès offert plus haut."""
    return max([plan] + await _plans_offerts(user_id, db), key=lambda p: RANG_PLAN.get(p, 0))


def _a_moyen_de_paiement(sub: dict) -> bool:
    """Un moyen de paiement est-il rattaché à cet abonnement ?

    Trois endroits possibles, dans l'ordre où Stripe les consulte pour facturer :
    la carte propre à l'abonnement, celle par défaut du client, puis — dernier
    recours, un appel réseau — les cartes attachées au client. Le dernier point
    compte : après un Checkout, la carte est bien attachée au client alors que
    `invoice_settings.default_payment_method` peut rester vide.
    """
    if sub.get("default_payment_method"):
        return True

    customer = sub.get("customer")
    if isinstance(customer, dict):  # objet développé (`expand`)
        reglages = customer.get("invoice_settings") or {}
        if reglages.get("default_payment_method"):
            return True
        customer = customer.get("id")

    if not customer:
        return False

    try:
        client = stripe.Customer.retrieve(customer)
        reglages = client.get("invoice_settings") or {}
        if reglages.get("default_payment_method"):
            return True
        cartes = stripe.PaymentMethod.list(customer=customer, type="card", limit=1)
        return bool(cartes.get("data"))
    except Exception as e:  # noqa: BLE001
        # En cas de doute on N'ACCORDE PAS l'accès : un faux positif ici, c'est du
        # produit livré gratuitement, exactement ce que ce garde-fou empêche.
        log.warning("stripe.moyen_paiement_indetermine", customer=customer,
                    error=str(e)[:120])
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Empreinte de carte : une carte n'ouvre qu'UN essai gratuit, quel que soit l'e-mail
# ─────────────────────────────────────────────────────────────────────────────
#
# `users.essai_utilise_at` verrouille l'essai par COMPTE. Le contournement est
# évident : nouvelle adresse e-mail, même carte, 7 jours gratuits de plus, en
# boucle. Stripe attribue à chaque numéro de carte une empreinte stable dans le
# compte (`card.fingerprint`) qui survit au changement d'e-mail, de client et de
# `payment_method` — c'est cette empreinte qu'on mémorise.

def _cartes_du_client(sub: dict) -> list[dict]:
    """Cartes rattachées à cet abonnement/ce client, avec leur empreinte Stripe.

    On ratisse large volontairement : la carte du checkout est attachée au CLIENT,
    et selon le moment où le webhook arrive elle n'est pas encore recopiée dans
    `default_payment_method`. Ne regarder que ce champ laissait passer la moitié
    des cas.

    Renvoie une liste vide si Stripe est injoignable : un webhook qui lève est
    rejoué en boucle par Stripe, ce qui coûterait plus cher que la fraude qu'on
    cherche à bloquer. L'échec est journalisé en `warning` pour rester visible.
    """
    cartes: list[dict] = []
    vues: set[str] = set()

    def _ajouter(pm: dict) -> None:
        carte = (pm or {}).get("card") or {}
        empreinte = carte.get("fingerprint")
        if not empreinte or empreinte in vues:
            return
        vues.add(empreinte)
        cartes.append({
            "empreinte": empreinte,
            "pm": pm.get("id"),
            "marque": carte.get("brand"),
            "dernier4": carte.get("last4"),
            "financement": carte.get("funding"),
        })

    pm_abo = sub.get("default_payment_method")
    if isinstance(pm_abo, dict):
        _ajouter(pm_abo)

    customer = sub.get("customer")
    if isinstance(customer, dict):
        customer = customer.get("id")
    if not customer or not settings.stripe_secret_key:
        return cartes

    try:
        for pm in stripe.PaymentMethod.list(customer=customer, type="card",
                                            limit=10).get("data", []):
            _ajouter(pm)
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.empreintes_indisponibles", customer=customer,
                    error=str(e)[:120])
    return cartes


async def _carte_dun_autre_compte(user: User, cartes: list[dict],
                                  db: AsyncSession) -> Optional[CarteConnue]:
    """Première carte de la liste déjà rattachée à un AUTRE compte, sinon None."""
    for carte in cartes:
        connue = await db.get(CarteConnue, carte["empreinte"])
        if connue is not None and connue.user_id and connue.user_id != user.user_id:
            return connue
    return None


def _insert(db: AsyncSession):
    """`INSERT … ON CONFLICT` du dialecte de la session (PostgreSQL en prod, SQLite en test)."""
    if db.get_bind().dialect.name == "sqlite":
        from sqlalchemy.dialects.sqlite import insert
    else:
        from sqlalchemy.dialects.postgresql import insert
    return insert


async def _memoriser_cartes(user: User, cartes: list[dict], db: AsyncSession) -> None:
    """Enregistre les cartes vues. Le PREMIER compte qui présente une carte la garde.

    Une carte présentée par un second compte n'est pas réattribuée : on incrémente
    seulement son compteur de tentatives, qui sert de signal de fraude organisée.

    Insertion en `ON CONFLICT DO NOTHING` et non « lire puis ajouter » : au checkout,
    Stripe envoie `payment_method.attached`, `setup_intent.succeeded`,
    `customer.updated` et `customer.subscription.created` dans la même seconde. Deux
    webhooks lisaient « carte inconnue » en parallèle, le second levait
    `UniqueViolationError` → 500 → rejeu Stripe (constaté le 2026-09-12).
    """
    maintenant = datetime.now(timezone.utc)
    for carte in cartes:
        insertion = await db.execute(
            _insert(db)(CarteConnue).values(
                empreinte=carte["empreinte"],
                user_id=user.user_id,
                email=user.email,
                stripe_payment_method_id=carte.get("pm"),
                marque=carte.get("marque"),
                dernier4=carte.get("dernier4"),
                financement=carte.get("financement"),
                tentatives_autres_comptes=0,
                premiere_vue=maintenant,
                derniere_vue=maintenant,
            ).on_conflict_do_nothing(index_elements=["empreinte"])
        )
        if insertion.rowcount == 1:
            continue
        connue = (await db.execute(
            select(CarteConnue).where(CarteConnue.empreinte == carte["empreinte"])
            .execution_options(populate_existing=True)
        )).scalar_one()
        connue.derniere_vue = maintenant
        if connue.user_id in (None, user.user_id):
            connue.user_id = user.user_id
            connue.email = user.email
            connue.stripe_payment_method_id = carte.get("pm") or connue.stripe_payment_method_id
        else:
            connue.tentatives_autres_comptes = (connue.tentatives_autres_comptes or 0) + 1


async def _controler_carte(user: User, sub: dict,
                           db: AsyncSession) -> tuple[str, Optional[CarteConnue]]:
    """Verdict sur les cartes de cet abonnement : "ok", "essai_refuse" ou "bloque".

    Politique réglée par `CARTE_REUTILISEE_POLITIQUE` (cf. api/config.py). Le défaut
    `refus_essai` coupe la fraude sans punir un couple qui partage une carte : le
    second compte peut s'abonner, il paie simplement dès le premier jour.
    """
    politique = (settings.carte_reutilisee_politique or "refus_essai").strip().lower()
    cartes = _cartes_du_client(sub)
    if not cartes:
        return "ok", None

    # Mémoriser AVANT de chercher le conflit : si un autre compte a présenté la même
    # carte dans la même seconde, c'est sa ligne (celle qui a gagné l'insertion)
    # qu'on relit, et le conflit est vu au lieu de passer entre les deux webhooks.
    await _memoriser_cartes(user, cartes, db)
    conflit = None if politique == "ignorer" else await _carte_dun_autre_compte(user, cartes, db)
    if conflit is None:
        return "ok", None

    log.warning("stripe.carte_reutilisee", user_id=user.user_id,
                empreinte=conflit.empreinte, compte_dorigine=conflit.email,
                tentatives=conflit.tentatives_autres_comptes, politique=politique)
    return ("bloque" if politique == "blocage" else "essai_refuse"), conflit


def _detail_carte(connue: Optional[CarteConnue]) -> dict:
    """Résumé lisible pour le journal admin — jamais de numéro de carte."""
    if connue is None:
        return {}
    return {
        "carte": f"{connue.marque or 'carte'} ••{connue.dernier4 or '????'}",
        "compte_dorigine": connue.email,
        "tentatives": connue.tentatives_autres_comptes,
    }


async def _empreintes_deja_prises(user: User, db: AsyncSession) -> bool:
    """Le client Stripe de CE compte porte-t-il déjà une carte vue ailleurs ?

    Contrôle d'entrée du checkout : il évite d'ouvrir un essai qu'on annulerait
    trois secondes plus tard par webhook. Ne couvre que les cartes DÉJÀ
    enregistrées (client qui revient) — une carte saisie pendant le checkout n'est
    connue qu'après, d'où le double contrôle côté webhook.
    """
    if not user.stripe_customer_id:
        return False
    cartes = _cartes_du_client({"customer": user.stripe_customer_id})
    if not cartes:
        return False
    return await _carte_dun_autre_compte(user, cartes, db) is not None


class CheckoutRequest(BaseModel):
    plan: str         # standard / expert (ou starter / pro compat)
    periodicite: str  # monthly / annual
    # Abonné existant : le changement de formule n'est appliqué QU'APRÈS
    # confirmation explicite. Sans elle, l'API renvoie un aperçu chiffré.
    # (2026-09-29 : un clic sur un bouton « Standard » 8 s après une souscription
    # Expert a rétrogradé un client qui venait de payer 19 €.)
    confirmer: bool = False
    # Date de prorata renvoyée par l'aperçu : le montant débité est alors
    # exactement celui annoncé, même si le client a mis du temps à confirmer.
    proration_date: Optional[int] = None


@router.post("/stripe/checkout")
async def create_checkout(
    body: CheckoutRequest,
    db: AsyncSession = Depends(get_db),
    # Adresse confirmée exigée : sans elle, l'essai gratuit se multiplie à volonté,
    # une adresse bidon par compte.
    user: User = Depends(require_verified_email),
):
    """Crée une session Stripe Checkout et retourne l'URL de paiement.

    Trois règles, toutes absentes avant le 2026-08-20 :
    1. un compte déjà abonné ne repasse PAS par Checkout — il change de plan sur
       son abonnement existant (sinon il en cumule autant qu'il clique) ;
    2. l'essai gratuit n'est accordé qu'une fois par compte ;
    3. la carte est exigée à l'ouverture de l'essai.
    """
    plan_cible = _normalize_plan(body.plan)
    price_key = f"{body.plan}_{body.periodicite}"
    price_id = PRICE_MAP.get(price_key)
    if not price_id:
        raise HTTPException(status_code=400, detail="Plan invalide")

    # 1) Déjà abonné ? On ne crée JAMAIS un second abonnement.
    vivants = await _subs_vivantes(user.user_id, db)
    en_attente = (await db.execute(
        select(Subscription).where(Subscription.user_id == user.user_id,
                                   Subscription.statut.in_(STATUTS_EN_ATTENTE_PAIEMENT))
    )).scalars().all()
    if any(s.statut == "past_due" for s in vivants) or (en_attente and not vivants):
        # Une facture est impayée (ou un premier paiement en cours) : changer de
        # formule mélange deux prix sur une même période (cas du 26/09 : facture
        # Expert réglée après un passage en Standard), ouvrir un second abonnement
        # ferait payer deux fois.
        raise HTTPException(
            status_code=409,
            detail="Un prélèvement est en attente sur votre abonnement. Réglez-le "
                   "depuis votre profil avant de changer de formule.",
        )
    if not vivants and _abonnements_stripe_vivants(user.stripe_customer_id):
        # Stripe connaît un abonnement que notre base n'a pas encore reçu (webhook
        # en route) : l'ouvrir une seconde fois serait un double prélèvement.
        raise HTTPException(
            status_code=409,
            detail="Votre abonnement est en cours d'activation. Patientez une minute "
                   "puis rechargez la page.",
        )
    if vivants:
        courant = _abonnement_courant(vivants)
        if courant.plan == plan_cible and courant.periodicite == body.periodicite:
            raise HTTPException(
                status_code=409,
                detail="Vous êtes déjà abonné à cette formule. "
                       "Gérez votre abonnement depuis votre profil.",
            )
        if courant.periodicite != body.periodicite:
            # Changer d'intervalle refacture la totalité tout de suite et déplace
            # l'échéance : jamais sans un échange humain.
            raise HTTPException(
                status_code=409,
                detail="Le passage mensuel ↔ annuel se fait sur demande : écrivez-nous "
                       "à contact@blackturf.fr.",
            )
        if not body.confirmer:
            return {"confirmation_requise": True,
                    "apercu": _apercu_changement(user, courant, plan_cible,
                                                 body.periodicite, price_id)}
        return await _changer_de_plan(user, vivants, plan_cible, body.periodicite,
                                      price_id, db, proration_date=body.proration_date)

    # Récupérer ou créer le customer Stripe
    customer_id = user.stripe_customer_id
    _expirer_sessions_ouvertes(customer_id)
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=f"{user.prenom or ''} {user.nom or ''}".strip() or user.email,
            metadata={"user_id": user.user_id},
        )
        customer_id = customer.id
        user.stripe_customer_id = customer_id
        await db.commit()

    # 2) Essai gratuit SUPPRIMÉ (décision de l'exploitant du 2026-10-04) : trop de
    # résiliations au 7e jour. La découverte payante passe par les passes jour /
    # semaine / mois (services/passes.py). Aucun chemin n'ouvre plus d'essai :
    # `trial_period_days` n'est jamais envoyé à Stripe. Les essais ouverts avant
    # cette date suivent leur cours (webhooks inchangés).
    droit_a_lessai = False

    # 2 bis) Carte déjà vue sur un autre compte : l'essai ne se rouvre pas avec une
    # nouvelle adresse e-mail. Le contrôle définitif est côté webhook (la carte du
    # checkout n'existe pas encore ici) ; celui-ci sert au client qui REVIENT avec
    # une carte déjà enregistrée, et évite d'ouvrir un essai pour l'annuler aussitôt.
    if droit_a_lessai or settings.carte_reutilisee_politique == "blocage":
        if await _empreintes_deja_prises(user, db):
            if settings.carte_reutilisee_politique == "blocage":
                raise HTTPException(
                    status_code=409,
                    detail="Cette carte bancaire est déjà rattachée à un autre compte "
                           "BlackTurf. Utilisez le compte d'origine ou une autre carte.",
                )
            droit_a_lessai = False
            log.warning("stripe.essai_refuse_carte_connue", user_id=user.user_id)

    # Filleul : pas d'essai, 5 € de remise sur la première facture payante.
    # Coupon posé par le serveur uniquement — la saisie d'un code promo est alors
    # désactivée (Stripe refuse de cumuler les deux, et un second code ne doit pas
    # s'ajouter à la remise de parrainage).
    remise: dict = {"allow_promotion_codes": True}
    parrainage_filleul = await parrainage.remise_filleul_due(user, db)
    if parrainage_filleul is not None and await _empreintes_deja_prises(user, db):
        # Carte déjà vue sur un autre compte : c'est un ancien client qui rouvre un
        # compte pour la remise. Ni remise, ni essai — plein tarif.
        log.warning("stripe.remise_parrainage_refusee_carte_connue", user_id=user.user_id)
        parrainage_filleul = None
        droit_a_lessai = False
    if parrainage_filleul is not None:
        droit_a_lessai = False
        try:
            remise = {"discounts": [{"coupon": parrainage.coupon_filleul()}]}
        except Exception as e:  # noqa: BLE001
            # Jamais de checkout plein tarif en silence : la remise serait perdue
            # pour de bon au premier paiement.
            log.error("stripe.coupon_parrainage_indisponible", error=str(e)[:150])
            raise HTTPException(
                status_code=503,
                detail="La remise de parrainage est momentanément indisponible. "
                       "Réessayez dans quelques minutes.",
            )

    subscription_data: dict = {
        "metadata": {"user_id": user.user_id, "plan": plan_cible},
    }
    if parrainage_filleul is not None:
        subscription_data["metadata"]["parrainage_id"] = parrainage_filleul.parrainage_id
    # Créer la session
    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": price_id, "quantity": 1}],
        mode="subscription",
        success_url=f"{settings.frontend_url}/abonnement/succes?session_id={{CHECKOUT_SESSION_ID}}&plan={plan_cible}",
        cancel_url=f"{settings.frontend_url}/tarifs",
        # 3) Carte exigée dès l'ouverture de l'essai (décision produit du
        # 2026-08-20). `if_required` — l'essai sans carte — laissait partir des
        # essais qu'aucun moyen de paiement ne pouvait convertir, et rendait
        # l'abus indétectable côté Stripe. `always` est aussi le défaut Stripe :
        # le paramètre reste explicite pour que le choix soit lisible ici.
        payment_method_collection="always",
        subscription_data=subscription_data,
        locale="fr",
        **remise,
    )

    log.info("stripe.checkout_created", user_id=user.user_id, plan=plan_cible,
             essai_accorde=droit_a_lessai,
             remise_parrainage=parrainage_filleul is not None)
    return {"url": session.url, "essai": droit_a_lessai,
            "remise_parrainage": parrainage_filleul is not None}


# ── Passes sans renouvellement ───────────────────────────────────────────────
# Cumul plafonné : au-delà, un achat de plus n'apporte rien au client et
# allonge l'exposition aux contestations bancaires.
PASS_CUMUL_MAX = timedelta(days=31)


class PassRequest(BaseModel):
    duree: str  # jour / semaine / mois
    # Ignoré depuis la v2 : la case de renonciation est sur la page de paiement
    # Stripe (consent_collection), qui refuse de payer sans elle. Gardé pour les
    # pages encore en cache qui l'envoient.
    renonciation: bool = False


class PassConfirmation(BaseModel):
    session_id: str


@router.post("/stripe/pass")
async def creer_checkout_pass(
    body: PassRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(require_verified_email),
):
    """Session Stripe Checkout d'un pass : paiement unique, aucun abonnement.

    Le prix vient du SERVEUR (services.passes.PASSES) ; le client ne choisit que
    la durée. Rien n'est accordé ici : l'accès naît du paiement encaissé
    (webhook `checkout.session.completed` ou page de retour), cf. passes.accorder.
    """
    from services import passes

    if body.duree not in passes.PASSES:
        raise HTTPException(status_code=400, detail="Durée invalide")
    if user.is_admin:
        raise HTTPException(status_code=409, detail="Un compte administrateur a déjà accès à tout.")
    vivants = [s for s in await _subs_vivantes(user.user_id, db) if s.statut in STATUTS_ACCES]
    if any(s.plan == "expert" for s in vivants):
        raise HTTPException(
            status_code=409,
            detail="Votre abonnement Expert donne déjà un accès illimité : un pass "
                   "ne vous apporterait rien.",
        )
    fin_actuelle = await passes._fin_des_passes(db, user.user_id)
    if fin_actuelle and fin_actuelle > datetime.now(timezone.utc) + PASS_CUMUL_MAX:
        raise HTTPException(
            status_code=409,
            detail="Votre accès est déjà ouvert pour plus d'un mois. Revenez plus près "
                   "de son échéance pour le prolonger.",
        )

    prix, _duree, libelle = passes.PASSES[body.duree]
    customer_id = user.stripe_customer_id
    _expirer_sessions_ouvertes(customer_id)
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=f"{user.prenom or ''} {user.nom or ''}".strip() or user.email,
            metadata={"user_id": user.user_id},
        )
        customer_id = customer.id
        user.stripe_customer_id = customer_id
        await db.commit()

    metadata = {
        "type": "pass", "duree": body.duree, "user_id": user.user_id,
        "renonciation_version": passes.RENONCIATION_VERSION,
    }
    # Remise de parrainage (−5 €) : Pass Semaine et Mois seulement — jamais le
    # Pass Jour, que la remise rendrait gratuit. Mêmes garde-fous que pour un
    # abonnement : une seule fois par filleul, refusée si sa carte enregistrée
    # appartient déjà à un autre compte (ancien client qui rouvre un compte).
    remise: dict = {}
    if body.duree in parrainage.DUREES_PASS_PARRAINAGE:
        lien_filleul = await parrainage.remise_filleul_due(user, db)
        if lien_filleul is not None and await _empreintes_deja_prises(user, db):
            log.warning("stripe.remise_pass_refusee_carte_connue", user_id=user.user_id)
            lien_filleul = None
        if lien_filleul is not None:
            try:
                remise = {"discounts": [{"coupon": parrainage.coupon_filleul()}]}
            except Exception as e:  # noqa: BLE001
                log.error("stripe.coupon_parrainage_indisponible", error=str(e)[:150])
                raise HTTPException(status_code=503, detail="La remise de parrainage est momentanément "
                                                            "indisponible. Réessayez dans quelques minutes.")
            metadata["remise_parrainage"] = "1"
            metadata["parrainage_id"] = lien_filleul.parrainage_id
    price_id = passes.prix_stripe(body.duree) if _stripe_joignable() else None
    ligne = ({"price": price_id, "quantity": 1} if price_id else {
        "quantity": 1,
        "price_data": {
            "currency": passes.DEVISE,
            "unit_amount": prix,
            "product_data": {"name": f"BlackTurf — {libelle}"},
        },
    })
    session = stripe.checkout.Session.create(
        customer=customer_id,
        client_reference_id=user.user_id,
        mode="payment",
        payment_method_types=["card"],
        line_items=[ligne],
        metadata=metadata,
        # Le paiement porte aussi les métadonnées : un remboursement ou une
        # contestation (événements de charge) retrouve ainsi le pass.
        payment_intent_data={"metadata": metadata, "description": f"BlackTurf — {libelle}"},
        # Case OBLIGATOIRE sur la page Stripe : accès immédiat + renonciation au
        # droit de rétractation. Stripe bloque le paiement tant qu'elle n'est pas
        # cochée et l'atteste dans `session.consent` (vérifié à l'octroi).
        consent_collection={"terms_of_service": "required"},
        custom_text={
            "terms_of_service_acceptance": {
                "message": passes.RENONCIATION_TEXTE + f" [Conditions]({settings.frontend_url}/cgv#passes)",
            },
            "submit": {"message": "Paiement unique : aucun abonnement, aucun prélèvement suivant."},
        },
        # Session courte (minimum Stripe : 30 min) : pas de vieil onglet payé
        # après un changement de tarif ou un autre achat.
        expires_at=int((datetime.now(timezone.utc) + timedelta(minutes=30)).timestamp()),
        success_url=f"{settings.frontend_url}/abonnement/succes?pass={body.duree}&session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{settings.frontend_url}/tarifs",
        locale="fr",
        **remise,
    )
    log.info("stripe.checkout_pass_cree", user_id=user.user_id, duree=body.duree,
             remise_parrainage=bool(remise))
    return {"url": session.url, "remise_parrainage": bool(remise)}


@router.post("/stripe/pass/confirmer")
async def confirmer_pass(
    body: PassConfirmation,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Page de retour : relit la session CHEZ STRIPE et accorde le pass si elle est
    payée. Filet si le webhook tarde ou n'est pas branché ; idempotent avec lui."""
    from services import passes

    sid = (body.session_id or "").strip()
    if not sid.startswith("cs_") or len(sid) > 100:
        raise HTTPException(status_code=400, detail="Session invalide")
    try:
        session = stripe.checkout.Session.retrieve(sid)
    except stripe.error.InvalidRequestError:
        raise HTTPException(status_code=404, detail="Session introuvable")
    meta = dict(session.get("metadata") or {})
    if meta.get("user_id") != user.user_id:
        # Session d'un autre compte : on ne dit rien de plus.
        raise HTTPException(status_code=404, detail="Session introuvable")
    try:
        p, _cree = await passes.accorder(db, session)
    except passes.PassInvalide as e:
        log.info("stripe.pass_non_confirme", user_id=user.user_id, raison=str(e))
        raise HTTPException(status_code=409, detail="Paiement pas encore confirmé. Réessayez dans un instant.")
    await db.refresh(user)
    actif = await passes.pass_actif(db, user.user_id)
    return {"plan": user.plan, "duree": p.duree, "debut": p.debut, "fin": (actif or {}).get("fin") or p.fin}


def _abonnement_courant(vivants: list[Subscription]) -> Subscription:
    """L'abonnement à modifier : celui qui DONNE accès, de la formule la plus haute,
    puis le plus récent. `vivants[0]` (le plus récent) pouvait être un essai sans
    carte alors qu'un Expert payé courait à côté — c'est ce dernier qu'on fermait."""
    return max(vivants, key=lambda s: (s.statut in STATUTS_ACCES,
                                       RANG_PLAN.get(s.plan, 0),
                                       s.created_at.timestamp() if s.created_at else 0))


def _sens_changement(courant: Subscription, plan_cible: str, periodicite: str) -> str:
    if RANG_PLAN.get(plan_cible, 0) > RANG_PLAN.get(courant.plan, 0):
        return "hausse"
    if RANG_PLAN.get(plan_cible, 0) < RANG_PLAN.get(courant.plan, 0):
        return "baisse"
    return "periodicite" if periodicite != courant.periodicite else "aucun"


def _en_essai(sub_stripe: dict) -> bool:
    return sub_stripe.get("status") == "trialing"


def _mode_prorata(sens: str, sub_stripe: dict) -> str:
    """Hausse (ou changement de périodicité) en période PAYÉE : la différence est
    encaissée tout de suite. Reportée sur la prochaine facture, elle n'était
    jamais payée si le client résiliait entre-temps — Expert gratuit jusqu'à
    l'échéance. Baisse, ou tout changement pendant l'essai : crédit/débit
    reporté sur la prochaine facture."""
    if _en_essai(sub_stripe) or sens == "baisse":
        return "create_prorations"
    return "always_invoice"


def _euros(cents: Optional[int]) -> str:
    c = int(cents or 0)
    return (f"{c / 100:.2f}".replace(".", ",") if c % 100 else f"{c // 100}") + " €"


def _date_fr(ts: Optional[int]) -> str:
    if not ts:
        return "la prochaine échéance"
    mois = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre")
    d = datetime.fromtimestamp(int(ts), tz=timezone.utc)
    return f"{d.day} {mois[d.month - 1]} {d.year}"


def _apercu_changement(user: User, courant: Subscription, plan_cible: str,
                       periodicite: str, price_id: str) -> dict:
    """Ce qui va se passer, chiffré PAR STRIPE, avant que le client confirme."""
    sub_stripe = stripe.Subscription.retrieve(courant.stripe_subscription_id)
    item = sub_stripe["items"]["data"][0]
    sens = _sens_changement(courant, plan_cible, periodicite)
    mode = _mode_prorata(sens, sub_stripe)
    en_essai = _en_essai(sub_stripe)
    fin_periode = item.get("current_period_end") or sub_stripe.get("current_period_end")
    # Prix lu chez Stripe : l'annuel vaut 115,20 € / 182,40 €, pas un chiffre rond.
    try:
        prix_cible = stripe.Price.retrieve(price_id).get("unit_amount")
    except Exception:  # noqa: BLE001
        prix_cible = None

    immediat = ajustement = None
    proration_date = int(datetime.now(timezone.utc).timestamp())
    try:
        apercu = stripe.Invoice.upcoming(
            customer=sub_stripe.get("customer"),
            subscription=courant.stripe_subscription_id,
            subscription_items=[{"id": item["id"], "price": price_id}],
            subscription_proration_behavior=mode,
            subscription_proration_date=proration_date,
        )
        prorata = sum(int(ligne.get("amount") or 0) for ligne in apercu["lines"]["data"]
                      if ligne.get("proration"))
        if mode == "always_invoice":
            # Un crédit client (parrainage) est consommé en premier par Stripe.
            credit = 0
            try:
                solde = int(stripe.Customer.retrieve(sub_stripe.get("customer")).get("balance") or 0)
                credit = -solde if solde < 0 else 0
            except Exception:  # noqa: BLE001
                pass
            immediat = max(prorata - credit, 0)
        else:
            ajustement = prorata
    except Exception as e:  # noqa: BLE001 — l'aperçu ne bloque pas, le message reste honnête
        log.warning("stripe.apercu_changement_indisponible", user_id=user.user_id, error=str(e)[:150])

    nom = plan_cible.capitalize()
    unite = "/an" if periodicite == "annual" else "/mois"
    prix_txt = f"{_euros(prix_cible)}{unite}" if prix_cible else "le tarif de la formule"
    resilie = bool(sub_stripe.get("cancel_at_period_end") or sub_stripe.get("cancel_at"))
    if en_essai:
        message = (f"Passer en {nom} ? Votre essai gratuit continue jusqu'au "
                   f"{_date_fr(sub_stripe.get('trial_end'))}. Aucun prélèvement aujourd'hui ; "
                   f"ensuite {prix_txt}.")
    elif mode == "always_invoice" and immediat is not None and immediat < 50:
        # Sous 0,50 €, Stripe ne débite pas : le montant rejoint la facture suivante.
        message = (f"Passer en {nom} maintenant ? La différence ({_euros(immediat)}) est trop "
                   f"faible pour être prélevée seule : elle sera ajoutée à votre facture du "
                   f"{_date_fr(fin_periode)}, puis {prix_txt}.")
    elif mode == "always_invoice":
        montant = (f"{_euros(immediat)} (différence au prorata jusqu'au {_date_fr(fin_periode)})"
                   if immediat is not None else "La différence au prorata")
        message = (f"Passer en {nom} maintenant ? {montant} sera prélevé aujourd'hui, "
                   f"puis {prix_txt} à partir du {_date_fr(fin_periode)}.")
    else:
        credit = (f" Le temps non utilisé ({_euros(-ajustement)}) sera déduit de cette facture."
                  if ajustement is not None and ajustement < 0 else "")
        message = (f"Passer en {nom} maintenant ? Les fonctions de votre formule actuelle "
                   f"s'arrêtent tout de suite. Prochaine facture le {_date_fr(fin_periode)} : "
                   f"{prix_txt}.{credit}")
    if resilie:
        message += " Votre résiliation reste programmée : l'abonnement s'arrêtera à l'échéance."
    return {
        "sens": sens, "plan_actuel": courant.plan, "plan_cible": plan_cible,
        "en_essai": en_essai, "montant_immediat_cents": immediat,
        "ajustement_prochaine_facture_cents": ajustement,
        "prochaine_echeance": fin_periode, "prix_cible_cents": prix_cible,
        "resiliation_programmee": resilie, "message": message,
        "proration_date": proration_date,
    }


async def _changer_de_plan(
    user: User,
    vivants: list[Subscription],
    plan_cible: str,
    periodicite: str,
    price_id: str,
    db: AsyncSession,
    proration_date: Optional[int] = None,
) -> dict:
    """Standard ↔ Expert : on MODIFIE l'abonnement existant.

    Avant le 2026-08-20, tout passage d'une formule à l'autre repassait par
    Checkout et créait un SECOND abonnement, le premier restant actif : le client
    était facturé deux fois. Ici, une seule ligne Stripe suit le client, la
    différence de prix est proratisée sur la prochaine facture, et l'essai en
    cours est conservé (Stripe garde `trial_end` lors d'un changement d'article).
    """
    courant = _abonnement_courant(vivants)
    sub_stripe = stripe.Subscription.retrieve(courant.stripe_subscription_id)
    item_id = sub_stripe["items"]["data"][0]["id"]
    sens = _sens_changement(courant, plan_cible, periodicite)
    mode = _mode_prorata(sens, sub_stripe)

    if sub_stripe.get("pending_update"):
        # Un changement attend déjà son paiement (3-D Secure) : renvoyer vers la
        # MÊME facture, jamais en créer une seconde qui pourrait être payée aussi.
        facture = sub_stripe.get("latest_invoice")
        if isinstance(facture, str):
            facture = stripe.Invoice.retrieve(facture)
        return {
            "url": (facture or {}).get("hosted_invoice_url") or f"{settings.frontend_url}/profil",
            "change_de_plan": False, "paiement_requis": True, "plan": courant.plan,
            "message": "Un changement de formule attend déjà la confirmation de votre banque.",
        }

    params: dict = {"items": [{"id": item_id, "price": price_id}], "proration_behavior": mode}
    maintenant = int(datetime.now(timezone.utc).timestamp())
    if proration_date and maintenant - 2 * 3600 <= proration_date <= maintenant:
        params["proration_date"] = int(proration_date)
    if mode == "always_invoice":
        # La nouvelle formule n'est appliquée QUE si la différence est payée : une
        # carte refusée ou une authentification 3-D Secure laisse la formule
        # actuelle en place (`pending_update`, qui expire seul sous 23 h).
        params["payment_behavior"] = "pending_if_incomplete"
    else:
        params["metadata"] = {"user_id": user.user_id, "plan": plan_cible}
    try:
        maj = stripe.Subscription.modify(courant.stripe_subscription_id, **params)
    except stripe.error.CardError:
        raise HTTPException(
            status_code=402,
            detail="Votre banque a refusé le paiement de la différence. "
                   "Votre formule n'a pas changé.",
        )

    if maj.get("pending_update"):
        # Paiement à finaliser (3-D Secure) ou refusé : rien ne change ici. Le
        # webhook appliquera la formule si le client règle la facture.
        facture = maj.get("latest_invoice")
        if isinstance(facture, str):
            facture = stripe.Invoice.retrieve(facture)
        url = (facture or {}).get("hosted_invoice_url") or f"{settings.frontend_url}/profil"
        log.warning("stripe.plan_change_paiement_requis", user_id=user.user_id, plan=plan_cible)
        return {
            "url": url, "change_de_plan": False, "paiement_requis": True, "plan": courant.plan,
            "message": "Le paiement de la différence doit être confirmé auprès de votre "
                       "banque. Votre formule changera dès qu'il sera validé.",
        }
    if mode == "always_invoice":
        try:
            stripe.Subscription.modify(courant.stripe_subscription_id,
                                       metadata={"user_id": user.user_id, "plan": plan_cible})
        except Exception as e:  # noqa: BLE001 — métadonnée informative seulement
            log.warning("stripe.metadata_plan_non_posee", error=str(e)[:120])

    # Doublons hérités de l'ancien tunnel : un compte ne doit porter qu'UN
    # abonnement. Ceux encore en essai n'ont rien coûté, on les ferme sur-le-champ ;
    # ceux déjà payés courent jusqu'à l'échéance déjà réglée.
    for doublon in [v for v in vivants if v is not courant]:
        try:
            # L'état LIVE décide : `essai_fin` reste renseigné après un essai payé,
            # et un doublon payé supprimé sur-le-champ perdait sa période réglée.
            statut_live = stripe.Subscription.retrieve(doublon.stripe_subscription_id).get("status")
            if statut_live == "trialing":
                stripe.Subscription.delete(doublon.stripe_subscription_id)
                doublon.statut = "canceled"
            elif statut_live in ("active",):
                stripe.Subscription.modify(doublon.stripe_subscription_id,
                                           cancel_at_period_end=True)
                doublon.statut = "cancel_at_period_end"
            else:
                continue  # impayé ou déjà clos : ne rien réétiqueter
            log.warning("stripe.doublon_ferme", user_id=user.user_id,
                        sub=doublon.stripe_subscription_id, statut=doublon.statut)
        except Exception as e:  # noqa: BLE001
            log.error("stripe.doublon_fermeture_echouee", user_id=user.user_id,
                      sub=doublon.stripe_subscription_id, error=str(e)[:120])

    # Mise à jour immédiate : le webhook `subscription.updated` confirmera, mais
    # l'utilisateur revient sur le site dans la seconde et doit voir son plan.
    plan_precedent = courant.plan
    courant.plan = plan_cible
    courant.periodicite = periodicite
    statut_stripe = maj.get("status")
    if statut_stripe in ("active", "trialing"):
        # Un essai resté sans carte le reste : changer de formule ne débloque rien.
        # Une résiliation programmée le reste aussi.
        if courant.statut != STATUT_SANS_CARTE:
            courant.statut = ("cancel_at_period_end" if _resiliation_programmee(maj)
                              else "active")
    try:
        user.plan = await _plan_effectif(user.user_id, db)
        await journaliser(db, "changement_plan", user, courant,
                          plan_precedent=plan_precedent,
                          montant_cents=_montant_cents(maj))
        await db.commit()
    except Exception as e:  # noqa: BLE001
        # Stripe a déjà changé la formule (et encaissé) : le webhook réalignera la
        # base. Le client ne doit pas lire « échec » après avoir payé.
        log.error("stripe.plan_change_base_non_ecrite", user_id=user.user_id, error=str(e)[:200])
        await db.rollback()

    log.info("stripe.plan_change", user_id=user.user_id, plan=plan_cible,
             sub=courant.stripe_subscription_id, doublons_fermes=len(vivants) - 1)
    if _en_essai(sub_stripe):
        suite = "Votre essai gratuit continue ; aucun prélèvement aujourd'hui."
    elif mode == "always_invoice":
        suite = "La différence au prorata a été réglée."
    else:
        suite = "Le temps non utilisé est déduit de votre prochaine facture."
    return {
        "url": f"{settings.frontend_url}/abonnement/succes?plan={plan_cible}&change=1&sens={sens}"
               + ("&essai=1" if _en_essai(sub_stripe) else ""),
        "change_de_plan": True,
        "plan": plan_cible,
        "message": f"Votre abonnement est passé en {plan_cible.capitalize()}. {suite}",
    }


@router.post("/stripe/portal")
async def customer_portal(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Accès au portail client Stripe (gérer/annuler abonnement)."""
    if not user.stripe_customer_id:
        raise HTTPException(status_code=400, detail="Aucun abonnement Stripe")

    session = stripe.billing_portal.Session.create(
        customer=user.stripe_customer_id,
        return_url=f"{settings.frontend_url}/profil",
    )
    return {"url": session.url}


@router.post("/stripe/cancel")
async def cancel_subscription(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Résiliation de l'abonnement en self-service (honore L215-1-1 « résiliation en
    quelques clics »). Fonctionne AVEC ou SANS Stripe configuré :
    - Stripe + abonnement actif → annulation à la fin de la période (cancel_at_period_end).
    - Sinon (plan accordé manuellement / Stripe non configuré) → la demande est
      enregistrée et notifiée par email ; l'accès reste ouvert jusqu'à traitement.
    """
    cancelled_via_stripe = False
    # 1) Essai Stripe si configuré + abonnement connu.
    #
    # On boucle sur TOUS les abonnements vivants. L'ancien `scalar_one_or_none()`
    # levait `MultipleResultsFound` dès qu'un compte en portait plusieurs — cas
    # créé par l'ancien tunnel de changement de plan. L'exception était avalée par
    # le `except` ci-dessous : le client recevait « demande enregistrée » et RIEN
    # n'était résilié chez Stripe (constaté le 2026-08-20).
    if settings.stripe_secret_key and user.stripe_customer_id:
        subs = await _subs_vivantes(user.user_id, db)
        for sub in subs:
            if not sub.stripe_subscription_id:
                continue
            if sub.statut == "cancel_at_period_end":
                # Double clic : déjà résilié, ne pas journaliser (ni notifier) deux fois.
                cancelled_via_stripe = True
                continue
            if sub.statut == "past_due":
                # Impayé : pas de « fin de période » à honorer, l'accès est déjà
                # coupé. Clore TOUT DE SUITE et annuler la facture — sinon les
                # relances J+3/J+7 débitaient un client qui avait résilié.
                try:
                    stripe.Subscription.delete(sub.stripe_subscription_id)
                    for inv in stripe.Invoice.list(subscription=sub.stripe_subscription_id,
                                                   status="open", limit=10):
                        try:
                            stripe.Invoice.void_invoice(inv["id"])
                        except Exception as e:  # noqa: BLE001
                            log.warning("stripe.cancel.void_echoue", facture=inv.get("id"),
                                        error=str(e)[:120])
                    sub.statut = "canceled"
                    cancelled_via_stripe = True
                    user.plan = await _plan_effectif(user.user_id, db,
                                                     sauf_stripe_id=sub.stripe_subscription_id)
                    await journaliser(db, "resilie", user, sub,
                                      detail={"statut_precedent": "past_due",
                                              "motif": "resiliation_pendant_impaye"})
                except Exception as e:  # noqa: BLE001
                    log.warning("stripe.cancel.impaye_echoue", user_id=user.user_id,
                                sub=sub.stripe_subscription_id, error=str(e)[:120])
                continue
            try:
                stripe.Subscription.modify(sub.stripe_subscription_id,
                                           cancel_at_period_end=True)
                sub.statut = "cancel_at_period_end"
                cancelled_via_stripe = True
                await journaliser(db, "resiliation_demandee", user, sub)
            except Exception as e:  # noqa: BLE001
                log.warning("stripe.cancel.api_failed", user_id=user.user_id,
                            sub=sub.stripe_subscription_id, error=str(e)[:120])
        if cancelled_via_stripe:
            await db.commit()

    # 2) Toujours notifier (preuve de la demande) — sans dépendre de Stripe
    try:
        from services.alerts import send_email
        await send_email(
            to="contact@blackturf.fr",
            subject=f"[BlackTurf] Demande de résiliation — {user.email}",
            html=f"<p>Demande de résiliation.</p><p>User: {user.email} ({user.user_id})</p>"
                 f"<p>Plan: {user.plan} — via Stripe: {cancelled_via_stripe}</p>",
        )
        from services.email_compte import resiliation
        html, texte = resiliation(cancelled_via_stripe)
        await send_email(
            to=user.email,
            subject="BlackTurf — Votre demande de résiliation",
            html=html, text=texte,
        )
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.cancel.email_failed", user_id=user.user_id, error=str(e)[:120])

    log.info("stripe.cancel.requested", user_id=user.user_id, via_stripe=cancelled_via_stripe)
    return {
        "ok": True,
        "via_stripe": cancelled_via_stripe,
        "message": ("Résiliation enregistrée : effective à la fin de la période en cours."
                    if cancelled_via_stripe else
                    "Demande de résiliation enregistrée. Traitée sous 72h, accès maintenu jusque-là."),
    }


@router.post("/stripe/webhook")
async def stripe_webhook(
    request: Request,
    stripe_signature: Optional[str] = Header(None),
    db: AsyncSession = Depends(get_db),
):
    """Traite les événements Stripe (subscription lifecycle)."""
    payload = await request.body()
    if not settings.stripe_webhook_secret:
        # Secret vide = n'importe qui peut signer un faux événement (vérifié avec
        # stripe 9.11 : la signature HMAC d'une clé vide est acceptée).
        log.error("stripe.webhook.secret_absent")
        raise HTTPException(status_code=503, detail="Webhook non configuré")

    try:
        event = stripe.Webhook.construct_event(
            payload, stripe_signature, settings.stripe_webhook_secret
        )
    except stripe.error.SignatureVerificationError:
        log.warning("stripe.webhook.invalid_signature")
        raise HTTPException(status_code=400, detail="Signature invalide")

    event_type = event["type"]
    data = event["data"]["object"]
    event_id = event.get("id", "")

    # Idempotence / anti-replay : Stripe redélivre les webhooks (at-least-once) et un
    # payload+signature capturé peut être rejoué dans la fenêtre de 5 min. On ignore
    # tout event_id déjà traité. Table créée à la volée (pattern maison, cf. profil_run_log).
    await db.execute(text(
        "CREATE TABLE IF NOT EXISTS stripe_events ("
        "event_id TEXT PRIMARY KEY, event_type TEXT, "
        "processed_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP)"
    ))
    if event_id:
        # Réservation AVANT traitement : deux livraisons simultanées du même
        # événement (Stripe livre « au moins une fois ») ne peuvent plus être
        # traitées deux fois. En cas d'échec du traitement, la réservation est
        # retirée pour que la relivraison de Stripe le rejoue.
        res = await db.execute(text(
            "INSERT INTO stripe_events (event_id, event_type) VALUES (:e, :t) "
            "ON CONFLICT (event_id) DO NOTHING"
        ), {"e": event_id, "t": event_type})
        await db.commit()
        if not res.rowcount:
            log.info("stripe.webhook.duplicate_ignored", event_id=event_id)
            return {"ok": True}

    log.info("stripe.webhook", event_type=event_type, event_id=event_id)
    try:
        await _traiter_evenement(event_type, data, db)
    except Exception:
        await db.rollback()
        if event_id:
            await db.execute(text("DELETE FROM stripe_events WHERE event_id = :e"), {"e": event_id})
            await db.commit()
        raise
    return {"ok": True}


async def _traiter_evenement(event_type: str, data: dict, db: AsyncSession) -> None:
    if event_type == "customer.subscription.created":
        await _handle_subscription_created(data, db)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data, db)
    elif event_type == "customer.subscription.deleted":
        await _handle_subscription_deleted(data, db)
    elif event_type == "customer.subscription.paused":
        # Une pause n'est pas une fin : l'accès est suspendu, la reprise
        # (`subscription.updated` → active) le rend. La traiter comme une
        # suppression la rendait définitive.
        await _handle_subscription_updated(data, db)
    elif event_type in ("invoice.payment_succeeded",):
        await _handle_payment_succeeded(data, db)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data, db)
    elif event_type == "checkout.session.completed":
        await _handle_checkout_pass(data, db)
    elif event_type == "charge.refunded":
        await parrainage.sur_remboursement(data, db, "paiement_rembourse")
        # Remboursement TOTAL d'un pass : accès retiré. Un remboursement partiel
        # (geste commercial) laisse l'accès.
        if data.get("refunded"):
            from services.passes import retirer_par_paiement
            await retirer_par_paiement(db, _payment_intent_id(data), "paiement_rembourse")
    elif event_type == "charge.dispute.created":
        await parrainage.sur_remboursement(data, db, "paiement_conteste")
        from services.passes import retirer_par_paiement
        await retirer_par_paiement(db, _payment_intent_id(data), "paiement_conteste")
    elif event_type == "customer.subscription.trial_will_end":
        await _handle_trial_will_end(data, db)
    elif event_type in ("payment_method.attached", "customer.updated",
                        "setup_intent.succeeded"):
        # Une carte vient d'arriver : débloquer les essais mis en attente.
        await _handle_moyen_paiement_ajoute(data, db)


def _payment_intent_id(obj: dict) -> Optional[str]:
    pi = obj.get("payment_intent")
    return pi.get("id") if isinstance(pi, dict) else pi


async def _handle_checkout_pass(session: dict, db: AsyncSession) -> None:
    """Session Checkout terminée : seules celles d'un pass nous concernent (les
    abonnements arrivent par `customer.subscription.*`)."""
    from services import passes

    if (session.get("metadata") or {}).get("type") != "pass":
        return
    try:
        await passes.accorder(db, session)
    except passes.PassInvalide as e:
        # Session signée par Stripe mais qui ne justifie pas l'accès (montant
        # différent, non payée…) : rien n'est accordé, l'exploitant est alerté par
        # le journal d'erreurs. Pas d'exception : Stripe la relivrerait en boucle.
        log.error("stripe.pass_refuse", session=session.get("id"), raison=str(e))


async def _find_user_by_customer(customer_id: str, db: AsyncSession) -> Optional[User]:
    result = await db.execute(select(User).where(User.stripe_customer_id == customer_id))
    return result.scalar_one_or_none()


def _ts(sub: dict, key: str):
    """Convertit un timestamp Stripe en datetime UTC, None si absent (gardes .get :
    selon l'event/la version d'API la clé peut manquer → éviter un KeyError → 500 →
    retry Stripe en boucle).

    Repli sur l'ARTICLE d'abonnement : les versions récentes de l'API portent
    `current_period_start`/`current_period_end` sur `items.data[0]` et non plus sur
    l'objet abonnement. D'où trois lignes `subscriptions` avec des périodes NULL en
    production (constaté le 2026-08-20).
    """
    v = sub.get(key)
    if v is None:
        try:
            v = sub["items"]["data"][0].get(key)
        except (KeyError, IndexError, TypeError):
            v = None
    return datetime.fromtimestamp(v, tz=timezone.utc) if v else None


def _montant_cents(sub: dict) -> Optional[int]:
    """Prix réel facturé, en centimes. Lu sur le price Stripe, jamais sur une
    table de prix codée en dur — celle de `/admin/revenue` annonçait 9,90 € et
    19,90 € alors que Stripe facture 12,00 € et 19,00 €."""
    try:
        return sub["items"]["data"][0]["price"].get("unit_amount")
    except (KeyError, IndexError, TypeError):
        return None


def _plan_from_sub(sub: dict) -> Optional[str]:
    """Plan dérivé du price_id réel. None si price inconnu → on N'ACCORDE PAS de plan
    par défaut (l'ancien fallback 'standard' donnait un accès payant gratuitement)."""
    try:
        price_id = sub["items"]["data"][0]["price"]["id"]
    except (KeyError, IndexError, TypeError):
        return None
    return PLAN_FROM_PRICE.get(price_id)


async def _handle_subscription_created(sub: dict, db: AsyncSession):
    user = await _find_user_by_customer(sub.get("customer"), db)
    if not user:
        log.warning("stripe.webhook.user_not_found", customer=sub.get("customer"))
        return

    # Idempotence : si l'abonnement existe déjà (re-livraison/retry), on délègue à
    # l'update plutôt que de créer un doublon (qui faussait MRR/ARR).
    existing = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub.get("id"))
    )
    if existing.scalar_one_or_none() is not None:
        await _handle_subscription_updated(sub, db)
        return

    plan = _plan_from_sub(sub)
    if plan is None:
        log.error("stripe.unknown_price", sub=sub.get("id"))
        return  # ne PAS accorder de plan sur un price non mappé

    deja = await _subs_vivantes(user.user_id, db)
    if deja:
        # Ne devrait plus arriver (sessions expirées, contrôle Stripe au checkout) :
        # si c'est le cas, l'exploitant le sait tout de suite.
        log.error("stripe.second_abonnement_cree", user_id=user.user_id, sub=sub.get("id"),
                  existants=[d.stripe_subscription_id for d in deja])
        try:
            from services.alerts import send_email
            await send_email(
                to="contact@blackturf.fr",
                subject=f"[BlackTurf] Second abonnement créé — {user.email}",
                html=f"<p>Nouvel abonnement {sub.get('id')} alors que "
                     f"{', '.join(d.stripe_subscription_id or '?' for d in deja)} court déjà. "
                     f"À vérifier (double prélèvement possible).</p>",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("stripe.alerte_doublon_echouee", error=str(e)[:120])

    price_id = sub["items"]["data"][0]["price"]["id"]
    recurring = (sub["items"]["data"][0]["price"].get("recurring") or {})
    periodicite = "annual" if recurring.get("interval") == "year" or "annual" in price_id else "monthly"

    import uuid
    statut_reel = sub.get("status")
    est_active = statut_reel in ("active", "trialing")

    # Carte déjà présentée par un AUTRE compte : c'est le contournement du verrou
    # d'essai (nouvelle adresse e-mail, même carte). Contrôle définitif — ici la
    # carte du checkout est enfin connue de Stripe.
    verdict_carte, carte_connue = await _controler_carte(user, sub, db)
    if verdict_carte == "bloque":
        try:
            stripe.Subscription.delete(sub["id"])
        except Exception as e:  # noqa: BLE001
            log.error("stripe.annulation_carte_refusee_echouee", sub=sub.get("id"),
                      error=str(e)[:150])
        await journaliser(db, "carte_refusee_autre_compte", user, None, plan=plan,
                          stripe_subscription_id=sub["id"],
                          montant_cents=_montant_cents(sub),
                          detail=_detail_carte(carte_connue))
        await db.commit()
        log.warning("stripe.abonnement_refuse_carte", user_id=user.user_id,
                    sub=sub.get("id"))
        return

    # Essai refusé : on coupe la période gratuite SUR-LE-CHAMP côté Stripe, ce qui
    # déclenche la facturation immédiate. Le compte n'obtient l'accès qu'au
    # paiement effectif (`invoice.payment_succeeded`), jamais avant.
    essai_refuse = (verdict_carte == "essai_refuse"
                    and statut_reel == "trialing"
                    and _ts(sub, "trial_end") is not None)
    if essai_refuse:
        try:
            maj = stripe.Subscription.modify(sub["id"], trial_end="now")
            statut_reel = maj.get("status") or statut_reel
        except Exception as e:  # noqa: BLE001
            # On n'a pas pu couper l'essai : on refuse quand même l'accès. L'essai
            # courra chez Stripe, mais sans rien livrer — l'inverse (accès accordé
            # « en attendant ») serait précisément le produit offert qu'on bloque.
            log.error("stripe.fin_essai_forcee_echouee", sub=sub.get("id"),
                      error=str(e)[:150])
        est_active = False

    # Essai ouvert sans carte : l'abonnement est enregistré, mais il n'ouvre
    # aucun accès tant qu'un moyen de paiement n'est pas rattaché.
    sans_carte = (statut_reel == "trialing" and not _a_moyen_de_paiement(sub))
    if essai_refuse:
        statut_local = "incomplete"
        sans_carte = False
    elif sans_carte:
        statut_local = STATUT_SANS_CARTE
    elif est_active:
        statut_local = "active"
    else:
        statut_local = statut_reel

    subscription = Subscription(
        sub_id=str(uuid.uuid4()),
        user_id=user.user_id,
        stripe_subscription_id=sub["id"],
        plan=plan,
        periodicite=periodicite,
        statut=statut_local,
        periode_debut=_ts(sub, "current_period_start"),
        periode_fin=_ts(sub, "current_period_end"),
        # Essai refusé = essai inexistant : le garder en base ferait croire au
        # suivi admin (et au client) qu'une période gratuite court encore.
        essai_fin=None if essai_refuse else _ts(sub, "trial_end"),
    )
    db.add(subscription)

    # BUG corrigé (2026-08-17) : le plan était accordé ICI même quand `statut_reel`
    # valait "incomplete" (carte non validée / 3-D Secure non terminé / checkout
    # abandonné avant confirmation) — Stripe émet quand même `subscription.created`
    # dès la création de l'objet, avant paiement effectif. Résultat : un compte
    # affiché comme abonné côté site sans paiement réel. On aligne sur
    # _handle_subscription_updated, qui lui vérifiait déjà le statut.
    if est_active:
        # L'essai est consommé ICI, quand Stripe confirme qu'il a bien démarré —
        # pas à l'ouverture du checkout, sinon une session abandonnée brûlerait le
        # droit à l'essai d'un client qui n'a rien obtenu. Il est consommé MÊME
        # sans carte : l'essai a bien été ouvert.
        if subscription.essai_fin is not None and user.essai_utilise_at is None:
            user.essai_utilise_at = datetime.now(timezone.utc)
            log.info("stripe.essai_consomme", user_id=user.user_id, plan=plan)
        if not sans_carte:
            user.plan = await _avec_offert(user.user_id, plan, db)

    if essai_refuse:
        await journaliser(db, "essai_refuse_carte_reutilisee", user, subscription,
                          montant_cents=_montant_cents(sub),
                          detail=_detail_carte(carte_connue))
    elif statut_local in (STATUT_SANS_CARTE, "active"):
        await journaliser(
            db,
            STATUT_SANS_CARTE if sans_carte
            else ("essai_ouvert" if subscription.essai_fin else "abonnement_actif"),
            user, subscription,
            montant_cents=_montant_cents(sub),
        )

    await db.commit()
    log.info("stripe.subscription_created", user_id=user.user_id, plan=plan,
             statut=statut_reel, plan_accorde=est_active and not sans_carte,
             sans_carte=sans_carte, essai_refuse=essai_refuse)


def _resiliation_programmee(sub: dict) -> bool:
    """Vrai si l'abonnement s'arrêtera seul à l'échéance.

    Le portail client récent pose `cancel_at` (date) plutôt que
    `cancel_at_period_end` : les deux formes sont lues.
    """
    return bool(sub.get("cancel_at_period_end") or sub.get("cancel_at"))


async def _handle_subscription_updated(sub: dict, db: AsyncSession):
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await _handle_subscription_created(sub, db)
        return

    if subscription.statut == "canceled" and sub.get("status") != "canceled":
        # Clos de notre côté (impayé perdu) : un `updated` arrivé dans le désordre
        # ne doit ni rouvrir l'accès ni journaliser un « abonnement actif ».
        # Un abonnement clos chez Stripe ne se réactive jamais.
        log.info("stripe.updated_ignore_abonnement_clos", sub=sub.get("id"),
                 statut_stripe=sub.get("status"))
        return

    # Stripe ne garantit pas l'ordre des événements : un `updated(past_due)` ancien
    # arrivé après le paiement recoupait l'accès d'un client à jour. On applique
    # l'état ACTUEL de l'abonnement, relu chez Stripe.
    if _stripe_joignable():
        try:
            sub = stripe.Subscription.retrieve(sub["id"])
        except Exception as e:  # noqa: BLE001
            log.warning("stripe.relecture_updated_echouee", sub=sub.get("id"), error=str(e)[:120])

    plan = _plan_from_sub(sub)
    if plan is None:
        # Prix inconnu (variable d'environnement changée) : on garde la formule
        # connue mais on applique quand même le statut (impayé, résiliation).
        log.error("stripe.unknown_price", sub=sub.get("id"))
        plan = subscription.plan

    plan_precedent = subscription.plan
    statut_precedent = subscription.statut

    statut_stripe = sub.get("status")
    sans_carte = (statut_stripe == "trialing" and not _a_moyen_de_paiement(sub))

    subscription.plan = plan
    if sans_carte:
        subscription.statut = STATUT_SANS_CARTE
    elif statut_stripe in ("active", "trialing"):
        # Une résiliation programmée reste `active`/`trialing` chez Stripe jusqu'à
        # l'échéance : seul le drapeau la distingue. Sans lui, le webhook qui suit
        # `/stripe/cancel` d'une seconde ÉCRASAIT `cancel_at_period_end` par
        # `active` et journalisait « Abonnement actif » — la résiliation
        # disparaissait du suivi admin (constaté le 2026-09-16 sur 3 comptes).
        subscription.statut = ("cancel_at_period_end" if _resiliation_programmee(sub)
                               else "active")
    else:
        subscription.statut = statut_stripe
    subscription.periode_debut = _ts(sub, "current_period_start") or subscription.periode_debut
    subscription.periode_fin = _ts(sub, "current_period_end") or subscription.periode_fin
    subscription.essai_fin = _ts(sub, "trial_end") or subscription.essai_fin

    user = await _find_user_by_customer(sub.get("customer"), db)
    if user:
        if subscription.statut in STATUTS_ACCES:
            user.plan = await _avec_offert(user.user_id, plan, db)
            if subscription.essai_fin is not None and user.essai_utilise_at is None:
                user.essai_utilise_at = datetime.now(timezone.utc)
        else:
            # Un autre abonnement peut encore courir : ne pas rétrograder à l'aveugle.
            user.plan = await _plan_effectif(
                user.user_id, db, sauf_stripe_id=subscription.stripe_subscription_id
            )

        # On ne journalise QUE ce qui change : Stripe émet `subscription.updated`
        # pour bien des remous internes (compteurs d'essai, métadonnées), et un
        # e-mail par remous rendrait la supervision illisible.
        if statut_precedent == STATUT_SANS_CARTE and subscription.statut in STATUTS_ACCES:
            await journaliser(db, "carte_ajoutee", user, subscription,
                              montant_cents=_montant_cents(sub))
        elif plan_precedent != plan:
            await journaliser(db, "changement_plan", user, subscription,
                              plan_precedent=plan_precedent,
                              montant_cents=_montant_cents(sub))
        elif statut_precedent != subscription.statut:
            if subscription.statut == "cancel_at_period_end":
                # Résiliation faite hors du site (portail Stripe, tableau de bord).
                type_ = "resiliation_demandee"
            elif (statut_precedent == "cancel_at_period_end"
                  and subscription.statut == "active"):
                type_ = "resiliation_annulee"
            elif subscription.statut in STATUTS_ACCES:
                type_ = "abonnement_actif"
            else:
                type_ = subscription.statut
            await journaliser(db, type_, user, subscription,
                              montant_cents=_montant_cents(sub),
                              detail={"statut_precedent": statut_precedent})

    await db.commit()
    log.info("stripe.subscription_updated", plan=plan, statut=subscription.statut,
             sans_carte=sans_carte)


async def _handle_subscription_deleted(sub: dict, db: AsyncSession):
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
    )
    subscription = result.scalar_one_or_none()
    statut_precedent = subscription.statut if subscription else None
    if subscription:
        subscription.statut = "canceled"

    user = await _find_user_by_customer(sub["customer"], db)
    if user and statut_precedent == "canceled":
        # Déjà clos de notre côté (impayé perdu, cf. services.relances_paiement) :
        # le mouvement est journalisé, ne pas y ajouter une « résiliation ».
        pass
    elif user:
        # Un essai qui meurt faute de carte n'est pas une résiliation : c'est un
        # prospect qui n'a jamais converti. Les confondre fausserait le churn.
        await journaliser(
            db,
            "essai_termine_sans_carte" if statut_precedent == STATUT_SANS_CARTE
            else "resilie",
            user, subscription,
            stripe_subscription_id=sub["id"],
            montant_cents=_montant_cents(sub),
            detail={"statut_precedent": statut_precedent},
        )
        # `free` seulement s'il ne reste RIEN. Poser `free` inconditionnellement
        # coupait l'accès dès la fin du premier abonnement, même quand un second
        # courait encore (constaté le 2026-08-20 : 3 essais expirant à 24 h d'écart).
        user.plan = await _plan_effectif(user.user_id, db, sauf_stripe_id=sub["id"])

    await db.commit()
    log.info("stripe.subscription_deleted", customer=sub["customer"],
             plan_restant=user.plan if user else None)


def _sub_id_facture(invoice: dict) -> Optional[str]:
    """Abonnement auquel se rattache une facture.

    `invoice.subscription` a DISPARU des versions d'API récentes (le compte tourne
    en 2026-05-27.dahlia) : l'identifiant est descendu dans
    `parent.subscription_details.subscription`, et en dernier recours sur la ligne
    de facture. Sans ce repli, `invoice.payment_failed` ne retrouvait jamais
    l'abonnement — l'échec de paiement était donc journalisé sans JAMAIS couper
    l'accès (constaté le 2026-08-27, avant tout premier débit réel).
    """
    def _id(v) -> Optional[str]:
        if isinstance(v, str):
            return v
        if isinstance(v, dict):
            return v.get("id")
        return None

    direct = _id(invoice.get("subscription"))
    if direct:
        return direct

    details = (invoice.get("parent") or {}).get("subscription_details") or {}
    via_parent = _id(details.get("subscription"))
    if via_parent:
        return via_parent

    try:
        ligne = invoice["lines"]["data"][0]
        details_ligne = (ligne.get("parent") or {}).get("subscription_item_details") or {}
        return _id(details_ligne.get("subscription")) or _id(ligne.get("subscription"))
    except (KeyError, IndexError, TypeError):
        return None


async def _handle_payment_succeeded(invoice: dict, db: AsyncSession):
    """Un paiement passe : l'accès est rendu immédiatement.

    Contrepartie indispensable du blocage sur échec (cf. `_handle_payment_failed`) :
    sans ce traitement, un client dont la carte finit par passer resterait coupé
    jusqu'au prochain remous de son abonnement.

    Les factures à 0 € (ouverture d'un essai) ne prouvent aucun paiement et ne
    rendent donc aucun accès.
    """
    sub_id = _sub_id_facture(invoice)
    montant = invoice.get("amount_paid") or 0
    log.info("stripe.payment_succeeded", invoice_id=invoice.get("id"),
             sub=sub_id, montant_cents=montant)
    if montant <= 0:
        # Facture soldée par le crédit du client : rien d'encaissé, mais la
        # remise de parrainage d'un filleul est consommée.
        client = await _find_user_by_customer(invoice.get("customer"), db)
        if client is not None:
            if (invoice.get("total") or 0) > 0:
                await parrainage.sur_facture_reglee_par_credit(client, invoice, db)
            # Facture d'un parrain réglée (0 € : entièrement couverte par ses
            # crédits) : un nouveau mois commence, ses crédits reportés sont posés.
            await parrainage.liberer_credits(client, db)
            await db.commit()
        return

    user = await _find_user_by_customer(invoice.get("customer"), db)
    # Formule FACTURÉE (prix de la ligne), pas celle du compte : un abonné peut
    # régler une facture Expert après être repassé en Standard (2026-09-29).
    from services.revenus_stripe import ligne_facturee
    prix_facture = ligne_facturee(invoice)[0]
    plan_facture = PLAN_FROM_PRICE.get(prix_facture) if prix_facture else None
    sub = None
    if sub_id:
        sub = (await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )).scalar_one_or_none()
    if user is None or sub is None:
        # Stripe ne garantit pas l'ORDRE des webhooks : une facture payée peut
        # arriver avant `customer.subscription.created`. L'ancien code repartait
        # sans rien écrire — l'argent était encaissé mais absent du journal (écart
        # constaté le 2026-09-25 sur l'écran Revenus). On ne touche à aucun accès
        # ici (l'abonnement le fera en arrivant), mais l'encaissement est journalisé.
        await journaliser(db, "paiement_recu", user, None,
                          stripe_subscription_id=sub_id,
                          montant_cents=montant,
                          detail={"facture": invoice.get("id"),
                                  "motif": invoice.get("billing_reason"),
                                  "client_stripe": invoice.get("customer"),
                                  "abonnement_pas_encore_connu": sub is None,
                                  "compte_inconnu": user is None,
                                  "plan_facture": plan_facture})
        if user is not None:
            await parrainage.sur_paiement(user, invoice, db)
        await db.commit()
        log.warning("stripe.paiement_journalise_sans_abonnement",
                    invoice_id=invoice.get("id"), sub=sub_id, montant_cents=montant)
        return

    if sub.statut == "canceled":
        # Abonnement clos chez nous (impayé perdu) : un paiement tardif (facture
        # hébergée payée, événement dans le désordre) ne le rouvre PAS — aucun
        # abonnement Stripe vivant ne viendrait jamais retirer cet accès. Il est
        # journalisé et signalé pour remboursement.
        await journaliser(db, "paiement_recu", user, sub,
                          montant_cents=montant,
                          detail={"facture": invoice.get("id"),
                                  "motif": invoice.get("billing_reason"),
                                  "plan_facture": plan_facture,
                                  "abonnement_clos": True,
                                  "a_rembourser": True})
        await db.commit()
        log.error("stripe.paiement_sur_abonnement_clos", sub=sub_id, montant_cents=montant,
                  email=user.email)
        try:
            from services.alerts import send_email
            await send_email(
                to="contact@blackturf.fr",
                subject=f"[BlackTurf] Paiement reçu sur un abonnement clos — {user.email}",
                html=f"<p>{montant / 100:.2f} € encaissés (facture {invoice.get('id')}) sur "
                     f"l'abonnement clos {sub_id}. Accès NON rouvert : à rembourser ou "
                     f"réabonner à la main.</p>",
            )
        except Exception as e:  # noqa: BLE001
            log.warning("stripe.alerte_paiement_clos_echouee", error=str(e)[:120])
        return

    reprise = sub.statut not in STATUTS_ACCES
    if reprise:
        sub.statut = "active"
    # Un essai facturé est un essai terminé : la date de fin ne doit plus laisser
    # croire à une période gratuite en cours.
    fin_dessai = sub.essai_fin is not None
    if fin_dessai:
        sub.essai_fin = None
    user.plan = await _plan_effectif(user.user_id, db)

    # Journalisé à CHAQUE encaissement réel, pas seulement quand l'accès reprend.
    # Un abonnement déjà `active` qui bascule de l'essai au payant ne changeait
    # aucun statut : le tout premier euro encaissé serait passé sans un mot, ni
    # dans le journal admin ni par e-mail. C'est le mouvement que l'exploitant
    # attend le plus.
    await journaliser(db, "paiement_recu", user, sub,
                      montant_cents=montant,
                      detail={"facture": invoice.get("id"),
                              "motif": invoice.get("billing_reason"),
                              "premier_paiement_apres_essai": fin_dessai,
                              # État CONSTATÉ après traitement, jamais une
                              # comparaison avant/après : cf. `_handle_payment_failed`.
                              "plan_apres": user.plan,
                              "plan_facture": plan_facture,
                              "acces_ouvert": user.plan != "free"})
    # Premier vrai paiement d'un filleul : c'est lui, et lui seul, qui crédite le
    # parrain. Les factures à 0 € sont écartées plus haut.
    await parrainage.sur_paiement(user, invoice, db)
    # Et si ce client est lui-même parrain : nouveau mois, crédits reportés posés.
    await parrainage.liberer_credits(user, db)
    await db.commit()
    log.info("stripe.acces_retabli" if reprise else "stripe.paiement_encaisse",
             user_id=user.user_id, plan=user.plan, montant_cents=montant)


async def _handle_payment_failed(invoice: dict, db: AsyncSession):
    """Paiement en échec : accès coupé, compte rétrogradé.

    Décision de l'exploitant du 2026-08-27. Avant, l'abonnement passait `past_due`
    et `past_due` donnait accès : Stripe relançant la carte jusqu'à trois semaines,
    le produit restait livré tout ce temps sans un centime encaissé — le scénario
    exact de la carte prépayée vidée à la fin de l'essai.

    L'abonnement Stripe, lui, N'EST PAS annulé : le premier paiement qui passe rend
    l'accès dans la seconde.

    Depuis le 2026-09-16, ce n'est plus Stripe qui relance (jusqu'à 8 refus en
    13 jours sur un compte : l'effet « site arnaque »). Sa collecte automatique est
    coupée dès le premier refus ; `services.relances_paiement` retente à J+3 et J+7
    puis clôt l'abonnement.
    """
    from services.relances_paiement import (couper_collecte_stripe, premier_refus,
                                            prochaine_relance)

    sub_id = _sub_id_facture(invoice)
    user = await _find_user_by_customer(invoice.get("customer"), db)
    if not user:
        log.warning("stripe.payment_failed_user_inconnu", customer=invoice.get("customer"))
        return

    if sub_id and _changement_en_attente(invoice, sub_id):
        # Différence d'un passage Standard → Expert refusée : la formule payée
        # reste en place, rien n'est impayé. Couper l'accès ici (ancien code)
        # privait un client à jour de sa formule payée, et les relances pouvaient
        # finir par CLORE son abonnement.
        abo = (await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )).scalar_one_or_none()
        await journaliser(db, "changement_formule_refuse", user, abo,
                          stripe_subscription_id=sub_id,
                          montant_cents=invoice.get("amount_due"),
                          detail={"facture": invoice.get("id")})
        await db.commit()
        log.warning("stripe.changement_formule_paiement_refuse", sub=sub_id)
        return

    sub = None
    if sub_id:
        sub = (await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )).scalar_one_or_none()
    if sub is not None:
        sub.statut = "past_due"

    facture_id = invoice.get("id")
    if facture_id and invoice.get("auto_advance") is not False:
        couper_collecte_stripe(facture_id)
    debut = (await premier_refus(db, facture_id) if facture_id else None) or datetime.now(timezone.utc)
    relance = prochaine_relance(debut, invoice.get("attempt_count") or 1)

    plan_precedent = user.plan
    # `past_due` ne fait plus partie des statuts d'accès : l'abonnement en échec
    # est écarté du calcul, un AUTRE abonnement vivant peut encore porter le compte.
    user.plan = await _plan_effectif(user.user_id, db, sauf_stripe_id=sub_id)

    # L'état est CONSTATÉ, pas déduit d'une comparaison avant/après. Le premier
    # impayé réel (2026-08-27) a montré pourquoi : `customer.subscription.updated`
    # arrive 4 secondes AVANT `invoice.payment_failed` et a déjà rétrogradé le
    # compte, si bien que le plan ne bougeait plus ici. Le journal affichait donc
    # « accès coupé : non » alors que l'accès était bel et bien coupé — l'état
    # juste avec l'étiquette qui ment, le pire des deux mondes pour qui relit.
    await journaliser(db, "paiement_echoue", user, sub,
                      plan_precedent=plan_precedent if plan_precedent != user.plan else None,
                      stripe_subscription_id=sub_id,
                      montant_cents=invoice.get("amount_due"),
                      detail={"facture": invoice.get("id"),
                              "tentative": invoice.get("attempt_count"),
                              # Prochaine relance planifiée par NOUS (None = plus aucune).
                              "prochaine_relance": int(relance.timestamp()) if relance else None,
                              "motif": invoice.get("billing_reason"),
                              "plan_apres": user.plan,
                              "acces_ouvert": user.plan != "free"})
    await db.commit()

    log.warning("stripe.payment_failed", customer=invoice.get("customer"),
                sub=sub_id, plan_precedent=plan_precedent, plan=user.plan,
                abonnement_connu=sub is not None)


def _changement_en_attente(invoice: dict, sub_id: str) -> bool:
    """Vrai si la facture refusée est la différence d'un changement de formule en
    attente de paiement, sur un abonnement par ailleurs à jour.

    Pas la fin d'essai refusée (même motif `subscription_update`) : là
    l'abonnement lui-même est impayé (`past_due`), et c'est bien un impayé."""
    if invoice.get("billing_reason") != "subscription_update" or not _stripe_joignable():
        return False
    try:
        live = stripe.Subscription.retrieve(sub_id)
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.relecture_abo_echouee", sub=sub_id, error=str(e)[:120])
        return False
    return bool(live.get("pending_update")) or live.get("status") in ("active", "trialing")


async def _handle_trial_will_end(sub: dict, db: AsyncSession):
    """Stripe prévient 3 jours avant la fin d'un essai. C'est le moment où
    l'exploitant peut encore relancer un prospect qui n'a pas mis sa carte."""
    user = await _find_user_by_customer(sub.get("customer"), db)
    if not user:
        return
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
    )
    abo = result.scalar_one_or_none()
    await journaliser(db, "essai_bientot_fini", user, abo,
                      plan=_plan_from_sub(sub),
                      stripe_subscription_id=sub["id"],
                      essai_fin=_ts(sub, "trial_end"),
                      montant_cents=_montant_cents(sub),
                      detail={"carte_enregistree": _a_moyen_de_paiement(sub)})
    await db.commit()


async def _regler_impaye_apres_nouvelle_carte(abo: Subscription, user: User,
                                              db: AsyncSession) -> None:
    if not _stripe_joignable() or not abo.stripe_subscription_id:
        return
    from services.relances_paiement import relances_faites
    try:
        live = stripe.Subscription.retrieve(abo.stripe_subscription_id)
        if live.get("status") not in ("past_due", "unpaid"):
            return
        ouvertes = list(stripe.Invoice.list(subscription=abo.stripe_subscription_id,
                                            status="open", limit=5))
    except Exception as e:  # noqa: BLE001
        log.warning("stripe.impaye_relecture_echouee", sub=abo.stripe_subscription_id, error=str(e)[:120])
        return
    for facture in ouvertes:
        n, derniere = await relances_faites(db, facture["id"])
        if derniere is not None and datetime.now(timezone.utc) - derniere < timedelta(minutes=10):
            continue  # une tentative vient d'avoir lieu (double événement carte)
        resultat = None
        try:
            payee = stripe.Invoice.pay(facture["id"])
            resultat = payee.get("status")
        except stripe.error.CardError:
            resultat = "refusee"
        except Exception as e:  # noqa: BLE001
            log.warning("stripe.impaye_paiement_echoue", facture=facture.get("id"), error=str(e)[:120])
            continue
        await journaliser(db, "relance_paiement", user, abo, notifier=False,
                          montant_cents=facture.get("amount_due"),
                          detail={"facture": facture["id"], "numero": 1 + n,
                                  "resultat": resultat, "declencheur": "nouvelle_carte"})


async def _handle_moyen_paiement_ajoute(objet: dict, db: AsyncSession):
    """Une carte vient d'être rattachée : réévaluer les essais bloqués.

    Stripe n'émet PAS `customer.subscription.updated` quand une carte est
    attachée au client depuis le portail. Sans ce traitement, un abonné qui
    régularise resterait bloqué jusqu'au prochain remous de son abonnement —
    c'est-à-dire, en pratique, jusqu'à la fin de son essai.
    """
    customer_id = objet.get("customer") or objet.get("id")
    if not customer_id:
        return
    user = await _find_user_by_customer(customer_id, db)
    if not user:
        return

    # Toute carte qui passe par ici est mémorisée, qu'un essai soit bloqué ou non :
    # c'est ce qui alimente le verrou « une carte = un seul essai gratuit ».
    verdict_carte, carte_connue = await _controler_carte(user, {"customer": customer_id}, db)

    # Impayé + nouvelle carte : le profil promet l'accès « dès que le paiement
    # passe ». Stripe ne retente plus seul (collecte coupée au premier refus) :
    # on tente UNE fois, comptée comme une relance.
    for impaye in (await db.execute(
        select(Subscription).where(Subscription.user_id == user.user_id,
                                   Subscription.statut == "past_due")
    )).scalars().all():
        await _regler_impaye_apres_nouvelle_carte(impaye, user, db)

    bloques = (await db.execute(
        select(Subscription).where(
            Subscription.user_id == user.user_id,
            Subscription.statut == STATUT_SANS_CARTE,
        )
    )).scalars().all()
    if not bloques:
        await db.commit()
        return

    debloques = 0
    for abo in bloques:
        try:
            sub_stripe = stripe.Subscription.retrieve(abo.stripe_subscription_id)
        except Exception as e:  # noqa: BLE001
            log.warning("stripe.relecture_abo_echouee", sub=abo.stripe_subscription_id,
                        error=str(e)[:120])
            continue
        if sub_stripe.get("status") not in ("trialing", "active"):
            continue
        if not _a_moyen_de_paiement(sub_stripe):
            continue

        # La carte qui débloque l'essai appartient à un autre compte : elle
        # régularise le moyen de paiement, elle n'offre pas 7 jours de plus.
        if verdict_carte != "ok" and sub_stripe.get("status") == "trialing":
            try:
                stripe.Subscription.modify(abo.stripe_subscription_id, trial_end="now")
            except Exception as e:  # noqa: BLE001
                log.error("stripe.fin_essai_forcee_echouee", sub=abo.stripe_subscription_id,
                          error=str(e)[:150])
            abo.statut = "incomplete"
            abo.essai_fin = None
            await journaliser(db, "essai_refuse_carte_reutilisee", user, abo,
                              montant_cents=_montant_cents(sub_stripe),
                              detail=_detail_carte(carte_connue))
            continue

        abo.statut = "active"
        debloques += 1
        await journaliser(db, "carte_ajoutee", user, abo,
                          montant_cents=_montant_cents(sub_stripe))

    if debloques:
        user.plan = await _plan_effectif(user.user_id, db)
        await db.commit()
        log.info("stripe.acces_debloque", user_id=user.user_id, plan=user.plan,
                 abonnements=debloques)
