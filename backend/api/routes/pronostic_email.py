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

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import rate_limit_public
from api.routes.predictions import _signaux_du_champ
from db.database import get_db
from db.models import (
    Course, Prediction, Participation, Cheval, ValueBet, FeatureML,
    PronosticEmailEnvoi, PronosticEmailBlocage,
)
from services.alerts import send_email, JEU_RESPONSABLE_TXT
from services.cote_juste import cote_juste as _cote_juste

log = structlog.get_logger()
router = APIRouter()

SITE = "https://blackturf.fr"

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


def _lecture_prix_couleur(texte: Optional[str]) -> str:
    """Même code couleur que `LecturePrix` côté site : vert = le marché paie
    au-dessus de la cote juste (bon prix), rouge = en dessous, gris = neutre."""
    if not texte:
        return "#9ca0a8"
    if texte.startswith("+"):
        return "#059669"
    if texte.startswith("−") or texte.startswith("-"):
        return "#b91c1c"
    return "#7c818a"


def _mail_html(course: Course, chevaux: list[dict], lien_course: str, lien_desinscription: str) -> str:
    from html import escape as _e
    heure = course.date_heure.strftime("%Hh%M") if course.date_heure else ""
    titre_course = f"{course.hippodrome_nom} — {course.course_id[-4:]}"

    SENS_STYLE = {"positif": ("▲", "#059669"), "negatif": ("▼", "#b91c1c"), "neutre": ("●", "#92400e")}

    lignes = ""
    for c in chevaux:
        etoiles = "⭐" * c["niveau_value_bet"] if c["niveau_value_bet"] else ""
        cote_txt = _fmt_cote(c["cote"]) if c["cote"] else "—"
        juste_txt = _fmt_cote_juste(c["cote_juste"]) if c["cote_juste"] is not None else "—"
        lecture = c.get("lecture_prix")
        lecture_html = (
            f'<span style="color:{_lecture_prix_couleur(lecture)};font-weight:700">{_e(lecture)}</span>'
            if lecture else '<span style="color:#c8ccc5">—</span>'
        )
        signaux_html = ""
        if c["signaux"]:
            puces = []
            for sg in c["signaux"]:
                fleche, couleur = SENS_STYLE.get(sg["sens"], SENS_STYLE["neutre"])
                puces.append(
                    f'<span style="color:{couleur}">{fleche}</span> {_e(sg["label"])}'
                )
            signaux_html = (
                f'<div style="font-size:11px;color:#7c818a;margin-top:4px;line-height:1.5">'
                + " &nbsp;·&nbsp; ".join(puces) + "</div>"
            )
        lignes += f"""
    <tr style="border-bottom:1px solid #e5e5e0">
      <td style="padding:12px 8px;font-size:20px;font-weight:700;color:#9a6b11;width:32px;vertical-align:top">{c['rang_predit']}</td>
      <td style="padding:12px 8px;vertical-align:top">
        <div style="font-weight:600;color:#16181c">N°{c['numero']} {_e(c['nom'])}{" " + etoiles if etoiles else ""}</div>
        <div style="font-size:12px;color:#7c818a;margin-top:2px">
          Cote {cote_txt} &nbsp;·&nbsp; Cote juste {juste_txt} &nbsp;·&nbsp; {lecture_html}
        </div>
        {signaux_html}
      </td>
      <td style="padding:12px 8px;text-align:right;vertical-align:top;white-space:nowrap">
        <div style="font-weight:700;color:#16181c">{c['proba_top1']}%</div>
        <div style="font-size:11px;color:#7c818a">victoire</div>
        <div style="font-size:11px;color:#7c818a;margin-top:2px">top-3 {c['proba_top3']}%</div>
      </td>
    </tr>"""

    return f"""<!doctype html>
<html lang="fr"><body style="margin:0;background:#f6f6f3;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#16181c">
  <div style="max-width:560px;margin:0 auto;padding:32px 24px">
    <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#9a6b11;margin:0 0 24px">BlackTurf</p>
    <h1 style="font-size:22px;line-height:1.25;margin:0 0 6px">Le pronostic de {_e(titre_course)}</h1>
    <p style="font-size:13px;color:#7c818a;margin:0 0 24px">Départ {heure} — le classement complet de l&apos;algorithme, comme demandé sur la fiche de cette course.</p>

    <table style="width:100%;border-collapse:collapse;margin:0 0 20px">
      {lignes}
    </table>

    <p style="font-size:11px;line-height:1.6;color:#9ca0a8;margin:0 0 24px">
      Cote juste = 1 / probabilité de victoire estimée par le modèle, sans marge — le prix à partir duquel le
      pari devient rentable si la probabilité est exacte. Lecture du prix = écart entre la cote payée par le
      marché et cette cote juste.
    </p>

    <p style="margin:0 0 24px">
      <a href="{lien_course}" style="display:inline-block;background:#16181c;color:#fff;text-decoration:none;padding:13px 22px;border-radius:4px;font-size:15px;font-weight:600">Voir l&apos;analyse complète</a>
    </p>

    <p style="font-size:12px;line-height:1.6;color:#9ca0a8;margin:24px 0 0;padding-top:16px;border-top:1px solid #dcdcd5">
      {JEU_RESPONSABLE_TXT}
    </p>
    <p style="font-size:12px;line-height:1.6;color:#9ca0a8;margin:12px 0 0">
      Vous recevez cet e-mail unique parce que vous l&apos;avez demandé sur blackturf.fr.
      Ce n&apos;est pas un abonnement : rien d&apos;autre ne partira.
      <a href="{lien_desinscription}" style="color:#9ca0a8">Ne plus recevoir ce type d&apos;e-mail</a>.
    </p>
  </div>
</body></html>"""


