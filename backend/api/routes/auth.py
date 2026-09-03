"""
Auth routes — BlackTurf.
JWT (login/register/refresh) + Google OAuth.
"""
import uuid
import secrets
import structlog
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, EmailStr, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import httpx

from api.config import get_settings
from db.database import get_db
from db.models import User
from api.middleware.throttle import rate_limit_auth

settings = get_settings()
log = structlog.get_logger()

router = APIRouter()
pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")
# auto_error=False : l'absence d'en-tête Authorization n'est plus une erreur, on
# retombe sur le cookie httpOnly (cf. _access_token).
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

# ─────────────────────────────────────────────
# Cookies de session
# ─────────────────────────────────────────────
# Les jetons vivaient dans localStorage : lisibles par n'importe quel script de la
# page, donc exfiltrables par une seule XSS — et le refresh vaut 7 jours. On les
# pose désormais en cookies httpOnly, invisibles pour JavaScript.
#
# SameSite=Lax suffit contre le CSRF ici : le navigateur n'envoie pas ces cookies
# sur une requête POST/PUT/DELETE déclenchée depuis un AUTRE site. blackturf.fr et
# api.blackturf.fr partagent le même site déclarable (blackturf.fr), donc le
# front continue de les envoyer normalement.
ACCESS_COOKIE = "access_token"
REFRESH_COOKIE = "refresh_token"
# Témoin LISIBLE par le front (aucune valeur secrète : juste "1"). Les cookies de
# session étant httpOnly, le navigateur ne peut plus savoir s'il a une session ;
# sans ce témoin, chaque visiteur anonyme déclencherait un /auth/me en 401 à
# chaque chargement de page.
SESSION_HINT_COOKIE = "bt_session"
# Le cookie de refresh n'est utile QUE sur les routes d'authentification : le
# restreindre réduit d'autant sa surface d'exposition.
REFRESH_COOKIE_PATH = "/api/v1/auth"


def _cookie_secure() -> bool:
    """`Secure` en production seulement — sinon le dev en http:// perdrait le cookie."""
    return settings.environment == "production"


def _hint_cookie_domain() -> Optional[str]:
    """Domaine parent partagé par le front et l'API, en production uniquement.

    En local (localhost, ports différents) un attribut Domain casserait le cookie ;
    on le laisse alors lié à l'hôte.
    """
    if settings.environment != "production":
        return None
    hote = settings.api_url.split("//")[-1].split("/")[0].split(":")[0]
    morceaux = hote.split(".")
    return "." + ".".join(morceaux[-2:]) if len(morceaux) >= 2 else None


def _set_auth_cookies(response: Response, tokens: "TokenResponse") -> None:
    response.set_cookie(
        ACCESS_COOKIE, tokens.access_token,
        max_age=settings.access_token_expire_minutes * 60,
        httponly=True, secure=_cookie_secure(), samesite="lax", path="/",
    )
    response.set_cookie(
        REFRESH_COOKIE, tokens.refresh_token,
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=True, secure=_cookie_secure(), samesite="lax",
        path=REFRESH_COOKIE_PATH,
    )
    # Le témoin est posé sur le DOMAINE PARENT : le front tourne sur blackturf.fr
    # et ne verrait jamais un cookie limité à api.blackturf.fr. Les jetons, eux,
    # restent volontairement liés au seul hôte de l'API — un sous-domaine compromis
    # ne doit pas les recevoir.
    response.set_cookie(
        SESSION_HINT_COOKIE, "1",
        max_age=settings.refresh_token_expire_days * 86400,
        httponly=False, secure=_cookie_secure(), samesite="lax", path="/",
        domain=_hint_cookie_domain(),
    )


def _clear_auth_cookies(response: Response) -> None:
    response.delete_cookie(ACCESS_COOKIE, path="/")
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    response.delete_cookie(SESSION_HINT_COOKIE, path="/", domain=_hint_cookie_domain())


