"""
Auth routes — BlackTurf.
JWT (login/register/refresh) + Google OAuth.
"""
import uuid
import structlog
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from api.config import get_settings
from db.database import get_db
from db.models import User

settings = get_settings()
log = structlog.get_logger()

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login")

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str
    nom: Optional[str] = None
    prenom: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    plan: str
    user_id: str


class RefreshRequest(BaseModel):
    refresh_token: str


class GoogleCallbackRequest(BaseModel):
    code: str
    redirect_uri: str


class UserMeResponse(BaseModel):
    user_id: str
    email: str
    nom: Optional[str]
    prenom: Optional[str]
    plan: str
    profil_risque: str
    email_verified: bool
    bankroll_initiale: Optional[float]
    created_at: datetime


# ─────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────
def _hash(password: str) -> str:
    return pwd_ctx.hash(password)


def _verify(password: str, hashed: str) -> bool:
    return pwd_ctx.verify(password, hashed)


def _create_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    payload["exp"] = datetime.now(timezone.utc) + expires_delta
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_tokens(user_id: str, plan: str) -> TokenResponse:
    access = _create_token(
        {"sub": user_id, "plan": plan, "type": "access"},
        timedelta(minutes=settings.access_token_expire_minutes),
    )
    refresh = _create_token(
        {"sub": user_id, "type": "refresh"},
        timedelta(days=settings.refresh_token_expire_days),
    )
    return TokenResponse(access_token=access, refresh_token=refresh, plan=plan, user_id=user_id)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            raise credentials_exc
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exc
    return user


