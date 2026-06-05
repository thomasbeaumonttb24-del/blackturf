"""
race_dynamics.py — Signaux de dynamique de course (Phase 1).

Module de calcul PUR (aucun accès DB, aucun scraping). Transforme les temps
bruts déjà collectés en signaux exploitables par les features ML :

  - parse_temps_to_seconds : normalise les formats de temps hippiques en secondes
  - compute_reduction_km   : réduction kilométrique (temps individuel / km) — trot
  - compute_acceleration   : le cheval a-t-il accéléré ou faibli en fin de course ?

RÈGLE D'INTÉGRITÉ : aucune valeur inventée. Toute entrée manquante, nulle ou
incohérente → retour None. On ne fabrique jamais un signal par défaut.
"""
from __future__ import annotations

import re
from typing import Optional

# Seuils du label d'accélération (index = vitesse finale / vitesse moyenne).
ACCEL_SEUIL_HAUT = 1.05   # ≥ → a accéléré (fini plus vite que son allure moyenne)
ACCEL_SEUIL_BAS = 0.95    # ≤ → a faibli

# Bornes de plausibilité (rejet des valeurs aberrantes plutôt que stockage).
REDUCTION_KM_MIN_S = 55.0    # ~65 km/h : record absolu trot, en dessous = aberrant
REDUCTION_KM_MAX_S = 160.0   # ~22 km/h : plus lent = donnée douteuse
VITESSE_MS_MAX = 22.0        # ~79 km/h : plafond galop, au-delà = parse erroné


def parse_temps_to_seconds(s: Optional[str]) -> Optional[float]:
    """
    Convertit un temps hippique en secondes (float). None si non interprétable.

    Formats gérés :
      "1'12\"3"   → 72.3   (min ' sec " dixièmes — notation trot FR)
      "1'12\"30"  → 72.30
      "1'12"      → 72.0
      "12\"3"     → 12.3
      "1:12.3"    → 72.3   (notation chrono)
      "1:12"      → 72.0
      "72.3" / "72,3" → 72.3
    """
    if s is None:
        return None
    t = str(s).strip()
    if not t:
        return None
    t = t.replace(",", ".")

    # Notation trot : 1'12"3  /  12"3  /  1'12  /  3'24" (quote sans dixièmes)
    m = re.fullmatch(r"(?:(\d+)')?(\d+)(?:\"(\d*))?", t)
    if m:
        minutes = int(m.group(1)) if m.group(1) else 0
        secondes = int(m.group(2))
        frac_raw = m.group(3)
        frac = 0.0
        if frac_raw:  # non None et non vide
            # "3" → 0.3 ; "30" → 0.30 ; "05" → 0.05
            frac = int(frac_raw) / (10 ** len(frac_raw))
        # Sans minutes ni séparateur ", un grand nombre = déjà des secondes ("72")
        if m.group(1) is None and m.group(3) is None:
            return float(secondes)
        return minutes * 60 + secondes + frac

    # Notation chrono : 1:12.3  /  1:12
    m = re.fullmatch(r"(\d+):(\d{1,2}(?:\.\d+)?)", t)
    if m:
        return int(m.group(1)) * 60 + float(m.group(2))

    # Décimal simple : 72.3
    m = re.fullmatch(r"\d+(?:\.\d+)?", t)
    if m:
        return float(t)

    return None


def compute_reduction_km(
    temps_total: Optional[str | float],
    distance_m: Optional[int],
) -> Optional[float]:
    """
    Réduction kilométrique = temps individuel ramené au kilomètre (secondes/km).
    Référence trot pour comparer des courses de distances différentes.

    Retourne les secondes/km, ou None si non calculable / hors bornes plausibles.
    """
    if distance_m is None or distance_m < 500:
        return None
    secs = temps_total if isinstance(temps_total, (int, float)) else parse_temps_to_seconds(temps_total)
    if secs is None or secs <= 0:
        return None
    reduction = secs / (distance_m / 1000.0)
    if not (REDUCTION_KM_MIN_S <= reduction <= REDUCTION_KM_MAX_S):
        return None
    return round(reduction, 2)


