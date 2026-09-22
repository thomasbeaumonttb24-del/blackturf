"""
Pronostic gratuit d'UNE course, par e-mail — capture sur la fiche course.

POST /api/v1/courses/{course_id}/envoyer-pronostic

Inspiré du popup Boturfers.fr : le visiteur d'une fiche course laisse son e-mail
et reçoit — pour CETTE course précise, pas une lettre générique — le classement IA
du moment (top chevaux + probabilités). Envoi TRANSACTIONNEL, déclenché par une
action explicite sur cette course : pas de double opt-in comme la newsletter
hebdo (`api/routes/newsletter.py`), mais chaque e-mail porte son lien de
désinscription, et une adresse qui l'utilise n'en reçoit plus jamais.

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
from db.database import get_db
from db.models import (
    Course, Prediction, Participation, Cheval, ValueBet,
    PronosticEmailEnvoi, PronosticEmailBlocage,
)
from services.alerts import send_email, JEU_RESPONSABLE_TXT

log = structlog.get_logger()
router = APIRouter()

SITE = "https://blackturf.fr"
TOP_N = 3  # nombre de chevaux détaillés dans l'e-mail — assez pour montrer la valeur, pas la fiche entière

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


async def _top_chevaux(db: AsyncSession, course_id: str) -> list[dict]:
    """Top N chevaux du pronostic (même requête que /courses/{id}/predictions),
    enrichis du value bet actif s'il y en a un. [] si rien n'est calculé."""
    q = (
        select(Prediction, Participation, Cheval)
        .join(Participation, Participation.participation_id == Prediction.participation_id)
        .join(Cheval, Cheval.cheval_id == Participation.cheval_id)
        .where(and_(Prediction.course_id == course_id,
                    Participation.non_partant == False))  # noqa: E712
        .order_by(Prediction.rang_predit)
        .limit(TOP_N)
    )
    rows = (await db.execute(q)).all()
    if not rows:
        return []

    vb_res = await db.execute(
        select(ValueBet).where(and_(ValueBet.course_id == course_id, ValueBet.actif == True))  # noqa: E712
    )
    vbs_by_pid = {vb.participation_id: vb for vb in vb_res.scalars().all()}

    chevaux = []
    for pred, part, cheval in rows:
        vb = vbs_by_pid.get(part.participation_id)
        chevaux.append({
            "numero": part.numero,
            "nom": cheval.nom,
            "rang_predit": pred.rang_predit,
            "proba_top1": round(pred.proba_top1 * 100, 1),
            "proba_top3": round(pred.proba_top3 * 100, 1),
            "cote": part.cote_pmu,
            "niveau_value_bet": vb.niveau if vb else None,
        })
    return chevaux


def _mail_html(course: Course, chevaux: list[dict], lien_course: str, lien_desinscription: str) -> str:
    heure = course.date_heure.strftime("%Hh%M") if course.date_heure else ""
    titre_course = f"{course.hippodrome_nom} — {course.course_id[-4:]}"

    lignes = ""
    for c in chevaux:
        etoiles = "⭐" * c["niveau_value_bet"] if c["niveau_value_bet"] else ""
        cote_txt = f"cote {c['cote']:.1f}" if c["cote"] else "cote non communiquée"
        lignes += f"""
    <tr style="border-bottom:1px solid #e5e5e0">
      <td style="padding:12px 8px;font-size:20px;font-weight:700;color:#9a6b11;width:36px">{c['rang_predit']}</td>
      <td style="padding:12px 8px">
        <div style="font-weight:600;color:#16181c">N°{c['numero']} {c['nom']}</div>
        <div style="font-size:12px;color:#7c818a;margin-top:2px">{cote_txt}{" · " + etoiles if etoiles else ""}</div>
      </td>
      <td style="padding:12px 8px;text-align:right">
        <div style="font-weight:700;color:#16181c">{c['proba_top1']}%</div>
        <div style="font-size:11px;color:#7c818a">victoire</div>
      </td>
    </tr>"""

    return f"""<!doctype html>
<html lang="fr"><body style="margin:0;background:#f6f6f3;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#16181c">
  <div style="max-width:520px;margin:0 auto;padding:32px 24px">
    <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#9a6b11;margin:0 0 24px">BlackTurf</p>
    <h1 style="font-size:22px;line-height:1.25;margin:0 0 6px">Le pronostic de {titre_course}</h1>
    <p style="font-size:13px;color:#7c818a;margin:0 0 24px">Départ {heure} — comme demandé sur la fiche de cette course.</p>

    <table style="width:100%;border-collapse:collapse;margin:0 0 24px">
      {lignes}
    </table>

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
    lignes = "\n".join(
        f"{c['rang_predit']}. N°{c['numero']} {c['nom']} — {c['proba_top1']}% de victoire estimée"
        for c in chevaux
    )
    return (
        f"Le pronostic de {course.hippodrome_nom} — départ {heure}\n\n"
        f"{lignes}\n\n"
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

    chevaux = await _top_chevaux(db, course_id)
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
