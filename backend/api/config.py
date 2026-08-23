from pydantic_settings import BaseSettings
from pydantic import Field, field_validator, model_validator
from functools import lru_cache

_WEAK_SECRETS = {"changeme", "secret", "dev", "test", "password", "secret_key", "votre_secret"}


class Settings(BaseSettings):
    # App
    environment: str = "development"
    frontend_url: str = "https://blackturf.fr"
    api_url: str = "https://api.blackturf.fr"
    allowed_origins: list[str] = ["https://blackturf.fr", "https://www.blackturf.fr"]

    # DB
    database_url: str
    database_url_sync: str = ""

    # Redis
    redis_url: str

    # JWT
    secret_key: str
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 720  # 12h : 15min etait trop court (sessions mobiles mortes en continu)
    refresh_token_expire_days: int = 7

    # External APIs
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    brightdata_proxy: str = ""
    betfair_ingest_token: str = ""   # secret partagé pour /admin/api/ingest-betfair
    stripe_secret_key: str = ""
    stripe_publishable_key: str = ""
    stripe_webhook_secret: str = ""
    stripe_price_starter_monthly: str = ""
    stripe_price_starter_annual: str = ""
    stripe_price_pro_monthly: str = ""
    stripe_price_pro_annual: str = ""
    resend_api_key: str = ""
    email_from: str = "noreply@blackturf.fr"
    email_from_name: str = "BlackTurf"
    openweather_api_key: str = ""

    # IndexNow : signale à Bing, Yandex, Naver et Seznam qu'une URL vient de changer.
    # Google N'UTILISE PAS ce protocole. La clé n'est pas un secret — elle est publiée
    # en clair sur le site, c'est le mécanisme même du protocole. Vide = fonction inactive.
    indexnow_key: str = ""

    # ── Publication Instagram (Graph API) ──────────────────────────────────────────
    # `instagram_publication_active` est le SEUL interrupteur qui autorise une
    # publication reelle. Il reste a 0 tant que personne ne le passe explicitement a 1 :
    # publier au nom d'une marque est irreversible et public, cela ne doit jamais
    # demarrer simplement parce qu'un jeton se trouve present dans l'environnement.
    meta_access_token: str = ""
    instagram_user_id: str = ""
    instagram_publication_active: bool = False

    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""

    # Web Push
    vapid_public_key: str = ""
    vapid_private_key: str = ""
    vapid_subject: str = "mailto:admin@blackturf.fr"

    # ML
    models_path: str = "./models"
    model_min_auc: float = 0.60
    retrain_hour_utc: int = 2
    retrain_every_n_results: int = 20
    # Le dataset JSON se déplie fortement en mémoire pendant l'entraînement.
    # Trois mois (~40k partants en production) tiennent dans le worker 6 Gio ;
    # une fenêtre plus longue reste configurable sur un serveur plus puissant.
    retrain_history_months: int = Field(default=3, ge=1, le=36)

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    # Monitoring
    sentry_dsn: str = ""

    # Admin
    admin_email: str = "admin@blackturf.fr"

    model_config = {
        "env_file": ".env",
        "case_sensitive": False,
        "protected_namespaces": ("settings_",),
    }

    @field_validator("secret_key")
    @classmethod
    def _secret_strength(cls, v: str) -> str:
        # HS256 : un secret faible est brute-forçable hors-ligne → forge de JWT
        # arbitraires (n'importe quel sub / is_admin). On exige >= 32 caractères.
        if len(v) < 32:
            raise ValueError("SECRET_KEY doit faire au moins 32 caractères")
        if v.strip().lower() in _WEAK_SECRETS:
            raise ValueError("SECRET_KEY trivial interdit")
        return v

    @model_validator(mode="after")
    def _validate_prod(self):
        # En production : pas d'origine CORS wildcard avec credentials, et pas de
        # secret par défaut. Échoue au démarrage plutôt que d'exposer une faille.
        if self.environment == "production":
            if "*" in self.allowed_origins:
                raise ValueError("CORS wildcard '*' interdit en production")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
