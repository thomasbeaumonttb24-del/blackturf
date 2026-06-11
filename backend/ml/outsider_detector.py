"""
outsider_detector.py — Détection des COURSES À OUTSIDER (grosses cotes jouables).

Objectif : identifier les courses où une grosse cote a une vraie chance de
rentrer — et lesquelles — pour orienter le profil risqué et l'affichage.

Signaux 100% mesurés (aucune invention) :
  1. OUVERTURE du champ : marché peu concentré (HHI bas), favori fragile
     (écart proba top1-top2 faible), champ fourni → plus de place pour une surprise.
  2. DIVERGENCE modèle/marché : le modèle place un ou plusieurs outsiders
     (cote 8-40) nettement au-dessus de leur proba implicite (edge > 0).
  3. BASE HISTORIQUE : taux de surprises réel (gagnant à proba < 20%) mesuré sur
     race_learning_log par discipline × taille de champ — la fréquence à laquelle
     ce TYPE de course produit des surprises.

Le score course ∈ [0,1] combine ces signaux ; les candidats outsiders sont
listés avec leurs raisons réelles. Pas de candidat à edge → pas de course à
outsider, quel que soit le « feeling ».
"""
from __future__ import annotations

import re
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

OUTSIDER_COTE_MIN = 8.0
OUTSIDER_COTE_MAX = 40.0
SCORE_SEUIL_COURSE = 0.55     # au-delà : course "à outsider"

_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF\U00002190-\U000021FF️✅⚡⤵⤴✨]"
)


def _strip(s) -> str:
    """Retire emojis + espaces superflus (affichage propre, aligné sur narrative)."""
    if not isinstance(s, str):
        return s
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", s)).strip()


def _field_bucket(nb: int) -> str:
    if nb >= 14:
        return "grand"
    if nb >= 10:
        return "moyen"
    return "petit"


