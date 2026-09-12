"""Banc de mesure des plans de mise — rejeu A/B sur cohorte FIGÉE.

Rejoue `generer_plan` (chemin PRODUIT : respect_montant=True, mêmes entrées
apprises que /mise-plan et profil_run_log) puis `settle_plan` aux vrais rapports
PMU, sur toutes les courses terminées d'une fenêtre de dates FIGÉE. Écrit une
ligne par (course × profil) dans un CSV, puis imprime un résumé par profil,
type, discipline, taille de champ, accord/désaccord marché.

Discipline de mesure (mémoire blackturf-rejeu-ab-0823) :
  - cohorte figée par bornes de dates (jamais « les N dernières courses ») ;
  - anti-fuite : predictions.created_at < courses.date_heure, cote_figee ;
  - heat FIGÉ (il se recalcule sur le ROI récent et bougeait entre deux bras) ;
  - le profil risqué ne se juge pas sous ~2 000 courses (1,8 % de réussite) ;
  - ROI brut ET winsorisé ET sans les 5 plus gros gains : une cellule qui
    s'effondre quand on retire 5 gagnants n'est pas une cellule rentable.

Usage (conteneur jetable, sources montées par-dessus l'image) :
    python scripts/bench_plans.py --variant base --out /out/base.csv \
        --debut 2026-06-11 --fin 2026-09-13 [--heat 0.42] [--workers 3] [--limit N]
    python scripts/bench_plans.py --resume /out/base.csv [/out/autre.csv ...]

Les VARIANTES sont des monkeypatchs appliqués dans chaque worker (jamais des
drapeaux dans le code produit) : ajouter une entrée dans `VARIANTS`.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import datetime as _dt
import json
import math
import os
import sys
from collections import defaultdict

MONTANT = 10
WINSOR = 30.0
PROFILS = ("conservateur", "equilibre", "agressif")
CIBLES = {"conservateur": 1.8, "equilibre": 4.0, "agressif": 10.0}

# ──────────────────────────────────────────────────────────────────────────────
# Variantes = monkeypatchs (appliqués dans chaque worker)
# ──────────────────────────────────────────────────────────────────────────────
def _v_base():
    pass


def _v_ancien():
    """Sélection d'avant le 2026-09-12 (ancrage top-2, sans tilt, sans gros lot,
    rang 4, gagnant sec non borné) — mais avec la diversification « garde le
    meilleur » du 2026-09-12. `prod_avant` reproduit le moteur d'avant en entier."""
    from services import mise_calculator as mc
    mc.ANCRAGE_MODE = "top2"
    mc.DESACCORD_BOOST_R1 = 1.0
    mc.DESACCORD_MALUS_FAVORI = 1.0
    mc.PROFIL_CONFIG["agressif"]["loterie"] = set()
    mc.PROFIL_CONFIG["agressif"]["types"] = set(mc.PROFIL_CONFIG["agressif"]["types"]) - {"Trio"}
    mc.PROFIL_CONFIG["agressif"]["rang_max"] = 4
    mc.PROFIL_CONFIG["agressif"]["rang_max_simple"] = None


def _v_prod_avant():
    """Moteur de production d'avant le 2026-09-12, à l'identique (mesuré : les
    résultats coïncident avec ceux de l'image de prod d'alors)."""
    from services import mise_calculator as mc
    _v_ancien()
    mc._DIVERSIFICATION_GARDE_LE_MEILLEUR = False
    # Multi en 5/6/7 étaient encore au catalogue prudent/modéré (à 15/45/105 €, donc
    # jamais finançables sur 10 € : sans effet sur le rejeu à 10 €).


def _v_sans_des():
    from services import mise_calculator as mc
    mc.DESACCORD_BOOST_R1 = 1.0
    mc.DESACCORD_MALUS_FAVORI = 1.0


def _v_sans_trio():
    from services import mise_calculator as mc
    mc.PROFIL_CONFIG["agressif"]["loterie"] = set()
    mc.PROFIL_CONFIG["agressif"]["types"] = set(mc.PROFIL_CONFIG["agressif"]["types"]) - {"Trio"}


def _v_top2():
    from services import mise_calculator as mc
    mc.ANCRAGE_MODE = "top2"


def _v_rang4():
    from services import mise_calculator as mc
    mc.PROFIL_CONFIG["agressif"]["rang_max"] = 4


