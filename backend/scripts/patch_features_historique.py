"""
patch_features_historique.py — Lot « historique v2 » (BT_HIST_V2) sur les vecteurs
`features_ml` déjà stockés, SANS recalcul complet ni fuite.

Deux temps, jamais mêlés :

  calcul     (LECTURE SEULE) : pour chaque course terminée, calcule la même course
             deux fois avec le code actuel —
               • « avant » : historique d'avant le lot (drapeau éteint), copie PMU de
                 la course elle-même écartée ;
               • « après » : lot v2 actif.
             Une clé n'est corrigée QUE si le calcul « avant » reproduit EXACTEMENT
             la valeur stockée : toutes les autres entrées (cotes, ELO, saisons…)
             sont alors celles du calcul d'origine, et la seule différence
             introduite est le lot. Les vecteurs non reproduits gardent leur valeur.
             Écrit un fichier JSONL (une ligne par partant corrigé) + un résumé.

  appliquer  (ÉCRITURE) : réécrit les SEULES clés du fichier dans `features_ml`
             (`features || patch`), `computed_at` jamais modifié. Chaque ancienne
             valeur est déjà dans le fichier (clé "ancien") : retour arrière =
             réappliquer "ancien".

POURQUOI PAS recompute_features_prerace.py : recalculer tout le vecteur injecte des
valeurs d'après course (fuite du 24/09 : ELO du résultat, cote de clôture, saisons).
Et un recalcul naïf de l'historique lit la copie PMU de la course elle-même (datée
de la veille) : mesuré sur 300 courses, la reproduction des valeurs stockées passe
de 74 % à 79 % sur `time_decay_form` une fois cette copie écartée.

    python scripts/patch_features_historique.py calcul --depuis 2025-09-01 \
        --sortie /out/patch_v2_0.jsonl --shard 0/4
    python scripts/patch_features_historique.py appliquer --fichiers /out/patch_v2_*.jsonl
"""
from __future__ import annotations

import argparse
import asyncio
import glob
import json
import math
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

CLES_IDENTITE = {"participation_id", "course_id"}


