"""
isotonic_utils.py — Régression isotone CENTRÉE (CIR) pour les courbes de calibration.

PROBLÈME CORRIGÉ (mesuré en prod le 2026-08-31)
-----------------------------------------------
Une régression isotone classique produit une fonction EN ESCALIER : de longs paliers
sur lesquels toutes les entrées distinctes sont mappées vers UNE seule valeur. Mesure
prod : la courbe active avait 62 points de rupture pour seulement 31 `y` distincts,
avec par exemple tout x ∈ [0.036317, 0.047025] → y = 0.042435.

Conséquence directe : deux chevaux d'une même course dont la proba modèle diffère de
25 % en relatif ressortaient avec EXACTEMENT la même proba calibrée, donc la même
« cote juste » affichée. Mesuré sur 7 jours : 10.99 probas distinctes en brut pour
11.06 partants → 6.70 après calibration (96 % des courses avec au moins un doublon).

MÉTHODE
-------
Régression isotone centrée (Oron & Flournoy, "Centered Isotonic Regression", 2017) :
on fitte l'isotone classique, puis chaque BLOC plat est réduit à un point unique placé
au CENTROÏDE (moyenne des x du bloc). On interpole linéairement entre les centres → la
courbe devient STRICTEMENT croissante : deux entrées distinctes donnent deux sorties
distinctes, tout en conservant le niveau de calibration de chaque bloc.

Le taux de chaque bloc est lissé, (k + a) / (n + 2a) avec a pseudo-observations, au
lieu du taux brut k/n : un bloc à 0.0 exact (aucun gagnant observé parmi les plus
petites probas) n'est pas « probabilité nulle », et le lissage régularise toute la
courbe (force calibrée en 5 plis, cf. _PRIOR). Ce lissage peut inverser deux blocs de
tailles très différentes ; la monotonie est alors rétablie en FUSIONNANT les blocs
concernés (PAVA sur les taux lissés), jamais par un pas epsilon — un epsilon
recollerait les blocs en QUASI-plateau, x bougeant de 43 % pour 0,02 % de y (mesuré),
soit le défaut d'origine sous une autre forme. Si les données ne séparent pas deux
blocs, ils ne forment qu'un point.

Aucune valeur inventée : le fit reste celui des vraies arrivées, seule la FORME de la
reconstruction change (centres de blocs au lieu de marches).
"""
from __future__ import annotations

import numpy as np
import structlog

log = structlog.get_logger(module="isotonic_utils")

# Écart relatif minimal imposé entre deux `y` consécutifs de la courbe reconstruite.
# Garantit la stricte croissance malgré les arrondis de sérialisation.
_MIN_REL_STEP = 1e-4

# Force de la prior du taux de bloc, en pseudo-observations : (k + a) / (n + 2a).
# Balayée en 5 plis groupés PAR COURSE sur les données réelles (2026-08-31), moyennes :
#   a     logloss   brier     ece      cotes justes distinctes / partants
#   0.5   0.29309   0.08127   0.03299  98 %   (Jeffreys pur : trop peu lissé)
#   5     0.26783   0.07641   0.02104  98 %
#   8     0.26824   0.07648   0.02304  98 %   (bosse locale — la métrique n'est
#                                              PAS lisse en a, un « milieu de
#                                              plateau » choisi au jugé est faux)
#   12    0.26767   0.07642   0.02054  98 %   ← optimum sur les trois métriques
#   20    0.26881   0.07648   0.02123  97 %
#   60    0.27107   0.07672   0.02489  97 %   (sur-lissé : les blocs fusionnent)
# Références du même run : sans calibration du tout 0.26824 / 0.07659 / 0.02072 / 99 %,
# isotone classique (l'existant) 0.27323 / 0.07680 / 0.01962 / 68 %.
_PRIOR = 12.0


def _taux_lisse(k: float, n: float, a: float = _PRIOR) -> float:
    """Taux de succès lissé (k + a) / (n + 2a). Évite les blocs à 0.0 / 1.0 exacts
    et régularise l'ensemble de la courbe."""
    if n <= 0:
        return 0.5
    return (k + a) / (n + 2.0 * a)


