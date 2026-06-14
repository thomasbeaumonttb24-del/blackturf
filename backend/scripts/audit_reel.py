"""
audit_reel.py — AUDIT VÉRITÉ (lecture seule) sur les données de PROD.

À lancer SUR LE VPS (là où vivent les vraies données) :
    python scripts/audit_reel.py
    python scripts/audit_reel.py --json   # sortie machine

Ne fait QUE des SELECT. N'écrit rien, ne ré-entraîne rien, ne mise rien.

Répond aux 4 questions qu'on ne peut pas trancher sans la vraie base :
  1. INVENTAIRE   — combien de courses de référence exploitables (le "test sur des milliers").
  2. LEAKAGE      — combien de prédictions ont été calculées APRÈS la course (created_at >= date_heure).
                    C'est LE chiffre qui dit si le +150% in-sample est réel ou une illusion.
  3. ROI PROFILS  — ROI HONNÊTE (pronos figés avant course only) vs ROI brut (tous settled),
                    par profil de risque. L'écart = la sur-estimation.
  4. CALIBRATION  — Brier + ECE du Top-1 sur les pronos figés avant course (proba vs réalité).
  5. MODÈLE ACTIF — métriques fiables (mêmes garde-fous que le site).
"""
import sys
import os
import json
import argparse
import asyncio
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("DATABASE_URL_SYNC", "postgresql://blackturf:blackturf_dev@localhost:5432/blackturf")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("SECRET_KEY", "dev-secret-key-change-in-production-must-be-64-chars-minimum-ok")

import db.models  # noqa: F401
from sqlalchemy import text
from db.database import AsyncSessionLocal as async_session


def _pct(x, nd=1):
    return "—" if x is None else f"{round(float(x) * 100, nd)}%"


def _f(x, nd=4):
    return "—" if x is None else f"{round(float(x), nd)}"