async def require_pro(user: User = Depends(get_current_user)) -> User:
    if user.plan not in ("starter", "standard", "pro", "expert"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Abonnement requis")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès admin requis")
    return user


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(User).where(User.email == body.email))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Email déjà utilisé")

    user = User(
        user_id=str(uuid.uuid4()),
        email=body.email,
        hashed_password=_hash(body.password),
        nom=body.nom,
        prenom=body.prenom,
        plan="free",
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    log.info("auth.register", user_id=user.user_id, email=user.email)

    # Send verification email (non-blocking)
    try:
        import redis.asyncio as aioredis
        from services.alerts import send_email
        token = str(uuid.uuid4())
        r = aioredis.from_url(settings.redis_url)
        await r.setex(f"email_verify:{token}", 86400, user.user_id)
        await r.aclose()
        verify_url = f"{settings.frontend_url}/verifier-email?token={token}"
        html = f"""
        <div style="font-family:sans-serif;max-width:500px;margin:auto;">
          <h2 style="color:#F59E0B;">🏇 Bienvenue sur BlackTurf, {user.prenom or 'parieur'} !</h2>
          <p>Confirmez votre adresse email pour activer toutes les fonctionnalités :</p>
          <p><a href="{verify_url}" style="background:#F59E0B;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Vérifier mon email</a></p>
          <p style="color:#666;font-size:12px;">Lien valable 24 heures.</p>
          <hr style="border-color:#333;"/>
          <p style="color:#666;font-size:11px;">⚠️ Le jeu peut créer une dépendance — joueurs-info-service.fr — 09 74 75 13 13</p>
        </div>
        """
        await send_email(to=user.email, subject="BlackTurf — Vérifiez votre adresse email", html=html)
    except Exception as e:
        log.warning("auth.register.verify_email_failed", error=str(e))

    return create_tokens(user.user_id, user.plan)


@router.post("/login", response_model=TokenResponse)
async def login(
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not _verify(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    log.info("auth.login", user_id=user.user_id)
    return create_tokens(user.user_id, user.plan)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    try:
        payload = jwt.decode(body.refresh_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token invalide")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expiré")

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    return create_tokens(user.user_id, user.plan)


@router.post("/google", response_model=TokenResponse)
async def google_oauth(body: GoogleCallbackRequest, db: AsyncSession = Depends(get_db)):
    """Échange un code Google OAuth contre des tokens BlackTurf."""
    google_client_id = getattr(settings, "google_client_id", "")
    google_client_secret = getattr(settings, "google_client_secret", "")
    if not google_client_id:
        raise HTTPException(status_code=501, detail="OAuth Google non configuré")

    async with httpx.AsyncClient() as client:
        token_resp = await client.post(GOOGLE_TOKEN_URL, data={
            "code": body.code,
            "client_id": google_client_id,
            "client_secret": google_client_secret,
            "redirect_uri": body.redirect_uri,
            "grant_type": "authorization_code",
        })
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Échange de code Google échoué")
        g_token = token_resp.json()["access_token"]

        user_resp = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {g_token}"})
        g_user = user_resp.json()

    google_id = g_user["id"]
    email = g_user["email"]

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result2 = await db.execute(select(User).where(User.email == email))
        user = result2.scalar_one_or_none()
        if user:
            user.google_id = google_id
            user.email_verified = True
        else:
            user = User(
                user_id=str(uuid.uuid4()),
                email=email,
                google_id=google_id,
                email_verified=True,
                nom=g_user.get("family_name"),
                prenom=g_user.get("given_name"),
                plan="free",
            )
            db.add(user)

    await db.commit()
    await db.refresh(user)
    log.info("auth.google", user_id=user.user_id, email=user.email)
    return create_tokens(user.user_id, user.plan)


@router.get("/me", response_model=UserMeResponse)
async def me(user: User = Depends(get_current_user)):
    return UserMeResponse(
        user_id=user.user_id,
        email=user.email,
        nom=user.nom,
        prenom=user.prenom,
        plan=user.plan,
        profil_risque=user.profil_risque,
        email_verified=user.email_verified,
        bankroll_initiale=user.bankroll_initiale,
        created_at=user.created_at,
    )


@router.patch("/me")
async def update_me(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    allowed = {"nom", "prenom", "profil_risque", "bankroll_initiale"}
    for k, v in body.items():
        if k in allowed:
            setattr(user, k, v)
    await db.commit()
    return {"ok": True}


@router.post("/resend-verification")
async def resend_verification(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Renvoie l'email de vérification."""
    if user.email_verified:
        return {"ok": True}
    import redis.asyncio as aioredis
    from services.alerts import send_email
    token = str(uuid.uuid4())
    r = aioredis.from_url(settings.redis_url)
    try:
        await r.setex(f"email_verify:{token}", 86400, user.user_id)
    finally:
        await r.aclose()
    verify_url = f"{settings.frontend_url}/verifier-email?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:auto;">
      <h2 style="color:#F59E0B;">🏇 BlackTurf — Vérification de votre email</h2>
      <p>Cliquez sur le lien ci-dessous pour confirmer votre adresse email :</p>
      <p><a href="{verify_url}" style="background:#F59E0B;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Vérifier mon email</a></p>
      <hr style="border-color:#333;"/>
      <p style="color:#666;font-size:11px;">⚠️ Le jeu peut créer une dépendance — joueurs-info-service.fr — 09 74 75 13 13</p>
    </div>
    """
    await send_email(to=user.email, subject="BlackTurf — Vérifiez votre adresse email", html=html)
    return {"ok": True}


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    """Vérifie l'email avec le token reçu par email."""
    import redis.asyncio as aioredis
    r = aioredis.from_url(settings.redis_url)
    try:
        user_id = await r.get(f"email_verify:{token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Token expiré ou invalide")
        await r.delete(f"email_verify:{token}")
    finally:
        await r.aclose()

    result = await db.execute(select(User).where(User.user_id == user_id.decode()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    user.email_verified = True
    await db.commit()
    log.info("auth.email_verified", user_id=user.user_id)
    return {"ok": True, "message": "Email vérifié avec succès"}


@router.post("/forgot-password")
async def forgot_password(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Génère un token de reset et envoie un email. Anti-énumération : répond toujours 200."""
    import redis.asyncio as aioredis
    from services.alerts import send_email

    email = body.get("email", "").strip().lower()
    if not email:
        return {"ok": True}

    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if not user:
        return {"ok": True}  # Anti-enumeration

    token = str(uuid.uuid4())
    r = aioredis.from_url(settings.redis_url)
    try:
        await r.setex(f"pwd_reset:{token}", 3600, user.user_id)
    finally:
        await r.aclose()

    reset_url = f"{settings.frontend_url}/reinitialiser-mot-de-passe?token={token}"
    html = f"""
    <div style="font-family:sans-serif;max-width:500px;margin:auto;">
      <h2 style="color:#F59E0B;">🏇 BlackTurf — Réinitialisation de mot de passe</h2>
      <p>Bonjour {user.prenom or 'parieur'},</p>
      <p>Cliquez sur le lien ci-dessous pour réinitialiser votre mot de passe (valable 1 heure) :</p>
      <p><a href="{reset_url}" style="background:#F59E0B;color:#000;padding:12px 24px;border-radius:8px;text-decoration:none;font-weight:bold;">Réinitialiser mon mot de passe</a></p>
      <p style="color:#666;font-size:12px;">Si vous n'avez pas demandé cette réinitialisation, ignorez cet email.</p>
      <hr style="border-color:#333;"/>
      <p style="color:#666;font-size:11px;">⚠️ Le jeu peut créer une dépendance — joueurs-info-service.fr — 09 74 75 13 13</p>
    </div>
    """
    await send_email(to=email, subject="BlackTurf — Réinitialisation de mot de passe", html=html)
    log.info("auth.forgot_password", user_id=user.user_id)
    return {"ok": True}


@router.post("/reset-password")
async def reset_password(
    body: dict,
    db: AsyncSession = Depends(get_db),
):
    """Réinitialise le mot de passe avec le token."""
    import redis.asyncio as aioredis

    token = body.get("token", "")
    new_password = body.get("password", "")

    if not token or len(new_password) < 8:
        raise HTTPException(status_code=400, detail="Token ou mot de passe invalide")

    r = aioredis.from_url(settings.redis_url)
    try:
        user_id = await r.get(f"pwd_reset:{token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Token expiré ou invalide")
        await r.delete(f"pwd_reset:{token}")
    finally:
        await r.aclose()

    result = await db.execute(select(User).where(User.user_id == user_id.decode()))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="Utilisateur introuvable")

    user.hashed_password = pwd_ctx.hash(new_password)
    await db.commit()
    log.info("auth.reset_password", user_id=user.user_id)
    return {"ok": True}


@router.put("/push-subscription")
async def save_push_subscription(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Enregistre la souscription Web Push."""
    user.push_subscription = body
    await db.commit()
    return {"ok": True}
