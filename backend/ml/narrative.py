"""
Générateur de narrative IA — BlackTurf.
Produit une analyse en langage naturel pour chaque course et recommandation.

Sources d'information :
  - Features ML par partant (SHAP → contribution positive/négative)
  - Prédictions + value bets + signaux marché
  - Contexte course (terrain, discipline, distance, pénétromètre)
  - Historique des chevaux (running style, ELO trend)
  - Claude API pour la partie langage naturel

L'analyse structurée (JSON) est générée en interne.
Le résumé narratif passe par Claude API (claude-haiku pour la vitesse + coût).

Hiérarchie des explications (du plus au moins important) :
  1. Signaux marché (SPI, gap Betfair, steam Betclic) — argent intelligent
  2. Forme récente (tendance ELO, dernières courses)
  3. Adéquation course (class drop, terrain, distance)
  4. Facteurs jockey/entraîneur (association, retour spécialiste)
  5. Signaux complémentaires (draw bias, équipement, bounce)
"""
import json
import math
import re
import structlog
from typing import Optional
import httpx

from api.config import get_settings

log = structlog.get_logger(module="narrative")
settings = get_settings()

# Retrait des emojis (look pro, épuré). Couvre les plages emoji + symboles usuels.
_EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF\U00002600-\U000027BF\U00002B00-\U00002BFF"
    "\U0001F1E6-\U0001F1FF\U00002190-\U000021FF️✅⚡⤵⤴✨]"
)


def _strip_emoji(s) -> str:
    """Retire les emojis d'une chaîne et nettoie les espaces (pro/épuré)."""
    if not isinstance(s, str):
        return s
    return re.sub(r"\s{2,}", " ", _EMOJI_RE.sub("", s)).strip()


def _clean_labels(items: list) -> list:
    """Retire les emojis des champs label/detail d'une liste de signaux."""
    for it in items:
        if isinstance(it, dict):
            for k in ("label", "detail", "signal"):
                if k in it:
                    it[k] = _strip_emoji(it[k])
    return items


# ── Feature groups avec labels humains ──────────────────────────────────────
FEATURE_GROUPS = {
    # Signaux marché
    "steam_move_betclic":     ("Steam Betclic",    "Cote en forte baisse depuis l'ouverture"),
    "gap_pmu_betfair":        ("Gap PMU/Betfair",  "PMU surcoté vs marché efficient"),
    "spi_score":              ("SPI",               "Argent pro détecté (mouvement de cote)"),
    "mouvement_30min":        ("Mouvement cote",   "Cote PMU en baisse ces 30 dernières minutes"),
    "pool_gagnant_ratio":     ("Pool actif",       "Fort volume de paris sur ce cheval"),
    # Forme
    "forme_1_course":         ("Dernière course",  "Performance récente"),
    "forme_5_courses":        ("Forme 5 courses",  "Forme sur les 5 dernières sorties"),
    "forme_tendance":         ("Tendance",          "Progression ou régression"),
    "career_momentum":        ("Momentum carrière","Dynamique ELO long terme"),
    "regularite":             ("Régularité",        "Constance dans les performances"),
    # Adéquation course
    "class_drop_ratio":       ("Descente catégorie","Dotation inférieure aux habitudes"),
    "class_jump_score":       ("Classe",            "Rapport dotation vs habitudes"),
    "pref_terrain_actuel":    ("Terrain",           "Affinité avec le terrain du jour"),
    "penetrometre_coef":      ("Pénétromètre",      "Coefficient de sol officiel"),
    "pref_distance_actuelle": ("Distance",           "Performances à cette distance"),
    "running_style_terrain_fit": ("Style×Terrain", "Adéquation style de course et terrain"),
    "pace_conflict_score":    ("Conflit de rythme","Présence d'autres meneurs dans la course"),
    # ELO et force
    "elo_vs_moyenne":         ("Force relative",   "ELO vs moyenne du champ"),
    "elo_discipline":         ("Niveau discipline","Score ELO dans cette discipline"),
    "velocity_elo":           ("Progression ELO",  "Vitesse de progression récente"),
    # Jockey / entraîneur
    "asso_jockey_entraineur_taux": ("Duo J×E",   "Taux de victoire de l'association"),
    "jockey_forme_30j":       ("Jockey forme",    "Win rate jockey sur 30 jours"),
    "trainer_return_bonus":   ("Spécialiste retour","Entraîneur fort après longue absence"),
    "changement_jockey":      ("Changement jockey","Jockey différent de la dernière course"),
    # Draw / équipement
    "draw_bias_score":        ("Numéro de départ", "Avantage du numéro de départ"),
    "premier_deferre":        ("Déferré",          "Premiers défers = souvent positif"),
    "premieres_oeilleres":    ("Œillères",         "Premières œillères = souvent positif"),
    # Bounce / class
    "bounce_score":           ("Bounce factor",   "Rebond potentiel après course exceptionnelle"),
    "form_vs_career_rate":    ("Forme vs carrière","Surperformance récente vs moyenne carrière"),
}


