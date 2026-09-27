"""
Pronostic gratuit d'UNE course, par e-mail — capture sur la fiche course.

POST /api/v1/courses/{course_id}/envoyer-pronostic

Inspiré du popup Boturfers.fr : le visiteur d'une fiche course laisse son e-mail
et reçoit — pour CETTE course précise, pas une lettre générique — le classement IA
complet, avec les mêmes chiffres que la fiche abonné (cote, cote juste, lecture
du prix, signaux). Envoi TRANSACTIONNEL, déclenché par une action explicite sur
cette course : pas de double opt-in comme la newsletter hebdo
(`api/routes/newsletter.py`), mais chaque e-mail porte son lien de
désinscription, et une adresse qui l'utilise n'en reçoit plus jamais.

Un seul envoi par ADRESSE et par JOUR CALENDAIRE, quelle que soit la course
demandée (vérifié dans `envoyer_pronostic` sur `envoye_at`) : ce popup est un
aimant à prospects, pas un moyen de recevoir le classement IA de toutes les
courses du jour gratuitement en le redemandant course après course.

RÈGLE : on ne promet jamais un contenu qu'on ne livre pas. Si la course n'a pas
encore de pronostic calculé, on le dit — on n'enregistre rien et on n'envoie rien.
"""
import secrets
from datetime import datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import rate_limit_public
from api.routes.predictions import _signaux_du_champ
from db.database import get_db
from db.models import (
    Course, Prediction, Participation, Cheval, ValueBet, FeatureML, Jockey,
    PronosticEmailEnvoi, PronosticEmailBlocage,
)
from services.alerts import send_email, JEU_RESPONSABLE_TXT
from services.cote_juste import cote_juste as _cote_juste
from services import email_pronostic

log = structlog.get_logger()
router = APIRouter()

SITE = "https://blackturf.fr"
PARIS = ZoneInfo("Europe/Paris")


def _debut_jour_paris(maintenant: Optional[datetime] = None) -> datetime:
    """Minuit du jour calendaire de Paris : la journée du visiteur, pas celle d'UTC
    (qui repartait à 2 h du matin l'été et laissait passer un second envoi).
    Rendu en UTC pour être comparé tel quel à `envoye_at`, stocké en UTC."""
    return (maintenant or datetime.now(timezone.utc)).astimezone(PARIS).replace(
        hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)

# Mêmes seuils que `ClassementAlgo`/`LecturePrix` côté site
# (frontend/src/components/courses/classement.tsx) : l'e-mail doit lire le même
# écart marché/cote juste de la même façon, pas une approximation maison.
COTE_JUSTE_MAX = 999.0
ECART_MEILLEUR_PRIX = 0.08
# Signaux joints par cheval : 3, comme l'aperçu public (NB_SIGNAUX_PAR_LIGNE) —
# assez pour montrer la lecture du modèle sans transformer l'e-mail en pavé.
NB_SIGNAUX_PAR_CHEVAL = 3

# Formulation affichée sous le champ e-mail du popup, enregistrée avec la demande —
# même logique que `CONSENTEMENT` dans newsletter.py : pouvoir dire à quoi la
# personne a consenti, pas seulement qu'elle a validé un formulaire.
CONSENTEMENT = (
    "Je souhaite recevoir par e-mail le pronostic IA de cette course. Envoi unique, "
    "pas d'abonnement, désinscription en un clic."
)


class DemandeIn(BaseModel):
    email: EmailStr
    source: Optional[str] = Field(default=None, max_length=40)


class DemandeOut(BaseModel):
    ok: bool
    message: str


def _token() -> str:
    return secrets.token_urlsafe(32)


