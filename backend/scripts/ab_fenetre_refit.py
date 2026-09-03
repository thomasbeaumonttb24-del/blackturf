"""Combien coûte l'angle mort du hold-out temporel ? — rejeu A/B, ne déploie rien.

La question
───────────
`BlackTurfEnsemble.train()` réserve les 20 % de courses les plus RÉCENTES pour
mesurer honnêtement le modèle, et déploie l'artefact entraîné sur les 80 %
anciens — sans refit final. Tant que la fenêtre valait trois mois, cela coûtait
~18 jours d'ignorance. Depuis qu'elle vaut douze mois (v520, 25/08/2026), cela en
coûte ~78 : v527, promu le 01/09, porte `train_fin = 2026-06-15` et n'a jamais vu
les 4 209 courses réglées depuis.

Ce que ce script mesure, et ce qu'il ne mesure pas
──────────────────────────────────────────────────
Deux bras entraînés sur EXACTEMENT les mêmes données, jusqu'à la même date de
coupure, ne différant que par la taille du hold-out :

    bras « prod »  frac_train = 0.80  → aveugle sur ~20 % du temps
    bras « frais » frac_train = 0.98  → aveugle sur ~2 % du temps

Puis les deux prédisent sur les courses POSTÉRIEURES à la coupure : strictement
hors-échantillon pour l'un comme pour l'autre. C'est la seule comparaison qui
isole l'ignorance du reste — comparer v519 (fenêtre 3 mois) à v527 (12 mois)
confondrait taille de fenêtre et fraîcheur.

Ce n'est PAS une mesure de ROI. Le classement intra-course est ce qui décide du
pronostic ; ce que le plan de mise en fait est une autre chaîne, mesurée
ailleurs. Un gain de classement est une condition nécessaire, pas suffisante.

Trois gardes, chacune pour une erreur déjà commise ici
──────────────────────────────────────────────────────
- Anti-fuite : `fm.computed_at < c.date_heure` des deux côtés (features figées
  AVANT le départ), et le dataset d'entraînement est reconstruit TEL QU'IL ÉTAIT
  à la coupure (`date_fin`), sans quoi le bras « frais » verrait l'avenir.
- Décision APPARIÉE : le verdict vient de la différence de classement COURSE PAR
  COURSE entre les deux bras, et de son intervalle de confiance. Les deux
  moitiés chronologiques restent affichées — elles montrent si l'effet tient
  dans le temps, et un effet de régime s'y voit — mais elles ne décident plus.
  « Même signe deux fois » est un pile ou face gagné deux fois ; et
  symétriquement, un effet réel tombe du mauvais côté une fois sur quatre.
- Référence : l'écart au MARCHÉ (`delta_market`), pas l'AUC nue. Une AUC de 0,76
  n'est ni bonne ni mauvaise dans l'absolu ; ce qui compte est ce qu'elle ajoute
  à un `ORDER BY cote_pmu`.

Pourquoi apparié, chiffré
─────────────────────────
Le bruit dominant est de savoir quel cheval a gagné, et il est COMMUN aux deux
bras puisque ce sont les mêmes courses. Le laisser dans les deux termes, c'est
comparer deux nombres noyés dans une variance qui aurait dû s'annuler. Mesuré le
2026-09-03 sur le profil risqué : écart-type du rendement PAR PARI de 359 %, à 87
paris par jour — soit 371 jours pour distinguer deux points de ROI en
échantillons indépendants, ~870 pour en distinguer quatre. Aucune décision
produit n'attend ça, et c'est pourquoi le ROI vécu n'arbitre RIEN : les journées
vont de −66 % à +24 % sans qu'aucune gate n'ait bougé. Corollaire pratique :
séquencer les déploiements pour « préserver l'attribution » n'achète rien,
puisque aucune séquence ne rend deux gates attribuables par le ROI vécu. Elles
restent en revanche séparables au banc, où on les active une à une sur les mêmes
courses.

Résultat (2026-09-03, verdict apparié le 2026-09-04) — MESURÉ, PUIS CONSERVÉ
───────────────────────────────────────────────────────────────────────────
Coupure 01/07/2026, fenêtre 12 mois, évaluation sur les 2 838 courses du 01/07 au
30/08. Écart au marché, par moitié chronologique :

    fenêtre entière   prod −0,0371   frais −0,0394   gain frais −0,0023
    première moitié   prod −0,0427   frais −0,0484   gain frais −0,0057
    seconde moitié    prod −0,0314   frais −0,0301   gain frais +0,0012

Test apparié, différence de classement PAR COURSE (frais − prod), 2 733 courses
appariées, écart-type par course 0,2190 :

    écart moyen  −0,00228     IC 95 %  [−0,01081 ; +0,00614]

CONCLUSION, ET SA LIMITE — la seconde compte autant que la première.

L'intervalle contient zéro : aucun gain n'est démontré, donc rien à déployer, et
la refonte du gate de promotion qu'un refit aurait exigée n'a pas lieu d'être.

Mais il ne dit PAS que l'hypothèse est fausse — première rédaction de ce fichier
(commit « l'angle mort du hold-out ne coûte pas de classement — hypothèse
fausse »), qui concluait au SIGNE des deux moitiés et qui est ici RETIRÉE. La
borne haute vaut +0,006, soit environ le tiers de tout l'avantage de v527 sur le
marché (+0,019) : un effet de cette taille serait considérable et cette mesure ne
l'exclut pas. Le bon énoncé est « non résolu à cette taille d'échantillon ».

Ce que ce banc peut voir, chiffré, parce que c'est la vraie leçon :
erreur-type de l'écart apparié = 0,2190 / √2 733 ≈ 0,0042. Il tranche donc les
effets d'environ 0,012 et plus. Descendre à 0,002 demanderait ~98 000 courses,
soit ~2 000 jours au rythme actuel — et même en jetant TOUT l'historique
disponible (~20 000 courses) on ne descendrait qu'à ~0,004. Le banc de plans
souffre de la même limite par un autre chemin (session blackturf-97, 2026-09-04 :
écart apparié à ±5,5 points de ROI sur 4 147 courses, ~15 points détectables).

Autrement dit : on cherche des gains de 3 à 5 points avec des instruments qui
n'en voient que 15. Aucun raffinement de protocole ne rattrape ça — seul un effet
GROS (retirer un type de pari entier, pas resserrer un seuil) est arbitrable ici.

Deux réserves qui empêchent de lire ces chiffres comme un verdict sur la
production, et qu'il ne faut pas perdre :

- Le niveau absolu n'est PAS comparable au `rank_delta_market` = +0,019 de v527.
  L'évaluation ci-dessus porte sur le label VICTOIRE avec une proba de TOP-3,
  quand la production mesure top-3 contre top-3. La cote (1/cote) étant une
  probabilité de victoire, elle part avantagée sur ce label. La comparaison
  ENTRE LES DEUX BRAS reste valide — scoring identique des deux côtés.
- Le produit ne sert jamais la proba nue mais `alpha × modèle + (1 − alpha) ×
  marché` (cf. `_head_to_head_auc`). Mesuré le 02/09 sur 727 courses : le modèle
  NU perd contre la cote (−0,0114) là où la proba SERVIE la bat (+0,0012). Le
  résultat ci-dessus va dans le même sens et ne révèle donc rien de neuf.

Usage
─────
    python -m scripts.ab_fenetre_refit --coupure 2026-07-01
    python -m scripts.ab_fenetre_refit --coupure 2026-07-01 --max-rows 40000  # essai rapide
"""
import argparse
import asyncio
import json
from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
from sqlalchemy import text