async def _has_col(s, table: str, col: str) -> bool:
    return bool((await s.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.columns
                       WHERE table_name = :t AND column_name = :c)
    """), {"t": table, "c": col})).scalar())


async def section_inventaire(s) -> dict:
    # colonnes récentes (migrations 0021 / 0024) — absentes sur un schéma partiel
    has_figee = await _has_col(s, "predictions", "cote_figee")
    has_raw = await _has_col(s, "predictions", "proba_top1_raw")
    figee_expr = "(SELECT count(*) FROM predictions WHERE cote_figee IS NOT NULL)" if has_figee else "NULL"
    raw_expr = "(SELECT count(*) FROM predictions WHERE proba_top1_raw IS NOT NULL)" if has_raw else "NULL"
    q = await s.execute(text(f"""
        SELECT
          (SELECT count(*) FROM courses)                                          AS courses_total,
          (SELECT count(*) FROM courses WHERE statut = 'termine')                 AS courses_termine,
          (SELECT count(*) FROM courses c JOIN resultats r ON r.course_id = c.course_id
             WHERE c.statut = 'termine' AND r.classement IS NOT NULL)             AS avec_arrivee,
          (SELECT count(*) FROM courses c JOIN resultats r ON r.course_id = c.course_id
             WHERE c.statut = 'termine' AND r.rapports IS NOT NULL
               AND r.rapports::text <> '{{}}')                                    AS avec_rapports,
          (SELECT min(date_heure) FROM courses WHERE statut = 'termine')          AS depuis,
          (SELECT max(date_heure) FROM courses WHERE statut = 'termine')          AS jusqu_a,
          (SELECT count(*) FROM predictions)                                      AS predictions,
          {figee_expr}                                                            AS pred_figees,
          {raw_expr}                                                              AS pred_raw
    """))
    r = q.mappings().first()
    return dict(r) if r else {}


async def section_leakage(s) -> dict:
    """Prédictions calculées avant vs après le départ, sur courses terminées."""
    q = await s.execute(text("""
        SELECT
          count(*)                                                AS total,
          count(*) FILTER (WHERE pr.created_at <  c.date_heure)   AS pre_course,
          count(*) FILTER (WHERE pr.created_at >= c.date_heure)   AS post_ou_pendant,
          count(DISTINCT c.course_id)                                                  AS courses,
          count(DISTINCT c.course_id) FILTER (WHERE pr.created_at >= c.date_heure)      AS courses_avec_leak
        FROM predictions pr
        JOIN courses c ON c.course_id = pr.course_id
        WHERE c.statut = 'termine' AND c.date_heure IS NOT NULL
    """))
    r = q.mappings().first()
    d = dict(r) if r else {}
    tot = d.get("total") or 0
    d["pct_post"] = (d.get("post_ou_pendant", 0) / tot * 100) if tot else None
    return d


async def section_profils(s) -> dict:
    """ROI honnête (figé avant course, non backfillé) vs brut (tous settled), par profil."""
    out = {"existe": False, "honnete": {}, "brut": {}}
    # la table peut ne pas exister si l'apprentissage profils n'a jamais tourné
    exists = (await s.execute(text("""
        SELECT EXISTS (SELECT 1 FROM information_schema.tables
                       WHERE table_name = 'profil_run_log')
    """))).scalar()
    if not exists:
        return out
    out["existe"] = True

    honnete = await s.execute(text("""
        SELECT r.profil,
               count(*)                                          AS n,
               sum((r.resultat->>'total_mise')::float)           AS mise,
               sum((r.resultat->>'total_gain')::float)           AS gain,
               count(*) FILTER (WHERE (r.resultat->>'net')::float > 0) AS benef
        FROM profil_run_log r
        JOIN courses c ON c.course_id = r.course_id
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND r.created_at < c.date_heure
          AND COALESCE(r.meta->>'backfill', '') <> 'true'
        GROUP BY r.profil
    """))
    brut = await s.execute(text("""
        SELECT r.profil,
               count(*)                                          AS n,
               sum((r.resultat->>'total_mise')::float)           AS mise,
               sum((r.resultat->>'total_gain')::float)           AS gain,
               count(*) FILTER (WHERE (r.resultat->>'net')::float > 0) AS benef
        FROM profil_run_log r
        WHERE r.statut = 'settled' AND r.resultat IS NOT NULL
        GROUP BY r.profil
    """))

    def pack(rows):
        d = {}
        for row in rows.mappings().all():
            mise = float(row["mise"] or 0)
            gain = float(row["gain"] or 0)
            n = int(row["n"] or 0)
            d[row["profil"]] = {
                "n_runs": n,
                "roi": round((gain - mise) / mise * 100, 1) if mise > 0 else None,
                "net": round(gain - mise, 1),
                "taux_benef": round((row["benef"] or 0) / n * 100, 1) if n else None,
            }
        return d

    out["honnete"] = pack(honnete)
    out["brut"] = pack(brut)
    return out


async def section_calibration(s) -> dict:
    """Brier + ECE du Top-1 sur les pronos figés AVANT course.
    Outcome = ce cheval a-t-il gagné (1er au classement officiel)."""
    rows = (await s.execute(text("""
        SELECT pr.proba_top1::float AS p, p.numero AS num, r.classement AS clt
        FROM predictions pr
        JOIN participations p ON p.participation_id = pr.participation_id
        JOIN courses c        ON c.course_id = pr.course_id
        JOIN resultats r      ON r.course_id = c.course_id
        WHERE c.statut = 'termine' AND c.date_heure IS NOT NULL
          AND pr.created_at < c.date_heure          -- pronos figés avant course UNIQUEMENT
          AND pr.proba_top1 IS NOT NULL
          AND r.classement IS NOT NULL
    """))).all()

    def _winner_num(clt):
        """classement = liste de dicts {numero, position, ...} (parfois liste de
        scalaires selon l'historique). Gagnant = position==1, sinon 1er élément."""
        try:
            items = clt if isinstance(clt, list) else json.loads(clt)
        except Exception:
            return None
        if not items:
            return None
        first_num = None
        for it in items:
            if isinstance(it, dict):
                if it.get("position") == 1:
                    return it.get("numero")
                if first_num is None:
                    first_num = it.get("numero")
            else:
                return it  # liste de scalaires : le 1er = gagnant
        return first_num

    n = 0
    brier_sum = 0.0
    # ECE 10 bins
    bins = [{"p": 0.0, "y": 0.0, "n": 0} for _ in range(10)]
    for p, num, clt in rows:
        if p is None or not clt:
            continue
        winner = _winner_num(clt)
        if winner is None:
            continue
        # le gagnant peut être stocké en int ou en str
        won = 1.0 if str(winner) == str(num) else 0.0
        brier_sum += (p - won) ** 2
        n += 1
        b = min(9, int(p * 10))
        bins[b]["p"] += p
        bins[b]["y"] += won
        bins[b]["n"] += 1

    if n == 0:
        return {"n": 0}
    ece = 0.0
    bin_detail = []
    for b in bins:
        if b["n"] == 0:
            continue
        conf = b["p"] / b["n"]
        acc = b["y"] / b["n"]
        ece += (b["n"] / n) * abs(conf - acc)
        bin_detail.append({"conf": round(conf, 3), "freq_reel": round(acc, 3), "n": b["n"]})
    return {"n": n, "brier": round(brier_sum / n, 4), "ece": round(ece, 4), "bins": bin_detail}


async def section_modele(s) -> dict:
    try:
        from sqlalchemy import select
        from db.models import ModelVersion
        from api.model_metrics import real_model_metrics
        mv = (await s.execute(
            select(ModelVersion).where(ModelVersion.est_actif == True)  # noqa: E712
            .order_by(ModelVersion.version_num.desc())
        )).scalars().first()
        if mv is None:
            return {"trouve": False}
        m = await real_model_metrics(s, mv)
        return {
            "trouve": True,
            "auc_raw": getattr(mv, "auc_roc", None),
            "version": mv.version_num,
            "synthetique": bool(getattr(mv, "est_synthetique", False)),
            "nb_courses_train": mv.nb_courses_train,
            "auc_fiable": m.get("auc_roc"),
            "walk_forward_auc": getattr(mv, "walk_forward_auc", None),
            "precision_top3": m.get("precision_top3"),
            "roi_simule": m.get("roi_simule"),
            "nb_courses_evaluees": m.get("nb_courses_evaluees"),
        }
    except Exception as e:  # noqa: BLE001
        return {"erreur": str(e)[:160]}


async def _safe(fn) -> dict:
    """Chaque section dans sa propre session : une erreur SQL avorte la
    transaction asyncpg, donc on isole pour que le reste de l'audit survive."""
    try:
        async with async_session() as s:
            return await fn(s)
    except Exception as e:  # noqa: BLE001
        return {"erreur": str(e)[:200]}


async def main(as_json: bool) -> int:
    inv = await _safe(section_inventaire)
    leak = await _safe(section_leakage)
    prof = await _safe(section_profils)
    cal = await _safe(section_calibration)
    mod = await _safe(section_modele)

    report = {"inventaire": inv, "leakage": leak, "profils": prof,
              "calibration": cal, "modele": mod}

    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return 0

    L = "=" * 64
    print(L); print("AUDIT VÉRITÉ BLACKTURF — lecture seule"); print(L)

    print("\n1) INVENTAIRE (data de référence exploitable)")
    print(f"   courses totales        : {inv.get('courses_total')}")
    print(f"   terminées              : {inv.get('courses_termine')}")
    print(f"   avec arrivée officielle: {inv.get('avec_arrivee')}")
    print(f"   avec rapports PMU      : {inv.get('avec_rapports')}  <- réglables au réel")
    print(f"   période                : {inv.get('depuis')}  ->  {inv.get('jusqu_a')}")
    print(f"   prédictions            : {inv.get('predictions')}")
    print(f"   dont figées (cote_figee): {inv.get('pred_figees')}")
    print(f"   dont proba brute (raw) : {inv.get('pred_raw')}  <- besoin pour calibration propre")

    print("\n2) LEAKAGE (prédictions calculées après le départ ?)")
    print(f"   prédictions / courses term.: {leak.get('total')} sur {leak.get('courses')} courses")
    print(f"   AVANT course (sain)        : {leak.get('pre_course')}")
    print(f"   APRÈS/pendant (LEAK)       : {leak.get('post_ou_pendant')}  ({_pct(leak.get('pct_post') and leak['pct_post']/100)})")
    print(f"   courses contaminées        : {leak.get('courses_avec_leak')}")
    print("   >> si APRÈS > 0 sur courses dont on tire des métriques, le ROI in-sample est gonflé.")

    print("\n3) ROI PAR PROFIL DE RISQUE (figé avant course = HONNÊTE)")
    if not prof.get("existe"):
        print("   table profil_run_log absente — l'apprentissage par profil n'a jamais tourné.")
    else:
        for p in ("conservateur", "equilibre", "agressif"):
            h = prof["honnete"].get(p, {})
            b = prof["brut"].get(p, {})
            print(f"   {p:13s} HONNÊTE roi={_f(h.get('roi'),1)}%  n={h.get('n_runs',0)}  benef={_f(h.get('taux_benef'),1)}%"
                  f"   | BRUT roi={_f(b.get('roi'),1)}%  n={b.get('n_runs',0)}")
        print("   >> écart HONNÊTE vs BRUT = sur-estimation due aux runs backfillés.")

    print("\n4) CALIBRATION Top-1 (pronos figés avant course)")
    if cal.get("n", 0) == 0:
        print("   pas assez de pronos pré-course exploitables.")
    else:
        print(f"   n={cal['n']}  Brier={cal['brier']}  ECE={cal['ece']}")
        print("   (Brier: plus bas = mieux ; ECE: écart confiance/réalité, vise < 0.03)")
        for b in cal.get("bins", []):
            flag = "  <-- sur-confiant" if b["conf"] - b["freq_reel"] > 0.05 else ""
            print(f"     proba~{b['conf']:.2f}  réel={b['freq_reel']:.2f}  n={b['n']}{flag}")

    print("\n5) MODÈLE ACTIF (métriques fiables)")
    if mod.get("erreur"):
        print(f"   erreur lecture: {mod['erreur']}")
    elif not mod.get("trouve"):
        print("   aucun modèle actif.")
    else:
        print(f"   v{mod.get('version')}{'  [SYNTHÉTIQUE]' if mod.get('synthetique') else ''}  "
              f"train={mod.get('nb_courses_train')} lignes")
        print(f"   AUC brut={_f(mod.get('auc_raw'))}  AUC fiable={_f(mod.get('auc_fiable'))}  walk-forward AUC={_f(mod.get('walk_forward_auc'))}")
        print(f"   précision Top-3={_pct(mod.get('precision_top3'))}  "
              f"ROI simulé={_f(mod.get('roi_simule'))}  (sur {mod.get('nb_courses_evaluees')} courses)")

    print("\n" + L)
    print("Interprétation rapide :")
    print(" - LEAK > 0 sur courses évaluées  -> +150% in-sample = illusion, ne pas miser dessus.")
    print(" - ROI HONNÊTE < 0 par profil      -> pas d'edge réel encore, garder mises minimales.")
    print(" - ECE élevé / sur-confiance        -> calibration à refaire hors-échantillon.")
    print(L)
    return 0


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--json", action="store_true", help="Sortie JSON machine")
    args = p.parse_args()
    sys.exit(asyncio.run(main(args.json)))
