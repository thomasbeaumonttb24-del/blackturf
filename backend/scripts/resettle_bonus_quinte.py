"""
resettle_bonus_quinte.py — corrige les règlements de jackpots (Tiercé / Quarté+ /
Quinté+) figés AVANT les correctifs de lecture des rapports détaillés (2026-09-23
et 2026-09-24 : rapport lu par libellé, Bonus 4sur5 / Bonus 3, Ordre).

Mesure du 2026-09-24 (lecture seule) : 9 tickets sur 4 courses ont gagné un Bonus
mais restent stockés perdants — 7 instantanés `bet_plan_snapshots` (Bonus 4sur5,
02092026R1C1 et 20082026R1C8) et 2 runs `profil_run_log` (Bonus 3, 13072026R1C8
et 28072026R1C8).

- `bet_plan_settlements` est un journal EN AJOUT : on n'écrase rien, on ajoute un
  règlement plus récent (le dernier `settled_at` fait foi, cf. settle_course_plans).
- `profil_run_log` : `resultat` / `roi_reel` mis à jour, l'ancienne valeur étant
  d'abord écrite dans `--sauvegarde` (JSON).

Périmètre volontairement étroit : seuls les plans contenant un jackpot désordre ou
un module Quinté+, sur des courses dont le détail des rapports est publié. Garde-fou :
`--attendu-snapshots` / `--attendu-runs` — si le nombre de corrections diffère, rien
n'est écrit.

    python scripts/resettle_bonus_quinte.py --dry-run
    python scripts/resettle_bonus_quinte.py --sauvegarde /tmp/runs_avant.json
"""
import argparse
import asyncio
import json
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import db.models  # noqa: E402,F401
from sqlalchemy import text  # noqa: E402
from db.database import AsyncSessionLocal  # noqa: E402
from db.models import BetPlanSettlement  # noqa: E402
from services.bet_settlement import settle_plan  # noqa: E402

JACKPOTS = ("Tiercé", "Quarté", "Quinté")


def _json(v):
    if isinstance(v, (dict, list)):
        return v
    return json.loads(v) if isinstance(v, str) and v else {}


def _a_un_jackpot(plan: dict) -> bool:
    if (plan.get("module_quinte") or {}).get("disponible"):
        return True
    for niv in plan.get("niveaux") or []:
        for p in niv.get("paris") or []:
            if any(j in str(p.get("type") or "") for j in JACKPOTS):
                return True
    return False


def _gain(bilan: dict) -> float:
    """Gain du PLAN PRINCIPAL seul. Le module Quinté+ figé dans les plans du 23/09
    au 24/09 17 h n'était pas affiché aux utilisateurs : son règlement ne doit pas
    faire apparaître une « correction » sur un ticket que personne n'a vu."""
    return round(float(bilan.get("total_gain") or 0.0), 2)


async def _resultats(session):
    rows = (await session.execute(text("""
        SELECT r.course_id, r.classement, r.rapports, c.nb_partants, r.rapports_detail
        FROM resultats r JOIN courses c ON c.course_id = r.course_id
        WHERE r.classement IS NOT NULL
          AND r.rapports_detail IS NOT NULL
          AND (r.rapports_detail ? 'e_quinte_plus' OR r.rapports_detail ? 'e_quarte_plus'
               OR r.rapports_detail ? 'e_tierce')
    """))).all()
    out = {}
    for cid, cl, rp, nbp, det in rows:
        cl = _json(cl)
        out[cid] = (cl if isinstance(cl, list) else [], _json(rp) or {}, nbp or len(cl or []),
                    _json(det) or None)
    return out


async def _non_partants(session, cid):
    rows = (await session.execute(text(
        "SELECT numero FROM participations WHERE course_id = :c AND non_partant = true"),
        {"c": cid})).all()
    return {int(r[0]) for r in rows if r[0] is not None}