def egal(a, b) -> bool:
    """Égalité stricte à l'arrondi flottant près (1e-9 relatif)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b or a == b and type(a) is type(b)
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        fa, fb = float(a), float(b)
        if math.isnan(fa) or math.isnan(fb):
            return math.isnan(fa) and math.isnan(fb)
        return abs(fa - fb) <= 1e-9 * max(1.0, abs(fa))
    return a == b


def corrections_course(avant: dict, apres: dict, stocke: dict) -> tuple[dict, dict]:
    """(patch, stats) pour UNE course.

    avant / apres / stocke : {participation_id: {clé: valeur}}.
    Une clé est corrigée si (1) le lot la change, (2) le calcul « avant » reproduit
    exactement la valeur stockée. `stats[clé]` compte : diff (le lot la change),
    corrige, non_reproduit.
    """
    patch: dict = {}
    stats: dict = defaultdict(lambda: {"diff": 0, "corrige": 0, "non_reproduit": 0,
                                       "non_fini": 0})
    for pid, v_apres in apres.items():
        v_avant = avant.get(pid)
        v_sto = stocke.get(pid)
        if v_avant is None or v_sto is None:
            continue
        p_nouveau, p_ancien = {}, {}
        for k, nouvelle in v_apres.items():
            if k in CLES_IDENTITE or k not in v_avant or egal(nouvelle, v_avant[k]):
                continue
            s = stats[k]
            s["diff"] += 1
            if isinstance(nouvelle, float) and not math.isfinite(nouvelle):
                s["non_fini"] += 1          # jsonb refuse NaN/inf : jamais écrit
                continue
            if k in v_sto and egal(v_sto[k], v_avant[k]):
                p_nouveau[k] = nouvelle
                p_ancien[k] = v_sto[k]
                s["corrige"] += 1
            else:
                s["non_reproduit"] += 1
        if p_nouveau:
            patch[pid] = {"patch": p_nouveau, "ancien": p_ancien}
    return patch, stats


async def _courses(depuis: datetime, jusqua: datetime | None) -> list[str]:
    from db.database import AsyncSessionLocal
    async with AsyncSessionLocal() as s:
        await s.execute(text("SET TRANSACTION READ ONLY"))
        rows = (await s.execute(text(f"""
            SELECT c.course_id FROM courses c
            WHERE c.statut = 'termine' AND c.date_heure >= :d
              {"AND c.date_heure < :f" if jusqua else ""}
              AND EXISTS (SELECT 1 FROM participations p
                          JOIN features_ml f ON f.participation_id = p.participation_id
                          WHERE p.course_id = c.course_id AND f.computed_at < c.date_heure)
            ORDER BY c.course_id
        """), {"d": depuis, **({"f": jusqua} if jusqua else {})})).all()
    return [r[0] for r in rows]


async def calcul(args) -> int:
    from db.database import AsyncSessionLocal
    from ml.features import compute_all_features_for_course

    depuis = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    jusqua = (datetime.strptime(args.jusqua, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              if args.jusqua else None)
    i_shard, n_shard = (int(x) for x in args.shard.split("/"))
    cids = [c for j, c in enumerate(await _courses(depuis, jusqua)) if j % n_shard == i_shard]
    if args.limite:
        cids = cids[:args.limite]
    print(f"[patch-v2] shard {i_shard}/{n_shard} : {len(cids)} courses", flush=True)

    tot: dict = defaultdict(lambda: {"diff": 0, "corrige": 0, "non_reproduit": 0,
                                     "non_fini": 0})
    n_vect = n_patch = 0
    erreurs = []
    t0 = time.monotonic()
    with open(args.sortie, "w", encoding="utf-8") as out:
        for i, cid in enumerate(cids, 1):
            try:
                async with AsyncSessionLocal() as s:
                    # Instantané unique et LECTURE SEULE : toute écriture lèverait.
                    await s.execute(text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                    avant = {f["participation_id"]: f for f in await compute_all_features_for_course(
                        s, cid, hist_dedup=False, exclure_copie_course=True)}
                    apres = {f["participation_id"]: f for f in await compute_all_features_for_course(
                        s, cid, hist_dedup=True, exclure_copie_course=True)}
                    stocke = dict((await s.execute(text("""
                        SELECT f.participation_id, f.features
                        FROM features_ml f
                        JOIN participations p ON p.participation_id = f.participation_id
                        JOIN courses c ON c.course_id = p.course_id
                        WHERE p.course_id = :c AND f.computed_at < c.date_heure
                    """), {"c": cid})).all())
                    await s.rollback()
            except Exception as e:  # noqa: BLE001 — une course en échec se voit, ne bloque pas
                erreurs.append(f"{cid}: {type(e).__name__}: {str(e)[:160]}")
                continue
            patch, stats = corrections_course(avant, apres, stocke)
            n_vect += len(stocke)
            for k, s_ in stats.items():
                for m, v in s_.items():
                    tot[k][m] += v
            for pid, p in patch.items():
                out.write(json.dumps({"participation_id": pid, "course_id": cid, **p},
                                     ensure_ascii=False) + "\n")
                n_patch += 1
            if i % 200 == 0:
                el = time.monotonic() - t0
                print(f"[patch-v2] {i}/{len(cids)} — {el/i:.2f} s/course, "
                      f"reste ~{el/i*(len(cids)-i)/60:.0f} min", flush=True)
    resume = {"shard": args.shard, "courses": len(cids), "vecteurs": n_vect,
              "vecteurs_corriges": n_patch, "erreurs": len(erreurs),
              "exemples_erreurs": erreurs[:20], "cles": dict(tot)}
    with open(args.sortie + ".resume.json", "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=1)
    print(f"[patch-v2] fini : {n_patch} vecteurs corrigés sur {n_vect}, "
          f"{len(erreurs)} erreurs", flush=True)
    return 0 if not erreurs else 2


async def appliquer(args) -> int:
    from db.database import AsyncSessionLocal
    fichiers = sorted(f for motif in args.fichiers for f in glob.glob(motif))
    n = 0
    for chemin in fichiers:
        with open(chemin, encoding="utf-8") as fh:
            lignes = [json.loads(l) for l in fh if l.strip()]
        async with AsyncSessionLocal() as s:
            for ligne in lignes:
                valeurs = ligne["ancien"] if args.retour_arriere else ligne["patch"]
                # `||` ne remplace que ces clés ; `computed_at` n'est pas dans le SET.
                await s.execute(text("""
                    UPDATE features_ml SET features = features || CAST(:p AS jsonb)
                    WHERE participation_id = :pid
                """), {"p": json.dumps(valeurs), "pid": ligne["participation_id"]})
                n += 1
            await s.commit()
        print(f"[patch-v2] {chemin} : {len(lignes)} vecteurs "
              f"{'restaurés' if args.retour_arriere else 'corrigés'}", flush=True)
    print(f"[patch-v2] total {n}", flush=True)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("calcul")
    c.add_argument("--depuis", default="2025-09-01")
    c.add_argument("--jusqua", default=None)
    c.add_argument("--sortie", required=True)
    c.add_argument("--shard", default="0/1")
    c.add_argument("--limite", type=int, default=0)
    a = sub.add_parser("appliquer")
    a.add_argument("--fichiers", nargs="+", required=True)
    a.add_argument("--retour-arriere", action="store_true")
    args = ap.parse_args()
    return asyncio.run(calcul(args) if args.mode == "calcul" else appliquer(args))


if __name__ == "__main__":
    sys.exit(main())