def _v_rang5():
    from services import mise_calculator as mc
    mc.PROFIL_CONFIG["agressif"]["rang_max"] = 5


def _v_des_fort():
    from services import mise_calculator as mc
    mc.DESACCORD_BOOST_R1 = 1.8
    mc.DESACCORD_MALUS_FAVORI = 0.4


def _v_sg3():
    from services import mise_calculator as mc
    mc.PROFIL_CONFIG["agressif"]["rang_max_simple"] = 3


def _v_sg2():
    from services import mise_calculator as mc
    mc.PROFIL_CONFIG["agressif"]["rang_max_simple"] = 2


def _v_combo1():
    """rang 5 pour les combinaisons, rang 3 pour les paris à un cheval."""
    from services import mise_calculator as mc
    mc.PROFIL_CONFIG["agressif"]["rang_max"] = 5
    mc.PROFIL_CONFIG["agressif"]["rang_max_simple"] = 3


def _v_combo1_pmin2():
    from services import mise_calculator as mc
    _v_combo1()
    mc.PROFIL_CONFIG["agressif"]["min_proba"] = 0.02


def _v_combo1_covfreq():
    from services import mise_calculator as mc
    _v_combo1()
    mc._COUVERTURE_ALTERNE_GROS_LOT = False


def _v_combo1_pmin2_covfreq():
    from services import mise_calculator as mc
    _v_combo1_pmin2()
    mc._COUVERTURE_ALTERNE_GROS_LOT = False


def _v_combo1_sans_trio():
    _v_combo1()
    _v_sans_trio()


def _v_combo1_div_ancien():
    from services import mise_calculator as mc
    _v_combo1()
    mc._DIVERSIFICATION_GARDE_LE_MEILLEUR = False


def _v_div_ancien():
    from services import mise_calculator as mc
    mc._DIVERSIFICATION_GARDE_LE_MEILLEUR = False


VARIANTS = {
    "prod_avant": _v_prod_avant,
    "combo1": _v_combo1,
    "combo1_pmin2": _v_combo1_pmin2,
    "combo1_covfreq": _v_combo1_covfreq,
    "combo1_pmin2_covfreq": _v_combo1_pmin2_covfreq,
    "combo1_sans_trio": _v_combo1_sans_trio,
    "combo1_div_ancien": _v_combo1_div_ancien,
    "div_ancien": _v_div_ancien,
    "sg3": _v_sg3,
    "sg2": _v_sg2,
    "base": _v_base,
    "ancien": _v_ancien,
    "sans_des": _v_sans_des,
    "sans_trio": _v_sans_trio,
    "top2": _v_top2,
    "rang4": _v_rang4,
    "rang5": _v_rang5,
    "des_fort": _v_des_fort,
}


