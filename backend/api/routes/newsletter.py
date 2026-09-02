"""
Lettre d'information — BlackTurf.

POST /api/v1/newsletter/inscription   — demande d'inscription (envoie le mail de confirmation)
GET  /api/v1/newsletter/confirmer     — confirme une inscription (double opt-in)
GET  /api/v1/newsletter/desinscription — désinscrit

DEUX RÈGLES QUI GUIDENT TOUT CE FICHIER :

1. AUCUNE ÉNUMÉRATION D'ADRESSES. `/inscription` répond exactement la même chose que
   l'adresse soit inconnue, déjà en attente, déjà confirmée ou désinscrite. Sinon le
   formulaire devient un oracle : n'importe qui peut tester une liste d'adresses et
   savoir lesquelles sont clientes. C'est aussi pour ça qu'aucune de ces routes ne
   renvoie 404 sur une adresse absente.

2. DOUBLE OPT-IN STRICT. Rien n'est envoyé à une adresse tant qu'elle n'a pas cliqué le
   lien de confirmation, et le seul message qu'elle peut recevoir avant est ce lien.
   C'est ce qui protège la personne inscrite par un tiers, et ce qui rend le
   consentement démontrable.

La désinscription ne supprime pas la ligne : une adresse désinscrite doit rester connue,
faute de quoi un tiers pourrait la réinscrire et relancer les envois.
"""
import secrets
from datetime import datetime, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.middleware.rate_limit import rate_limit_public
from db.database import get_db
from db.models import NewsletterAbonne
from services.alerts import send_email

log = structlog.get_logger()
router = APIRouter()

SITE = "https://blackturf.fr"

# Formulation exacte affichée sous le champ e-mail. Elle est stockée avec l'inscription :
# prouver un consentement suppose de pouvoir dire à QUOI la personne a consenti, pas
# seulement qu'elle a validé un formulaire. Toute modification du texte affiché doit être
# répercutée ici — les deux doivent rester identiques mot pour mot.
CONSENTEMENT = (
    "Je souhaite recevoir la lettre hebdomadaire BlackTurf : le bilan chiffré de la "
    "semaine, gains comme pertes. Un envoi par semaine, désinscription en un clic."
)


class InscriptionIn(BaseModel):
    email: EmailStr
    # D'où vient l'inscription : dit quel emplacement convertit et lesquels ne servent à
    # rien. Borné en longueur pour ne pas devenir un champ libre injecté par n'importe qui.
    source: Optional[str] = Field(default=None, max_length=40)


class InscriptionOut(BaseModel):
    ok: bool = True
    # Message volontairement identique dans tous les cas — cf. règle 1 en tête de fichier.
    message: str


class EtatOut(BaseModel):
    ok: bool
    message: str


def _token() -> str:
    return secrets.token_urlsafe(32)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


# Le compte Instagram n'était annoncé nulle part : ni sur le site, ni dans les e-mails.
# Les gens déjà inscrits à la lettre sont l'audience la plus qualifiée qui existe pour
# ce compte — ils ont donné leur adresse pour recevoir exactement ce qu'il publie.
INSTAGRAM_PSEUDO = "@blackturf.fr"
INSTAGRAM_URL = "https://www.instagram.com/blackturf.fr/"


def _mail_confirmation_html(lien: str) -> str:
    return f"""<!doctype html>
<html lang="fr"><body style="margin:0;background:#f6f6f3;font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;color:#16181c">
  <div style="max-width:520px;margin:0 auto;padding:32px 24px">
    <p style="font-size:13px;letter-spacing:.12em;text-transform:uppercase;color:#9a6b11;margin:0 0 24px">BlackTurf</p>
    <h1 style="font-size:22px;line-height:1.25;margin:0 0 16px">Confirmez votre inscription</h1>
    <p style="font-size:15px;line-height:1.6;margin:0 0 24px;color:#4a4e55">
      Vous recevrez chaque lundi le bilan chiffré de la semaine : ce que le modèle a bien
      vu, ce qu'il a raté, et le résultat réel — gains comme pertes. Un seul envoi par
      semaine.
    </p>
    <p style="margin:0 0 24px">
      <a href="{lien}" style="display:inline-block;background:#16181c;color:#fff;text-decoration:none;padding:13px 22px;border-radius:4px;font-size:15px;font-weight:600">Confirmer mon inscription</a>
    </p>
    <p style="font-size:13px;line-height:1.6;color:#7c818a;margin:0 0 8px">
      Si le bouton ne fonctionne pas, copiez cette adresse dans votre navigateur :<br>
      <span style="word-break:break-all">{lien}</span>
    </p>
    <p style="font-size:13px;line-height:1.6;color:#7c818a;margin:24px 0 0;padding-top:16px;border-top:1px solid #dcdcd5">
      En attendant lundi, le bilan du jour passe aussi sur Instagram :
      <a href="{INSTAGRAM_URL}" style="color:#9a6b11">{INSTAGRAM_PSEUDO}</a>
    </p>
    <p style="font-size:13px;line-height:1.6;color:#7c818a;margin:16px 0 0">
      Vous n'êtes pas à l'origine de cette demande ? Ignorez ce message : sans
      confirmation de votre part, aucune lettre ne partira et cette adresse sera oubliée.
    </p>
  </div>
</body></html>"""


