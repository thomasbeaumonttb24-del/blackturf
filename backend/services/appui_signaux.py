"""Appui des signaux — POURQUOI ce cheval entre dans le plan, au-delà de son rang.

Demande produit du 2026-10-07 : un cheval ne doit pas entrer dans un plan « parce
que l'algo le classe 2ᵉ » ou être joué placé « parce qu'il est 4ᵉ ». Son choix doit
s'appuyer sur des faits mesurés AVANT la course :

  1. ÉCART DE PRIX — la chance du modèle contre la chance que le marché lui donne
     (cote PMU dé-viguée sur le champ). Un cheval que le PMU paie plus que sa
     chance est un pari à valeur ; un cheval que le marché paie moins que sa chance
     est un don au prélèvement, quel que soit son rang.
  2. DÉTECTION D'OUTSIDER — chance de place estimée par le cerveau dédié aux
     grosses cotes (`ml.outsider_brain`, registre `outsider_signaux`). L'outsider
     moyen coté 15+ se place 13 % du temps ; un outsider retenu, 27 à 35 %.
  3. PROFIL DU CHEVAL — `ml.horse_context` : forme récente, terrain/distance,
     jockey/entraîneur, argent qui rentre (cote qui baisse, enjeux), presse.

Le résultat par cheval est un score borné dans [-1, 1] et des phrases qui citent
la valeur qui les motive. Aucune donnée inventée : une composante absente est
ÉCARTÉE (jamais remplacée par une valeur neutre qui pèserait dans la moyenne).

Le score n'est PAS une porte : la promesse « chaque course est jouée » et les
tranches de rapport des profils restent intactes. C'est un multiplicateur de
conviction (borné) qui fait préférer, à rang égal, le pari le mieux appuyé.
"""
from __future__ import annotations

import math
from typing import Optional

# Poids des composantes (somme 1 sur les composantes disponibles, renormalisée).
POIDS_VALEUR = 0.50
POIDS_PROFIL = 0.35
POIDS_OUTSIDER = 0.15

# Écart de prix : ratio chance modèle / chance marché. ×1,6 → +1 ; ÷1,6 → −1.
_RATIO_PLEIN = 1.6
# Seuils de phrase : en dessous, l'écart n'est pas assez net pour être cité.
_RATIO_CITE_POUR = 1.10
_RATIO_CITE_CONTRE = 0.85
# Profil : sous-score de catégorie à partir duquel on la cite.
_SOUS_SCORE_CITE = 0.15
# Profil : au moins 2 catégories sur 5 renseignées pour compter.
_QUALITE_PROFIL_MIN = 0.40
# Outsider : taux de place de l'outsider moyen (cote ≥ 15) et plage utile.
_OUTSIDER_TAUX_BASE = 0.13
_OUTSIDER_PLAGE = 0.15

# Multiplicateur de conviction d'un candidat : 1 + k × appui, borné.
K_SIMPLE = 0.30          # pari à un seul cheval : son appui décide davantage
K_COMBINE = 0.20
MULT_MIN = 0.75
MULT_MAX = 1.30

_LIBELLES_PROFIL = {
    "forme_recente": "forme récente",
    "terrain_distance": "terrain et distance",
    "jockey_driver": "jockey/entraîneur",
    "cote_enjeux": "argent qui rentre",
    "presse": "presse",
}


