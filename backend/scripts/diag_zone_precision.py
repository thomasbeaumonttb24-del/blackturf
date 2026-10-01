"""
diag_zone_precision.py — Précision du modèle France / étranger, et ce qui l'explique.

Question : le modèle se trompe-t-il davantage sur les courses étrangères, et si oui,
l'écart vient-il du MANQUE D'HISTORIQUE (chevaux dont la carrière se court hors des
programmes PMU, donc absente de `participations`) ou d'autre chose (discipline,
marché) ?

Les mesures déjà en base (signal_performance, valuebets_visibilite) portent sur le
ROI et les rapports. Celle-ci porte sur la PRÉCISION pure, sans aucun pari :

  - % de courses où le cheval n°1 du modèle gagne / finit dans les 3 premiers ;
  - % de courses où le gagnant est dans le top 3 du modèle ;
  - log-loss du gagnant (probas normalisées sur la course) : la mesure de qualité
    probabiliste, comparable d'une course à l'autre ;
  - ratio proba annoncée / victoires réelles (calibration, > 1 = surannonce) ;
  - les MÊMES mesures pour le MARCHÉ (cote figée au moment du pronostic) : le
    modèle n'a de valeur que là où il bat le marché, et la difficulté propre d'une
    zone se lit sur le marché, pas sur le modèle seul.

Ventilations :
  1. zone (France / étranger, cf. services/hippodromes) ;
  2. zone × famille de discipline (trot / galop) — l'étranger est surtout du galop,
     la France surtout du trot : sans ce découpage l'écart de zone mêle les deux ;
  3. zone × COUVERTURE D'HISTORIQUE = part des partants ayant au moins
     HIST_MIN_COURSES courses connues en base avant ce jour. C'est la ventilation
     décisive : si à couverture égale l'étranger rejoint la France, l'écart vient
     du manque d'historique, et l'importer est la bonne piste ;
  4. étranger par pays (pays sous MIN_COURSES masqués).

Anti-fuite (mêmes règles que les autres rejeux) :
  - pronostic FIGÉ strictement avant le départ (`created_at < date_heure`),
    `is_replayable` uniquement, modèles retirés exclus (fuite du 24/09) ;
  - cote FIGÉE (`cote_figee`) pour le marché — jamais `participations.cote_pmu`,
    réécrite avec la cote finale après la course ;
  - historique compté sur les seules courses ANTÉRIEURES ayant un résultat.

Intégrité : un segment sous MIN_COURSES affiche NULL, jamais extrapolé. Une course
dont un partant n'a pas de cote figée n'entre pas dans les mesures MARCHÉ (elle
reste dans les mesures modèle) : on ne compare modèle et marché que sur les mêmes
courses.

⚠️ Lecture seule. N'écrit rien.

Usage (dans le conteneur api) :
    cd /app && PYTHONPATH=/app python scripts/diag_zone_precision.py [--jours 180] [--json]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import math
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from sqlalchemy import text

from services.hippodromes import ZONE_ETRANGER, ZONE_FRANCE, zone_depuis_pays

# Un cheval est « couvert » s'il a au moins ce nombre de courses connues avant ce jour.
HIST_MIN_COURSES = 3
# Bornes des tranches de couverture (part des partants couverts), en %.
COUVERTURE_BORNES = (25, 50, 75)
# Segment sous ce nombre de courses → NULL.
MIN_COURSES = 50
# Une course sous ce nombre de partants évalués n'est pas mesurée (trop peu de
# chevaux pour qu'un top 3 veuille dire quelque chose).
MIN_PARTANTS = 4
# Plancher de probabilité dans la log-loss (une proba nulle donnerait l'infini).
P_MIN = 1e-4

_GALOP = {"PLAT", "HAIES", "STEEPLE", "STEEPLE-CHASE", "CROSS", "OBSTACLE"}
_TROT = {"ATTELE", "ATTELÉ", "MONTE", "MONTÉ", "TROT"}


def famille_discipline(discipline: str | None) -> str:
    """Trot / galop / inconnu. Jamais devinée : une discipline absente reste inconnue."""
    d = (discipline or "").strip().upper()
    if d in _TROT or d.startswith("TROT"):
        return "trot"
    if d in _GALOP or d.startswith("PLAT"):
        return "galop"
    return "inconnu"


def tranche_couverture(part_couverts: float) -> str:
    """Libellé de tranche pour une part de partants couverts dans [0, 1]."""
    pct = 100.0 * part_couverts
    lo = 0
    for hi in COUVERTURE_BORNES:
        if pct < hi:
            return f"{lo}-{hi} %"
        lo = hi
    return f"{lo}-100 %"


def positions_depuis_classement(classement) -> dict[int, int]:
    """numéro → position d'arrivée, depuis `resultats.classement` (liste ou {classement: […]})."""
    if not classement:
        return {}
    data = classement if isinstance(classement, (list, dict)) else json.loads(classement)
    entries = data if isinstance(data, list) else data.get("classement", [])
    out: dict[int, int] = {}
    for e in entries:
        if not isinstance(e, dict):
            continue
        pos = e.get("position") or e.get("place") or e.get("rang")
        num = e.get("numero") or e.get("num")
        try:
            if pos is not None and num is not None and int(pos) > 0:
                out[int(num)] = int(pos)
        except (TypeError, ValueError):
            continue
    return out


