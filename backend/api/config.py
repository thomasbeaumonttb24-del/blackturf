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

    # Pool de connexions PostgreSQL, PAR PROCESSUS. Ces valeurs sont un BUDGET
    # partagé, pas un réglage local : le serveur n'accepte que
    # `max_connections - superuser_reserved_connections` sessions au total
    # (50 - 3 = 47 en production, cf. docker-compose.prod.yml), et cinq
    # processus s'y connectent — les DEUX workers uvicorn de l'API, le scraper,
    # le worker RQ et le scheduler.
    #
    # Les valeurs d'origine (20 + 40 = 60 par processus) autorisaient donc à
    # elles seules 300 connexions contre 47 disponibles. La saturation n'arrive
    # pas au repos (23 sessions ouvertes le 01/09) mais au premier pic simultané,
    # et elle ne se manifeste pas là où elle naît : le 31/08 à 20:31 c'est
    # `/admin/api/adaptive-learning/history` qui est tombé en
    # `TooManyConnectionsError`, une requête parfaitement innocente qui n'avait
    # que le tort d'arriver après les autres.
    #
    # Les défauts ci-dessous sont dimensionnés pour le PIRE cas : un processus
    # qui ne reçoit aucune surcharge par `environment:` reste sous le budget
    # (4+4=8 par processus, soit 8 × 5 = 40 < 47). Les surcharges par service
    # vivent dans les deux compose et sont verrouillées par
    # `tests/test_deploy_config_safety.py::test_budget_connexions_postgres`.
    db_pool_size: int = Field(default=4, ge=1, le=50)
    db_max_overflow: int = Field(default=4, ge=0, le=50)
    # Une connexion gardée indéfiniment finit par être coupée en silence par le
    # réseau ou par le serveur ; `pool_pre_ping` la détecte mais après un
    # aller-retour perdu. Les recycler évite le cas — même classe de panne que la
    # socket Redis morte après une nuit d'inactivité (27/08).
    db_pool_recycle_s: int = Field(default=1800, ge=60)

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
    # graph.instagram.com = voie « Instagram Login » (aucune Page Facebook requise).
    # graph.facebook.com = voie « Facebook Login », qui exige une Page liee.
    instagram_api_host: str = "graph.instagram.com"

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
    # Fenêtre d'historique du retraining. Elle est GLISSANTE : chaque nuit elle
    # perd un jour ancien et gagne un jour récent. Tant qu'elle valait trois mois,
    # le nombre de partants d'entraînement DÉCROISSAIT mécaniquement (les semaines
    # de mai portaient ~3 900 partants, celles d'août ~2 800) alors que la base en
    # contenait 175 000 exploitables sur douze mois — 76 % jetés chaque nuit, et
    # aucune saison hivernale dans le modèle d'été. Douze mois couvrent un cycle
    # complet. Le plafond `retrain_max_rows` protège la RAM, pas la fenêtre.
    retrain_history_months: int = Field(default=12, ge=1, le=36)
    # Garde-fou mémoire : au-delà, on garde les N partants les PLUS RÉCENTS. Un
    # plafond fait stagner le compteur, il ne le fait pas décroître — contrairement
    # à une fenêtre glissante trop courte.
    retrain_max_rows: int = Field(default=220_000, ge=1_000)
    # Retrain déclenché en journée par post_course. Le worker RQ est unique : un
    # entraînement de 20 min (fenêtre douze mois) y bloque règlements, prédictions
    # et alertes. Le nightly de 02:00 UTC voit le même dataset, hors courses.
    retrain_intraday_enabled: bool = False

    # Telegram
    telegram_bot_token: str = ""
    telegram_webhook_secret: str = ""

    # Monitoring
    sentry_dsn: str = ""

    # Admin
    admin_email: str = "admin@blackturf.fr"

    # Carte déjà vue sur un AUTRE compte (empreinte Stripe `card.fingerprint`) :
    #   "refus_essai" — l'essai gratuit est refusé, l'abonnement payant reste
    #                   possible. Coupe la fraude « nouvel e-mail, même carte »
    #                   sans punir un couple qui partage une carte. DÉFAUT.
    #   "blocage"     — la carte ne peut pas être rattachée à un second compte :
    #                   l'abonnement est annulé sur-le-champ.
    #   "ignorer"     — aucun contrôle (comportement d'avant le 2026-08-27).
    carte_reutilisee_politique: str = "refus_essai"

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