def explain_prediction(features: dict, proba_top3: float, proba_top1: float,
                        vb: Optional[dict] = None) -> dict:
    """
    Génère une explication structurée des facteurs clés pour un partant.
    Retourne un dict avec les facteurs positifs et négatifs.
    """
    positifs = []
    negatifs = []
    alertes = []

    # ── Signaux marché (priorité max) ──────────────────────────────────────
    steam = features.get("steam_move_betclic", 0)
    if steam > 0.08:
        positifs.append({"feature": "steam_move_betclic", "label": "🔥 Steam Betclic",
                         "detail": f"Cote baissée de {steam*100:.0f}% depuis l'ouverture — argent pro",
                         "score": min(steam * 10, 1.0), "categorie": "marche"})

    gap_bf = features.get("gap_pmu_betfair", 0)
    if gap_bf > 0.10:
        positifs.append({"feature": "gap_pmu_betfair", "label": "🎯 Gap PMU/Betfair",
                         "detail": f"PMU surcoté de {gap_bf*100:.0f}% vs Betfair Exchange — value bet confirmé",
                         "score": min(gap_bf * 5, 1.0), "categorie": "marche"})
    elif gap_bf < -0.10:
        negatifs.append({"feature": "gap_pmu_betfair", "label": "⚠️ PMU sous-coté",
                         "detail": f"PMU {abs(gap_bf)*100:.0f}% moins favorable que Betfair — valeur faible",
                         "score": min(abs(gap_bf) * 5, 1.0), "categorie": "marche"})

    spi = features.get("spi_score", 0)
    if spi > 0.15:
        positifs.append({"feature": "spi_score", "label": "⚡ SPI actif",
                         "detail": f"Signal argent pro {spi:.2f} — forte baisse de cote détectée",
                         "score": spi, "categorie": "marche"})

    # ── Forme récente ──────────────────────────────────────────────────────
    f5 = features.get("forme_5_courses", 0.5)
    tendance = features.get("forme_tendance", 0)
    if f5 > 0.65:
        positifs.append({"feature": "forme_5_courses", "label": "🔥 Forme excellente",
                         "detail": f"Score de forme {f5:.0%} sur 5 dernières courses",
                         "score": f5, "categorie": "forme"})
    elif f5 < 0.35:
        negatifs.append({"feature": "forme_5_courses", "label": "📉 Forme basse",
                         "detail": f"Score de forme {f5:.0%} — performances décevantes récentes",
                         "score": 1 - f5, "categorie": "forme"})

    if tendance > 0.20:
        positifs.append({"feature": "forme_tendance", "label": "📈 En progression",
                         "detail": f"Tendance ascendante +{tendance:.2f} — cheval en montée de forme",
                         "score": min(tendance, 1), "categorie": "forme"})
    elif tendance < -0.20:
        negatifs.append({"feature": "forme_tendance", "label": "📉 En régression",
                         "detail": f"Tendance descendante {tendance:.2f} — performances en baisse",
                         "score": min(abs(tendance), 1), "categorie": "forme"})

    # ── Class drop ────────────────────────────────────────────────────────
    class_drop = features.get("class_drop_ratio", 1.0)
    if class_drop < 0.75:
        positifs.append({"feature": "class_drop_ratio", "label": "⬇️ Descente de catégorie",
                         "detail": f"Course {(1-class_drop)*100:.0f}% moins dotée qu'à l'habitude — avantage de classe",
                         "score": min((1 - class_drop) * 2, 1.0), "categorie": "classe"})
    elif class_drop > 1.40:
        negatifs.append({"feature": "class_drop_ratio", "label": "⬆️ Montée de catégorie",
                         "detail": f"Course {(class_drop-1)*100:.0f}% plus dotée qu'à l'habitude — défi",
                         "score": min((class_drop - 1) * 1.5, 1.0), "categorie": "classe"})

    # ── Terrain ───────────────────────────────────────────────────────────
    terrain_fit = features.get("pref_terrain_actuel", 0.5)
    rs_fit = features.get("running_style_terrain_fit", 0.5)
    pace_conflict = features.get("pace_conflict_score", 0)

    if terrain_fit > 0.65 and rs_fit > 0.6:
        positifs.append({"feature": "pref_terrain_actuel", "label": "🌿 Terrain idéal",
                         "detail": f"Excellent sur ce type de sol ({terrain_fit:.0%} win rate historique)",
                         "score": terrain_fit, "categorie": "conditions"})
    elif terrain_fit < 0.35:
        negatifs.append({"feature": "pref_terrain_actuel", "label": "🌧️ Terrain défavorable",
                         "detail": f"Performances médiocres sur ce sol ({terrain_fit:.0%})",
                         "score": 1 - terrain_fit, "categorie": "conditions"})

    if pace_conflict > 0.6:
        negatifs.append({"feature": "pace_conflict_score", "label": "⚔️ Conflit de rythme",
                         "detail": f"Plusieurs meneurs dans la course — guerre de vitesse probable",
                         "score": pace_conflict, "categorie": "conditions"})

    # ── ELO ──────────────────────────────────────────────────────────────
    elo_vs = features.get("elo_vs_moyenne", 0)
    if elo_vs > 50:
        positifs.append({"feature": "elo_vs_moyenne", "label": "💪 Supérieur au champ",
                         "detail": f"ELO {elo_vs:.0f} points au-dessus de la moyenne — domination potentielle",
                         "score": min(elo_vs / 200, 1.0), "categorie": "elo"})
    elif elo_vs < -50:
        negatifs.append({"feature": "elo_vs_moyenne", "label": "📉 Inférieur au champ",
                         "detail": f"ELO {abs(elo_vs):.0f} points sous la moyenne — challenge difficile",
                         "score": min(abs(elo_vs) / 200, 1.0), "categorie": "elo"})

    # ── Jockey / entraîneur ───────────────────────────────────────────────
    asso_taux = features.get("asso_jockey_entraineur_taux", 0)
    asso_nb = features.get("asso_jockey_entraineur_nb", 0)
    if asso_nb >= 5 and asso_taux > 0.25:
        positifs.append({"feature": "asso_jockey_entraineur_taux", "label": "🤝 Duo efficace",
                         "detail": f"Association J×E à {asso_taux*100:.0f}% ({asso_nb} courses ensemble)",
                         "score": min(asso_taux * 2, 1.0), "categorie": "professionnel"})

    changement_j = features.get("changement_jockey", 0)
    if changement_j:
        alertes.append({"label": "⚠️ Changement de jockey",
                        "detail": "Jockey différent de la dernière course — signal ambigu"})

    # ── Équipement ────────────────────────────────────────────────────────
    if features.get("premier_deferre", 0):
        positifs.append({"feature": "premier_deferre", "label": "🔧 Premiers défers",
                         "detail": "Mise au fer pour la première fois — souvent signe d'amélioration",
                         "score": 0.7, "categorie": "equipement"})
    if features.get("nouvelles_oeilleres", 0):
        positifs.append({"feature": "nouvelles_oeilleres", "label": "👓 Nouvelles œillères",
                         "detail": "Changement d'œillères — peut améliorer la concentration",
                         "score": 0.6, "categorie": "equipement"})

    # ── Bounce / draw ──────────────────────────────────────────────────────
    bounce = features.get("bounce_score", 0)
    if bounce > 0.3:
        alertes.append({"label": "🔄 Attention rebond",
                        "detail": f"Vient d'une course exceptionnelle — possible régression (bounce factor {bounce:.2f})"})

    draw = features.get("draw_bias_score", 0)
    if draw > 0.10:
        positifs.append({"feature": "draw_bias_score", "label": "🎲 Position favorable",
                         "detail": f"Numéro de départ historiquement favorable sur cet hippodrome",
                         "score": draw, "categorie": "conditions"})

    # Trier par score décroissant
    positifs.sort(key=lambda x: x["score"], reverse=True)
    negatifs.sort(key=lambda x: x["score"], reverse=True)

    # Composite confidence
    conf = features.get("composite_confidence", 0.5)

    return {
        "proba_top3": proba_top3,
        "proba_top1": proba_top1,
        "facteurs_positifs": _clean_labels(positifs[:5]),
        "facteurs_negatifs": _clean_labels(negatifs[:3]),
        "alertes": _clean_labels(alertes),
        "confiance_composite": conf,
        "nb_signaux_positifs": len(positifs),
        "nb_signaux_negatifs": len(negatifs),
        "verdict": _verdict(positifs, negatifs, proba_top3, vb),
    }