def mesurer_course(partants: list[dict], positions: dict[int, int]) -> dict | None:
    """Mesures d'UNE course. Fonction PURE (aucune I/O) → testable sans DB.

    `partants` : [{numero, proba, cote, n_avant}] — partants évalués, non-partants exclus.
    Retourne None si la course n'est pas mesurable (trop peu de partants, pas de
    gagnant parmi les partants évalués, probas nulles).
    """
    if len(partants) < MIN_PARTANTS:
        return None
    gagnants = {n for n, p in positions.items() if p == 1}
    nums = [p["numero"] for p in partants]
    if not gagnants or not gagnants & set(nums):
        return None
    total = sum(max(0.0, p["proba"]) for p in partants)
    if total <= 0:
        return None

    def _rangs(cle, reverse):
        # Tri stable sur le numéro pour départager les égalités de façon déterministe.
        return [p["numero"] for p in sorted(partants, key=lambda p: (
            -cle(p) if reverse else cle(p), p["numero"]))]

    ordre_modele = _rangs(lambda p: p["proba"], reverse=True)
    proba_gagnant = sum(max(0.0, p["proba"]) for p in partants if p["numero"] in gagnants) / total
    m = {
        "n_partants": len(partants),
        "part_couverts": sum(1 for p in partants if p["n_avant"] >= HIST_MIN_COURSES) / len(partants),
        "modele_top1_gagne": ordre_modele[0] in gagnants,
        "modele_top1_place": positions.get(ordre_modele[0], 99) <= 3,
        "gagnant_dans_top3_modele": bool(gagnants & set(ordre_modele[:3])),
        "modele_logloss": -math.log(max(P_MIN, proba_gagnant)),
        "proba_annoncee": sum(max(0.0, p["proba"]) for p in partants),
        "n_gagnants": len(gagnants & set(nums)),
        "marche": None,
    }
    cotes = [p["cote"] for p in partants]
    if all(c is not None and c > 1.0 for c in cotes):
        impl_total = sum(1.0 / c for c in cotes)
        ordre_marche = _rangs(lambda p: p["cote"], reverse=False)
        impl_gagnant = sum(1.0 / p["cote"] for p in partants if p["numero"] in gagnants) / impl_total
        m["marche"] = {
            "top1_gagne": ordre_marche[0] in gagnants,
            "top1_place": positions.get(ordre_marche[0], 99) <= 3,
            "gagnant_dans_top3": bool(gagnants & set(ordre_marche[:3])),
            "logloss": -math.log(max(P_MIN, impl_gagnant)),
        }
    return m


def agreger(mesures: list[dict]) -> dict:
    """Agrégat d'un segment. Fonction PURE. Sous MIN_COURSES : métriques à None."""
    n = len(mesures)
    out: dict = {"n_courses": n, "fiable": n >= MIN_COURSES}
    if not out["fiable"]:
        return out

    def pct(cle, src):
        return 100.0 * sum(1 for x in src if x[cle]) / len(src)

    out.update(
        partants_moy=sum(x["n_partants"] for x in mesures) / n,
        couverture_moy_pct=100.0 * sum(x["part_couverts"] for x in mesures) / n,
        modele_top1_gagne_pct=pct("modele_top1_gagne", mesures),
        modele_top1_place_pct=pct("modele_top1_place", mesures),
        gagnant_top3_modele_pct=pct("gagnant_dans_top3_modele", mesures),
        modele_logloss=sum(x["modele_logloss"] for x in mesures) / n,
        # Calibration : somme des probas annoncées / victoires réelles. Les probas
        # brutes ne somment pas forcément à 1 sur une course : ce ratio le montre.
        ratio_annonce_reel=(sum(x["proba_annoncee"] for x in mesures)
                            / max(1, sum(x["n_gagnants"] for x in mesures))),
        # Hasard pur : 1 / nb partants, pour situer le taux de réussite.
        hasard_top1_pct=100.0 * sum(1.0 / x["n_partants"] for x in mesures) / n,
    )
    avec_marche = [x for x in mesures if x["marche"]]
    nm = len(avec_marche)
    out["n_courses_marche"] = nm
    if nm >= MIN_COURSES:
        diffs = [x["modele_logloss"] - x["marche"]["logloss"] for x in avec_marche]
        moy = sum(diffs) / nm
        et = math.sqrt(sum((d - moy) ** 2 for d in diffs) / max(1, nm - 1) / nm)
        out.update(
            marche_top1_gagne_pct=100.0 * sum(1 for x in avec_marche if x["marche"]["top1_gagne"]) / nm,
            marche_top1_place_pct=100.0 * sum(1 for x in avec_marche if x["marche"]["top1_place"]) / nm,
            gagnant_top3_marche_pct=100.0 * sum(1 for x in avec_marche if x["marche"]["gagnant_dans_top3"]) / nm,
            marche_logloss=sum(x["marche"]["logloss"] for x in avec_marche) / nm,
            modele_logloss_memes_courses=sum(x["modele_logloss"] for x in avec_marche) / nm,
            # < 0 : le modèle fait mieux que le marché. IC 95 % apparié (mêmes courses).
            ecart_logloss_modele_marche=moy,
            ecart_logloss_ic95=1.96 * et,
        )
    return out