def _num(x) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def _clip(v: float, lo: float = -1.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def chances_marche(preds: list[dict]) -> dict[int, float]:
    """Chance de victoire implicite du marché, dé-viguée sur les chevaux COTÉS.

    Un cheval sans cote réelle n'a pas de chance de marché (absent du dict) :
    on ne lui en invente pas une.
    """
    inv: dict[int, float] = {}
    for p in preds:
        c = _num(p.get("cote_pmu"))
        if c is None or c <= 1.0 or p.get("numero") is None:
            continue
        inv[int(p["numero"])] = 1.0 / c
    tot = sum(inv.values())
    if tot <= 0:
        return {}
    return {n: v / tot for n, v in inv.items()}


def appui_par_cheval(preds: list[dict], horse_contexts: Optional[dict] = None) -> dict[int, dict]:
    """Score d'appui et justifications de chaque partant.

    `preds` : numero, proba_top1, cote_pmu et, optionnellement, `outsider`
    ({chance_place, niveau}) — le signal figé du registre des outsiders.
    Retour : {numero: {"score", "pour": [...], "contre": [...], "composantes": {...},
    "ratio_prix", "cote_juste"}}.
    """
    q = chances_marche(preds)
    # Chance du modèle renormalisée sur le champ (Σ = 1), comme celle du marché :
    # on compare deux distributions, pas une proba brute à une cote vigée.
    _p = {int(p["numero"]): _num(p.get("proba_top1")) for p in preds
          if p.get("numero") is not None and not p.get("non_partant")}
    _tot = sum(v for v in _p.values() if v and v > 0)
    pm = {n: v / _tot for n, v in _p.items() if v and v > 0} if _tot > 0 else {}
    out: dict[int, dict] = {}
    for p in preds:
        if p.get("numero") is None or p.get("non_partant"):
            continue
        n = int(p["numero"])
        pour: list[str] = []
        contre: list[str] = []
        comp: dict[str, float] = {}

        # 1. Écart de prix modèle / marché.
        p1 = pm.get(n)
        cote = _num(p.get("cote_pmu"))
        ratio = None
        cote_juste = None
        if p1 and n in q and q[n] > 0:
            ratio = p1 / q[n]
            cote_juste = 1.0 / p1
            comp["valeur"] = _clip(math.log(ratio) / math.log(_RATIO_PLEIN))
            if ratio >= _RATIO_CITE_POUR:
                pour.append(f"sous-coté : {p1 * 100:.0f} % de chance de gagner selon le modèle "
                            f"contre {q[n] * 100:.0f} % selon le marché (cote {cote:.1f})")
            elif ratio <= _RATIO_CITE_CONTRE:
                contre.append(f"sur-joué : {p1 * 100:.0f} % de chance selon le modèle contre "
                              f"{q[n] * 100:.0f} % selon le marché (cote {cote:.1f})")

        # 2. Détection d'outsider (registre figé du cerveau dédié).
        o = p.get("outsider") or {}
        ch = _num(o.get("chance_place"))
        if ch is not None:
            comp["outsider"] = _clip((ch - _OUTSIDER_TAUX_BASE) / _OUTSIDER_PLAGE, 0.0, 1.0)
            pour.append(f"outsider détecté{' (fort)' if o.get('niveau') == 'fort' else ''} : "
                        f"{ch * 100:.0f} % de chance de se placer, contre "
                        f"{_OUTSIDER_TAUX_BASE * 100:.0f} % pour un outsider moyen")

        # 3. Profil du cheval (forme, terrain, jockey, marché, presse).
        ctx = (horse_contexts or {}).get(n) or {}
        ps = _num(ctx.get("profil_score"))
        if ps is not None and float(ctx.get("qualite_donnee") or 0.0) >= _QUALITE_PROFIL_MIN:
            comp["profil"] = _clip(ps)
            for cat, data in (ctx.get("signaux") or {}).items():
                s = _num((data or {}).get("sous_score"))
                if s is None or not data.get("disponible"):
                    continue
                lib = _LIBELLES_PROFIL.get(cat, cat)
                if cat == "cote_enjeux":
                    mvt = _num((data.get("valeurs_brutes") or {}).get("mouvement_30min"))
                    if mvt is not None and mvt >= 0.05:
                        pour.append(f"l'argent rentre : cote en baisse de {mvt * 100:.0f} % "
                                    "dans la dernière demi-heure")
                        continue
                    if mvt is not None and mvt <= -0.10:
                        contre.append(f"la cote dérive de {-mvt * 100:.0f} % dans la dernière "
                                      "demi-heure (le marché s'en détourne)")
                        continue
                if s >= _SOUS_SCORE_CITE:
                    pour.append(f"{lib} favorable")
                elif s <= -_SOUS_SCORE_CITE:
                    contre.append(f"{lib} défavorable")

        poids = {"valeur": POIDS_VALEUR, "profil": POIDS_PROFIL, "outsider": POIDS_OUTSIDER}
        tot = sum(poids[k] for k in comp)
        score = sum(poids[k] * v for k, v in comp.items()) / tot if tot > 0 else None
        neutre = None
        if ratio is not None and not pour and not contre:
            neutre = (f"prix conforme à sa chance ({p1 * 100:.0f} % selon le modèle, "
                      f"{q[n] * 100:.0f} % selon le marché) : aucun signal ne le distingue")
        out[n] = {
            "score": round(score, 4) if score is not None else None,
            "neutre": neutre,
            "pour": pour,
            "contre": contre,
            "composantes": {k: round(v, 4) for k, v in comp.items()},
            "ratio_prix": round(ratio, 4) if ratio is not None else None,
            "cote_juste": round(cote_juste, 2) if cote_juste is not None else None,
        }
    return out


def appui_candidat(numeros: list[int], appui: dict[int, dict]) -> Optional[float]:
    """Appui d'un pari : moitié moyenne, moitié maillon faible.

    Une combinaison ne vaut que par son cheval le moins appuyé : un Trio dont un
    pied a le marché et les signaux contre lui ne doit pas profiter de l'appui des
    deux autres. Sans aucun cheval noté → None (aucun effet).
    """
    s = [appui[n]["score"] for n in numeros if n in appui and appui[n].get("score") is not None]
    if not s:
        return None
    return 0.5 * (sum(s) / len(s)) + 0.5 * min(s)


def multiplicateur_appui(numeros: list[int], appui: dict[int, dict]) -> float:
    """Multiplicateur de conviction borné [MULT_MIN, MULT_MAX] ; 1.0 sans signal."""
    a = appui_candidat(numeros, appui)
    if a is None:
        return 1.0
    k = K_SIMPLE if len(numeros) == 1 else K_COMBINE
    return round(_clip(1.0 + k * a, MULT_MIN, MULT_MAX), 4)


async def charger_outsiders(session, course_id: str) -> dict[int, dict]:
    """Signaux ACTIFS du détecteur d'outsiders pour une course : {numero: {chance_place,
    niveau}}. Le registre est figé à T-10 (cf. services.outsiders), comme le plan.
    Table absente ou lecture impossible → {} (composante écartée, jamais inventée)."""
    from sqlalchemy import text
    try:
        # Point de sauvegarde : un échec de lecture n'annule pas la transaction de
        # l'appelant (le gel des plans écrit dans la même session).
        async with session.begin_nested():
            rows = (await session.execute(text("""
                SELECT numero, chance_place, niveau FROM outsider_signaux
                WHERE course_id = :cid AND actif
            """), {"cid": course_id})).all()
    except Exception:  # noqa: BLE001 — base sans la table (tests, ancienne migration)
        return {}
    out: dict[int, dict] = {}
    for numero, chance, niveau in rows:
        try:
            out[int(numero)] = {"chance_place": float(chance), "niveau": niveau}
        except (TypeError, ValueError):
            continue
    return out