async def main(args) -> int:
    async with AsyncSessionLocal() as s:
        res = await _resultats(s)
        snaps = (await s.execute(text("""
            SELECT DISTINCT ON (t.plan_snapshot_id)
                   t.plan_snapshot_id, t.course_id, s.plan, t.bilan
            FROM bet_plan_settlements t
            JOIN bet_plan_snapshots s ON s.plan_snapshot_id = t.plan_snapshot_id
            WHERE t.statut = 'settled' AND t.course_id = ANY(:cids)
            ORDER BY t.plan_snapshot_id, t.settled_at DESC
        """), {"cids": list(res)})).all()
        runs = (await s.execute(text("""
            SELECT log_id, course_id, plan, resultat, roi_reel, statut
            FROM profil_run_log
            WHERE statut IN ('settled', 'partial') AND course_id = ANY(:cids)
        """), {"cids": list(res)})).all()

        a_ajouter, a_maj = [], []
        for sid, cid, plan, ancien in snaps:
            plan = _json(plan)
            if not _a_un_jackpot(plan):
                continue
            cl, rp, nbp, det = res[cid]
            bilan = settle_plan(plan, cl, rp, nbp, det, await _non_partants(s, cid))
            if abs(_gain(bilan) - _gain(_json(ancien))) > 0.005:
                a_ajouter.append((sid, cid, bilan, _gain(_json(ancien))))
        for log_id, cid, plan, ancien, roi_ancien, statut in runs:
            plan = _json(plan)
            if not _a_un_jackpot(plan):
                continue
            cl, rp, nbp, det = res[cid]
            bilan = settle_plan(plan, cl, rp, nbp, det, await _non_partants(s, cid))
            if abs(_gain(bilan) - _gain(_json(ancien))) > 0.005:
                a_maj.append((log_id, cid, bilan, _json(ancien), roi_ancien, statut))

    print(f"Instantanés à re-régler : {len(a_ajouter)}")
    for sid, cid, b, g0 in a_ajouter:
        print(f"  {cid} {sid[:8]} gain {g0:.2f} -> {_gain(b):.2f}")
    print(f"Runs profil_run_log à corriger : {len(a_maj)}")
    for log_id, cid, b, anc, _, _ in a_maj:
        print(f"  {cid} log {log_id} gain {_gain(anc):.2f} -> {_gain(b):.2f}")

    if (args.attendu_snapshots is not None and len(a_ajouter) != args.attendu_snapshots) or \
       (args.attendu_runs is not None and len(a_maj) != args.attendu_runs):
        print("ARRÊT : le nombre de corrections diffère de l'attendu — rien n'est écrit.")
        return 2
    if args.dry_run:
        print("DRY-RUN — aucune écriture.")
        return 0

    if a_maj:
        Path(args.sauvegarde).write_text(json.dumps([
            {"log_id": log_id, "course_id": cid, "resultat": anc, "roi_reel": roi, "statut": st}
            for log_id, cid, _, anc, roi, st in a_maj], ensure_ascii=False, default=str))
        print(f"Sauvegarde des anciens runs : {args.sauvegarde}")

    now = datetime.now(timezone.utc)
    async with AsyncSessionLocal() as s:
        for sid, cid, b, _ in a_ajouter:
            statut = "partial" if b.get("en_attente") else "settled"
            await s.execute(BetPlanSettlement.__table__.insert().values(
                settlement_id=str(uuid.uuid4()), plan_snapshot_id=sid, course_id=cid,
                bilan=b, montant_mise=float(b.get("total_mise") or 0.0),
                montant_retour=float(b.get("total_gain") or 0.0),
                net=float(b.get("net") or 0.0),
                roi=(float(b["roi"]) / 100.0) if b.get("roi") is not None else None,
                nb_paris=int(b.get("nb_paris") or 0), nb_gagnes=int(b.get("nb_gagnes") or 0),
                statut=statut, settled_at=now))
        for log_id, cid, b, _, _, _ in a_maj:
            roi = b.get("roi")
            await s.execute(text("""
                UPDATE profil_run_log
                SET resultat = CAST(:res AS jsonb), roi_reel = :roi, statut = :st,
                    settled_at = now()
                WHERE log_id = :id
            """), {"res": json.dumps(b, default=str),
                   "roi": (roi / 100.0) if roi is not None else None,
                   "st": "partial" if b.get("en_attente") else "settled", "id": log_id})
        await s.commit()
    print(f"Écrit : {len(a_ajouter)} règlements ajoutés, {len(a_maj)} runs corrigés.")
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--attendu-snapshots", type=int, default=None)
    p.add_argument("--attendu-runs", type=int, default=None)
    p.add_argument("--sauvegarde", default="/tmp/profil_run_log_avant_resettle_bonus.json")
    sys.exit(asyncio.run(main(p.parse_args())))