def _mail_texte(course: Course, chevaux: list[dict], lien_course: str, lien_desinscription: str) -> str:
    heure = course.date_heure.strftime("%Hh%M") if course.date_heure else ""

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
    envoi = existant.scalar_one_or_none()
    if envoi is not None:
        # Déjà envoyé pour cette adresse et cette course : pas de doublon.
        return reponse

    # Un envoi par adresse et par JOUR CALENDAIRE, toutes courses confondues :
    # sans ce verrou, rien n'empêchait de redemander le classement IA complet
    # course après course, gratuitement, toute la journée. Le popup n'est
    # censé donner qu'UN aperçu par jour (cf. verrou identique côté front,
    # `PronosticEmailPopup.tsx`) — la contrainte est répétée ici pour rester
    # vraie même si le stockage local du navigateur est vidé ou absent.
    debut_jour = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    deja_aujourdhui = await db.execute(
        select(PronosticEmailEnvoi).where(and_(
            PronosticEmailEnvoi.email == email,
            PronosticEmailEnvoi.envoye_at.isnot(None),
            PronosticEmailEnvoi.envoye_at >= debut_jour,
        ))
    )
    if deja_aujourdhui.scalar_one_or_none() is not None:
        return DemandeOut(
            ok=False,
            message="Votre envoi gratuit de la journée vous a déjà été envoyé aujourd'hui — revenez demain.",
        )

    envoi = PronosticEmailEnvoi(
        email=email,
        course_id=course_id,
        token_desinscription=_token(),
        source=payload.source,
    )
    db.add(envoi)

    lien_course = f"{SITE}/courses/{course_id}"
    lien_desinscription = f"{SITE}/api/v1/pronostic-email/desinscription?jeton={envoi.token_desinscription}"
    resultat = await send_email(
        to=email,
        subject=f"Le pronostic BlackTurf pour {course.hippodrome_nom}",
        html=_mail_html(course, chevaux, lien_course, lien_desinscription),
        text=_mail_texte(course, chevaux, lien_course, lien_desinscription),
    )
    if resultat:
        envoi.envoye_at = datetime.now(timezone.utc)
    else:
        log.warning("pronostic_email.echec_envoi", course_id=course_id, raison=getattr(resultat, "erreur", None))

    await db.commit()
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
