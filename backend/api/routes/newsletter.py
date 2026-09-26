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
from fastapi import APIRouter, Depends, Query, Request, HTTPException
from fastapi.responses import HTMLResponse
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
    from services.email_compte import confirmation_newsletter
    return confirmation_newsletter(lien)[0]


def _mail_confirmation_texte(lien: str) -> str:
    from services.email_compte import confirmation_newsletter
    return confirmation_newsletter(lien)[1]


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
@router.post("/newsletter/desinscription", response_model=EtatOut)
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


@router.post("/newsletter/desabonnement-compte")
async def desabonnement_compte(jeton: str, db: AsyncSession = Depends(get_db)):
    """RFC 8058: direct POST, no login, redirect or confirmation page."""
    from api.routes.notifications import DesabonnementRequest, desabonnement_marketing
    return await desabonnement_marketing(DesabonnementRequest(token=jeton), db)


@router.get("/newsletter/bilans/{periode}", response_class=HTMLResponse)
async def bilan_public(periode: str, db: AsyncSession = Depends(get_db)):
    from db.models import EmailEdition
    from services.email_templates import weekly
    edition = await db.get(EmailEdition, "hebdo-" + periode)
    if edition is None:
        raise HTTPException(404, "Bilan non publié")
    html, _ = weekly(edition.donnees, archive=f"{SITE}/api/v1/newsletter/bilans/{periode}")
    return HTMLResponse(html, headers={"Cache-Control": "public, max-age=3600",
                                     "Content-Security-Policy": "default-src 'none'; img-src https://blackturf.fr; style-src 'unsafe-inline'; base-uri 'none'; frame-ancestors 'none'"})


@router.post("/newsletter/resend-webhook")
async def resend_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    import base64
    import hashlib
    import hmac
    import json
    import time
    from api.config import get_settings
    from db.models import EmailLivraison
    secret = get_settings().resend_webhook_secret
    if not secret:
        raise HTTPException(503, "Webhook non configuré")
    body = await request.body()
    if len(body) > 262144:
        raise HTTPException(413, "Événement trop volumineux")
    timestamp = request.headers.get("svix-timestamp", "")
    event_id = request.headers.get("svix-id", "")
    try:
        if not event_id or abs(time.time() - int(timestamp)) > 300:
            raise ValueError()
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
        signature = base64.b64encode(hmac.new(key, f"{event_id}.{timestamp}.".encode() + body, hashlib.sha256).digest()).decode()
        candidates = request.headers.get("svix-signature", "").split()
        if not any(hmac.compare_digest("v1," + signature, candidate) for candidate in candidates):
            raise ValueError()
        event = json.loads(body)
    except (ValueError, TypeError):
        raise HTTPException(400, "Signature invalide") from None
    provider_id = event.get("data", {}).get("email_id")
    if not provider_id:
        return {"ok": True}
    row = (await db.execute(select(EmailLivraison).where(EmailLivraison.provider_id == provider_id)
                            .with_for_update())).scalar_one_or_none()
    if row:
        kind = event.get("type", "").removeprefix("email.")
        priority = {"sent": 0, "delivered": 1, "opened": 2, "clicked": 3, "bounced": 4, "complained": 5}
        if kind in priority and priority[kind] > priority.get(row.statut, -1):
            row.statut = kind
            await db.commit()
    return {"ok": True}


from api.routes.auth import require_admin


@router.get("/newsletter/suivi", dependencies=[Depends(require_admin)])
async def suivi_envois(db: AsyncSession = Depends(get_db)):
    """Aggregate delivery health; no recipient addresses exposed."""
    from sqlalchemy import func
    from db.models import EmailLivraison
    rows = (await db.execute(select(EmailLivraison.campagne, EmailLivraison.statut, func.count())
                            .group_by(EmailLivraison.campagne, EmailLivraison.statut)
                            .order_by(EmailLivraison.campagne.desc()).limit(200))).all()
    return {"campagnes": [{"campagne": c, "statut": s, "nombre": n} for c, s, n in rows]}