async def _access_token(
    request: Request,
    header_token: Optional[str] = Depends(oauth2_scheme),
) -> Optional[str]:
    """Jeton d'accès, depuis l'en-tête Authorization ou le cookie httpOnly.

    L'en-tête reste accepté : il sert aux clients non navigateur (scripts, tests)
    et laisse les sessions déjà ouvertes fonctionner le temps qu'elles basculent.
    """
    return header_token or request.cookies.get(ACCESS_COOKIE)

GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class RegisterRequest(BaseModel):
    email: EmailStr
    # Politique mot de passe : 10-128 chars (bcrypt tronque >72 octets → cap),
    # pas uniquement lettres ni uniquement chiffres (anti mots de passe triviaux).
    password: str = Field(min_length=10, max_length=128)
    nom: Optional[str] = None
    prenom: Optional[str] = None

    @field_validator("password")
    @classmethod
    def _password_strength(cls, v: str) -> str:
        if v.isalpha() or v.isdigit():
            raise ValueError("Mot de passe trop faible : mélangez lettres et chiffres")
        return v


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
    is_admin: bool = False
    bankroll_initiale: Optional[float]
    created_at: datetime
    # Essai ouvert mais bloqué faute de carte enregistrée. Sans ce signal, le
    # compte se retrouve en `free` sans la moindre explication — l'utilisateur
    # croit à une panne et écrit au support au lieu d'aller régulariser.
    essai_bloque_sans_carte: bool = False
    essai_fin: Optional[datetime] = None
    # Un abonnement Stripe existe et reste pilotable, MÊME si le compte est
    # retombé en `free`. Sans ce signal, la page profil décidait d'après le seul
    # `plan` : un paiement en échec rétrograde en `free`, le bouton « Gérer
    # l'abonnement via Stripe » disparaissait, et c'était le seul chemin pour
    # changer de carte. Le client était alors renvoyé vers /tarifs, où le
    # checkout refuse (409, `past_due` compte parmi les statuts vivants) en le
    # renvoyant vers le bouton qu'on venait de lui cacher. Impasse constatée le
    # 2026-09-03 sur deux abonnés à 19 €/mois.
    abonnement_gerable: bool = False
    # Cause de la rétrogradation, pour l'expliquer au lieu de laisser croire à
    # une panne. Vrai tant que Stripe relance la carte.
    paiement_en_echec: bool = False


# ─────────────────────────────────────────────
# JWT helpers
# ─────────────────────────────────────────────
def _hash(password: str) -> str:
    return pwd_ctx.hash(password)


def _verify(password: str, hashed: str) -> bool:
    return pwd_ctx.verify(password, hashed)


def _create_token(data: dict, expires_delta: timedelta) -> str:
    payload = data.copy()
    now = datetime.now(timezone.utc)
    payload["iat"] = int(now.timestamp())   # permet l'invalidation au reset de mot de passe
    payload["exp"] = now + expires_delta
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
    token: Optional[str] = Depends(_access_token),
    db: AsyncSession = Depends(get_db),
) -> User:
    credentials_exc = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Token invalide ou expiré",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if not token:
        raise credentials_exc
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "access":
            raise credentials_exc
        user_id: str = payload.get("sub")
        if not user_id:
            raise credentials_exc
    except JWTError:
        raise credentials_exc

    # RÉVOCATION des jetons d'ACCÈS. Elle n'était vérifiée qu'au refresh, au motif
    # documenté que « l'access token expire en 15 min » — or il vit 60 min (et
    # vivait 12 h tant que la variable n'atteignait pas le conteneur). Un jeton
    # émis avant un reset de mot de passe restait donc valable une heure entière
    # après ce reset : exactement ce que le reset est censé couper.
    # Coût : un GET Redis par requête authentifiée, fail-open comme au refresh.
    if await _refresh_revoked(user_id, payload.get("iat")):
        raise credentials_exc

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise credentials_exc
    return user


