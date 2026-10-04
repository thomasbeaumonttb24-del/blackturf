"""Passes sans renouvellement : jour (5 €), semaine (12 €), mois (24 €).

Décision de l'exploitant du 2026-10-04 : l'essai gratuit de 7 jours disparaît ;
à côté des abonnements (Standard 12 €/mois, Expert 19 €/mois), un accès Expert
payé une fois, coupé à l'échéance, sans rétractation ni remboursement.

Règles de sûreté — chacune ferme un contournement précis :

- RIEN n'est accordé sur la foi du navigateur. Le pass naît d'une session
  Stripe Checkout relue chez Stripe (page de retour) ou reçue signée (webhook),
  et `valider_session` en exige tout : mode paiement, payée, complète, montant
  et devise EXACTS du tarif de la durée, renonciation enregistrée, compte
  désigné par nos propres métadonnées (posées par le serveur à la création).
- UNE session = UN pass. Webhook et page de retour arrivent souvent ensemble :
  l'unicité de `stripe_session_id` en base tranche, le second appel ne fait rien.
- Pas de chevauchement perdu ni gagné : un pass acheté pendant qu'un autre court
  commence à la fin du précédent (le compte est verrouillé pendant le calcul,
  deux achats simultanés ne démarrent pas au même instant).
- Remboursement ou contestation bancaire = pass retiré aussitôt.
- Échéance appliquée à la seconde : `get_current_user` appelle
  `expirer_si_echu` pour un compte payant, et la tâche planifiée
  `job_expirer_passes` (chaque minute) couvre tout le reste (WebSocket, alertes).
- Le plan du compte n'est jamais écrit « à la main » : toujours
  `_plan_effectif`, qui prend la formule la plus haute entre abonnements,
  accès offerts et passes. Un abonné Standard qui prend un pass retrouve son
  Standard à l'échéance ; un pass n'efface jamais un abonnement.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PassAcces, User
from services.passes_catalogue import DEVISE, PASSES, lookup_key  # noqa: F401 (réexportés)

log = structlog.get_logger()

PLAN_PASS = "expert"


_PRIX_STRIPE: dict[str, str] = {}


def prix_stripe(duree: str) -> str | None:
    """Price ID Stripe du pass, retrouvé par sa lookup_key (mis en cache). None si
    le catalogue n'est pas en place : l'appelant facture alors le même montant en
    ligne (`price_data`) plutôt que de bloquer la vente. Le contrôle au paiement
    (montant exact) est identique dans les deux cas."""
    import stripe

    if duree in _PRIX_STRIPE:
        return _PRIX_STRIPE[duree]
    try:
        trouves = stripe.Price.list(lookup_keys=[lookup_key(duree)], active=True, limit=1).data
    except Exception as e:  # noqa: BLE001
        log.warning("passes.catalogue_illisible", duree=duree, error=str(e)[:150])
        return None
    prix = trouves[0] if trouves else None
    if (prix is None or prix.get("unit_amount") != PASSES[duree][0]
            or (prix.get("currency") or "").lower() != DEVISE or prix.get("recurring")):
        log.error("passes.prix_catalogue_absent_ou_faux", duree=duree, lookup_key=lookup_key(duree))
        return None
    _PRIX_STRIPE[duree] = prix["id"]
    return prix["id"]


# v2 : case cochée SUR la page de paiement Stripe (consent_collection), attestée
# par Stripe dans `session.consent`. v1 : case sur la page /tarifs (version du
# premier déploiement du 2026-10-04) — encore acceptée pour les sessions créées
# avant la bascule.
RENONCIATION_VERSION = "v2"
VERSIONS_RENONCIATION = ("v1", "v2")
RENONCIATION_TEXTE = (
    "Je demande l'accès immédiat au service et je renonce expressément à mon "
    "droit de rétractation. Paiement unique, sans renouvellement, non remboursable."
)


class PassInvalide(Exception):
    """Session Stripe qui ne justifie PAS l'octroi d'un pass."""


def _aware(d: Optional[datetime]) -> Optional[datetime]:
    return d.replace(tzinfo=timezone.utc) if d is not None and d.tzinfo is None else d


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def valider_session(session) -> dict:
    """Contrôle COMPLET d'une session Checkout. Renvoie les champs utiles ou lève
    PassInvalide. Ne fait confiance qu'à ce que Stripe a encaissé et à ce que le
    serveur a lui-même écrit dans les métadonnées."""
    meta = dict(session.get("metadata") or {})
    if meta.get("type") != "pass":
        raise PassInvalide("pas une session de pass")
    if session.get("mode") != "payment":
        raise PassInvalide("mode inattendu")
    if session.get("status") != "complete" or session.get("payment_status") != "paid":
        raise PassInvalide("paiement non encaissé")
    duree = meta.get("duree")
    if duree not in PASSES:
        raise PassInvalide("durée inconnue")
    prix = PASSES[duree][0]
    # Remise de parrainage (−5 €) : posée par le SERVEUR seulement (coupon à la
    # création de la session), jamais sur le Pass Jour. Le montant payé doit
    # alors valoir exactement prix − 5 €, remise comprise dans le détail Stripe.
    from services.parrainage import DUREES_PASS_PARRAINAGE, REMISE_CENTS
    remise = meta.get("remise_parrainage") == "1"
    if remise:
        remise_lue = int(((session.get("total_details") or {}).get("amount_discount")) or 0)
        if duree not in DUREES_PASS_PARRAINAGE or remise_lue != REMISE_CENTS:
            raise PassInvalide("remise de parrainage non conforme")
    attendu = prix - REMISE_CENTS if remise else prix
    if session.get("amount_total") != attendu or (session.get("currency") or "").lower() != DEVISE:
        raise PassInvalide("montant ou devise différents du tarif")
    user_id = meta.get("user_id")
    if not user_id:
        raise PassInvalide("compte absent")
    version = meta.get("renonciation_version")
    if version not in VERSIONS_RENONCIATION:
        raise PassInvalide("renonciation absente")
    if version == "v2":
        # La case est sur la page Stripe : Stripe refuse le paiement sans elle et
        # l'atteste ici. Horodatage = encaissement (la case précède le paiement).
        if ((session.get("consent") or {}).get("terms_of_service")) != "accepted":
            raise PassInvalide("renonciation non attestée par Stripe")
        renonciation_at = _maintenant()
    else:
        try:
            renonciation_at = _aware(datetime.fromisoformat(meta.get("renonciation_at") or ""))
        except ValueError:
            raise PassInvalide("renonciation illisible")
    pi = session.get("payment_intent")
    if isinstance(pi, dict):
        pi = pi.get("id")
    return {
        "renonciation_version": version,
        "session_id": session.get("id"),
        "user_id": user_id,
        "customer": session.get("customer"),
        "duree": duree,
        "montant_cents": attendu,
        "remise_parrainage": remise,
        "payment_intent": pi,
        "renonciation_at": renonciation_at,
    }


async def _fin_des_passes(db: AsyncSession, user_id: str) -> Optional[datetime]:
    """Fin du dernier pass actif encore à courir (les passes s'enchaînent)."""
    fin = (await db.execute(
        select(func.max(PassAcces.fin)).where(
            PassAcces.user_id == user_id, PassAcces.statut == "actif",
            PassAcces.fin > _maintenant(),
        )
    )).scalar_one_or_none()
    return _aware(fin)


async def pass_actif(db: AsyncSession, user_id: str) -> Optional[dict]:
    """Pass en cours : {plan, fin} — `fin` = fin de l'accès, passes enchaînés compris."""
    maintenant = _maintenant()
    en_cours = (await db.execute(
        select(PassAcces.pass_id).where(
            PassAcces.user_id == user_id, PassAcces.statut == "actif",
            PassAcces.debut <= maintenant, PassAcces.fin > maintenant,
        ).limit(1)
    )).scalar_one_or_none()
    if en_cours is None:
        return None
    return {"plan": PLAN_PASS, "fin": await _fin_des_passes(db, user_id)}


async def plan_pass_actif(db: AsyncSession, user_id: str) -> Optional[str]:
    actif = await pass_actif(db, user_id)
    return actif["plan"] if actif else None


async def accorder(db: AsyncSession, session) -> tuple[PassAcces, bool]:
    """Accorde le pass d'une session payée. Idempotent : (pass, créé maintenant ?).

    Lève PassInvalide si la session ne le justifie pas."""
    from api.routes.stripe_routes import _plan_effectif
    from services.abonnements import journaliser

    v = valider_session(session)
    deja = (await db.execute(
        select(PassAcces).where(PassAcces.stripe_session_id == v["session_id"])
    )).scalar_one_or_none()
    if deja is not None:
        return deja, False

    # Verrou sur le compte : deux passes payés au même instant ne calculent pas
    # le même début (sans quoi l'un des deux serait perdu).
    user = (await db.execute(
        select(User).where(User.user_id == v["user_id"]).with_for_update()
        .execution_options(populate_existing=True)
    )).scalar_one_or_none()
    if user is None:
        raise PassInvalide("compte introuvable")
    if v["customer"] and v["customer"] != user.stripe_customer_id:
        # Client Stripe rattaché à un AUTRE compte : métadonnées incohérentes, on
        # n'accorde rien (l'exploitant tranche, le paiement reste visible chez
        # Stripe). Un client orphelin — double clic qui a créé deux clients, le
        # second ayant écrasé le premier sur le compte — reste accepté : les
        # métadonnées sont posées par le serveur, le paiement est bien de ce compte.
        autre = (await db.execute(
            select(User.user_id).where(User.stripe_customer_id == v["customer"])
        )).scalar_one_or_none()
        if autre is not None and autre != user.user_id:
            log.error("passes.client_incoherent", session=v["session_id"], user_id=user.user_id)
            raise PassInvalide("client Stripe rattaché à un autre compte")

    maintenant = _maintenant()
    debut = max(maintenant, await _fin_des_passes(db, user.user_id) or maintenant)
    fin = debut + PASSES[v["duree"]][1]
    p = PassAcces(
        user_id=user.user_id, duree=v["duree"], plan=PLAN_PASS,
        montant_cents=v["montant_cents"], stripe_session_id=v["session_id"],
        stripe_payment_intent=v["payment_intent"], debut=debut, fin=fin, statut="actif",
        renonciation_at=v["renonciation_at"], renonciation_version=v["renonciation_version"],
    )
    db.add(p)
    try:
        await db.flush()
    except IntegrityError:
        # L'autre appel (webhook / page de retour) vient de l'accorder. Le
        # rollback périme les objets chargés : l'appelant relit son compte.
        await db.rollback()
        deja = (await db.execute(
            select(PassAcces).where(PassAcces.stripe_session_id == v["session_id"])
        )).scalar_one()
        return deja, False

    precedent = user.plan
    user.plan = await _plan_effectif(user.user_id, db)
    await journaliser(db, "pass_achete", user, None, plan=PLAN_PASS, plan_precedent=precedent,
                      montant_cents=v["montant_cents"], periode_fin=fin,
                      detail={"duree": v["duree"], "debut": debut.isoformat(),
                              "session": v["session_id"], "remise_parrainage": v["remise_parrainage"]})

    # Carte qui a payé : mémorisée comme pour un abonnement (un ancien client qui
    # rouvre un compte est ainsi reconnu), puis parrainage éventuel. Rien ici ne
    # peut retirer le pass, déjà payé : erreurs consignées seulement.
    from services import parrainage
    await db.flush()
    try:
        cartes = parrainage.cartes_du_paiement(v["payment_intent"])
        # Point de sauvegarde : une erreur ici n'annule QUE ce bloc, jamais le pass.
        async with db.begin_nested():
            if user.parraine_par_id:
                # Version qui LÈVE : l'erreur annule le point de sauvegarde au
                # lieu de laisser une transaction en échec derrière elle.
                await parrainage._sur_paiement_pass(user, v["duree"], v["montant_cents"], v["remise_parrainage"],
                                                    v["session_id"], cartes, db)
            elif cartes:
                from api.routes.stripe_routes import _memoriser_cartes
                await _memoriser_cartes(user, cartes, db)
    except Exception as e:  # noqa: BLE001
        log.error("passes.parrainage_ou_carte_erreur", user_id=user.user_id, error=str(e)[:200])
    await db.commit()
    log.info("passes.accorde", user_id=user.user_id, duree=v["duree"], debut=debut, fin=fin)
    try:
        from services.email_compte import envoyer_confirmation_pass
        await envoyer_confirmation_pass(user, p)
    except Exception as e:  # noqa: BLE001 — l'accès est acquis, l'e-mail n'est qu'une trace
        log.warning("passes.email_confirmation_echoue", user_id=user.user_id, error=str(e)[:150])
    return p, True


async def retirer_par_paiement(db: AsyncSession, payment_intent: Optional[str], raison: str) -> int:
    """Remboursement / contestation : le pass payé par ce paiement est retiré."""
    from api.routes.stripe_routes import _plan_effectif
    from services.abonnements import journaliser

    if not payment_intent:
        return 0
    passes = (await db.execute(
        select(PassAcces).where(PassAcces.stripe_payment_intent == payment_intent,
                                PassAcces.statut == "actif")
    )).scalars().all()
    for p in passes:
        p.statut = "rembourse"
        await db.flush()
        user = await db.get(User, p.user_id)
        if user is None:
            continue
        precedent = user.plan
        user.plan = await _plan_effectif(user.user_id, db)
        await journaliser(db, "pass_retire", user, None, plan=p.plan, plan_precedent=precedent,
                          montant_cents=p.montant_cents,
                          detail={"raison": raison, "pass_id": p.pass_id, "duree": p.duree})
        log.warning("passes.retire", user_id=p.user_id, pass_id=p.pass_id, raison=raison)
    if passes:
        await db.commit()
    return len(passes)


async def expirer_passes(db: AsyncSession, user_id: Optional[str] = None) -> int:
    """Applique les échéances : le compte retrouve le plan que le reste justifie
    (abonnement, accès offert, pass suivant déjà payé…). Idempotent."""
    from api.routes.stripe_routes import _plan_effectif
    from services.abonnements import journaliser

    maintenant = _maintenant()
    q = select(PassAcces).where(PassAcces.statut == "actif", PassAcces.fin <= maintenant,
                                PassAcces.expire_traite_at.is_(None))
    if user_id:
        q = q.where(PassAcces.user_id == user_id)
    echus = (await db.execute(q)).scalars().all()
    for p in echus:
        p.expire_traite_at = maintenant
    if not echus:
        return 0
    await db.flush()
    a_relancer: list[User] = []
    for uid in {p.user_id for p in echus}:
        user = await db.get(User, uid)
        if user is None:
            continue
        precedent = user.plan
        user.plan = await _plan_effectif(uid, db)
        # Relance « continuez avec Expert » : seulement si le compte retombe
        # vraiment en gratuit (ni abonnement, ni pass suivant, ni accès offert)
        # et n'a pas refusé les e-mails commerciaux. Une seule fois par échéance :
        # `expire_traite_at` empêche de repasser ici pour le même pass.
        relance = user.plan == "free" and user.marketing_opt_out_at is None
        await journaliser(db, "pass_termine", user, None, plan=user.plan,
                          plan_precedent=precedent, notifier=False,
                          detail={"relance_expert": relance})
        if relance:
            a_relancer.append(user)
    await db.commit()
    log.info("passes.echus", n=len(echus), relances=len(a_relancer))
    for user in a_relancer:
        try:
            from services.email_compte import envoyer_fin_pass
            await envoyer_fin_pass(user)
        except Exception as e:  # noqa: BLE001 — l'échéance est appliquée, l'e-mail n'est qu'une relance
            log.warning("passes.email_fin_echoue", user_id=user.user_id, error=str(e)[:150])
    return len(echus)


async def expirer_si_echu(db: AsyncSession, user: User) -> None:
    """Contrôle à la requête (compte payant seulement) : un pass échu coupe l'accès
    à la seconde, sans attendre la tâche planifiée. Ne lève jamais : une panne ici
    ne doit pas déconnecter un abonné — la tâche planifiée rattrape."""
    if (user.plan or "free") == "free" or user.is_admin:
        return
    try:
        echu = (await db.execute(
            select(PassAcces.pass_id).where(
                PassAcces.user_id == user.user_id, PassAcces.statut == "actif",
                PassAcces.fin <= _maintenant(), PassAcces.expire_traite_at.is_(None),
            ).limit(1)
        )).scalar_one_or_none()
        if echu is not None:
            await expirer_passes(db, user.user_id)
            await db.refresh(user)
    except Exception as e:  # noqa: BLE001
        uid = user.user_id
        await db.rollback()
        # Le rollback périme l'objet : le relire explicitement, sinon la route
        # qui lit `user.plan` déclenche un chargement paresseux (MissingGreenlet).
        try:
            await db.refresh(user)
        except Exception:  # noqa: BLE001
            pass
        log.warning("passes.controle_requete_echoue", user_id=uid, error=str(e)[:150])