from db.database import AsyncSessionLocal
from ml.models import BlackTurfEnsemble
from ml.pipeline import _build_training_dataset_from_db
from ml.ranking_metrics import (extract_cotes, rank_auc_report,
                                within_race_auc_par_course)

# En deçà, aucune moitié ne conclut : l'écart mesuré serait du bruit.
MIN_COURSES_MOITIE = 200


async def _dataset_evaluation(session, debut: datetime, fin: datetime) -> pd.DataFrame:
    """Courses réglées de la fenêtre, features PRÉ-DÉPART, label victoire.

    Mêmes gardes anti-fuite que l'entraînement. Le label est la VICTOIRE et non
    le top-3 : c'est celui que `scripts/check_h2h_champion.py` utilise déjà pour
    le même usage, et le classement intra-course se juge sur le vainqueur.
    """
    result = await session.stream(text("""
        SELECT fm.features,
               pa.course_id,
               CASE WHEN (r.classement->0->>'numero')::int = pa.numero THEN 1 ELSE 0 END AS win
        FROM features_ml fm
        JOIN participations pa ON pa.participation_id = fm.participation_id
        JOIN courses c ON c.course_id = pa.course_id AND c.statut = 'termine'
        JOIN resultats r ON r.course_id = pa.course_id
        WHERE c.date_heure >= :debut AND c.date_heure < :fin
          AND c.date_heure IS NOT NULL AND fm.computed_at < c.date_heure
          AND jsonb_typeof(r.classement) = 'array'
        ORDER BY c.date_heure
    """), {"debut": debut, "fin": fin})

    # Curseur serveur et conversion PAR BLOCS, comme le builder d'entraînement :
    # un partant pèse ~30 Ko en dict Python (173 clés JSON) contre ~700 octets en
    # ligne de DataFrame. Tout matérialiser d'un coup ferait passer 30 000
    # partants de 20 Mo à près d'un gigaoctet — c'est précisément ce qui a fait
    # désigner le worker comme victime de l'OOM killer en août 2026.
    blocs: list[pd.DataFrame] = []
    async for partition in result.partitions(5000):
        bloc = pd.DataFrame([f if isinstance(f, dict) else json.loads(f)
                             for f, _, _ in partition])
        bloc["course_id"] = [c for _, c, _ in partition]
        bloc["_win"] = [w for _, _, w in partition]
        blocs.append(bloc.astype({c: "float32" for c in bloc.columns
                                  if bloc[c].dtype == "float64"}))
        del partition
    if not blocs:
        return pd.DataFrame()
    X = pd.concat(blocs, ignore_index=True)
    del blocs
    return X


