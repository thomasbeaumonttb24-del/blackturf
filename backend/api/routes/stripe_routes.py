"""
Stripe routes — BlackTurf.
Checkout, webhooks, portail client.
"""
import structlog
import stripe
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, Header
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from api.config import get_settings
from api.routes.auth import get_current_user, require_verified_email
from db.database import get_db
from db.models import CarteConnue, Subscription, User
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
    if not subs:
        return "free"
    return max((s.plan for s in subs), key=lambda p: RANG_PLAN.get(p, 0))


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


async def _memoriser_cartes(user: User, cartes: list[dict], db: AsyncSession) -> None:
    """Enregistre les cartes vues. Le PREMIER compte qui présente une carte la garde.

    Une carte présentée par un second compte n'est pas réattribuée : on incrémente
    seulement son compteur de tentatives, qui sert de signal de fraude organisée.
    """
    maintenant = datetime.now(timezone.utc)
    for carte in cartes:
        connue = await db.get(CarteConnue, carte["empreinte"])
        if connue is None:
            db.add(CarteConnue(
                empreinte=carte["empreinte"],
                user_id=user.user_id,
                email=user.email,
                stripe_payment_method_id=carte.get("pm"),
                marque=carte.get("marque"),
                dernier4=carte.get("dernier4"),
                financement=carte.get("financement"),
                premiere_vue=maintenant,
                derniere_vue=maintenant,
            ))
            continue
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

    conflit = None if politique == "ignorer" else await _carte_dun_autre_compte(user, cartes, db)
    await _memoriser_cartes(user, cartes, db)
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
    if vivants:
        courant = vivants[0]
        if courant.plan == plan_cible and courant.periodicite == body.periodicite:
            raise HTTPException(
                status_code=409,
                detail="Vous êtes déjà abonné à cette formule. "
                       "Gérez votre abonnement depuis votre profil.",
            )
        return await _changer_de_plan(user, vivants, plan_cible, body.periodicite,
                                      price_id, db)

    # Récupérer ou créer le customer Stripe
    customer_id = user.stripe_customer_id
    if not customer_id:
        customer = stripe.Customer.create(
            email=user.email,
            name=f"{user.prenom or ''} {user.nom or ''}".strip() or user.email,
            metadata={"user_id": user.user_id},
        )
        customer_id = customer.id
        user.stripe_customer_id = customer_id
        await db.commit()

    # 2) Essai gratuit : une seule fois par compte.
    #
    # Stripe ne déduplique pas les essais par client : sans ce contrôle, le cycle
    # « essai → annulation → nouveau checkout » rendait le produit gratuit à vie
    # (constaté en production le 2026-08-20, 3 essais ouverts en 24 h sur un même
    # compte). La consommation est enregistrée par le webhook, quand Stripe
    # confirme l'essai — un checkout abandonné ne brûle donc rien.
    droit_a_lessai = user.essai_utilise_at is None

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

    subscription_data: dict = {
        "metadata": {"user_id": user.user_id, "plan": plan_cible},
    }
    if droit_a_lessai:
        # Essai gratuit 7 jours : Standard ET Expert (alignés, cf. page /tarifs).
        subscription_data["trial_period_days"] = 7
        # Filet de sécurité : si la carte disparaît d'ici la fin de l'essai
        # (supprimée depuis le portail), on annule au lieu de laisser traîner un
        # impayé — le webhook repasse alors l'utilisateur en `free`.
        subscription_data["trial_settings"] = {
            "end_behavior": {"missing_payment_method": "cancel"}
        }

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
        allow_promotion_codes=True,
        locale="fr",
    )

    log.info("stripe.checkout_created", user_id=user.user_id, plan=plan_cible,
             essai_accorde=droit_a_lessai)
    return {"url": session.url, "essai": droit_a_lessai}


