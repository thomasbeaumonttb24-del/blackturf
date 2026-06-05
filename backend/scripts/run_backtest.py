"""
run_backtest.py — Backtest ROI en ligne de commande.

Rejoue les courses terminées d'une période et mesure le gain réel de la stratégie
value-bet. Lecture seule (aucune écriture en base).

Usage :
    python scripts/run_backtest.py --from 2026-01-01 --to 2026-03-31
    python scripts/run_backtest.py --from 2026-01-01 --to 2026-03-31 --kelly 0.5 --ev-min 0.05
"""
import sys
import os
import argparse
import asyncio
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401
from db.database import AsyncSessionLocal as async_session
from sqlalchemy import text
from ml.backtest import run_backtest, value_bet_strategy, portfolio_strategy


async def main(d_from, d_to, kelly, ev_min, bankroll, strategy, profil):
    async with async_session() as session:
        ids_r = await session.execute(text("""
            SELECT course_id FROM courses
            WHERE statut = 'termine' AND date_heure::date BETWEEN :a AND :b
            ORDER BY date_heure
        """), {"a": d_from, "b": d_to})
        course_ids = [r[0] for r in ids_r.fetchall()]
        if not course_ids:
            print(f"Aucune course terminée entre {d_from} et {d_to}.")
            return

        if strategy == "portfolio":
            strat_fn, strat_kwargs = portfolio_strategy, {"profil": profil}
        else:
            strat_fn, strat_kwargs = value_bet_strategy, {"kelly_fraction": kelly, "ev_min": ev_min}

        print(f"Backtest [{strategy}] sur {len(course_ids)} courses ({d_from} → {d_to})…")
        res = await run_backtest(
            session, course_ids, strategy=strat_fn, bankroll=bankroll, strategy_kwargs=strat_kwargs,
        )

    print("=" * 55)
    print("RÉSULTAT BACKTEST")
    print("=" * 55)
    print(f"  Courses jouées : {res.nb_courses}")
    print(f"  Paris          : {res.nb_bets}  (gagnés: {res.nb_wins})")
    print(f"  Hit-rate       : {res.hit_rate:.1%}")
    print(f"  Misé total     : {res.total_staked:.2f} €")
    print(f"  Retour total   : {res.total_returned:.2f} €")
    print(f"  Profit net     : {res.profit:+.2f} €")
    print(f"  ROI            : {res.roi:+.2%}")
    print(f"  Drawdown max   : {res.max_drawdown:.2f} €")
    print("  Par type :")
    for t, bt in res.by_type.items():
        print(f"    {t:10s} nb={bt['nb']:4d} roi={bt.get('roi', 0):+.2%} profit={bt['profit']:+.2f} €")
    print("=" * 55)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--from", dest="d_from", required=True, help="YYYY-MM-DD")
    p.add_argument("--to", dest="d_to", required=True, help="YYYY-MM-DD")
    p.add_argument("--kelly", type=float, default=0.25, help="Fraction de Kelly")
    p.add_argument("--ev-min", type=float, default=0.0, help="EV minimum pour parier")
    p.add_argument("--bankroll", type=float, default=100.0)
    p.add_argument("--strategy", choices=["value_bet", "portfolio"], default="value_bet")
    p.add_argument("--profil", default="equilibre", help="Profil portefeuille")
    args = p.parse_args()
    asyncio.run(main(
        date.fromisoformat(args.d_from), date.fromisoformat(args.d_to),
        args.kelly, args.ev_min, args.bankroll, args.strategy, args.profil,
    ))