def segmenter(courses: list[dict]) -> dict:
    """Ventile les mesures de course (avec leurs clés zone/famille/pays). Fonction PURE."""
    seg: dict[str, dict[str, list]] = {"zone": defaultdict(list), "zone_discipline": defaultdict(list),
                                       "zone_couverture": defaultdict(list), "pays_etranger": defaultdict(list)}
    for c in courses:
        z, m = c["zone"], c["mesure"]
        seg["zone"][z].append(m)
        seg["zone_discipline"][f"{z} · {c['famille']}"].append(m)
        seg["zone_couverture"][f"{z} · {tranche_couverture(m['part_couverts'])}"].append(m)
        if z == ZONE_ETRANGER:
            seg["pays_etranger"][c["pays"]].append(m)
    return {nom: {k: agreger(v) for k, v in sorted(d.items())} for nom, d in seg.items()}


async def charger(session, jours: int | None) -> list[dict]:
    """Lit les pronostics figés, les cotes figées, l'historique et les arrivées."""
    from ml.prediction_evaluation import sans_modeles_retires

    depuis = (datetime.now(timezone.utc) - timedelta(days=jours)) if jours else None
    filtre_date = "AND c.date_heure >= :depuis" if depuis else ""
    params = {"depuis": depuis} if depuis else {}

    # Historique point-in-time : nb de courses ANTÉRIEURES (avec résultat) du même
    # cheval. Fenêtre sur toute la table : une course hors période compte dans
    # l'historique d'une course de la période, comme pour le modèle.
    rows = (await session.execute(text(f"""
        WITH hist AS (
            SELECT p.participation_id,
                   COUNT(*) OVER (PARTITION BY p.cheval_id ORDER BY c.date_heure
                                  ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) AS n_avant
            FROM participations p
            JOIN courses c   ON c.course_id = p.course_id
            JOIN resultats r ON r.course_id = p.course_id
            WHERE c.date_heure IS NOT NULL
              AND COALESCE(p.non_partant, false) = false
        )
        SELECT pe.course_id, pa.numero, pe.proba_top1, pe.cote_figee,
               COALESCE(h.n_avant, 0), c.discipline, hp.pays
        FROM prediction_evaluation pe
        JOIN participations pa ON pa.participation_id = pe.participation_id
        JOIN courses c         ON c.course_id = pe.course_id
        JOIN resultats r       ON r.course_id = pe.course_id
        LEFT JOIN hippodromes hp ON hp.nom = c.hippodrome_nom
        LEFT JOIN hist h       ON h.participation_id = pe.participation_id
        WHERE pe.proba_top1 IS NOT NULL
          AND pe.is_replayable = true
          AND pe.created_at IS NOT NULL
          AND c.date_heure IS NOT NULL
          AND pe.created_at < c.date_heure
          AND COALESCE(pa.non_partant, false) = false
          {filtre_date}
          {sans_modeles_retires("pe")}
    """), params)).all()

    par_course: dict[str, dict] = {}
    for course_id, numero, proba, cote, n_avant, discipline, pays in rows:
        if numero is None:
            continue
        c = par_course.setdefault(course_id, {"partants": {}, "discipline": discipline, "pays": pays})
        # Une ligne par participation dans la vue ; on garde la première par numéro
        # par sécurité (jamais deux probas pour un même partant).
        c["partants"].setdefault(int(numero), {
            "numero": int(numero), "proba": float(proba),
            "cote": float(cote) if cote is not None else None, "n_avant": int(n_avant)})

    if not par_course:
        return []
    arrivees = dict((await session.execute(text(
        "SELECT course_id, classement FROM resultats WHERE course_id = ANY(:ids)"),
        {"ids": list(par_course)})).all())

    courses = []
    for course_id, c in par_course.items():
        zone = zone_depuis_pays(c["pays"])
        if zone is None:       # pays inconnu : aucune zone devinée
            continue
        m = mesurer_course(list(c["partants"].values()), positions_depuis_classement(arrivees.get(course_id)))
        if m is None:
            continue
        courses.append({"course_id": course_id, "zone": zone, "pays": str(c["pays"]).upper(),
                        "famille": famille_discipline(c["discipline"]), "mesure": m})
    return courses