async def _changer_de_plan(
    user: User,
    vivants: list[Subscription],
    plan_cible: str,
    periodicite: str,
    price_id: str,
    db: AsyncSession,
) -> dict:
    """Standard ↔ Expert : on MODIFIE l'abonnement existant.

    Avant le 2026-08-20, tout passage d'une formule à l'autre repassait par
    Checkout et créait un SECOND abonnement, le premier restant actif : le client
    était facturé deux fois. Ici, une seule ligne Stripe suit le client, la
    différence de prix est proratisée sur la prochaine facture, et l'essai en
    cours est conservé (Stripe garde `trial_end` lors d'un changement d'article).
    """
    courant = vivants[0]
    sub_stripe = stripe.Subscription.retrieve(courant.stripe_subscription_id)
    item_id = sub_stripe["items"]["data"][0]["id"]

    maj = stripe.Subscription.modify(
        courant.stripe_subscription_id,
        items=[{"id": item_id, "price": price_id}],
        # Crédit/débit au prorata reporté sur la prochaine facture : le client
        # obtient son nouveau plan tout de suite sans prélèvement surprise.
        proration_behavior="create_prorations",
        metadata={"user_id": user.user_id, "plan": plan_cible},
    )

    # Doublons hérités de l'ancien tunnel : un compte ne doit porter qu'UN
    # abonnement. Ceux encore en essai n'ont rien coûté, on les ferme sur-le-champ ;
    # ceux déjà payés courent jusqu'à l'échéance déjà réglée.
    for doublon in vivants[1:]:
        try:
            if doublon.statut == "trialing" or doublon.essai_fin is not None:
                stripe.Subscription.delete(doublon.stripe_subscription_id)
                doublon.statut = "canceled"
            else:
                stripe.Subscription.modify(doublon.stripe_subscription_id,
                                           cancel_at_period_end=True)
                doublon.statut = "cancel_at_period_end"
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
        if courant.statut != STATUT_SANS_CARTE:
            courant.statut = "active"
            user.plan = plan_cible
    await journaliser(db, "changement_plan", user, courant,
                      plan_precedent=plan_precedent,
                      montant_cents=_montant_cents(maj))
    await db.commit()

    log.info("stripe.plan_change", user_id=user.user_id, plan=plan_cible,
             sub=courant.stripe_subscription_id, doublons_fermes=len(vivants) - 1)
    return {
        "url": f"{settings.frontend_url}/abonnement/succes?plan={plan_cible}&change=1",
        "change_de_plan": True,
        "plan": plan_cible,
        "message": f"Votre abonnement est passé en {plan_cible.capitalize()}. "
                   "La différence est ajustée au prorata sur votre prochaine facture.",
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
        await send_email(
            to=user.email,
            subject="BlackTurf — Votre demande de résiliation",
            html="<p>Votre demande de résiliation a bien été enregistrée.</p>"
                 + ("<p>Votre abonnement prendra fin à l'échéance de la période en cours ; "
                    "vous gardez l'accès jusque-là.</p>" if cancelled_via_stripe else
                    "<p>Elle sera traitée sous 72h. Vous conservez l'accès jusqu'au traitement. "
                    "Pour toute question : contact@blackturf.fr</p>")
                 + "<hr/><p style='color:#666;font-size:11px;'>Jeu responsable — "
                   "joueurs-info-service.fr — 09 74 75 13 13</p>",
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
        "processed_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    ))
    if event_id:
        seen = await db.execute(text("SELECT 1 FROM stripe_events WHERE event_id = :e"),
                                {"e": event_id})
        if seen.first() is not None:
            log.info("stripe.webhook.duplicate_ignored", event_id=event_id)
            return {"ok": True}

    log.info("stripe.webhook", event_type=event_type, event_id=event_id)

    if event_type == "customer.subscription.created":
        await _handle_subscription_created(data, db)
    elif event_type == "customer.subscription.updated":
        await _handle_subscription_updated(data, db)
    elif event_type in ("customer.subscription.deleted", "customer.subscription.paused"):
        await _handle_subscription_deleted(data, db)
    elif event_type in ("invoice.payment_succeeded",):
        await _handle_payment_succeeded(data, db)
    elif event_type == "invoice.payment_failed":
        await _handle_payment_failed(data, db)
    elif event_type == "customer.subscription.trial_will_end":
        await _handle_trial_will_end(data, db)
    elif event_type in ("payment_method.attached", "customer.updated",
                        "setup_intent.succeeded"):
        # Une carte vient d'arriver : débloquer les essais mis en attente.
        await _handle_moyen_paiement_ajoute(data, db)

    # Marque l'event traité APRÈS le traitement métier (at-least-once + handlers
    # idempotents → aucun event perdu, aucun double-effet).
    if event_id:
        await db.execute(text(
            "INSERT INTO stripe_events (event_id, event_type) VALUES (:e, :t) "
            "ON CONFLICT (event_id) DO NOTHING"
        ), {"e": event_id, "t": event_type})
        await db.commit()

    return {"ok": True}


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
            user.plan = plan

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


async def _handle_subscription_updated(sub: dict, db: AsyncSession):
    result = await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub["id"])
    )
    subscription = result.scalar_one_or_none()
    if not subscription:
        await _handle_subscription_created(sub, db)
        return

    plan = _plan_from_sub(sub)
    if plan is None:
        log.error("stripe.unknown_price", sub=sub.get("id"))
        return

    plan_precedent = subscription.plan
    statut_precedent = subscription.statut

    statut_stripe = sub.get("status")
    sans_carte = (statut_stripe == "trialing" and not _a_moyen_de_paiement(sub))

    subscription.plan = plan
    if sans_carte:
        subscription.statut = STATUT_SANS_CARTE
    elif statut_stripe in ("active", "trialing"):
        subscription.statut = "active"
    else:
        subscription.statut = statut_stripe
    subscription.periode_debut = _ts(sub, "current_period_start") or subscription.periode_debut
    subscription.periode_fin = _ts(sub, "current_period_end") or subscription.periode_fin
    subscription.essai_fin = _ts(sub, "trial_end") or subscription.essai_fin

    user = await _find_user_by_customer(sub.get("customer"), db)
    if user:
        if subscription.statut in STATUTS_ACCES:
            user.plan = plan
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
            await journaliser(db, "abonnement_actif" if subscription.statut in STATUTS_ACCES
                              else subscription.statut, user, subscription,
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
    if user:
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
    if not sub_id or montant <= 0:
        return

    user = await _find_user_by_customer(invoice.get("customer"), db)
    if not user:
        return
    sub = (await db.execute(
        select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
    )).scalar_one_or_none()
    if sub is None:
        return

    reprise = sub.statut not in STATUTS_ACCES
    if reprise:
        sub.statut = "active"
    # Un essai facturé est un essai terminé : la date de fin ne doit plus laisser
    # croire à une période gratuite en cours.
    if sub.essai_fin is not None:
        sub.essai_fin = None
    user.plan = await _plan_effectif(user.user_id, db)

    if reprise:
        await journaliser(db, "paiement_recu", user, sub,
                          montant_cents=montant,
                          detail={"facture": invoice.get("id"),
                                  "motif": invoice.get("billing_reason")})
    await db.commit()
    log.info("stripe.acces_retabli" if reprise else "stripe.paiement_encaisse",
             user_id=user.user_id, plan=user.plan, montant_cents=montant)


async def _handle_payment_failed(invoice: dict, db: AsyncSession):
    """Paiement en échec : accès coupé, compte rétrogradé.

    Décision de l'exploitant du 2026-08-27. Avant, l'abonnement passait `past_due`
    et `past_due` donnait accès : Stripe relançant la carte jusqu'à trois semaines,
    le produit restait livré tout ce temps sans un centime encaissé — le scénario
    exact de la carte prépayée vidée à la fin de l'essai.

    L'abonnement Stripe, lui, N'EST PAS annulé : les relances suivent leur cours et
    le premier paiement qui passe rend l'accès dans la seconde.
    """
    sub_id = _sub_id_facture(invoice)
    user = await _find_user_by_customer(invoice.get("customer"), db)
    if not user:
        log.warning("stripe.payment_failed_user_inconnu", customer=invoice.get("customer"))
        return

    sub = None
    if sub_id:
        sub = (await db.execute(
            select(Subscription).where(Subscription.stripe_subscription_id == sub_id)
        )).scalar_one_or_none()
    if sub is not None:
        sub.statut = "past_due"

    plan_precedent = user.plan
    # `past_due` ne fait plus partie des statuts d'accès : l'abonnement en échec
    # est écarté du calcul, un AUTRE abonnement vivant peut encore porter le compte.
    user.plan = await _plan_effectif(user.user_id, db, sauf_stripe_id=sub_id)

    await journaliser(db, "paiement_echoue", user, sub,
                      plan_precedent=plan_precedent if plan_precedent != user.plan else None,
                      stripe_subscription_id=sub_id,
                      montant_cents=invoice.get("amount_due"),
                      detail={"facture": invoice.get("id"),
                              "tentative": invoice.get("attempt_count"),
                              "motif": invoice.get("billing_reason"),
                              "acces_coupe": plan_precedent != user.plan})
    await db.commit()

    log.warning("stripe.payment_failed", customer=invoice.get("customer"),
                sub=sub_id, plan_precedent=plan_precedent, plan=user.plan,
                abonnement_connu=sub is not None)


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
