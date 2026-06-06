"""audit_schema_drift.py — compare colonnes ORM vs colonnes réelles en DB.

Repère toutes les colonnes que le modèle attend mais qui manquent en base
(= source des 500 UndefinedColumnError) en une passe, au lieu du whack-a-mole.
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import inspect
from db.database import engine
from db.models import Base


async def main() -> int:
    async with engine.connect() as conn:
        def work(sync_conn):
            insp = inspect(sync_conn)
            db_tables = set(insp.get_table_names())
            missing_cols = []
            missing_tables = []
            for table, tbl in Base.metadata.tables.items():
                if table not in db_tables:
                    missing_tables.append(table)
                    continue
                db_cols = {c["name"] for c in insp.get_columns(table)}
                for col in tbl.columns:
                    if col.name not in db_cols:
                        missing_cols.append((table, col.name, str(col.type)))
            return missing_tables, missing_cols

        missing_tables, missing_cols = await conn.run_sync(work)

    print("=== TABLES MODELE ABSENTES EN DB ===")
    for t in missing_tables:
        print(f"  {t}")
    print("=== COLONNES MODELE ABSENTES EN DB (causent 500) ===")
    for t, c, typ in missing_cols:
        print(f"  {t}.{c}  ({typ})")
    print(f"TOTAL tables manquantes={len(missing_tables)} colonnes manquantes={len(missing_cols)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