def _fmt_cote(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def _fmt_cote_juste(x: float) -> str:
    """Même précision adaptée à l'ordre de grandeur que `coteJuste()` côté site
    (frontend/src/components/courses/classement.tsx) et `services/cote_juste.py` :
    à 1 décimale fixe, deux chevaux séparés de 2 % de proba tombent sur le même prix."""
    if x < 10:
        return f"{x:.2f}".replace(".", ",")
    if x < 100:
        return f"{x:.1f}".replace(".", ",")
    return f"{x:.0f}"


def _lecture_prix(marche: Optional[float], juste: Optional[float]) -> Optional[str]:
    """Même lecture que le composant `LecturePrix` du site : écart relatif entre
    la cote payée par le marché et la cote juste du modèle. None si l'une des
    deux valeurs manque — l'e-mail affiche alors un tiret, comme le site."""
    if not marche or marche <= 0 or not juste or juste <= 0:
        return None
    if juste >= COTE_JUSTE_MAX:
        return "non chiffrable"
    ecart = marche / juste - 1
    if abs(ecart) < ECART_MEILLEUR_PRIX:
        return "au prix"
    pct = round(abs(ecart) * 100)
    return f"+{pct} %" if ecart > 0 else f"−{pct} %"


async def _classement_complet(db: AsyncSession, course: Course) -> list[dict]:
    """Classement COMPLET du pronostic pour cette course — tous les partants
    notés, pas seulement le podium — avec les mêmes chiffres que la fiche
    abonné : cote de marché, cote juste (`services/cote_juste.py`), lecture du
    prix, value bet et signaux réels (`api.routes.predictions._signaux_du_champ`,
    la même fonction que l'aperçu public). [] si rien n'est calculé.
    """
    course_id = course.course_id
    q = (
        select(Prediction, Participation, Cheval)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(and_(Prediction.course_id == course_id,
                    Participation.non_partant == False))  # noqa: E712
        .order_by(Prediction.rang_predit)
    )
    rows = (await db.execute(q)).all()
    if not rows:
        return []

    vb_res = await db.execute(
        select(ValueBet).where(and_(ValueBet.course_id == course_id, ValueBet.actif == True))  # noqa: E712
    )
    vbs = list(vb_res.scalars().all())
    vbs_by_pid = {vb.participation_id: vb for vb in vbs}

    # Cote de marché : `cote_pmu`, tenue à jour par le scraper — PAS un appel
    # live à `fetch_live_cotes` comme /courses/{id}/predictions. Cet endpoint
    # est déclenché en synchrone par la soumission d'un visiteur anonyme : un
    # appel réseau supplémentaire ici (parfois lent, notamment sur les
    # hippodromes étrangers) ferait échouer l'envoi pour une fraîcheur de cote
    # dont un e-mail figé au moment de la demande n'a pas besoin.
    #
    # Signaux réels, calculés depuis les features déjà en base — même source
    # que l'aperçu public (`api.routes.predictions._signaux_du_champ`).
    # ENRICHISSEMENT OPTIONNEL : un échec ici (SQL ou ML) ne doit jamais faire
    # échouer l'envoi lui-même — l'e-mail part alors sans signaux plutôt que pas
    # du tout. `desempoisonner` est indispensable : PostgreSQL avorte toute la
    # transaction dès qu'une requête échoue, et sans ce rollback l'échec
    # ressortirait sur le `commit` de l'envoi, quinze lignes plus bas, avec un
    # message qui n'aurait plus aucun rapport avec la cause (cf. db.database).
    signaux_par_pid: dict[str, list[dict]] = {}
    try:
        pids = [part.participation_id for _, part, _ in rows]
        features_par_pid: dict[str, dict] = {}
        if pids:
            fr = await db.execute(
                select(FeatureML.participation_id, FeatureML.features)
                .where(FeatureML.participation_id.in_(pids))
            )
            features_par_pid = {pid: (f or {}) for pid, f in fr.all() if f}
        signaux_par_pid, _agregat = _signaux_du_champ(rows, vbs, features_par_pid)
    except Exception:
        from db.database import desempoisonner
        await desempoisonner(db)
        signaux_par_pid = {}

    # Nom du jockey/driver, affiché sous le cheval comme sur la fiche. Même
    # statut d'enrichissement optionnel que les signaux.
    jockeys: dict[str, str] = {}
    try:
        ids = {part.jockey_id for _, part, _ in rows if part.jockey_id}
        if ids:
            jr = await db.execute(select(Jockey.jockey_id, Jockey.nom).where(Jockey.jockey_id.in_(ids)))
            jockeys = {jid: nom for jid, nom in jr.all() if nom}
    except Exception:
        from db.database import desempoisonner
        await desempoisonner(db)
        jockeys = {}

    chevaux = []
    for pred, part, cheval in rows:
        vb = vbs_by_pid.get(part.participation_id)
        marche = part.cote_pmu
        juste = _cote_juste(pred.proba_top1)
        chevaux.append({
            "numero": part.numero,
            "nom": cheval.nom,
            "rang_predit": pred.rang_predit,
            "proba_top1": round(pred.proba_top1 * 100, 1),
            "proba_top3": round(pred.proba_top3 * 100, 1),
            # Probabilités brutes (0–1) : le gabarit HTML les arrondit comme le site.
            "p1": pred.proba_top1 or 0.0,
            "p3": pred.proba_top3 or 0.0,
            "casaque_url": part.casaque_image_url,
            "jockey": jockeys.get(part.jockey_id) if part.jockey_id else None,
            "musique": part.musique,
            "calcule_a": pred.created_at,
            "cote": marche,
            "cote_juste": juste,
            "lecture_prix": _lecture_prix(marche, juste),
            "niveau_value_bet": vb.niveau if vb else None,
            "ev_max": vb.ev_max if vb else None,
            "signaux": [
                {"label": sg["label"], "sens": sg["sens"]}
                for sg in (signaux_par_pid.get(part.participation_id) or [])[:NB_SIGNAUX_PAR_CHEVAL]
            ],
        })
    return chevaux


def _infos_course(course: Course) -> dict:
    return {
        "nom": course.nom, "numero_reunion": course.numero_reunion, "numero": course.numero,
        "discipline": course.discipline, "hippodrome_nom": course.hippodrome_nom,
        "distance": course.distance, "nb_partants": course.nb_partants,
        "date_heure": course.date_heure, "allocation": course.allocation,
        "terrain": course.penetrometre_desc or course.terrain_officiel,
        "statut": course.statut, "est_quinte": course.est_quinte,
        "est_quarte": course.est_quarte, "est_tierce": course.est_tierce,
    }


def _mail_html(course: Course, chevaux: list[dict], lien_course: str, lien_desinscription: str) -> str:
    """Rendu calqué sur la fiche course du site — cf. services/email_pronostic.py."""
    horodatages = [c["calcule_a"] for c in chevaux if c.get("calcule_a")]
    return email_pronostic.rendu_html(
        _infos_course(course), chevaux, lien_course, lien_desinscription,
        calcule_a=max(horodatages) if horodatages else None,
        responsable=JEU_RESPONSABLE_TXT,
    )


def _mail_texte(course: Course, chevaux: list[dict], lien_course: str, lien_desinscription: str) -> str:
    heure = email_pronostic.heure_depart(course.date_heure)

    def _ligne(c: dict) -> str:
        cote_txt = _fmt_cote(c["cote"]) if c["cote"] else "—"
        juste_txt = _fmt_cote_juste(c["cote_juste"]) if c["cote_juste"] is not None else "—"
        lecture = c.get("lecture_prix") or "—"
        etoiles = " " + "⭐" * c["niveau_value_bet"] if c["niveau_value_bet"] else ""
        base = (
            f"{c['rang_predit']}. N°{c['numero']} {c['nom']}{etoiles} — {c['proba_top1']}% victoire "
            f"(top-3 {c['proba_top3']}%) — cote {cote_txt}, cote juste {juste_txt}, lecture du prix : {lecture}"
        )
        if c["signaux"]:
            base += "\n   " + " · ".join(f"{sg['label']}" for sg in c["signaux"])
        return base

    lignes = "\n".join(_ligne(c) for c in chevaux)
    return (
        f"Le pronostic de {course.hippodrome_nom} — départ {heure}\n"
        "Classement complet de l'algorithme :\n\n"
        f"{lignes}\n\n"
        "Cote juste = 1 / probabilité de victoire estimée par le modèle, sans marge. "
        "Lecture du prix = écart entre la cote du marché et cette cote juste.\n\n"
        f"Analyse complète : {lien_course}\n\n"
        f"{JEU_RESPONSABLE_TXT}\n\n"
        "Vous recevez cet e-mail unique parce que vous l'avez demandé sur blackturf.fr. "
        f"Ne plus recevoir ce type d'e-mail : {lien_desinscription}"
    )


@router.post(
    "/courses/{course_id}/envoyer-pronostic",
    response_model=DemandeOut,
    dependencies=[Depends(rate_limit_public)],
)
async def envoyer_pronostic(
    course_id: str,
    payload: DemandeIn,
    db: AsyncSession = Depends(get_db),
) -> DemandeOut:
    course_res = await db.execute(select(Course).where(Course.course_id == course_id))
    course = course_res.scalar_one_or_none()
    if not course:
        raise HTTPException(status_code=404, detail="Course introuvable")

    chevaux = await _classement_complet(db, course)
    if not chevaux:
        # Rien à envoyer : on ne promet pas un pronostic qui n'existe pas encore.
        return DemandeOut(
            ok=False,
            message="Le pronostic de cette course n'est pas encore disponible. Réessayez un peu avant le départ.",
        )

    email = payload.email.strip().lower()
    reponse = DemandeOut(ok=True, message="Le pronostic de cette course vient de partir par e-mail.")

    bloque = await db.execute(select(PronosticEmailBlocage).where(PronosticEmailBlocage.email == email))
    if bloque.scalar_one_or_none() is not None:
        # Adresse désinscrite de ce type d'e-mail : réponse identique, mais rien ne part.
        return reponse

    existant = await db.execute(
        select(PronosticEmailEnvoi).where(and_(
            PronosticEmailEnvoi.email == email,
            PronosticEmailEnvoi.course_id == course_id,
        ))
    )
    envoi = existant.scalars().first()
    if envoi is not None and envoi.envoye_at is not None:
        # Déjà envoyé pour cette adresse et cette course : pas de doublon.
        return reponse

    # Un envoi par adresse et par JOUR CALENDAIRE (Paris), toutes courses
    # confondues : sans ce verrou, rien n'empêchait de redemander le classement IA
    # complet course après course, gratuitement, toute la journée. Le popup n'est
    # censé donner qu'UN aperçu par jour (cf. verrou identique côté front,
    # `PronosticEmailPopup.tsx`) — la contrainte est répétée ici pour rester
    # vraie même si le stockage local du navigateur est vidé ou absent.
    # `.first()` et non `scalar_one_or_none()` : deux envois déjà présents le même
    # jour (demandes simultanées, données antérieures au verrou) levaient une
    # erreur 500 au lieu du message de quota.
    deja_aujourdhui = await db.execute(
        select(PronosticEmailEnvoi.envoi_id).where(and_(
            PronosticEmailEnvoi.email == email,
            PronosticEmailEnvoi.envoye_at.isnot(None),
            PronosticEmailEnvoi.envoye_at >= _debut_jour_paris(),
        )).limit(1)
    )
    if deja_aujourdhui.first() is not None:
        return DemandeOut(
            ok=False,
            message="Votre envoi gratuit de la journée vous a déjà été envoyé aujourd'hui — revenez demain.",
        )

    if envoi is None:
        envoi = PronosticEmailEnvoi(
            email=email,
            course_id=course_id,
            token_desinscription=_token(),
            source=payload.source,
        )
        db.add(envoi)
    # Sinon : demande précédente pour cette course dont l'envoi avait échoué
    # (`envoye_at` vide) — on réessaie au lieu d'annoncer un e-mail jamais parti.

    lien_course = f"{SITE}/courses/{course_id}"
    lien_desinscription = f"{SITE}/api/v1/pronostic-email/desinscription?jeton={envoi.token_desinscription}"
    resultat = await send_email(
        to=email,
        subject=f"🏇 Votre pronostic IA : {course.nom or course.hippodrome_nom} — départ {email_pronostic.heure_depart(course.date_heure)}",
        html=_mail_html(course, chevaux, lien_course, lien_desinscription),
        text=_mail_texte(course, chevaux, lien_course, lien_desinscription),
    )
    if resultat:
        envoi.envoye_at = datetime.now(timezone.utc)
    else:
        log.warning("pronostic_email.echec_envoi", course_id=course_id, raison=getattr(resultat, "erreur", None))

    await db.commit()
    if not resultat:
        # Ne jamais annoncer « parti » pour un e-mail qui n'est pas parti. La ligne
        # reste sans `envoye_at` : ne compte pas dans le quota, et une nouvelle
        # demande sur cette course réessaie l'envoi. 503 plutôt que ok=False : le
        # popup garde alors son formulaire affiché pour permettre ce nouvel essai.
        raise HTTPException(status_code=503, detail="L'envoi n'a pas abouti. Réessayez dans un instant.")
    return reponse


@router.get(
    "/pronostic-email/desinscription",
    response_model=DemandeOut,
    dependencies=[Depends(rate_limit_public)],
)
async def desinscription(
    jeton: str = Query(..., min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> DemandeOut:
    res = await db.execute(
        select(PronosticEmailEnvoi).where(PronosticEmailEnvoi.token_desinscription == jeton)
    )
    envoi = res.scalar_one_or_none()
    if envoi is None:
        return DemandeOut(ok=False, message="Ce lien de désinscription n'est plus valable.")

    exists = await db.execute(select(PronosticEmailBlocage).where(PronosticEmailBlocage.email == envoi.email))
    if exists.scalar_one_or_none() is None:
        db.add(PronosticEmailBlocage(email=envoi.email))
        await db.commit()

    return DemandeOut(ok=True, message="Vous ne recevrez plus ce type d'e-mail.")
