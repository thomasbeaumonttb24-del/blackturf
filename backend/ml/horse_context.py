"""Contexte cheval traçable pour le choix du ticket (audit 2026-09-23, section P0
« Les données de forme et d'équipement ne parviennent presque pas directement au
choix du ticket »).

Constat corrigé : `mise_calculator.generer_plan` ne transmettait au générateur de
candidats (`combo_bets.enumerate_bet_candidates`) que numéro, nom, `proba_top1`,
`proba_top3`, `cote_pmu` et `value_bet` (ce dernier explicitement hors décision).
La forme récente, le terrain/distance, le jockey/driver, la ferrure, l'évolution
de cote/enjeux et la presse pouvaient influencer le classement *indirectement*
(en amont, dans les features du modèle), mais aucune décision de ticket ne citait
explicitement « ce cheval entre à cause de X, celui-ci sort à cause de Y ».

Ce module construit ce `horse_context` à partir du vecteur `features_ml` déjà
calculé (aucune nouvelle collecte, aucune donnée inventée) et calcule :
  - un état de disponibilité EXPLICITE par catégorie de signal (jamais un signal
    absent traité comme neutre silencieusement) ;
  - un score de PROFIL par cheval pour cette course, distinct de la cote et du
    rang modèle ;
  - des contributions/objections traçables par cheval pour un ticket candidat.

Vérification de remplissage réel en base (lecture seule, VPS, 23/09/2026, 4426
vecteurs `features_ml` des 7 derniers jours) avant de choisir quelles clés
utiliser — cf. AUDIT_CLASSEMENT_MISE_2026-09-23.md, section « Correctif local
suivant — horse_context » :
  - `opposition_quality` vaut exactement 0.5 (son repli) sur 96,8 % des vecteurs
    → NON utilisé dans le score (déjà signalé mort par l'audit avant correction
    des index positionnels ; le correctif de lecture par nom ne l'a pas encore
    rendu informatif en production). Conservé UNIQUEMENT à titre indicatif si
    présent et non égal au repli.
  - `terrain_code` et `distance_reelle_ratio` sont quasi invariants par course
    (le premier est le terrain DU JOUR, identique pour tous les chevaux de la
    course : il ne peut pas différencier deux chevaux de la même course) → non
    utilisés dans le score, gardés en métadonnée.
  - `premier_deferre` / `premier_deferre_trot` / `deferre_code` : présents et
    variables (5,9 % / 4,7 % à vrai, 3 codes distincts) mais l'audit lui-même
    (section « Ce que les surprises montrent ») a mesuré qu'un premier déferrage
    ne se traduit PAS par un meilleur taux de victoire chez les grosses cotes
    (3,45 % contre 4,15 %) : aucune direction causale établie. Ces signaux sont
    donc rapportés (disponibilité + valeur brute, utiles aux contributions et
    objections narratives) mais PONDÉRÉS À ZÉRO dans le score numérique — les
    inclure avec un signe arbitraire serait fabriquer une opinion, pas un score.
  - Les autres clés utilisées ci-dessous ont une vraie distribution vérifiée
    (dizaines à milliers de valeurs distinctes, cf. audit) et sont donc traitées
    comme des signaux réels, pas des replis silencieux.

Le score et ses poids sont des heuristiques déclarées, choisies AVANT de lancer
l'ablation ci-dessous (aucun réglage a posteriori sur les résultats) — cf.
`backend/tests/test_horse_context.py` et le rapport d'ablation dans l'audit.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

HORSE_CONTEXT_VERSION = "1.0"

# Clés lues telles que produites par `ml.features.py` (aucune nouvelle collecte).
# Chaque entrée : (clé, catégorie). Une catégorie peut agréger plusieurs clés.
_FORME_KEYS = ("recent_win_rate", "forme_tendance")
_TERRAIN_DISTANCE_KEYS = ("pref_terrain_actuel", "pref_distance_actuelle")
_JOCKEY_DRIVER_KEYS = (
    "jockey_taux_victoire_global", "jockey_roi", "entraineur_taux_global",
    "combo_jockey_entraineur",
)
_COTE_ENJEUX_KEYS = ("mouvement_30min", "decote_detectee", "spi_score",
                     "pool_gagnant_evolution")
_PRESSE_KEYS = ("presse_score_borda", "pronostic_expert_rang")
# Ferrure : rapportée mais non pondérée dans le score (cf. docstring ci-dessus).
_FERRURE_KEYS = ("deferre_code", "premier_deferre", "premier_deferre_trot")

# Clés explicitement écartées du score car race-wide (ne différencient pas les
# chevaux d'une même course) ou mortes en production au moment du contrôle.
_EXCLUDED_FROM_SCORE = ("terrain_code", "distance_reelle_ratio", "opposition_quality")

# Âge maximal d'un vecteur features_ml au-delà duquel la donnée est marquée
# "périmée" (mais toujours utilisée : périmé n'est pas indisponible).
STALE_AFTER_MINUTES = 24 * 60


def _f(feats: dict, key: str) -> Optional[float]:
    v = feats.get(key)
    if v is None:
        return None
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return None
    if fv != fv:  # NaN
        return None
    return fv


def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


@dataclass
class SignalCategory:
    """Un groupe de signaux (ex. forme récente) pour un cheval donné."""
    disponible: bool
    valeurs_brutes: dict = field(default_factory=dict)
    sous_score: Optional[float] = None       # dans [-1, 1], None si indisponible
    motif_indisponible: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "disponible": self.disponible,
            "valeurs_brutes": self.valeurs_brutes,
            "sous_score": round(self.sous_score, 4) if self.sous_score is not None else None,
            "motif_indisponible": self.motif_indisponible,
        }


def _score_forme(feats: dict) -> SignalCategory:
    rwr = _f(feats, "recent_win_rate")
    tend = _f(feats, "forme_tendance")
    brut = {k: feats.get(k) for k in _FORME_KEYS if feats.get(k) is not None}
    if rwr is None and tend is None:
        return SignalCategory(False, brut, None, "recent_win_rate et forme_tendance absents")
    parts = []
    if rwr is not None:
        # Population observée (7j, VPS) : moyenne ~0.09, buckets 0/0.2/.../0.8.
        parts.append(_clip((rwr - 0.09) / 0.30))
    if tend is not None:
        # forme_tendance déjà borné [-1, 1] en production (vérifié).
        parts.append(_clip(tend))
    return SignalCategory(True, brut, sum(parts) / len(parts))


def _score_terrain_distance(feats: dict) -> SignalCategory:
    pt = _f(feats, "pref_terrain_actuel")
    pd = _f(feats, "pref_distance_actuelle")
    brut = {k: feats.get(k) for k in _TERRAIN_DISTANCE_KEYS if feats.get(k) is not None}
    if pt is None and pd is None:
        return SignalCategory(False, brut, None, "pref_terrain_actuel et pref_distance_actuelle absents")
    parts = []
    for v in (pt, pd):
        if v is not None:
            parts.append(_clip(2.0 * v - 1.0))
    return SignalCategory(True, brut, sum(parts) / len(parts))


def _score_jockey_driver(feats: dict) -> SignalCategory:
    jw = _f(feats, "jockey_taux_victoire_global")
    jroi = _f(feats, "jockey_roi")
    etx = _f(feats, "entraineur_taux_global")
    combo = _f(feats, "combo_jockey_entraineur")
    brut = {k: feats.get(k) for k in _JOCKEY_DRIVER_KEYS if feats.get(k) is not None}
    if jw is None and jroi is None and etx is None and combo is None:
        return SignalCategory(False, brut, None, "aucune statistique jockey/entraîneur")
    parts = []
    if jw is not None:
        parts.append(_clip((jw - 0.10) / 0.10))
    if etx is not None:
        parts.append(_clip((etx - 0.10) / 0.10))
    if jroi is not None:
        parts.append(_clip(jroi))
    if combo is not None:
        parts.append(_clip((combo - 0.03) * 3.0))
    return SignalCategory(True, brut, sum(parts) / len(parts))


def _score_cote_enjeux(feats: dict) -> SignalCategory:
    mvt = _f(feats, "mouvement_30min")
    dec = _f(feats, "decote_detectee")
    spi = _f(feats, "spi_score")
    pool = _f(feats, "pool_gagnant_evolution")
    brut = {k: feats.get(k) for k in _COTE_ENJEUX_KEYS if feats.get(k) is not None}
    if mvt is None and dec is None and spi is None and pool is None:
        return SignalCategory(False, brut, None, "aucun signal marché (mouvement/décote/SPI/pool)")
    parts = []
    if mvt is not None:
        # Cote qui BAISSE (mouvement négatif) = argent qui rentre = favorable.
        parts.append(_clip(-mvt))
    if dec is not None:
        parts.append(_clip(2.0 * dec - 1.0))
    if spi is not None:
        parts.append(_clip(2.0 * spi - 1.0))
    if pool is not None:
        parts.append(_clip(pool))
    return SignalCategory(True, brut, sum(parts) / len(parts))


def _score_presse(feats: dict) -> SignalCategory:
    borda = _f(feats, "presse_score_borda")
    rang = _f(feats, "pronostic_expert_rang")
    nb_experts = _f(feats, "nb_experts_presse")
    brut = {k: feats.get(k) for k in _PRESSE_KEYS if feats.get(k) is not None}
    if nb_experts is not None:
        brut["nb_experts_presse"] = nb_experts
    # nb_experts_presse == 0 pour ~24% des vecteurs (vérifié) : dans ce cas, la
    # course n'a simplement aucune couverture presse ce jour-là, ce n'est pas
    # une valeur neutre — c'est une absence de donnée à déclarer comme telle.
    if nb_experts is not None and nb_experts <= 0:
        return SignalCategory(False, brut, None, "aucun expert presse pour cette course")
    if borda is None and rang is None:
        return SignalCategory(False, brut, None, "presse_score_borda et pronostic_expert_rang absents")
    parts = []
    if borda is not None:
        parts.append(_clip(2.0 * borda - 1.0))
    if rang is not None:
        parts.append(_clip((6.0 - rang) / 5.0))
    return SignalCategory(True, brut, sum(parts) / len(parts))


def _report_ferrure(feats: dict) -> SignalCategory:
    """Rapportée pour la traçabilité (contributions/objections narratives) mais
    jamais incluse dans `profil_score` : aucune direction causale établie (cf.
    docstring du module) — un signe arbitraire ici fabriquerait une opinion.
    """
    brut = {k: feats.get(k) for k in _FERRURE_KEYS if feats.get(k) is not None}
    disponible = any(feats.get(k) is not None for k in _FERRURE_KEYS)
    return SignalCategory(disponible, brut, None,
                          None if disponible else "deferre_code/premier_deferre absents")


_SCORED_CATEGORIES = {
    "forme_recente": _score_forme,
    "terrain_distance": _score_terrain_distance,
    "jockey_driver": _score_jockey_driver,
    "cote_enjeux": _score_cote_enjeux,
    "presse": _score_presse,
}


def build_horse_context(feats: Optional[dict], computed_at: Optional[datetime] = None,
                        now: Optional[datetime] = None) -> dict:
    """Construit le `horse_context` d'un cheval pour la course en cours.

    `feats` : le dict `features_ml.features` de ce cheval (peut être None/vide
    si aucune feature n'a été calculée — dans ce cas TOUTES les catégories sont
    marquées indisponibles, jamais remplies par une valeur neutre par défaut).
    """
    feats = feats or {}
    now = now or datetime.now(timezone.utc)

    categories = {name: fn(feats) for name, fn in _SCORED_CATEGORIES.items()}
    ferrure = _report_ferrure(feats)

    scores_dispo = [c.sous_score for c in categories.values() if c.disponible]
    profil_score = sum(scores_dispo) / len(scores_dispo) if scores_dispo else None
    qualite_donnee = len(scores_dispo) / len(categories)

    age_minutes = None
    perime = None
    if computed_at is not None:
        ca = computed_at if computed_at.tzinfo else computed_at.replace(tzinfo=timezone.utc)
        age_minutes = max(0.0, (now - ca).total_seconds() / 60.0)
        perime = age_minutes > STALE_AFTER_MINUTES

    return {
        "version": HORSE_CONTEXT_VERSION,
        "as_of": computed_at.isoformat() if computed_at else None,
        "age_minutes": round(age_minutes, 1) if age_minutes is not None else None,
        "perime": perime,
        "signaux": {name: cat.to_dict() for name, cat in categories.items()},
        "ferrure": ferrure.to_dict(),
        "profil_score": round(profil_score, 4) if profil_score is not None else None,
        "qualite_donnee": round(qualite_donnee, 4),
    }


def build_horse_contexts_map(rows) -> dict:
    """`rows` : itérable de (numero, features_dict, computed_at). Retourne
    {numero: horse_context}. Un numéro sans features produit un contexte
    entièrement indisponible (jamais silencieusement absent de la map)."""
    out: dict = {}
    now = datetime.now(timezone.utc)
    for numero, feats, computed_at in rows:
        try:
            n = int(numero)
        except (TypeError, ValueError):
            continue
        out[n] = build_horse_context(feats, computed_at, now=now)
    return out


# ── Traçabilité par ticket candidat ─────────────────────────────────────────

_LIBELLES = {
    "forme_recente": "forme récente",
    "terrain_distance": "terrain/distance",
    "jockey_driver": "jockey/entraîneur",
    "cote_enjeux": "évolution cote/enjeux",
    "presse": "presse",
}

_SEUIL_NOTABLE = 0.15


def _raisons_cheval(numero: int, ctx: Optional[dict]) -> tuple[list[str], list[str]]:
    """Contributions/objections d'UN cheval à partir de son horse_context.
    Retourne (contributions, objections) — jamais de texte narratif décoratif :
    chaque item cite la catégorie et la valeur qui le motive.
    """
    contributions: list[str] = []
    objections: list[str] = []
    if not ctx:
        return contributions, ["contexte indisponible (aucune feature calculée)"]
    for cat, data in (ctx.get("signaux") or {}).items():
        label = _LIBELLES.get(cat, cat)
        if not data.get("disponible"):
            objections.append(f"{label} : indisponible ({data.get('motif_indisponible') or 'donnée absente'})")
            continue
        s = data.get("sous_score")
        if s is None:
            continue
        if s >= _SEUIL_NOTABLE:
            contributions.append(f"{label} favorable ({s:+.2f})")
        elif s <= -_SEUIL_NOTABLE:
            objections.append(f"{label} défavorable ({s:+.2f})")
    ferrure = ctx.get("ferrure") or {}
    if ferrure.get("disponible"):
        vb = ferrure.get("valeurs_brutes") or {}
        if vb.get("premier_deferre") or vb.get("premier_deferre_trot"):
            # Signalé, non pondéré (cf. docstring) : c'est une INFORMATION, pas
            # une contribution ni une objection tranchée.
            contributions.append("premier ferrage signalé (effet non établi, cf. audit — non pondéré)")
    if ctx.get("perime"):
        objections.append(f"données périmées (âge {ctx.get('age_minutes')} min)")
    return contributions, objections


def annotate_candidates_with_traceability(cands: list[dict], horse_contexts: dict,
                                          preds: Optional[list[dict]] = None) -> list[dict]:
    """Attache à chaque candidat une clé additive `contexte_traceabilite` :
    contributions/objections par cheval du ticket, et le(s) meilleur(s) cheval
    (par `profil_score`) écarté de ce ticket parmi les partants de la course.

    Modifie `cands` EN PLACE et le retourne. N'écrit aucune autre clé existante
    (`niveau`, `type_pari`, `chevaux`, `proba_gain`, `ev`, ... restent intacts) :
    n'influence donc PAS la sélection/gating faite ailleurs (`_select_conviction`,
    `enumerate_bet_candidates`) — purement descriptif, additif.
    """
    if not cands or not horse_contexts:
        return cands

    tous_numeros = set(horse_contexts.keys())
    if preds:
        for p in preds:
            try:
                tous_numeros.add(int(p["numero"]))
            except (TypeError, ValueError, KeyError):
                pass

    for c in cands:
        chevaux = c.get("chevaux") or []
        numeros_ticket = set()
        par_cheval = []
        for h in chevaux:
            try:
                n = int(h["numero"])
            except (TypeError, ValueError, KeyError):
                continue
            numeros_ticket.add(n)
            ctx = horse_contexts.get(n)
            contributions, objections = _raisons_cheval(n, ctx)
            par_cheval.append({
                "numero": n,
                "profil_score": (ctx or {}).get("profil_score"),
                "qualite_donnee": (ctx or {}).get("qualite_donnee"),
                "contributions": contributions,
                "objections": objections,
            })

        # Chevaux non retenus dans CE ticket mais avec un profil_score notable
        # supérieur au pire cheval retenu → objection traçable au ticket, pas
        # une raison de le rejeter automatiquement (la cote/le format du pari
        # peuvent justifier ce choix ; on le rend visible, pas décisif).
        scores_retenus = [pc["profil_score"] for pc in par_cheval if pc["profil_score"] is not None]
        pire_retenu = min(scores_retenus) if scores_retenus else None
        ecartes_notables = []
        if pire_retenu is not None:
            for n in sorted(tous_numeros - numeros_ticket):
                ctx = horse_contexts.get(n)
                ps = (ctx or {}).get("profil_score")
                if ps is not None and ps - pire_retenu >= _SEUIL_NOTABLE:
                    ecartes_notables.append({"numero": n, "profil_score": ps})

        c["contexte_traceabilite"] = {
            "version": HORSE_CONTEXT_VERSION,
            "chevaux": par_cheval,
            "ecartes_a_profil_superieur": ecartes_notables,
        }
    return cands
