"""Export read-only, replay in isolated SQLite, then fill ONLY missing snapshots.

Run as python -m scripts.elo_backfill_isole export|replay|apply PATH.
The export is a rollback before-image. Live horse ratings/history are never changed.
"""
import argparse
import asyncio
import hashlib
import itertools
import json
import math
import os
from datetime import date
from pathlib import Path

FIELDS = ("global", "plat", "trot", "obstacle")


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                     ensure_ascii=False).encode()).hexdigest()


def source_identity(data):
    return {"cutoff": data["cutoff"], "courses": data["courses"],
            "parts": [p[:4] for p in data["parts"]]}


async def read_source(session, cutoff):
    from sqlalchemy import text
    from datetime import datetime
    cutoff_value = datetime.fromisoformat(cutoff)
    courses = (await session.execute(text("""
        SELECT c.course_id, c.date_heure, c.discipline, c.niveau_course,
               c.allocation, r.classement
        FROM courses c LEFT JOIN resultats r USING(course_id)
        WHERE c.statut='termine' AND c.date_heure < CAST(:cutoff AS timestamptz)
        ORDER BY c.date_heure, c.course_id
    """), {"cutoff": cutoff_value})).all()
    parts = (await session.execute(text("""
        SELECT p.participation_id, p.course_id, p.cheval_id, p.numero,
               p.elo_avant_global, p.elo_avant_plat, p.elo_avant_trot, p.elo_avant_obstacle
        FROM participations p JOIN courses c USING(course_id)
        WHERE c.statut='termine' AND c.date_heure < CAST(:cutoff AS timestamptz)
        ORDER BY p.participation_id
    """), {"cutoff": cutoff_value})).all()
    return {"cutoff": cutoff,
            "courses": [[r[0], r[1].isoformat(), *r[2:]] for r in courses],
            "parts": [list(p) for p in parts]}


async def export(path):
    from datetime import datetime, timezone
    from sqlalchemy import text
    from db.database import AsyncSessionLocal
    if path.exists():
        raise ValueError("Refusing to overwrite a before-image")
    cutoff = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    async with AsyncSessionLocal() as s:
        await s.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
        await s.execute(text("SET LOCAL statement_timeout = '60s'"))
        data = await read_source(s, cutoff)
    data["source_sha256"] = digest(source_identity(data))
    data["elo_code_sha256"] = hashlib.sha256(Path("ml/elo.py").read_bytes()).hexdigest()
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"courses": len(data["courses"]), "parts": len(data["parts"]),
                      "missing": sum(any(v is None for v in p[4:]) for p in data["parts"]),
                      "source_sha256": data["source_sha256"]}), flush=True)


async def replay(path):
    # This mode cannot connect to PostgreSQL, even if the working directory has a .env.
    os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///:memory:"
    os.environ["ENVIRONMENT"] = "test"
    import structlog
    structlog.configure(wrapper_class=structlog.make_filtering_bound_logger(40))
    from sqlalchemy import select, text
    from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
    from db.models import Cheval, EloHistorique
    from ml.elo import update_elo_after_race, ELO_INITIAL
    data = json.loads(path.read_text(encoding="utf-8"))
    if data["source_sha256"] != digest(source_identity(data)):
        raise ValueError("Export checksum mismatch")
    if data["elo_code_sha256"] != hashlib.sha256(Path("ml/elo.py").read_bytes()).hexdigest():
        raise ValueError("ELO implementation differs from exported production code")
    copy_path = path.with_suffix(".sqlite")
    result_path = path.with_suffix(".result.json")
    if copy_path.exists() or result_path.exists():
        raise ValueError("Use a fresh export; refusing to overwrite replay artifacts")
    engine = create_async_engine("sqlite+aiosqlite:///" + copy_path.resolve().as_posix())
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Cheval.metadata.create_all(c, tables=[Cheval.__table__, EloHistorique.__table__]))
        await conn.execute(text("CREATE INDEX replay_elo_course ON elo_historique(course_id)"))
    by_course = {}
    for p in data["parts"]:
        by_course.setdefault(p[1], []).append(p)
    horse_ids = sorted({p[2] for p in data["parts"]})
    snapshots = []
    count = 0
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        for i in range(0, len(horse_ids), 1000):
            await s.execute(Cheval.__table__.insert(), [dict(cheval_id=h, nom=h,
                **{"elo_score_" + f: ELO_INITIAL for f in FIELDS}) for h in horse_ids[i:i+1000]])
        await s.commit()
        # All snapshots at a shared timestamp precede all results at that timestamp.
        for _, group in itertools.groupby(data["courses"], key=lambda c: c[1]):
            group = list(group)
            ids = sorted({p[2] for c in group for p in by_course.get(c[0], [])})
            horses = {}
            for i in range(0, len(ids), 500):
                horses.update({h.cheval_id: h for h in (await s.execute(
                    select(Cheval).where(Cheval.cheval_id.in_(ids[i:i+500])))).scalars()})
            for c in group:
                for p in by_course.get(c[0], []):
                    if any(v is None for v in p[4:]):
                        values = [getattr(horses[p[2]], "elo_score_" + f) for f in FIELDS]
                        snapshots.append([p[0], *values])
            for cid, when, disc, level, allocation, classement in group:
                if not isinstance(classement, list) or not classement:
                    raise ValueError("Missing result: " + cid)
                numbers = {int(p[3]): p[2] for p in by_course.get(cid, [])}
                ranked = []
                for r in classement:
                    horse = numbers.get(int(r["numero"]))
                    # Disqualifiés gardés : `classement_elo` les range derniers.
                    if horse is not None and (r.get("position") is not None or r.get("incident")):
                        ranked.append({"cheval_id": horse, "position": r.get("position"),
                                       "incident": r.get("incident")})
                if len({r["cheval_id"] for r in ranked}) != len(ranked):
                    raise ValueError("Duplicate result horse: " + cid)
                await update_elo_after_race(s, cid, disc or "plat", level, allocation, ranked,
                                            date_course=date.fromisoformat(when[:10]))
                count += 1
                if count % 500 == 0:
                    await s.commit()
                    print(f"replayed {count}/{len(data['courses'])}", flush=True)
        await s.commit()
    await engine.dispose()
    result = {"source_sha256": data["source_sha256"], "elo_code_sha256": data["elo_code_sha256"],
              "cutoff": data["cutoff"], "rows": snapshots, "courses_replayed": count}
    result["result_sha256"] = digest(result)
    result_path.write_text(json.dumps(result), encoding="utf-8")
    print(f"REPLAY_DONE {count} courses, {len(snapshots)} missing snapshots", flush=True)