def centered_isotonic_curve(x, y) -> dict:
    """Fit CIR sur (x, y binaire) → {"x": [...], "y": [...]} strictement croissant.

    Retourne {"x": [], "y": []} si le fit échoue ou si les données sont dégénérées
    (< 2 blocs exploitables) — l'appelant retombe alors sur l'identité, jamais sur
    une courbe inventée.
    """
    x = np.asarray(x, dtype=float)
    y = np.asarray(y, dtype=float)
    if x.size < 2 or x.size != y.size:
        return {"x": [], "y": []}

    try:
        from sklearn.isotonic import IsotonicRegression
    except Exception as e:  # sklearn absent → identité
        log.warning("cir.sklearn_missing", err=str(e)[:120])
        return {"x": [], "y": []}

    order = np.argsort(x, kind="mergesort")
    xs, ys = x[order], y[order]

    try:
        iso = IsotonicRegression(y_min=0.0, y_max=1.0, increasing=True, out_of_bounds="clip")
        fitted = np.asarray(iso.fit_transform(xs, ys), dtype=float)
    except Exception as e:
        log.warning("cir.fit_failed", err=str(e)[:160])
        return {"x": [], "y": []}

    # ── Découpage en blocs plats de la solution isotone ──────────────────────
    # On segmente sur les RUPTURES de la valeur fittée : deux blocs non adjacents
    # pourraient partager une valeur, np.unique les fusionnerait à tort.
    breaks = np.flatnonzero(np.diff(fitted) > 1e-12) + 1
    starts = np.concatenate(([0], breaks))
    ends = np.concatenate((breaks, [len(fitted)]))

    # Chaque bloc porte la somme de ses x (→ centroïde), son nombre d'observations
    # et son nombre de succès. Le taux retenu est lissé — cf. en-tête et _PRIOR.
    blocs: list[list[float]] = []                 # [sx (somme des x), n, k]
    for s, e in zip(starts, ends):
        if e - s <= 0:
            continue
        blocs.append([float(xs[s:e].sum()), float(e - s), float(ys[s:e].sum())])

    if len(blocs) < 2:
        return {"x": [], "y": []}

    # ── Remontée de la monotonie par FUSION de blocs (PAVA sur les taux lissés) ──
    # Le lissage peut inverser deux blocs de tailles très différentes (3 gagnants
    # sur 44 = 0.0778 contre 1 sur 22 = 0.0652). Les recoller par un pas epsilon
    # fabriquerait un QUASI-plateau — x qui bouge de 43 % pour 0,02 % de y, mesuré
    # en prod : le défaut même qu'on corrige. Fusionner est la bonne réponse : si
    # les données ne séparent pas deux blocs, ils ne forment qu'un point.
    pile: list[list[float]] = []
    for b in blocs:
        pile.append(b)
        while len(pile) > 1 and _taux_lisse(pile[-2][2], pile[-2][1]) >= _taux_lisse(pile[-1][2], pile[-1][1]):
            tete = pile.pop()
            pile[-1] = [pile[-1][0] + tete[0], pile[-1][1] + tete[1], pile[-1][2] + tete[2]]

    if len(pile) < 2:
        return {"x": [], "y": []}

    cx_a = np.asarray([b[0] / b[1] for b in pile], dtype=float)
    cy_a = np.asarray([_taux_lisse(b[2], b[1]) for b in pile], dtype=float)
    cy_a = np.clip(cy_a, 1e-6, 0.999)

    # Garde de stricte croissance : la fusion la garantit déjà, ceci ne couvre que
    # l'arrondi de sérialisation.
    for i in range(1, len(cy_a)):
        floor = cy_a[i - 1] * (1.0 + _MIN_REL_STEP) + 1e-9
        if cy_a[i] < floor:
            cy_a[i] = floor
    cy_a = np.clip(cy_a, 1e-6, 0.999)

    # Deux centroïdes peuvent coïncider si un bloc est réduit à un x répété.
    keep = np.concatenate(([True], np.diff(cx_a) > 1e-9))
    cx_a, cy_a = cx_a[keep], cy_a[keep]
    if cx_a.size < 2:
        return {"x": [], "y": []}

    # ── Ancres aux bords ─────────────────────────────────────────────────────
    # Sans ancre, np.interp CLAMPE hors des centroïdes → un palier plat réapparaît
    # sous le premier centre et au-dessus du dernier (exactement là où vivent les
    # gros outsiders et les favoris marqués). On prolonge la pente locale.
    x_lo = float(min(xs[0], cx_a[0]))
    x_hi = float(max(xs[-1], cx_a[-1]))
    slope_lo = (cy_a[1] - cy_a[0]) / max(cx_a[1] - cx_a[0], 1e-12)
    slope_hi = (cy_a[-1] - cy_a[-2]) / max(cx_a[-1] - cx_a[-2], 1e-12)
    if x_lo < cx_a[0] - 1e-9:
        y_lo = max(1e-6, min(cy_a[0] * 0.5, cy_a[0] - slope_lo * (cx_a[0] - x_lo)))
        cx_a = np.concatenate(([x_lo], cx_a))
        cy_a = np.concatenate(([y_lo], cy_a))
    if x_hi > cx_a[-1] + 1e-9:
        y_hi = min(0.999, max(cy_a[-1] * 1.001, cy_a[-1] + slope_hi * (x_hi - cx_a[-1])))
        cx_a = np.concatenate((cx_a, [x_hi]))
        cy_a = np.concatenate((cy_a, [y_hi]))

    return {
        "x": [round(float(v), 8) for v in cx_a.tolist()],
        "y": [round(float(v), 8) for v in cy_a.tolist()],
    }