def _verdict(positifs: list, negatifs: list, proba_top3: float, vb: Optional[dict]) -> str:
    """Verdict synthétique en une phrase."""
    if vb and vb.get("niveau", 0) >= 3:
        return "FORT SIGNAL VALUE BET"
    if vb and vb.get("niveau", 0) >= 2:
        return "SIGNAL VALUE BET"
    if len(positifs) >= 4 and len(negatifs) == 0 and proba_top3 > 0.55:
        return "TRÈS FAVORABLE"
    if len(positifs) >= 3 and len(negatifs) <= 1 and proba_top3 > 0.45:
        return "FAVORABLE"
    if len(negatifs) >= 3:
        return "DÉFAVORABLE"
    if proba_top3 < 0.30:
        return "OUTSIDER"
    return "NEUTRE"


async def generate_race_narrative(
    course_id: str,
    course_info: dict,
    predictions_with_features: list[dict],
    top_recommendation: Optional[dict] = None,
) -> str:
    """
    Génère une analyse narrative complète de la course via Claude API.

    Appel haiku (rapide + économique) avec les données structurées.
    Retourne texte markdown lisible par l'utilisateur.

    predictions_with_features : [{nom, numero, proba_top3, explanation: dict, ...}]
    """
    if not settings.anthropic_api_key:
        return _generate_rule_based_narrative(course_info, predictions_with_features, top_recommendation)

    # Préparer le résumé structuré pour Claude
    course_summary = _build_course_summary(course_info, predictions_with_features, top_recommendation)

    prompt = f"""Tu es BlackTurf, un système d'analyse hippique expert.
Analyse cette course et génère une analyse claire et utile pour un parieur.

**Contexte course :**
{course_summary}

**Règles :**
- Maximum 200 mots
- Langue : français
- Ton : expert, factuel, concis
- Structure : 1 phrase intro, top recommandations avec raisons, 1 alerte si pertinent
- Ne jamais garantir un résultat — utiliser des tournures probabilistes
- Inclure la mention jeu responsable en fin si niveau VB ≥ 3

Génère uniquement l'analyse, pas de titre ni d'en-tête."""

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": settings.anthropic_api_key,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": settings.anthropic_model,
                    "max_tokens": 400,
                    "messages": [{"role": "user", "content": prompt}],
                },
            )
            if resp.status_code == 200:
                data = resp.json()
                return data["content"][0]["text"].strip()
    except Exception as e:
        log.error("narrative.claude_failed", error=str(e))

    # Fallback si Claude indisponible
    return _generate_rule_based_narrative(course_info, predictions_with_features, top_recommendation)