def _mesurer(modele: BlackTurfEnsemble, X: pd.DataFrame) -> dict:
    """Classement du modèle, du marché, et l'écart — sur un échantillon donné."""
    if X.empty:
        return {"n_lignes": 0, "n_courses": 0}
    p = modele.predict_proba(X)
    rapport = rank_auc_report(X["_win"].to_numpy(), p,
                              X["course_id"].to_numpy(), cotes=extract_cotes(X))
    return {
        "n_lignes": int(len(X)),
        "n_courses": int(X["course_id"].nunique()),
        "rank_auc": rapport["rank_auc"],
        "market_rank_auc": rapport["market_rank_auc"],
        "delta_market": rapport["delta_market"],
    }


def _auc_par_course(modele, X: pd.DataFrame) -> dict:
    """Classement du modèle, COURSE PAR COURSE — la matière du test apparié."""
    if X.empty:
        return {}
    return within_race_auc_par_course(X["_win"].to_numpy(), modele.predict_proba(X),
                                      X["course_id"].to_numpy())


def _test_apparie(a: dict, b: dict, n_tirages: int = 2000,
                  graine: int = 42) -> dict:
    """Différence MOYENNE PAR COURSE entre deux bras, et son intervalle.

    Pourquoi apparié plutôt que deux moyennes comparées : le bruit dominant
    est de savoir quel cheval a gagné, et il est COMMUN aux deux bras puisque
    ce sont les mêmes courses. En le laissant dans les deux termes, on compare
    deux nombres noyés dans une variance qui aurait dû s'annuler. Chiffré sur
    le profil risqué le 2026-09-03 : l'écart-type du rendement par pari atteint
    359 %, soit 371 jours de production pour distinguer deux points de ROI en
    échantillons indépendants. Aucune décision produit ne peut attendre ça —
    donc tout arbitrage se fait apparié, sur les mêmes courses.

    L'intervalle vient d'un bootstrap sur les COURSES (et non sur les
    partants) : c'est la course qui est l'unité d'observation indépendante,
    deux partants d'une même course ne l'étant évidemment pas.

    Renvoie l'écart moyen, son intervalle à 95 %, et `conclut` — vrai seulement
    si l'intervalle exclut zéro. « Même signe deux fois » n'est pas une preuve,
    c'est un pile ou face gagné deux fois.
    """
    communes = sorted(set(a) & set(b))
    if len(communes) < 30:
        return {"n_courses": len(communes), "conclut": False, "ecart": None,
                "ic_bas": None, "ic_haut": None}
    d = np.array([b[c] - a[c] for c in communes], dtype=float)
    rng = np.random.default_rng(graine)
    tirages = rng.integers(0, len(d), size=(n_tirages, len(d)))
    moyennes = d[tirages].mean(axis=1)
    bas, haut = np.percentile(moyennes, [2.5, 97.5])
    return {
        "n_courses": len(communes),
        "ecart": float(d.mean()),
        "ecart_type": float(d.std(ddof=1)),
        "ic_bas": float(bas),
        "ic_haut": float(haut),
        "conclut": bool(bas > 0 or haut < 0),
    }


