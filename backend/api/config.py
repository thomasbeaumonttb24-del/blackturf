from pydantic_settings import BaseSettings
from pydantic import Field
from functools import lru_cache


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
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # External APIs
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-4-5-20251001"
    brightdata_proxy: str = ""
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


@lru_cache
def get_settings() -> Settings:
    return Settings()