def _build_course_summary(course_info: dict, predictions: list[dict],
                           top_reco: Optional[dict]) -> str:
    """Construit le résumé structuré pour le prompt Claude."""
    hippodrome = course_info.get("hippodrome_nom", "")
    discipline = course_info.get("discipline", "")
    distance = course_info.get("distance", 0)
    terrain = course_info.get("terrain_officiel", "")
    pen = course_info.get("penetrometre_coef")
    nb_partants = course_info.get("nb_partants", 0)

    lines = [
        f"Course : {hippodrome} · {discipline} · {distance}m · {nb_partants} partants",
        f"Terrain : {terrain}{f' ({pen:.1f})' if pen else ''}",
    ]

    # Top 3 prédictions
    top3 = sorted(predictions, key=lambda x: x.get("proba_top3", 0), reverse=True)[:3]
    for i, p in enumerate(top3, 1):
        nom = p.get("nom", "")
        num = p.get("numero", "")
        proba = p.get("proba_top3", 0)
        explanation = p.get("explanation", {})
        verdict = explanation.get("verdict", "")
        positifs = explanation.get("facteurs_positifs", [])
        vb = p.get("vb")
        ev = vb.get("ev_max", 0) if vb else 0
        cote = p.get("cote_pmu", 0)

        top_signal = positifs[0]["label"] if positifs else ""
        vb_str = f"· VB EV+{ev*100:.0f}%" if ev > 0.05 else ""
        lines.append(
            f"N°{num} {nom} : top-3 {proba*100:.0f}% · cote {cote:.1f} {vb_str} · {verdict}"
            + (f" — Signal principal : {top_signal}" if top_signal else "")
        )

    # Signaux marché
    market_signals = []
    for p in predictions:
        exp = p.get("explanation", {})
        for f in exp.get("facteurs_positifs", []):
            if f.get("categorie") == "marche":
                market_signals.append(f"{p.get('nom')} : {f['label']}")
    if market_signals:
        lines.append("Signaux marché : " + " | ".join(market_signals[:3]))

    return "\n".join(lines)