def _moities(X: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Deux moitiés CHRONOLOGIQUES, découpées par course et non par ligne."""
    courses = list(dict.fromkeys(X["course_id"].tolist()))
    coupe = set(courses[: len(courses) // 2])
    masque = X["course_id"].isin(coupe)
    return X[masque], X[~masque]


def _ligne(nom: str, m: dict) -> str:
    if not m.get("n_courses"):
        return f"  {nom:<12} — échantillon vide"
    delta = m["delta_market"]
    return (f"  {nom:<12} rang {m['rank_auc']:.4f}   marché {m['market_rank_auc']:.4f}   "
            f"écart {delta:+.4f}   ({m['n_courses']} courses)"
            if delta is not None else
            f"  {nom:<12} rang {m['rank_auc']:.4f}   (cotes indisponibles)")


async def main(coupure: datetime, mois: int, horizon_jours: int,
               max_rows: int | None) -> int:
    fin_eval = coupure + timedelta(days=horizon_jours)
    print(f"coupure     : {coupure:%Y-%m-%d}")
    print(f"fenêtre     : {mois} mois avant la coupure")
    print(f"évaluation  : {coupure:%Y-%m-%d} → {fin_eval:%Y-%m-%d}\n", flush=True)

    async with AsyncSessionLocal() as session:
        X, y, y_win = await _build_training_dataset_from_db(
            session, mois, max_rows=max_rows, date_fin=coupure)
        if len(X) < 300:
            print(f"ABANDON : {len(X)} lignes d'entraînement, insuffisant.")
            return 1
        n_courses_train = int(X["course_id"].nunique()) if "course_id" in X.columns else 0
        print(f"entraînement : {len(X)} partants / {n_courses_train} courses", flush=True)

        X_eval = await _dataset_evaluation(session, coupure, fin_eval)

    if X_eval.empty or X_eval["course_id"].nunique() < 2 * MIN_COURSES_MOITIE:
        n = 0 if X_eval.empty else X_eval["course_id"].nunique()
        print(f"ABANDON : {n} courses d'évaluation, il en faut "
              f"{2 * MIN_COURSES_MOITIE} pour juger sur deux moitiés.")
        return 1
    print(f"évaluation   : {len(X_eval)} partants / "
          f"{X_eval['course_id'].nunique()} courses\n", flush=True)

    premiere, seconde = _moities(X_eval)
    resultats: dict[str, dict] = {}
    par_course: dict[str, dict] = {}
    for nom, frac in (("prod", 0.80), ("frais", 0.98)):
        print(f"[{nom}] entraînement frac_train={frac} …", flush=True)
        t0 = datetime.now()
        modele = BlackTurfEnsemble()
        modele.train(X, y, y_win, frac_train=frac)
        print(f"[{nom}] entraîné en {(datetime.now() - t0).total_seconds() / 60:.1f} min",
              flush=True)
        resultats[nom] = {
            "tout": _mesurer(modele, X_eval),
            "moitie_1": _mesurer(modele, premiere),
            "moitie_2": _mesurer(modele, seconde),
        }
        # Gardé pour le test apparié : ce sont les MÊMES courses des deux côtés,
        # c'est ce qui permet au bruit commun de s'annuler.
        par_course[nom] = _auc_par_course(modele, X_eval)
        del modele

    print("\n" + "=" * 72)
    for periode, titre in (("tout", "Fenêtre entière"),
                           ("moitie_1", "Première moitié"),
                           ("moitie_2", "Seconde moitié")):
        print(f"\n{titre}")
        for nom in ("prod", "frais"):
            print(_ligne(nom, resultats[nom][periode]))
        a = resultats["prod"][periode].get("delta_market")
        b = resultats["frais"][periode].get("delta_market")
        if a is not None and b is not None:
            print(f"  {'gain frais':<12} {b - a:+.4f} d'écart au marché")

    # ── Le verdict, lui, est APPARIÉ ────────────────────────────────────────
    # Les deux moitiés ci-dessus restent affichées : elles montrent si l'effet
    # tient dans le temps. Mais elles ne DÉCIDENT plus. « Même signe deux fois »
    # est un pile ou face gagné deux fois, pas une preuve — et l'inverse est vrai
    # aussi : un effet réel peut tomber du mauvais côté une fois sur quatre.
    # Seul l'intervalle sur la différence PAR COURSE tranche.
    apparie = _test_apparie(par_course["prod"], par_course["frais"])
    print("\n" + "=" * 72)
    print("\nTest apparié — différence de classement PAR COURSE (frais − prod)")
    if apparie["ecart"] is None:
        print(f"  échantillon insuffisant ({apparie['n_courses']} courses appariées)")
        return 1
    print(f"  écart moyen      {apparie['ecart']:+.5f}")
    print(f"  IC 95 %          [{apparie['ic_bas']:+.5f} ; {apparie['ic_haut']:+.5f}]")
    print(f"  courses          {apparie['n_courses']}  "
          f"(écart-type par course {apparie['ecart_type']:.4f})")

    print("\n" + "=" * 72)
    if not apparie["conclut"]:
        print("VERDICT : l'intervalle contient zéro — aucun effet démontré. "
              "Garder le découpage actuel.")
    elif apparie["ecart"] > 0:
        print("VERDICT : le bras frais gagne, intervalle strictement positif — "
              "l'angle mort coûte du classement.")
    else:
        print("VERDICT : le bras frais PERD, intervalle strictement négatif — "
              "élargir l'apprentissage dégraderait le classement.")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--coupure", required=True,
                    help="date de coupure ISO, ex. 2026-07-01")
    ap.add_argument("--mois", type=int, default=12,
                    help="fenêtre d'entraînement en mois (défaut : celle de la prod)")
    ap.add_argument("--horizon-jours", type=int, default=60,
                    help="durée de la fenêtre d'évaluation après la coupure")
    ap.add_argument("--max-rows", type=int, default=None,
                    help="plafond de lignes d'entraînement (essai rapide)")
    args = ap.parse_args()
    _coupure = datetime.fromisoformat(args.coupure).replace(tzinfo=timezone.utc)
    raise SystemExit(asyncio.run(main(_coupure, args.mois, args.horizon_jours,
                                      args.max_rows)))