async def apply(path):
    from sqlalchemy import text
    from db.database import AsyncSessionLocal
    data = json.loads(path.read_text(encoding="utf-8"))
    result = json.loads(path.with_suffix(".result.json").read_text(encoding="utf-8"))
    claimed = result.pop("result_sha256")
    if digest(result) != claimed or digest(source_identity(data)) != result["source_sha256"]:
        raise ValueError("Artifact checksum mismatch")
    if result["courses_replayed"] != len(data["courses"]):
        raise ValueError("Incomplete replay")
    expected = {p[0] for p in data["parts"] if any(v is None for v in p[4:])}
    rows = result["rows"]
    if len(rows) != len(expected) or {r[0] for r in rows} != expected:
        raise ValueError("Unexpected or missing participation IDs")
    for r in rows:
        if len(r) != 5 or not all(math.isfinite(v) and 800 <= v <= 2800 for v in r[1:]):
            raise ValueError("Invalid reconstructed rating")
    async with AsyncSessionLocal() as s:
        await s.execute(text("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE"))
        await s.execute(text("SET LOCAL lock_timeout = '5s'"))
        await s.execute(text("SET LOCAL statement_timeout = '60s'"))
        if not (await s.execute(text("SELECT pg_try_advisory_xact_lock(20260922, 1)"))).scalar():
            raise ValueError("Another backfill is running")
        current = await read_source(s, data["cutoff"])
        if digest(source_identity(current)) != result["source_sha256"]:
            raise ValueError("Historical source changed since export; new replay required")
        if hashlib.sha256(Path("ml/elo.py").read_bytes()).hexdigest() != result["elo_code_sha256"]:
            raise ValueError("Production ELO implementation changed")
        await s.execute(text("CREATE TEMP TABLE elo_backfill (id text PRIMARY KEY, g double precision, p double precision, t double precision, o double precision) ON COMMIT DROP"))
        for i in range(0, len(rows), 1000):
            await s.execute(text("INSERT INTO elo_backfill VALUES (:id,:g,:p,:t,:o)"),
                            [dict(zip(("id", "g", "p", "t", "o"), r)) for r in rows[i:i+1000]])
        updated = await s.execute(text("""
            UPDATE participations p SET
                elo_avant_global=COALESCE(p.elo_avant_global,b.g),
                elo_avant_plat=COALESCE(p.elo_avant_plat,b.p),
                elo_avant_trot=COALESCE(p.elo_avant_trot,b.t),
                elo_avant_obstacle=COALESCE(p.elo_avant_obstacle,b.o)
            FROM elo_backfill b WHERE p.participation_id=b.id
              AND (p.elo_avant_global IS NULL OR p.elo_avant_plat IS NULL
                   OR p.elo_avant_trot IS NULL OR p.elo_avant_obstacle IS NULL)
        """))
        after = await read_source(s, data["cutoff"])
        before_by_id = {p[0]: p for p in current["parts"]}
        calculated = {r[0]: r[1:] for r in rows}
        for p in after["parts"]:
            old = before_by_id[p[0]]
            for index, value in enumerate(p[4:]):
                wanted = old[index + 4]
                if wanted is None and p[0] in calculated:
                    wanted = calculated[p[0]][index]
                if value != wanted:
                    raise ValueError("Post-update verification failed: " + p[0])
        await s.commit()
        print(f"APPLY_DONE {updated.rowcount} participations; live horse ratings/history untouched", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("export", "replay", "apply"))
    parser.add_argument("path", type=Path)
    args = parser.parse_args()
    asyncio.run(globals()[args.mode](args.path))