async def require_pro(user: User = Depends(get_current_user)) -> User:
    if user.plan not in ("starter", "standard", "expert"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Abonnement requis")
    return user


async def require_admin(user: User = Depends(get_current_user)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès admin requis")
    return user


async def require_verified_email(user: User = Depends(get_current_user)) -> User:
    """Réserve aux adresses confirmées ce qui coûte de l'argent ou de la réputation
    d'envoi : ouverture d'un essai Stripe, appels au modèle de langage.

    Les comptes créés avant la mise en service de la règle sont dispensés
    (cf. services.email_verification) — on ne ferme pas la porte derrière eux.
    """
    from services.email_verification import email_confirme

    if not email_confirme(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Confirmez votre adresse e-mail pour continuer. Le lien vous a été "
                   "envoyé à l'inscription ; vous pouvez le renvoyer depuis votre profil.",
        )
    return user


# ─────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────
@router.post("/register", response_model=TokenResponse)
async def register(body: RegisterRequest, response: Response,
                   db: AsyncSession = Depends(get_db),
                   _rl: None = Depends(rate_limit_auth)):
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
        token = secrets.token_urlsafe(32)
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

    tokens = create_tokens(user.user_id, user.plan)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/login", response_model=TokenResponse)
async def login(
    response: Response,
    form: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
    _rl: None = Depends(rate_limit_auth),
):
    result = await db.execute(select(User).where(User.email == form.username))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not _verify(form.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Identifiants incorrects")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Compte désactivé")
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    log.info("auth.login", user_id=user.user_id)
    tokens = create_tokens(user.user_id, user.plan)
    _set_auth_cookies(response, tokens)
    return tokens


@router.post("/logout")
async def logout(response: Response):
    """Efface les cookies de session. Le front ne peut pas le faire lui-même :
    des cookies httpOnly sont, par construction, hors de portée de JavaScript."""
    _clear_auth_cookies(response)
    return {"ok": True}


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    request: Request,
    response: Response,
    body: Optional[RefreshRequest] = None,
    db: AsyncSession = Depends(get_db),
):
    # Le jeton vient du cookie httpOnly ; le corps reste accepté pour les clients
    # non navigateur ET pour la bascule des sessions encore stockées côté client,
    # qui échangent ainsi leur ancien jeton contre des cookies.
    refresh_token = (body.refresh_token if body else None) or request.cookies.get(REFRESH_COOKIE)
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Token de rafraîchissement absent")
    try:
        payload = jwt.decode(refresh_token, settings.secret_key, algorithms=[settings.jwt_algorithm])
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token invalide")
        user_id = payload.get("sub")
    except JWTError:
        raise HTTPException(status_code=401, detail="Token expiré")

    # RÉVOCATION : un refresh token émis AVANT le dernier reset de mot de passe est
    # rejeté (un token volé ne survit pas au reset). Le même contrôle s'applique
    # désormais aussi aux jetons d'accès, dans `get_current_user` : les laisser
    # passer laissait survivre une session révoquée pendant toute leur durée de vie.
    if await _refresh_revoked(user_id, payload.get("iat")):
        raise HTTPException(status_code=401, detail="Session expirée, reconnectez-vous")

    result = await db.execute(select(User).where(User.user_id == user_id))
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="Utilisateur introuvable")
    tokens = create_tokens(user.user_id, user.plan)
    _set_auth_cookies(response, tokens)
    return tokens


async def _refresh_revoked(user_id: Optional[str], iat) -> bool:
    """True si le token (émis à `iat`) précède le dernier reset de mot de passe.

    Utilise le client Redis PARTAGÉ (`db.redis_client`) et non une connexion
    ouverte puis fermée à chaque appel : acceptable tant que seul le refresh
    appelait cette fonction, intenable depuis que chaque requête authentifiée la
    traverse — c'était une poignée de main TCP par requête.
    """
    if not user_id or iat is None:
        return False
    from db.redis_client import get_redis
    try:
        r = await get_redis()
        ts = await r.get(f"pwd_reset_at:{user_id}")
    except Exception:
        return False  # fail-open : panne Redis ne bloque pas une session légitime
    if not ts:
        return False
    try:
        return int(iat) < int(ts)
    except (TypeError, ValueError):
        return False