# ──────────────────────────────────────────────────────────────────────────────
# Chargement (une seule fois, dans le processus principal)
# ──────────────────────────────────────────────────────────────────────────────
async def _charger(debut, fin, limit):
    from sqlalchemy import text
    from db.database import AsyncSessionLocal
    from services.bet_catalog import derive_bet_flags

    async with AsyncSessionLocal() as s:
        cids = [r[0] for r in (await s.execute(text("""
            SELECT c.course_id FROM courses c
            JOIN resultats r ON r.course_id = c.course_id
            WHERE c.statut = 'termine' AND r.classement IS NOT NULL
              AND c.date_heure >= :d AND c.date_heure < :f
            ORDER BY c.date_heure
        """), {"d": debut, "f": fin})).fetchall()]
        if limit:
            cids = cids[:limit]
        data = []
        for cid in cids:
            rows = (await s.execute(text("""
                SELECT pa.numero, ch.nom, pr.proba_top3, pr.proba_top1, pr.cote_figee,
                       pa.non_partant, pr.proba_top1_low, pr.proba_top1_high
                FROM predictions pr
                JOIN participations pa ON pa.participation_id = pr.participation_id
                JOIN chevaux ch ON ch.cheval_id = pa.cheval_id
                JOIN courses co ON co.course_id = pr.course_id
                WHERE pa.course_id = :c
                  AND co.date_heure IS NOT NULL AND pr.created_at < co.date_heure
                  AND pr.cote_figee IS NOT NULL AND pr.cote_figee > 1.0
                ORDER BY pr.rang_predit
            """), {"c": cid})).fetchall()
            preds = [{"numero": r[0], "nom_cheval": r[1], "proba_top3": r[2],
                      "proba_top1": r[3], "cote_pmu": r[4], "non_partant": r[5],
                      "proba_top1_low": r[6], "proba_top1_high": r[7]} for r in rows]
            vivants = [p for p in preds if not p["non_partant"]]
            if len(vivants) < 5:
                continue
            ci_r = (await s.execute(text("""
                SELECT est_quinte, est_quarte, est_tierce, est_2sur4, nb_partants,
                       paris_disponibles, discipline, date_heure, hippodrome_nom
                FROM courses WHERE course_id = :c"""), {"c": cid})).fetchone()
            res = (await s.execute(text("""
                SELECT classement, rapports, rapports_detail FROM resultats
                WHERE course_id = :c"""), {"c": cid})).fetchone()
            if not ci_r or not res or not res[0]:
                continue
            ci = derive_bet_flags(ci_r[5], est_tierce=bool(ci_r[2]), est_quarte=bool(ci_r[1]),
                                  est_quinte=bool(ci_r[0]), est_2sur4=bool(ci_r[3]),
                                  nb_partants=ci_r[4])
            ci = dict(ci)
            ci["nb_partants"] = ci_r[4] or len(vivants)
            ci["discipline"] = ci_r[6]
            rang1 = max(vivants, key=lambda p: float(p["proba_top1"] or 0))["numero"]
            favori = min(vivants, key=lambda p: float(p["cote_pmu"]))["numero"]
            data.append({
                "course_id": cid, "date": ci_r[7].date().isoformat(),
                "discipline": ci_r[6], "nb": int(ci["nb_partants"]),
                "desaccord": int(rang1) != int(favori),
                "preds": preds, "ci": ci,
                "classement": res[0], "rapports": res[1], "rapports_detail": res[2],
                "non_partants": sorted({int(p["numero"]) for p in preds if p["non_partant"]}),
            })
        return data


async def _entrees(heat_fixe):
    """Mêmes entrées apprises que la route /mise-plan, préchargées."""
    from db.database import AsyncSessionLocal
    from ml.bet_performance import get_learned_type_weights, get_model_heat
    from ml.signal_performance import load_rapport_calibration, load_ev_band_performance
    async with AsyncSessionLocal() as s:
        heat = float(heat_fixe) if heat_fixe is not None else float(await get_model_heat(s))
        rc = await load_rapport_calibration(s)
        ev = await load_ev_band_performance(s)
        return heat, rc, ev, s


async def _poids(session, cles):
    from ml.bet_performance import get_learned_type_weights
    out = {}
    for profil, disc, nb in cles:
        out[f"{profil}|{disc}|{nb}"] = await get_learned_type_weights(
            session, profil=profil, discipline=disc, nb_partants=nb)
    return out


# ──────────────────────────────────────────────────────────────────────────────
# Worker
# ──────────────────────────────────────────────────────────────────────────────
_G = {}


def _init(variant, heat, rc, ev, poids):
    import warnings
    warnings.filterwarnings("ignore")
    VARIANTS[variant]()
    _G.update({"heat": heat, "rc": rc, "ev": ev, "poids": poids})