def _f(v, fmt="{:.1f}"):
    return "NULL" if v is None else fmt.format(v)


def _imprimer_segment(titre: str, segs: dict) -> None:
    print(f"\n── {titre} " + "─" * max(0, 100 - len(titre)))
    print(f"{'segment':<26}{'courses':>8}{'couv.%':>8}{'top1 G':>8}{'march.':>8}{'hasard':>8}"
          f"{'top1 P':>8}{'march.':>8}{'G∈top3':>8}{'march.':>8}{'LL mod':>8}{'LL mar':>8}"
          f"{'écart (IC95)':>16}{'ann/réel':>9}")
    for nom, a in segs.items():
        if not a["fiable"]:
            print(f"{nom:<26}{a['n_courses']:>8}   (n < {MIN_COURSES} : NULL)")
            continue
        ecart = a.get("ecart_logloss_modele_marche")
        ecart_s = "NULL" if ecart is None else f"{ecart:+.3f} ±{a['ecart_logloss_ic95']:.3f}"
        print(f"{nom:<26}{a['n_courses']:>8}{_f(a['couverture_moy_pct']):>8}"
              f"{_f(a['modele_top1_gagne_pct']):>8}{_f(a.get('marche_top1_gagne_pct')):>8}"
              f"{_f(a['hasard_top1_pct']):>8}"
              f"{_f(a['modele_top1_place_pct']):>8}{_f(a.get('marche_top1_place_pct')):>8}"
              f"{_f(a['gagnant_top3_modele_pct']):>8}{_f(a.get('gagnant_top3_marche_pct')):>8}"
              f"{_f(a.get('modele_logloss_memes_courses'), '{:.3f}'):>8}"
              f"{_f(a.get('marche_logloss'), '{:.3f}'):>8}{ecart_s:>16}"
              f"{_f(a['ratio_annonce_reel'], '{:.2f}'):>9}")


def imprimer(res: dict, jours: int | None) -> None:
    print(f"\nPrécision du modèle France / étranger — "
          f"{'tout l’historique' if not jours else f'{jours} derniers jours'}")
    print(f"Courses mesurées : {res['n_courses']}  ·  « couvert » = ≥ {HIST_MIN_COURSES} courses "
          f"connues en base avant ce jour")
    print("Colonnes : top1 G = n°1 gagne ; top1 P = n°1 dans les 3 ; G∈top3 = gagnant dans le top 3 ;"
          "\n  march. = même mesure pour le favori de la cote figée ; LL = log-loss du gagnant"
          " (plus bas = mieux) ;\n  écart = LL modèle − LL marché sur les mêmes courses (< 0 : le modèle"
          " bat le marché) ;\n  ann/réel = probas annoncées / victoires réelles (> 1 = surannonce).")
    _imprimer_segment("1. Par zone", res["segments"]["zone"])
    _imprimer_segment("2. Zone × discipline", res["segments"]["zone_discipline"])
    _imprimer_segment("3. Zone × couverture d'historique (part des partants couverts)",
                      res["segments"]["zone_couverture"])
    _imprimer_segment("4. Étranger par pays", res["segments"]["pays_etranger"])
    print("\nLecture :")
    print("  - Si l'écart FRA/ETR sur « top1 G » se retrouve aussi sur la colonne marché, la zone est")
    print("    simplement plus difficile (champs plus ouverts) : ce n'est pas un défaut du modèle.")
    print("  - Si l'« écart » modèle − marché est nettement pire à l'étranger, le modèle y apporte")
    print("    moins que le marché : c'est ce qu'il faut corriger.")
    print("  - Section 3 : si, à tranche de couverture égale, ETR rejoint FRA, l'écart vient du")
    print("    manque d'historique → importer l'historique étranger est la bonne piste.\n")


async def main(jours: int | None, as_json: bool) -> None:
    from db.database import AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        courses = await charger(session, jours)
    res = {"n_courses": len(courses), "jours": jours, "hist_min_courses": HIST_MIN_COURSES,
           "zones": [ZONE_FRANCE, ZONE_ETRANGER], "segments": segmenter(courses)}
    if as_json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        imprimer(res, jours)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--jours", type=int, default=None,
                    help="limiter aux courses des N derniers jours (défaut : tout l'historique)")
    ap.add_argument("--json", action="store_true", help="sortie JSON au lieu des tableaux")
    args = ap.parse_args()
    asyncio.run(main(args.jours, args.json))