def compute_outsider_score(predictions: list[dict],
                           surprise_rate: float | None = None) -> dict:
    """Score « course à outsider » + candidats. Fonction PURE (testable sans DB).

    predictions : [{numero, nom, proba_top1, cote_pmu}] (cote > 1).
    surprise_rate : taux de surprises historique du type de course (None si inconnu).
    """
    parts = [p for p in predictions
             if (p.get("cote_pmu") or 0) > 1.0 and (p.get("proba_top1") or 0) > 0]
    if len(parts) < 6:
        return {"score": 0.0, "course_a_outsider": False, "candidats": [], "signaux": []}

    cotes = [float(p["cote_pmu"]) for p in parts]
    p1 = [float(p["proba_top1"]) for p in parts]
    implied_raw = [1.0 / c for c in cotes]
    s_impl = sum(implied_raw)
    implied = [x / s_impl for x in implied_raw]      # overround retiré

    signaux: list[str] = []

    # 1. Ouverture du champ (marché) — HHI bas = course ouverte.
    hhi = sum(x * x for x in implied)
    # HHI ~1/n si parfaitement ouvert ; >0.15 = favori écrasant.
    ouverture = max(0.0, min(1.0, (0.18 - hhi) / 0.10))
    sorted_impl = sorted(implied, reverse=True)
    ecart_top2 = sorted_impl[0] - sorted_impl[1] if len(sorted_impl) >= 2 else 1.0
    fragilite_favori = max(0.0, min(1.0, (0.12 - ecart_top2) / 0.12))
    if ouverture > 0.5:
        signaux.append(f"Champ ouvert : aucun favori écrasant (HHI {hhi:.2f}).")
    if fragilite_favori > 0.5:
        signaux.append(f"Favori fragile : seulement {ecart_top2*100:.0f} pt d'écart avec le 2e au marché.")

    # 2. Outsiders à edge (modèle > marché) — cote 8-40.
    candidats = []
    for i, p in enumerate(parts):
        c = cotes[i]
        if not (OUTSIDER_COTE_MIN <= c <= OUTSIDER_COTE_MAX):
            continue
        edge = p1[i] - implied[i]
        if edge <= 0.005:
            continue
        ratio = p1[i] / max(implied[i], 1e-6)
        exp = p.get("explanation", {}) or {}
        p3 = float(p.get("proba_top3") or exp.get("proba_top3") or 0)
        # Raison #1 : la VALEUR marché (cœur du signal outsider).
        raisons = [
            f"Le modèle lui donne {p1[i]*100:.1f}% de victoire et {p3*100:.0f}% de placé, "
            f"le marché seulement {implied[i]*100:.1f}% (×{ratio:.1f}) — grosse cote sous-estimée par le public."
        ]
        # Raisons #2+ : les FACTEURS POSITIFS réels qui appuient le choix (forme, ELO,
        # terrain, marché, pedigree…) → justification concrète, pas juste l'edge.
        pos = exp.get("facteurs_positifs", []) or []
        for f in pos[:4]:
            lbl = _strip(f.get("label", "")); det = _strip(f.get("detail", ""))
            if lbl:
                raisons.append(f"{lbl} : {det}" if det else lbl)
        negs = exp.get("facteurs_negatifs", []) or []
        # Points de vigilance (honnêteté : un outsider garde des risques) — sans le
        # disqualifier (il reste à valeur), on les signale.
        vigilance = [f"{_strip(n.get('label',''))} : {_strip(n.get('detail',''))}".strip(" :")
                     for n in negs[:2] if n.get("label")]
        justification = (
            f"N°{p.get('numero')} {p.get('nom') or p.get('nom_cheval') or ''} (cote {c:.1f}) — "
            f"OUTSIDER À VALEUR : le modèle l'estime {ratio:.1f}× au-dessus du marché "
            f"({p1[i]*100:.1f}% vs {implied[i]*100:.1f}% de victoire), porté par "
            f"{len(pos)} signal(aux) favorable(s)"
            + (f" malgré {len(negs)} point(s) de vigilance" if negs else "")
            + f". À jouer en PETITE mise (gros rapport pour un risque assumé)."
        )
        candidats.append({
            "numero": p.get("numero"),
            "nom": p.get("nom") or p.get("nom_cheval") or "",
            "cote": round(c, 1),
            "rang_predit": p.get("rang_predit"),
            "proba_modele": round(p1[i], 4),
            "proba_top3": round(p3, 4),
            "proba_marche": round(implied[i], 4),
            "edge": round(edge, 4),
            "ratio_valeur": round(ratio, 2),
            "verdict": exp.get("verdict"),
            "confiance": round(float(exp.get("confiance_composite") or 0), 3),
            "facteurs_positifs": [
                {"label": _strip(f.get("label", "")), "detail": _strip(f.get("detail", "")),
                 "categorie": f.get("categorie")}
                for f in pos[:5]
            ],
            "points_vigilance": vigilance,
            "raisons": raisons,
            "justification": justification,
        })
    candidats.sort(key=lambda x: x["edge"], reverse=True)
    candidats = candidats[:3]
    edge_force = min(1.0, sum(c["edge"] for c in candidats) * 12) if candidats else 0.0
    if candidats:
        best = candidats[0]
        signaux.append(
            f"N°{best['numero']} {best['nom']} (cote {best['cote']}) : le modèle le voit "
            f"nettement au-dessus du marché."
        )

    # 3. Base historique des surprises pour ce type de course.
    base = 0.5
    if surprise_rate is not None:
        # taux typique ~0.20-0.30 ; 0.35+ = type de course très piégeux.
        base = max(0.0, min(1.0, (surprise_rate - 0.10) / 0.30))
        if surprise_rate >= 0.30:
            signaux.append(f"Historiquement, {surprise_rate*100:.0f}% de surprises sur ce type de course.")

    # Combinaison : SANS candidat à edge, pas de course à outsider (peu importe
    # l'ouverture) — on ne recommande jamais une grosse cote sans valeur détectée.
    if not candidats:
        score = round(0.25 * (0.6 * ouverture + 0.4 * fragilite_favori), 3)
        return {"score": score, "course_a_outsider": False, "candidats": [], "signaux": signaux}

    score = (0.45 * edge_force + 0.25 * ouverture + 0.15 * fragilite_favori + 0.15 * base)
    score = round(float(max(0.0, min(1.0, score))), 3)
    return {
        "score": score,
        "course_a_outsider": score >= SCORE_SEUIL_COURSE,
        "candidats": candidats,
        "signaux": signaux,
    }


async def get_surprise_rate(session: AsyncSession, discipline: str | None,
                            nb_partants: int | None) -> float | None:
    """Taux de surprises RÉEL (race_learning_log.was_surprise) pour la même
    discipline × taille de champ. None si < 30 courses (pas d'invention)."""
    try:
        r = (await session.execute(text("""
            SELECT COUNT(*) FILTER (WHERE was_surprise)::float / NULLIF(COUNT(*), 0), COUNT(*)
            FROM race_learning_log
            WHERE (:disc IS NULL OR lower(discipline) = lower(:disc))
              AND nb_partants IS NOT NULL
              AND (CASE WHEN nb_partants >= 14 THEN 'grand'
                        WHEN nb_partants >= 10 THEN 'moyen' ELSE 'petit' END) = :bucket
        """), {"disc": discipline, "bucket": _field_bucket(int(nb_partants or 10))})).first()
        if r and r[1] and int(r[1]) >= 30 and r[0] is not None:
            return float(r[0])
    except Exception as e:  # noqa: BLE001
        log.warning("outsider_detector.surprise_rate_failed", err=str(e)[:120])
    return None


async def detect_for_course(session: AsyncSession, course_id: str,
                            predictions: list[dict], discipline: str | None,
                            nb_partants: int | None) -> dict:
    """Détection complète pour une course (score + candidats + base historique)."""
    rate = await get_surprise_rate(session, discipline, nb_partants)
    result = compute_outsider_score(predictions, surprise_rate=rate)
    result["taux_surprises_historique"] = round(rate, 3) if rate is not None else None
    return result