def _run_course(d):
    from services.mise_calculator import generer_plan, plan_to_dict
    from services.bet_settlement import settle_plan
    rows = []
    for profil in PROFILS:
        rw = _G["poids"].get(f"{profil}|{d['discipline']}|{d['nb']}") or {}
        try:
            plan = plan_to_dict(generer_plan(
                MONTANT, profil, d["preds"], d["ci"], None, rw, _G["heat"], None,
                respect_montant=True, rapport_calib=_G["rc"], ev_band_perf=_G["ev"]))
        except Exception as e:  # une course qui casse le moteur doit se voir
            rows.append({"course_id": d["course_id"], "profil": profil, "erreur": str(e)[:120]})
            continue
        paris = [p for niv in plan.get("niveaux", []) for p in niv.get("paris", [])]
        bilan = settle_plan(plan, d["classement"], d["rapports"], d["nb"],
                            d["rapports_detail"], set(d["non_partants"]))
        mise = gain = 0.0
        n_att = n_gagne = 0
        gains = []
        types = []
        for pb in bilan.get("paris", []):
            st = pb.get("statut")
            m = float(pb.get("mise") or 0)
            if st == "en_attente":
                n_att += 1
                continue
            if st == "rembourse":
                continue
            g = float(pb.get("gain") or 0.0) if st == "gagne" else 0.0
            mise += m
            gain += g
            gains.append((m, g))
            if st == "gagne":
                n_gagne += 1
            types.append(pb.get("type"))
        cible = CIBLES[profil] * MONTANT
        hors_bande = ("tranche de gain habituelle" in (plan.get("resume_ia") or ""))
        min_ratio = min((float(p.get("gain_potentiel") or 0) / MONTANT for p in paris), default=0.0)
        rows.append({
            "course_id": d["course_id"], "date": d["date"], "discipline": d["discipline"],
            "nb": d["nb"], "desaccord": int(d["desaccord"]), "profil": profil,
            "nb_paris": len(paris), "mise": round(mise, 2), "gain": round(gain, 2),
            "gain_w": round(sum(min(g, WINSOR * m) for m, g in gains), 2),
            "n_gagne": n_gagne, "n_attente": n_att,
            "max_mise": max((float(p.get("mise") or 0) for p in paris), default=0.0),
            "hors_bande": int(hors_bande),
            "sous_tranche": int(bool(paris) and min_ratio < CIBLES[profil] - 1e-6),
            "types": "|".join(t or "" for t in types),
            "mises": "|".join(str(int(m)) for m, _ in gains),
            "gains": "|".join(str(round(g, 1)) for _, g in gains),
            "rangs_max": "|".join(str(max((int(h.get("rang") or 0) for h in p.get("chevaux", [])), default=0))
                                  for p in paris),
        })
    return rows


CHAMPS = ["course_id", "date", "discipline", "nb", "desaccord", "profil", "nb_paris", "mise",
          "gain", "gain_w", "n_gagne", "n_attente", "max_mise", "hors_bande", "sous_tranche",
          "types", "mises", "gains", "rangs_max", "erreur"]


# ──────────────────────────────────────────────────────────────────────────────
# Résumé
# ──────────────────────────────────────────────────────────────────────────────
def _roi(rows, key=None, sans=0):
    mise = sum(float(r["mise"]) for r in rows)
    if mise <= 0:
        return float("nan")
    if key is None:
        key = "gain"
    gs = sorted((float(r[key]) for r in rows), reverse=True)[sans:]
    return 100.0 * (sum(gs) - mise) / mise


def _pct(rows, pred):
    return 100.0 * sum(1 for r in rows if pred(r)) / max(len(rows), 1)


def resume(rows, titre=""):
    rows = [r for r in rows if not r.get("erreur")]
    print(f"\n===== {titre} — {len({r['course_id'] for r in rows})} courses =====")
    print("%-13s %5s %6s %6s %6s %7s %7s %7s %7s %6s %6s" % (
        "profil", "n", "tick", "mono%", "hit%", "ROI", "ROIw30", "sans5", "sans20", "hb%", "st%"))
    for profil in PROFILS:
        pr = [r for r in rows if r["profil"] == profil]
        if not pr:
            continue
        print("%-13s %5d %6.2f %6.1f %6.1f %+7.1f %+7.1f %+7.1f %+7.1f %6.1f %6.1f" % (
            profil, len(pr),
            sum(int(r["nb_paris"]) for r in pr) / len(pr),
            _pct(pr, lambda r: int(r["nb_paris"]) == 1),
            _pct(pr, lambda r: int(r["n_gagne"]) > 0),
            _roi(pr), _roi(pr, "gain_w"), _roi(pr, sans=5), _roi(pr, sans=20),
            _pct(pr, lambda r: int(r["hors_bande"]) == 1),
            _pct(pr, lambda r: int(r["sous_tranche"]) == 1)))