@router.post("/google", response_model=TokenResponse)
async def google_oauth(body: GoogleCallbackRequest, response: Response,
                       db: AsyncSession = Depends(get_db)):
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
        g_token = token_resp.json().get("access_token")
        if not g_token:
            raise HTTPException(status_code=400, detail="Réponse Google invalide")

        user_resp = await client.get(GOOGLE_USERINFO_URL, headers={"Authorization": f"Bearer {g_token}"})
        if user_resp.status_code != 200:
            raise HTTPException(status_code=400, detail="Profil Google inaccessible")
        g_user = user_resp.json()

    google_id = g_user.get("id")
    email = g_user.get("email")
    if not google_id or not email:
        raise HTTPException(status_code=400, detail="Profil Google incomplet")
    # Refuser un email Google non vérifié (sinon usurpation d'email).
    if g_user.get("verified_email") is False:
        raise HTTPException(status_code=400, detail="Email Google non vérifié")

    result = await db.execute(select(User).where(User.google_id == google_id))
    user = result.scalar_one_or_none()

    if not user:
        result2 = await db.execute(select(User).where(User.email == email))
        user = result2.scalar_one_or_none()
        if user:
            # ANTI ACCOUNT-TAKEOVER : ne PAS lier automatiquement Google à un compte
            # existant protégé par mot de passe (un attaquant créant un compte Google
            # au même email prendrait le contrôle). Lien auto seulement si le compte
            # n'a pas de mot de passe (créé via un autre SSO).
            if user.hashed_password:
                raise HTTPException(
                    status_code=409,
                    detail="Un compte existe déjà avec cet email. Connectez-vous par mot de passe, puis liez Google depuis votre profil.")
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

    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(user)
    log.info("auth.google", user_id=user.user_id, email=user.email)
    tokens = create_tokens(user.user_id, user.plan)
    _set_auth_cookies(response, tokens)
    return tokens