def compute_acceleration(
    dernier_400m: Optional[str | float],
    temps_total: Optional[str | float],
    distance_m: Optional[int],
) -> Optional[dict]:
    """
    Détermine si le cheval a accéléré ou faibli sur les derniers 400 m.

    index = vitesse(dernier 400m) / vitesse(moyenne course)
      ≥ 1.05 → "accelere"   (a fini plus vite que son allure moyenne)
      ≤ 0.95 → "faiblit"
      sinon  → "regulier"

    Retourne un dict {acceleration_index, acceleration_label, vitesse_finale_ms,
    vitesse_moyenne_ms}, ou None si données insuffisantes / aberrantes.
    """
    if distance_m is None or distance_m < 400:
        return None
    t_last = dernier_400m if isinstance(dernier_400m, (int, float)) else parse_temps_to_seconds(dernier_400m)
    t_total = temps_total if isinstance(temps_total, (int, float)) else parse_temps_to_seconds(temps_total)
    if not t_last or not t_total or t_last <= 0 or t_total <= 0:
        return None

    vitesse_finale = 400.0 / t_last
    vitesse_moyenne = distance_m / t_total

    # Garde-fou plausibilité : vitesses hippiques réalistes uniquement.
    if not (1.0 < vitesse_finale < VITESSE_MS_MAX) or not (1.0 < vitesse_moyenne < VITESSE_MS_MAX):
        return None

    index = vitesse_finale / vitesse_moyenne
    if index >= ACCEL_SEUIL_HAUT:
        label = "accelere"
    elif index <= ACCEL_SEUIL_BAS:
        label = "faiblit"
    else:
        label = "regulier"

    return {
        "acceleration_index": round(index, 3),
        "acceleration_label": label,
        "vitesse_finale_ms": round(vitesse_finale, 2),
        "vitesse_moyenne_ms": round(vitesse_moyenne, 2),
    }


# Clés de features exposées (ordre/présence garantis pour aligner train/inférence).
DYNAMICS_FEATURE_KEYS = (
    "dyn_taux_accelere",
    "dyn_taux_faiblit",
    "dyn_finit_fort",
    "dyn_nb_data",
    "dyn_reduction_km_best",
    "dyn_reduction_km_moy",
)


def aggregate_dynamics(rows) -> dict:
    """
    Agrège les signaux de dynamique sur l'historique récent d'un cheval.

    rows : itérable de (acceleration_label, reduction_km), du plus récent au plus
    ancien. Chaque champ peut être None (donnée absente — JAMAIS fabriquée).

    Retourne TOUJOURS les mêmes clés (cf. DYNAMICS_FEATURE_KEYS) pour garantir un
    vecteur de features stable. Si aucune donnée : valeurs neutres + dyn_nb_data=0
    (le modèle sait ainsi que le signal est absent plutôt que de lire un faux 0).
    """
    rows = list(rows)
    accel_num = accel_den = 0.0
    faiblit_num = 0.0
    reductions = []

    for i, row in enumerate(rows):
        label = row[0] if len(row) > 0 else None
        reduction = row[1] if len(row) > 1 else None
        w = 0.9 ** i  # pondération récence
        if label in ("accelere", "regulier", "faiblit"):
            accel_den += w
            if label == "accelere":
                accel_num += w
            elif label == "faiblit":
                faiblit_num += w
        if isinstance(reduction, (int, float)) and reduction > 0:
            reductions.append(float(reduction))

    if accel_den > 0:
        taux_accelere = accel_num / accel_den
        taux_faiblit = faiblit_num / accel_den
    else:
        taux_accelere = taux_faiblit = 0.0

    nb_data = sum(
        1 for r in rows
        if (len(r) > 0 and r[0] in ("accelere", "regulier", "faiblit"))
        or (len(r) > 1 and isinstance(r[1], (int, float)) and r[1] > 0)
    )

    return {
        "dyn_taux_accelere": round(taux_accelere, 3),
        "dyn_taux_faiblit": round(taux_faiblit, 3),
        "dyn_finit_fort": round(taux_accelere - taux_faiblit, 3),
        "dyn_nb_data": nb_data,
        "dyn_reduction_km_best": round(min(reductions), 2) if reductions else 0.0,
        "dyn_reduction_km_moy": round(sum(reductions) / len(reductions), 2) if reductions else 0.0,
    }