def _generate_rule_based_narrative(course_info: dict, predictions: list[dict],
                                    top_reco: Optional[dict]) -> str:
    """
    Narrative basée sur des règles (fallback sans Claude API).
    Produit un texte structuré depuis les explications ML.
    """
    top3 = sorted(predictions, key=lambda x: x.get("proba_top3", 0), reverse=True)[:3]
    if not top3:
        return "Analyse non disponible — données insuffisantes."

    top = top3[0]
    nom = top.get("nom", "")
    num = top.get("numero", "")
    proba = top.get("proba_top3", 0)
    explanation = top.get("explanation", {})
    positifs = explanation.get("facteurs_positifs", [])
    vb = top.get("vb")

    lines = []

    # Intro
    hippodrome = course_info.get("hippodrome_nom", "")
    discipline = course_info.get("discipline", "")
    if hippodrome:
        lines.append(f"**Course {hippodrome}** — {discipline}")

    # Recommandation principale
    if vb and vb.get("niveau", 0) >= 2:
        ev = vb.get("ev_max", 0)
        lines.append(f"**Value bet : N°{num} {nom}** (EV +{ev*100:.0f}%, proba top-3 {proba*100:.0f}%)")
    else:
        lines.append(f"**Favori IA : N°{num} {nom}** (proba top-3 {proba*100:.0f}%)")

    # Facteurs positifs top-3
    if positifs:
        raisons = " · ".join(_strip_emoji(f["label"]) for f in positifs[:3])
        lines.append(f"Pourquoi : {raisons}")

    # Autres chevaux
    if len(top3) > 1:
        autres = [f"N°{p['numero']} {p['nom']} ({p.get('proba_top3', 0)*100:.0f}%)"
                  for p in top3[1:3]]
        lines.append(f"Également en vue : {' · '.join(autres)}")

    # Alertes
    alertes = explanation.get("alertes", [])
    for a in alertes[:1]:
        lines.append(f"{_strip_emoji(a['label'])}: {_strip_emoji(a.get('detail', ''))}")

    # Retire les marqueurs markdown gras (non rendus côté fiche → afficher propre).
    return "\n".join(lines).replace("**", "")