def resume_segments(rows, profil):
    rows = [r for r in rows if not r.get("erreur") and r["profil"] == profil]
    print(f"\n--- {profil} : par segment (n courses, tickets, hit%, ROI brut, ROI w30) ---")

    def _seg(nom, fn):
        grp = defaultdict(list)
        for r in rows:
            grp[fn(r)].append(r)
        for k in sorted(grp):
            g = grp[k]
            print("  %-12s %-12s %5d %5.2f %5.1f %+7.1f %+7.1f" % (
                nom, k, len(g), sum(int(r["nb_paris"]) for r in g) / len(g),
                _pct(g, lambda r: int(r["n_gagne"]) > 0), _roi(g), _roi(g, "gain_w")))

    _seg("discipline", lambda r: r["discipline"])
    _seg("champ", lambda r: ("a<=8" if int(r["nb"]) <= 8 else "b9-11" if int(r["nb"]) <= 11
                              else "c12-14" if int(r["nb"]) <= 14 else "d15+"))
    _seg("desaccord", lambda r: str(r["desaccord"]))
    _seg("mois", lambda r: r["date"][:7])
    # Par type : une ligne par ticket
    print(f"--- {profil} : par type de pari (tickets, mise, hit%, ROI brut, ROI w30) ---")
    agg = defaultdict(lambda: {"n": 0, "mise": 0.0, "gain": 0.0, "gw": 0.0, "win": 0})
    for r in rows:
        ts = r["types"].split("|") if r["types"] else []
        ms = r["mises"].split("|") if r["mises"] else []
        gs = r["gains"].split("|") if r["gains"] else []
        for t, m, g in zip(ts, ms, gs):
            a = agg[t]
            m, g = float(m), float(g)
            a["n"] += 1
            a["mise"] += m
            a["gain"] += g
            a["gw"] += min(g, WINSOR * m)
            a["win"] += 1 if g > 0 else 0
    for t, a in sorted(agg.items(), key=lambda kv: -kv[1]["mise"]):
        if a["mise"] <= 0:
            continue
        print("  %-18s %5d %7.0f %5.1f %+7.1f %+7.1f" % (
            t, a["n"], a["mise"], 100 * a["win"] / a["n"],
            100 * (a["gain"] - a["mise"]) / a["mise"], 100 * (a["gw"] - a["mise"]) / a["mise"]))


def lire(path):
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variant", default="base", choices=sorted(VARIANTS))
    ap.add_argument("--out", default=None)
    ap.add_argument("--debut", default="2026-06-11")
    ap.add_argument("--fin", default="2026-09-13")
    ap.add_argument("--heat", type=float, default=None)
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--resume", nargs="*", default=None, help="résumer des CSV existants")
    ap.add_argument("--segments", action="store_true")
    a = ap.parse_args()

    if a.resume:
        for p in a.resume:
            rows = lire(p)
            resume(rows, os.path.basename(p))
            if a.segments:
                for profil in PROFILS:
                    resume_segments(rows, profil)
        return

    debut = _dt.datetime.fromisoformat(a.debut).replace(tzinfo=_dt.timezone.utc)
    fin = _dt.datetime.fromisoformat(a.fin).replace(tzinfo=_dt.timezone.utc)
    loop = asyncio.new_event_loop()
    data = loop.run_until_complete(_charger(debut, fin, a.limit))
    print(f"cohorte FIGÉE {a.debut} → {a.fin} : {len(data)} courses", flush=True)

    async def _prep():
        heat, rc, ev, s = await _entrees(a.heat)
        cles = sorted({(p, d["discipline"], d["nb"]) for d in data for p in PROFILS})
        poids = await _poids(s, cles)
        await s.close()
        return heat, rc, ev, poids
    heat, rc, ev, poids = loop.run_until_complete(_prep())
    print(f"heat={heat:.3f}  poids appris={len(poids)} contextes  variant={a.variant}", flush=True)

    import multiprocessing as mp
    rows = []
    t0 = _dt.datetime.now()
    with mp.get_context("fork").Pool(a.workers, initializer=_init,
                                     initargs=(a.variant, heat, rc, ev, poids)) as pool:
        for i, rs in enumerate(pool.imap_unordered(_run_course, data, chunksize=8), 1):
            rows.extend(rs)
            if i % 250 == 0:
                print(f"  {i}/{len(data)} courses  {(_dt.datetime.now()-t0).total_seconds():.0f}s", flush=True)
    err = [r for r in rows if r.get("erreur")]
    if err:
        print(f"⚠ {len(err)} erreurs moteur, ex: {err[0]}")
    if a.out:
        with open(a.out, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=CHAMPS)
            w.writeheader()
            for r in rows:
                w.writerow({k: r.get(k, "") for k in CHAMPS})
    resume(rows, a.variant)
    if a.segments:
        for profil in PROFILS:
            resume_segments(rows, profil)


if __name__ == "__main__":
    main()
