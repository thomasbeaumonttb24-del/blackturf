from logging.config import fileConfig
from sqlalchemy import engine_from_config, pool
from alembic import context

from db.models import Base  # noqa: F401 — importe tous les modèles
from api.config import get_settings

settings = get_settings()
config = context.config

# Migrations exécutées en SYNCHRONE (psycopg2) : standard alembic, et surtout
# les erreurs SQL remontent immédiatement (asyncpg les masque dans une
# transaction groupée). On dérive l'URL sync depuis la config.
_sync_url = settings.database_url_sync or settings.database_url.replace("+asyncpg", "+psycopg2")
config.set_main_option("sqlalchemy.url", _sync_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    url = config.get_main_option("sqlalchemy.url")
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    # AUTOCOMMIT : chaque statement DDL se valide seul. Plusieurs migrations
    # utilisent `try/except: pass` autour de DDL « peut déjà exister » ; en
    # transaction unique, un échec rattrapé laisse la transaction PostgreSQL
    # avortée et casse tout le reste. En autocommit, l'échec rattrapé est isolé.
    with connectable.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            transactional_ddl=False,
        )
        context.run_migrations()
    connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