def restore_within_race_order(mapped, source) -> np.ndarray:
    """Rend aux ex æquo ARTIFICIELS l'ordre que la calibration leur a effacé.

    `mapped` = probas après calibration, `source` = les mêmes probas AVANT.
    Deux chevaux dont la proba d'entrée DIFFÉRAIT mais dont la proba calibrée est
    identique sont un artefact de palier : on ré-étale le groupe autour de sa valeur
    commune, en respectant l'ordre d'entrée, sans jamais franchir les voisins.

    Deux chevaux dont la proba d'ENTRÉE était déjà identique restent identiques : on
    ne fabrique aucune différence qui n'existe pas dans le modèle.

    Filet de sécurité : avec une courbe CIR il n'y a plus de palier, donc plus d'ex
    æquo artificiel. Ça reste vrai des courbes ANCIENNES encore en base tant que le
    recalcul nocturne n'a pas tourné.
    """
    m = np.asarray(mapped, dtype=float).copy()
    s = np.asarray(source, dtype=float)
    if m.size != s.size or m.size < 2:
        return m

    # Demi-amplitude d'étalement, en relatif. Dimensionnée pour rester lisible à
    # 0,1 près sur une cote juste même quand un palier colle 5 ou 6 chevaux
    # ensemble, et bornée par la distance aux voisins immédiats du groupe.
    SPREAD = 0.03

    order = np.argsort(m, kind="mergesort")
    n = m.size
    i = 0
    while i < n:
        j = i
        while j + 1 < n and abs(m[order[j + 1]] - m[order[i]]) <= 1e-12:
            j += 1
        grp = order[i:j + 1]
        if len(grp) > 1:
            src = s[grp]
            if float(np.ptp(src)) > 0:                     # ex æquo ARTIFICIEL
                base = float(m[grp[0]])
                half = base * SPREAD
                # On ne franchit jamais les voisins immédiats du groupe : le palier
                # est réparé À L'INTÉRIEUR de sa place dans le classement.
                if i > 0:
                    half = min(half, (base - float(m[order[i - 1]])) * 0.45)
                if j + 1 < n:
                    half = min(half, (float(m[order[j + 1]]) - base) * 0.45)
                if half > 0:
                    # Étalement proportionnel aux VALEURS d'entrée (pas aux rangs) :
                    # deux chevaux que le modèle sépare à peine restent proches, ceux
                    # qu'il sépare franchement s'écartent d'autant. C'est ce que la
                    # courbe CIR ferait localement.
                    lo, hi = float(src.min()), float(src.max())
                    frac = (src - lo) / (hi - lo)          # ∈ [0, 1], ptp > 0 garanti
                    m[grp] = base + (frac - 0.5) * 2.0 * half
        i = j + 1

    return np.clip(m, 1e-6, 0.999)