def _chevaux_a_eviter(enriched: list[dict]) -> list[dict]:
    """Chevaux que l'analyse déconseille de jouer, avec MOTIFS réels (pas de décor) :
      - « surcoté par le public » : cote courte mais proba modèle nettement sous la
        proba implicite du marché → jouer ce cheval = payer trop cher sa chance ;
      - facteurs négatifs dominants (forme basse, terrain défavorable, ELO inférieur…).
    On ne liste que des chevaux que le public risque VRAIMENT de jouer (cote ≤ 15) —
    déconseiller un 80/1 n'apprend rien à personne."""
    out = []
    for p in enriched:
        cote = float(p.get("cote_pmu") or 0)
        if cote <= 1.0 or cote > 15.0:
            continue
        exp = p.get("explanation", {})
        raisons = []
        severite = 0.0
        # Surcote marché : proba modèle « victoire » très en-dessous de la proba implicite.
        p1 = float(p.get("proba_top1") or 0)
        implied = 1.0 / cote
        if p1 > 0 and p1 < implied * 0.55 and cote <= 9.0:
            raisons.append(
                f"Surcoté par le public : le marché lui donne ~{implied*100:.0f}% de chances, "
                f"le modèle {p1*100:.0f}% — sa cote ne paie pas son vrai risque."
            )
            severite += (implied - p1) * 3
        negs = exp.get("facteurs_negatifs", [])
        if len(negs) >= 2:
            labels = " · ".join(_strip_emoji(n.get("label", "")) for n in negs[:3])
            raisons.append(f"Facteurs défavorables : {labels}.")
            severite += sum(float(n.get("score", 0)) for n in negs[:3]) * 0.5
        if exp.get("verdict") == "DÉFAVORABLE":
            severite += 0.3
        if not raisons:
            continue
        out.append({
            "numero": p.get("numero"),
            "nom": p.get("nom"),
            "cote": round(cote, 1),
            "raisons": raisons,
            "_sev": severite,
        })
    out.sort(key=lambda x: x["_sev"], reverse=True)
    for o in out:
        o.pop("_sev", None)
    return out[:3]


async def generate_full_course_analysis(
    session,
    course_id: str,
    course_info: dict,
    predictions: list[dict],
    features_by_pid: dict,
) -> dict:
    """
    Génère l'analyse complète d'une course :
    - Explication par partant (structurée)
    - Narrative globale (Claude ou rule-based)
    - Score de confiance global du champ
    - Signaux marché résumés

    predictions : [{participation_id, numero, nom, proba_top3, proba_top1, cote_pmu, vb}]
    features_by_pid : {participation_id: features_dict}
    """
    # Générer explanation par partant
    enriched = []
    for pred in predictions:
        pid = pred.get("participation_id")
        features = features_by_pid.get(pid, {})
        vb = pred.get("vb")

        explanation = explain_prediction(
            features=features,
            proba_top3=pred.get("proba_top3", 0),
            proba_top1=pred.get("proba_top1", 0),
            vb=vb,
        )

        enriched.append({**pred, "explanation": explanation})

    # Narrative globale
    top_reco = max(enriched, key=lambda x: x.get("proba_top3", 0)) if enriched else None
    narrative = await generate_race_narrative(
        course_id=course_id,
        course_info=course_info,
        predictions_with_features=enriched,
        top_recommendation=top_reco,
    )

    # Signaux marché résumés
    market_signals = []
    for pred in enriched:
        for f in pred.get("explanation", {}).get("facteurs_positifs", []):
            if f.get("categorie") == "marche" and f.get("score", 0) > 0.2:
                market_signals.append({
                    "numero": pred.get("numero"),
                    "nom": pred.get("nom"),
                    "signal": f["label"],
                    "detail": f["detail"],
                    "score": f["score"],
                })

    # Score confiance global champ
    confidence_scores = [p.get("explanation", {}).get("confiance_composite", 0.5) for p in enriched]
    field_confidence = float(sum(confidence_scores) / max(len(confidence_scores), 1))

    return {
        "course_id": course_id,
        "narrative": narrative,
        "predictions": enriched,
        "market_signals": sorted(market_signals, key=lambda x: x["score"], reverse=True)[:5],
        "chevaux_a_eviter": _chevaux_a_eviter(enriched),
        "field_confidence": round(field_confidence, 3),
        "top_recommendation": {
            "numero": top_reco.get("numero") if top_reco else None,
            "nom": top_reco.get("nom") if top_reco else None,
            "verdict": top_reco.get("explanation", {}).get("verdict") if top_reco else None,
        } if top_reco else None,
    }