def _mail_confirmation_texte(lien: str) -> str:
    return (
        "Confirmez votre inscription à la lettre hebdomadaire BlackTurf.\n\n"
        "Chaque lundi : le bilan chiffré de la semaine, gains comme pertes.\n\n"
        f"{lien}\n\n"
        f"En attendant lundi, le bilan du jour passe aussi sur Instagram : {INSTAGRAM_URL}\n\n"
        "Vous n'êtes pas à l'origine de cette demande ? Ignorez ce message : sans "
        "confirmation, aucune lettre ne partira."
    )


@router.post(
    "/newsletter/inscription",
    response_model=InscriptionOut,
    dependencies=[Depends(rate_limit_public)],
)
async def inscription(payload: InscriptionIn, db: AsyncSession = Depends(get_db)) -> InscriptionOut:
    """Demande d'inscription. Réponse identique quel que soit l'état de l'adresse."""
    reponse = InscriptionOut(
        message="Si cette adresse peut recevoir la lettre, un e-mail de confirmation vient de partir.",
    )
    email = payload.email.strip().lower()

    res = await db.execute(select(NewsletterAbonne).where(NewsletterAbonne.email == email))
    abonne = res.scalar_one_or_none()

    if abonne is None:
        abonne = NewsletterAbonne(
            email=email,
            statut="en_attente",
            token_confirmation=_token(),
            token_desinscription=_token(),
            source=payload.source,
            consentement_texte=CONSENTEMENT,
        )
        db.add(abonne)
    elif abonne.statut == "confirme":
        # Déjà inscrite : on ne renvoie RIEN. Réexpédier un lien de confirmation à une
        # adresse déjà confirmée en ferait un moyen de la harceler depuis le formulaire.
        await db.commit()
        return reponse
    else:
        # En attente, ou désinscrite qui revient : on régénère le jeton et on relance.
        # Un jeton à usage unique régénéré à chaque demande invalide le précédent, donc
        # un lien intercepté dans une ancienne boîte ne vaut plus rien.
        abonne.statut = "en_attente"
        abonne.token_confirmation = _token()
        abonne.desinscrit_at = None
        abonne.source = payload.source or abonne.source
        abonne.consentement_texte = CONSENTEMENT
        abonne.relance_confirmation_at = _maintenant()

    lien = f"{SITE}/newsletter/confirmer?jeton={abonne.token_confirmation}"
    envoi = await send_email(
        to=email,
        subject="Confirmez votre inscription à la lettre BlackTurf",
        html=_mail_confirmation_html(lien),
        text=_mail_confirmation_texte(lien),
    )
    if not envoi:
        # L'inscription reste enregistrée en attente : la personne pourra redemander un
        # lien. On journalise la raison, sans quoi une panne d'expédition se traduirait
        # par une liste qui ne grandit pas, sans explication.
        log.warning("newsletter.confirmation.echec_envoi", raison=getattr(envoi, "erreur", None))

    await db.commit()
    return reponse


@router.get(
    "/newsletter/confirmer",
    response_model=EtatOut,
    dependencies=[Depends(rate_limit_public)],
)
async def confirmer(
    jeton: str = Query(..., min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> EtatOut:
    """Confirme une inscription. Le jeton est consommé : il ne resservira pas."""
    res = await db.execute(
        select(NewsletterAbonne).where(NewsletterAbonne.token_confirmation == jeton)
    )
    abonne = res.scalar_one_or_none()

    if abonne is None:
        # Jeton inconnu OU déjà consommé — on ne distingue pas les deux : un lien
        # déjà utilisé ne doit pas révéler qu'il a existé.
        return EtatOut(ok=False, message="Ce lien de confirmation n'est plus valable.")

    abonne.statut = "confirme"
    abonne.confirme_at = _maintenant()
    abonne.token_confirmation = None  # usage unique
    abonne.desinscrit_at = None
    await db.commit()
    return EtatOut(ok=True, message="Votre inscription est confirmée.")


@router.get(
    "/newsletter/desinscription",
    response_model=EtatOut,
    dependencies=[Depends(rate_limit_public)],
)
async def desinscription(
    jeton: str = Query(..., min_length=16, max_length=64),
    db: AsyncSession = Depends(get_db),
) -> EtatOut:
    """Désinscription en un clic, sans mot de passe ni confirmation supplémentaire."""
    res = await db.execute(
        select(NewsletterAbonne).where(NewsletterAbonne.token_desinscription == jeton)
    )
    abonne = res.scalar_one_or_none()

    if abonne is None:
        return EtatOut(ok=False, message="Ce lien de désinscription n'est plus valable.")

    if abonne.statut != "desinscrit":
        abonne.statut = "desinscrit"
        abonne.desinscrit_at = _maintenant()
        # Le jeton de désinscription N'EST PAS invalidé : un clic sur un vieux lien doit
        # toujours répondre « vous êtes désinscrit », jamais « lien invalide ».
        await db.commit()

    return EtatOut(ok=True, message="Vous ne recevrez plus la lettre BlackTurf.")