@router.get("/me", response_model=UserMeResponse)
async def me(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    # Reprise de session = signal d'usage réel (appelé au chargement de l'app) : on ne
    # le pose PAS à chaque requête (get_current_user est un Depends partagé partout),
    # seulement ici, pour ne pas noyer /me sous des écritures inutiles.
    now = datetime.now(timezone.utc)
    last = user.last_login_at
    # SQLite (tests) renvoie un datetime naïf malgré TIMESTAMPTZ en prod (Postgres) :
    # on le suppose UTC plutôt que de planter sur la comparaison.
    if last and last.tzinfo is None:
        last = last.replace(tzinfo=timezone.utc)
    if not last or (now - last) > timedelta(minutes=5):
        user.last_login_at = now
        await db.commit()

    # Essai en attente de carte : le front doit pouvoir l'expliquer et proposer
    # le portail Stripe. Import local — `stripe_routes` importe `auth`, l'importer
    # en tête d'`auth` créerait un cycle.
    from api.routes.stripe_routes import STATUT_SANS_CARTE, STATUTS_VIVANTS
    from db.models import Subscription

    # Une seule lecture pour les trois signaux : l'essai sans carte, l'existence
    # d'un abonnement pilotable, et le paiement en échec.
    vivants = (await db.execute(
        select(Subscription)
        .where(Subscription.user_id == user.user_id,
               Subscription.statut.in_(STATUTS_VIVANTS))
        .order_by(Subscription.created_at.desc())
    )).scalars().all()

    bloque = next((s for s in vivants if s.statut == STATUT_SANS_CARTE), None)
    # `essai_sans_carte` est un statut maison : il n'existe pas d'abonnement à
    # piloter tant que la carte n'est pas posée, et le portail Stripe n'a rien à
    # y montrer. Seuls les abonnements réellement portés par Stripe comptent.
    gerable = any(s.stripe_subscription_id and s.statut != STATUT_SANS_CARTE
                  for s in vivants)
    en_echec = any(s.statut == "past_due" for s in vivants)

    return UserMeResponse(
        user_id=user.user_id,
        email=user.email,
        nom=user.nom,
        prenom=user.prenom,
        plan=user.plan,
        profil_risque=user.profil_risque,
        email_verified=user.email_verified,
        is_admin=bool(user.is_admin),
        bankroll_initiale=user.bankroll_initiale,
        created_at=user.created_at,
        essai_bloque_sans_carte=bloque is not None,
        essai_fin=bloque.essai_fin if bloque else None,
        abonnement_gerable=gerable,
        paiement_en_echec=en_echec,
    )


@router.patch("/me")
async def update_me(
    body: dict,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Validation par champ : sans elle, profil_risque/bankroll_initiale étaient posés
    # bruts (ex. "abc", négatif, profil inconnu) → calculs de plan de mise corrompus.
    VALID_PROFILS = {"conservateur", "equilibre", "agressif"}
    updates: dict = {}
    for k, v in body.items():
        if k not in {"nom", "prenom", "profil_risque", "bankroll_initiale"}:
            continue
        if k == "profil_risque":
            if v not in VALID_PROFILS:
                raise HTTPException(status_code=422, detail="profil_risque invalide")
            updates[k] = v
        elif k == "bankroll_initiale":
            try:
                fv = float(v)
            except (TypeError, ValueError):
                raise HTTPException(status_code=422, detail="bankroll_initiale invalide")
            if not (0 < fv <= 1_000_000):
                raise HTTPException(status_code=422, detail="bankroll_initiale hors plage")
            updates[k] = round(fv, 2)
        else:  # nom / prenom
            if v is None:
                continue
            updates[k] = str(v).strip()[:100]
    for k, v in updates.items():
        setattr(user, k, v)
    await db.commit()
    return {"ok": True}


@router.post("/resend-verification")
async def resend_verification(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    # Un bouton « Renvoyer » est désormais affiché à tout compte non confirmé :
    # sans quota, il devient un robinet à e-mails (quota Resend, et une adresse
    # de tiers saisie par erreur se ferait matraquer).
    _rl: None = Depends(rate_limit_auth),
):
    """Renvoie l'email de vérification."""
    if user.email_verified:
        return {"ok": True}
    import redis.asyncio as aioredis
    from services.alerts import send_email
    token = secrets.token_urlsafe(32)
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
    _rl: None = Depends(rate_limit_auth),
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

    token = secrets.token_urlsafe(32)
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
    _rl: None = Depends(rate_limit_auth),
):
    """Réinitialise le mot de passe avec le token."""
    import redis.asyncio as aioredis

    token = body.get("token", "")
    new_password = body.get("password", "")

    # Même politique qu'au register (10 chars, pas trivial).
    if not token or len(new_password) < 10 or new_password.isalpha() or new_password.isdigit():
        raise HTTPException(status_code=400, detail="Mot de passe trop faible (min 10, lettres + chiffres)")

    r = aioredis.from_url(settings.redis_url)
    try:
        user_id = await r.get(f"pwd_reset:{token}")
        if not user_id:
            raise HTTPException(status_code=400, detail="Token expiré ou invalide")
        await r.delete(f"pwd_reset:{token}")
        uid = user_id.decode()
        # Invalide TOUS les tokens (access/refresh) émis avant ce reset : un token
        # volé ne survit pas au changement de mot de passe. TTL = durée du refresh.
        await r.setex(f"pwd_reset_at:{uid}",
                      settings.refresh_token_expire_days * 86400 + 3600,
                      int(datetime.now(timezone.utc).timestamp()))
    finally:
        await r.aclose()

    result = await db.execute(select(User).where(User.user_id == uid))
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
    # Validation + assainissement : ne JAMAIS stocker un JSON arbitraire tel quel
    # (re-servi ensuite → risque de stored XSS / pollution). On ne garde que la forme
    # attendue d'une PushSubscription.
    endpoint = body.get("endpoint")
    keys = body.get("keys")
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or not isinstance(keys, dict):
        raise HTTPException(status_code=422, detail="Souscription push invalide")
    exp = body.get("expirationTime")
    user.push_subscription = {
        "endpoint": endpoint[:1000],
        "keys": {
            "p256dh": str(keys.get("p256dh", ""))[:300],
            "auth": str(keys.get("auth", ""))[:300],
        },
        "expirationTime": exp if isinstance(exp, (int, float)) else None,
    }
    await db.commit()
    return {"ok": True}
