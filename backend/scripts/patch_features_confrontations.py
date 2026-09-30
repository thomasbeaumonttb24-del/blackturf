"""
patch_features_confrontations.py — Réécrit les SEULES clés `conf_*` des vecteurs
`features_ml` déjà stockés, avec la clé « même course » corrigée.

POURQUOI : jusqu'au 30/09/2026, `ml.confrontation_features._race_key` tenait deux
sorties pour la même course dès qu'elles partageaient date + hippodrome. Une réunion
compte 6 à 9 courses : le 1er de la 3e course « battait » le 3e de la 6e. Les six
clés `conf_*` du modèle comptaient ces faux duels. La clé ajoute désormais
discipline, distance et nombre de partants.

Si seul le direct changeait, le modèle serait servi sur une feature que son
dataset d'entraînement (les vecteurs figés dans `features_ml`) calcule autrement.
On corrige donc aussi les vecteurs stockés, AVANT le prochain réentraînement.

Même méthode que patch_features_historique.py, deux temps jamais mêlés :

  calcul     (LECTURE SEULE) : pour chaque course terminée, recharge l'historique
             des partants comme le direct (`_load_course_batch_data`, copie PMU de la
             course elle-même écartée) et calcule les clés deux fois :
               • « avant » : ancienne clé `_race_key_reunion` ;
               • « après » : clé corrigée.
             Une clé n'est corrigée QUE si « avant » reproduit EXACTEMENT la valeur
             stockée. Les vecteurs non reproduits gardent leur valeur.
  appliquer  (ÉCRITURE) : `features || patch`, `computed_at` jamais modifié ;
             `--retour-arriere` réapplique les anciennes valeurs du fichier.

    python scripts/patch_features_confrontations.py calcul --depuis 2025-09-01 \
        --sortie /out/patch_conf_0.jsonl --shard 0/4
    python scripts/patch_features_confrontations.py appliquer --fichiers /out/patch_conf_*.jsonl

Puis réentraîner (le cliquet de déploiement arbitre la promotion comme d'habitude).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from sqlalchemy import text  # noqa: E402

from ml.confrontation_features import (  # noqa: E402
    CONFRONTATION_FEATURE_KEYS,
    _race_key,
    _race_key_reunion,
    compute_confrontation_features,
)
from patch_features_historique import _courses, appliquer, corrections_course  # noqa: E402


def vecteurs_course(hist_by_cheval: dict, pid_par_cheval: dict) -> tuple[dict, dict]:
    """(avant, après) : {participation_id: {clés conf_*}} pour une course."""
    ids = list(pid_par_cheval)
    avant = compute_confrontation_features(hist_by_cheval, ids, race_key=_race_key_reunion)
    apres = compute_confrontation_features(hist_by_cheval, ids, race_key=_race_key)
    return ({pid_par_cheval[c]: v for c, v in avant.items()},
            {pid_par_cheval[c]: v for c, v in apres.items()})


async def calcul(args) -> int:
    from db.database import AsyncSessionLocal
    from ml.features import _load_course_batch_data

    depuis = datetime.strptime(args.depuis, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    jusqua = (datetime.strptime(args.jusqua, "%Y-%m-%d").replace(tzinfo=timezone.utc)
              if args.jusqua else None)
    i_shard, n_shard = (int(x) for x in args.shard.split("/"))
    cids = [c for j, c in enumerate(await _courses(depuis, jusqua)) if j % n_shard == i_shard]
    if args.limite:
        cids = cids[:args.limite]
    print(f"[patch-conf] shard {i_shard}/{n_shard} : {len(cids)} courses", flush=True)

    tot: dict = defaultdict(lambda: {"diff": 0, "corrige": 0, "non_reproduit": 0,
                                     "non_fini": 0})
    n_vect = n_patch = 0
    erreurs = []
    t0 = time.monotonic()
    with open(args.sortie, "w", encoding="utf-8") as out:
        for i, cid in enumerate(cids, 1):
            try:
                async with AsyncSessionLocal() as s:
                    await s.execute(text(
                        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
                    batch = await _load_course_batch_data(s, cid, exclure_copie_course=True)
                    pid_par_cheval = dict((await s.execute(text("""
                        SELECT cheval_id, participation_id FROM participations
                        WHERE course_id = :c
                    """), {"c": cid})).all())
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
            # Même champ que le direct : les cheval_id passés à compute_confrontation_features.
            champ = {c: pid_par_cheval[c] for c in batch["confrontations"] if c in pid_par_cheval}
            avant, apres = vecteurs_course(batch["hist_by_cheval"], champ)
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
                print(f"[patch-conf] {i}/{len(cids)} — {el/i:.2f} s/course, "
                      f"reste ~{el/i*(len(cids)-i)/60:.0f} min", flush=True)
    resume = {"shard": args.shard, "courses": len(cids), "vecteurs": n_vect,
              "vecteurs_corriges": n_patch, "erreurs": len(erreurs),
              "exemples_erreurs": erreurs[:20],
              "cles": {k: tot[k] for k in CONFRONTATION_FEATURE_KEYS if k in tot}}
    with open(args.sortie + ".resume.json", "w", encoding="utf-8") as f:
        json.dump(resume, f, ensure_ascii=False, indent=1)
    print(f"[patch-conf] fini : {n_patch} vecteurs corrigés sur {n_vect}, "
          f"{len(erreurs)} erreurs", flush=True)
    return 0 if not erreurs else 2


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
