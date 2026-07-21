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

    # ── FIGURE DE VITESSE (niveau des courses fréquentées) ──────────────────
    vit = features.get("vitesse_relative", 0.5)
    if vit >= 0.62:
        positifs.append({"feature": "vitesse_relative", "label": "Vitesse de référence",
                         "detail": f"Chronos récents au-dessus du niveau type de la distance ({vit*100:.0f}/100) — bon référentiel de vitesse.",
                         "score": min((vit - 0.5) * 2.2, 1.0), "categorie": "vitesse"})
    elif vit <= 0.35 and vit > 0:
        negatifs.append({"feature": "vitesse_relative", "label": "Vitesse en retrait",
                         "detail": f"Chronos récents sous le niveau de la distance ({vit*100:.0f}/100).",
                         "score": min((0.5 - vit) * 2.2, 1.0), "categorie": "vitesse"})

    # ── PEDIGREE (lignée du père à la distance) ─────────────────────────────
    sire = features.get("sire_dist_winrate", 0.5)
    if sire >= 0.6:
        positifs.append({"feature": "sire_dist_winrate", "label": "Pedigree adapté",
                         "detail": f"La lignée du père réussit à cette distance ({sire*100:.0f}% de top-3 sur la descendance).",
                         "score": min((sire - 0.5) * 2, 1.0), "categorie": "pedigree"})
    sire_t = features.get("sire_terrain_winrate", 0.5)
    if sire_t >= 0.6:
        positifs.append({"feature": "sire_terrain_winrate", "label": "Lignée + terrain",
                         "detail": f"La descendance du père performe sur ce type de terrain ({sire_t*100:.0f}%).",
                         "score": min((sire_t - 0.5) * 2, 1.0), "categorie": "pedigree"})

    # ── POIDS porté (plat/obstacle) ─────────────────────────────────────────
    dpoids = features.get("delta_poids", 0)
    if dpoids <= -0.3:
        positifs.append({"feature": "delta_poids", "label": "Allègement",
                         "detail": "Porte moins de poids que lors de ses dernières sorties — avantage.",
                         "score": min(abs(dpoids), 1.0) * 0.7, "categorie": "conditions"})
    elif dpoids >= 0.4:
        negatifs.append({"feature": "delta_poids", "label": "Surcharge de poids",
                         "detail": "Porte plus lourd que d'habitude — handicap réel.",
                         "score": min(dpoids, 1.0) * 0.7, "categorie": "conditions"})

    # ── CORDE (plat/obstacle) ───────────────────────────────────────────────
    corde = features.get("corde_preference", 0.5)
    if corde >= 0.62:
        positifs.append({"feature": "corde_preference", "label": "Corde favorable",
                         "detail": f"Réussit bien depuis cette zone de corde ({corde*100:.0f}% de top-3).",
                         "score": min((corde - 0.5) * 2, 1.0), "categorie": "conditions"})

    # ── FORME RÉCENTE du jockey / de l'entraîneur ──────────────────────────
    jf = features.get("jockey_forme_7j")
    if jf is not None and jf >= 0.28:
        positifs.append({"feature": "jockey_forme_7j", "label": "Jockey en forme",
                         "detail": f"Jockey à {jf*100:.0f}% de top-3 sur les 7 derniers jours.",
                         "score": min(jf * 1.8, 1.0), "categorie": "professionnel"})
    ef = features.get("entraineur_forme_14j")
    if ef is not None and ef >= 0.28:
        positifs.append({"feature": "entraineur_forme_14j", "label": "Écurie en réussite",
                         "detail": f"Entraîneur à {ef*100:.0f}% de top-3 sur 14 jours — écurie chaude.",
                         "score": min(ef * 1.7, 1.0), "categorie": "professionnel"})

    # ── RÉGULARITÉ carrière (podiums) ───────────────────────────────────────
    podium = features.get("taux_podium_carriere", 0)
    if podium >= 0.5:
        positifs.append({"feature": "taux_podium_carriere", "label": "Régulier au podium",
                         "detail": f"{podium*100:.0f}% de podiums en carrière — valeur sûre pour le placé.",
                         "score": min(podium, 1.0), "categorie": "regularite"})

    # ── DÉPLACEMENT (proxy fatigue voyage) ──────────────────────────────────
    depl = features.get("distance_deplacement", 0.5)
    if depl >= 0.8:
        negatifs.append({"feature": "distance_deplacement", "label": "Gros déplacement",
                         "detail": "Court très loin de ses hippodromes habituels — voyage exigeant.",
                         "score": (depl - 0.5) * 1.4, "categorie": "conditions"})

    # ── REPOS / FRAÎCHEUR ───────────────────────────────────────────────────
    fr = features.get("fraicheur_score", 0.5)
    jours = features.get("jours_repos") or features.get("jours_depuis_derniere_db")
    if fr >= 0.95:
        positifs.append({"feature": "fraicheur_score", "label": "Fraîcheur idéale",
                         "detail": f"Repos optimal ({int(jours)} j) — revient frais et affûté." if jours else "Repos dans la fenêtre idéale.",
                         "score": 0.55, "categorie": "forme"})
    elif jours and jours > 75:
        alertes.append({"label": "Longue absence",
                        "detail": f"{int(jours)} jours sans courir — condition à confirmer."})

    # ── DÉBUTANT / inexpérience ─────────────────────────────────────────────
    if features.get("est_inedit", 0):
        alertes.append({"label": "Inédit",
                        "detail": "N'a jamais couru — aucune référence, pari à l'aveugle."})
    nbc = features.get("nb_courses_total") or features.get("nb_courses")
    if nbc is not None and 0 < nbc <= 3:
        alertes.append({"label": "Peu d'expérience",
                        "detail": f"Seulement {int(nbc)} course(s) en carrière — marge de progression mais incertitude."})

    # ── AVIS ENTRAÎNEUR + afflux de mises ──────────────────────────────────
    avis = features.get("avis_entraineur_score", 0.5)
    if avis >= 0.9:
        positifs.append({"feature": "avis_entraineur_score", "label": "Avis entraîneur positif",
                         "detail": "L'entourage affiche de la confiance pour cette course.",
                         "score": 0.5, "categorie": "professionnel"})
    pool_ev = features.get("pool_gagnant_evolution", 0)
    if pool_ev >= 0.15:
        positifs.append({"feature": "pool_gagnant_evolution", "label": "Afflux de mises",
                         "detail": "Volume de jeu en forte hausse sur ce cheval — argent qui arrive.",
                         "score": min(pool_ev, 1.0), "categorie": "marche"})

    # ── PROGRESSION ELO long terme ──────────────────────────────────────────
    velo = features.get("velocity_elo", 0)
    if velo >= 12:
        positifs.append({"feature": "velocity_elo", "label": "Cote ELO en hausse",
                         "detail": "Niveau (ELO) en nette progression sur ses dernières courses.",
                         "score": min(velo / 40, 1.0), "categorie": "elo"})

    # ── CONFRONTATIONS DIRECTES (a-t-il déjà battu ses rivaux du jour ?) ─────
    conf_nb = features.get("conf_nb_rencontres", 0)
    conf_taux = features.get("conf_taux_victoire", 0)
    conf_battus = features.get("conf_nb_rivaux_battus", 0)
    conf_net = features.get("conf_bilan_net", 0)
    if conf_nb >= 2 and conf_taux >= 0.60:
        positifs.append({"feature": "conf_taux_victoire", "label": "Ascendant sur ses rivaux",
                         "detail": (f"A déjà battu {int(conf_battus)} concurrent(s) présent(s) aujourd'hui "
                                    f"({conf_taux*100:.0f}% de duels gagnés sur {int(conf_nb)} rencontres)."),
                         "score": min(conf_taux * (1 + max(conf_net, 0)), 1.0), "categorie": "confrontation"})
    elif conf_nb >= 2 and conf_taux <= 0.35:
        negatifs.append({"feature": "conf_taux_victoire", "label": "Dominé en confrontation",
                         "detail": (f"Souvent battu par des rivaux engagés aujourd'hui "
                                    f"({conf_taux*100:.0f}% de duels gagnés sur {int(conf_nb)})."),
                         "score": min((1 - conf_taux) * 0.8, 1.0), "categorie": "confrontation"})

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
Analyse cette course et produis une synthèse courte mais COMPLÈTE pour un parieur.

**Contexte course :**
{course_summary}

**Règles :**
- Maximum 160 mots, français, ton expert factuel.
- Une ligne par point, dans cet ordre, en t'appuyant UNIQUEMENT sur les données ci-dessus :
  1. Lecture : course ouverte ou favori détaché (déduis-le des écarts de proba de victoire).
  2. Favori IA : le rang 1 du modèle + ses 2 atouts les plus concrets.
  3. Également en vue : les rangs 2-3 (les chances secondaires logiques).
  4. Outsiders / potentiels : chevaux sous-cotés par le marché (edge positif) ou à valeur, s'il y en a ; sinon l'écris pas.
  5. Conclusion : le scénario le plus probable + comment le jouer (placé sécurisé, combiné, ou champ large si course ouverte).
- Exploite les confrontations directes et les signaux marché quand ils sont fournis.
- Ne jamais garantir un résultat — tournures probabilistes.
- Mention jeu responsable en fin uniquement si niveau VB ≥ 3.

Génère uniquement l'analyse, pas de titre, pas de markdown, pas de puces numérotées."""

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

    # Top 3 prédictions — trié par RANG_PREDIT (2026-07-13 : clé EXACTE du classement
    # « Analyse algorithme » du front). Trier par proba_top1 divergeait dès que le ranker
    # (BT_RANKER_BLEND) réordonnait le rang sans toucher la proba → favori narrative ≠ #1
    # classement. On aligne pour garantir la corrélation pronos ↔ analyse.
    top3 = sorted(
        predictions,
        key=lambda x: (x.get("rang_predit") or 99, -x.get("proba_top1", 0)),
    )[:3]
    lines.append("Classement modèle (rang 1 = favori IA, par proba de victoire) :")
    for i, p in enumerate(top3, 1):
        nom = p.get("nom", "")
        num = p.get("numero", "")
        p1 = p.get("proba_top1", 0)
        p3 = p.get("proba_top3", 0)
        explanation = p.get("explanation", {})
        verdict = explanation.get("verdict", "")
        positifs = explanation.get("facteurs_positifs", [])
        vb = p.get("vb")
        ev = vb.get("ev_max", 0) if vb else 0
        cote = p.get("cote_pmu", 0)

        top_signals = " / ".join(_strip_emoji(f["label"]) for f in positifs[:2]) if positifs else ""
        edge = _market_edge(p)
        edge_str = f"· edge modèle {edge*100:+.0f}pt" if abs(edge) >= 0.02 else ""
        vb_str = f"· VB EV+{ev*100:.0f}%" if ev > 0.05 else ""
        lines.append(
            f"#{i} N°{num} {nom} : victoire {p1*100:.0f}% · placé {p3*100:.0f}% · cote {cote:.1f} {edge_str} {vb_str} · {verdict}"
            + (f" — Atouts : {top_signals}" if top_signals else "")
        )

    # Outsiders à valeur : hors top1, cote longue, modèle au-dessus du marché ou value bet
    fav_num = top3[0].get("numero") if top3 else None
    outsiders = []
    for p in predictions:
        if p.get("numero") == fav_num:
            continue
        cote = float(p.get("cote_pmu") or 0)
        edge = _market_edge(p)
        vb_niv = (p.get("vb") or {}).get("niveau", 0)
        if cote >= 6 and (edge > 0.03 or vb_niv >= 2):
            outsiders.append((p, cote, edge))
    outsiders.sort(key=lambda t: t[2], reverse=True)
    if outsiders:
        lines.append("Outsiders à valeur (sous-cotés par le marché) : " + " | ".join(
            f"N°{p.get('numero')} {p.get('nom')} (cote {cote:.0f}, edge {edge*100:+.0f}pt)"
            for p, cote, edge in outsiders[:3]
        ))

    # Confrontations directes : ascendant/dominé déjà résolu en facteurs (categorie confrontation)
    confront = []
    for p in predictions:
        for f in p.get("explanation", {}).get("facteurs_positifs", []):
            if f.get("categorie") == "confrontation":
                confront.append(f"N°{p.get('numero')} {p.get('nom')} : {_strip_emoji(f['detail'])}")
    if confront:
        lines.append("Confrontations directes : " + " | ".join(confront[:3]))

    # Signaux marché
    market_signals = []
    for p in predictions:
        exp = p.get("explanation", {})
        for f in exp.get("facteurs_positifs", []):
            if f.get("categorie") == "marche":
                market_signals.append(f"{p.get('nom')} : {_strip_emoji(f['label'])}")
    if market_signals:
        lines.append("Signaux marché : " + " | ".join(market_signals[:3]))

    return "\n".join(lines)


def _generate_rule_based_narrative(course_info: dict, predictions: list[dict],
                                    top_reco: Optional[dict]) -> str:
    """
    Narrative basée sur des règles (fallback sans Claude API).
    Produit un texte structuré depuis les explications ML.
    """
    # Classement modèle = par RANG_PREDIT (2026-07-13 : clé EXACTE du classement
    # « Analyse algorithme » du front). Avant : tri par proba_top1, qui divergeait du
    # rang_predit dès que le ranker (BT_RANKER_BLEND) réordonnait → favori IA ≠ #1 affiché.
    # Le favori IA est le rang 1 du modèle, PAS le meilleur placé / value bet.
    model_order = sorted(
        predictions,
        key=lambda x: (x.get("rang_predit") or 99, -x.get("proba_top1", 0)),
    )
    if not model_order:
        return "Analyse non disponible — données insuffisantes."

    top = model_order[0]
    nom = top.get("nom", "")
    num = top.get("numero", "")
    p1 = top.get("proba_top1", 0)
    p3 = top.get("proba_top3", 0)
    explanation = top.get("explanation", {})
    positifs = explanation.get("facteurs_positifs", [])

    lines = []

    # En-tête course retiré : redondant avec l'en-tête de la fiche (hippodrome ·
    # discipline · distance · partants déjà affichés). On va droit à l'analyse.

    # 1. Lecture de course — favori détaché ou course ouverte (selon les écarts).
    p1_2 = model_order[1].get("proba_top1", 0) if len(model_order) > 1 else 0
    ecart = p1 - p1_2
    if p1 >= 0.40 and ecart >= 0.12:
        lecture = "favori IA détaché, il domine le classement du modèle."
    elif p1 < 0.28:
        lecture = "course ouverte — pas de favori marqué, le placé et les outsiders prennent de la valeur."
    else:
        lecture = "course resserrée — un favori léger devant un groupe d'outsiders crédibles."
    lines.append(f"Lecture : {lecture}")

    # 2. Favori IA = rang 1 du modèle + ses atouts concrets.
    lines.append(f"Favori IA : N°{num} {nom} — victoire {p1*100:.0f}%, placé {p3*100:.0f}%.")
    if positifs:
        raisons = " · ".join(_strip_emoji(f["label"]) for f in positifs[:3])
        lines.append(f"Atouts : {raisons}.")

    # 3. Également en vue : rangs 2-3 (chances secondaires logiques).
    if len(model_order) > 1:
        autres = [
            f"N°{p['numero']} {p['nom']} (victoire {p.get('proba_top1', 0)*100:.0f}% / placé {p.get('proba_top3', 0)*100:.0f}%)"
            for p in model_order[1:3]
        ]
        lines.append("Également en vue : " + " · ".join(autres) + ".")

    # 4. Outsiders / potentiels : cote longue + modèle au-dessus du marché (edge) ou value bet.
    outs = []
    for p in model_order:
        if p.get("numero") == num:
            continue
        cote = float(p.get("cote_pmu") or 0)
        edge = _market_edge(p)
        vb_niv = (p.get("vb") or {}).get("niveau", 0)
        if cote >= 6 and (edge > 0.03 or vb_niv >= 2):
            outs.append((p, cote, edge))
    outs.sort(key=lambda t: t[2], reverse=True)
    if outs:
        labels = [f"N°{p['numero']} {p['nom']} (cote {cote:.0f}, jugé sous-coté)" for p, cote, _ in outs[:2]]
        lines.append("Outsiders à valeur : " + " · ".join(labels) + ".")

    # 5. Conclusion / scénario le plus probable + comment le jouer.
    if p1 >= 0.40 and ecart >= 0.12:
        scenario = (f"Conclusion : N°{num} doit confirmer sa supériorité — base solide pour le placé "
                    f"et tête des combinés.")
    elif p1 < 0.28:
        scenario = ("Conclusion : arrivée indécise — privilégier le placé et glisser un outsider à valeur "
                    "dans les jeux à champ large.")
    else:
        scenario = (f"Conclusion : N°{num} en patron logique mais le placé reste à portée des suivants — "
                    f"sécuriser via un combiné placé avec les chances secondaires.")
    lines.append(scenario)

    # Alerte (point de vigilance sur le favori)
    for a in explanation.get("alertes", [])[:1]:
        lines.append(f"À surveiller — {_strip_emoji(a['label'])} : {_strip_emoji(a.get('detail', ''))}.")

    # Retire les marqueurs markdown gras (non rendus côté fiche → afficher propre).
    return "\n".join(lines).replace("**", "")


def _market_edge(p: dict) -> float:
    """Edge modèle vs marché sur la VICTOIRE : proba_top1 − proba implicite (1/cote,
    overround non retiré, suffisant comme garde-fou de cohérence). >0 = le modèle
    aime ce cheval PLUS que le marché → ne peut PAS être « à éviter »."""
    cote = float(p.get("cote_pmu") or 0)
    if cote <= 1.0:
        return 0.0
    return float(p.get("proba_top1") or 0) - 1.0 / cote


def _horse_facts(p: dict) -> dict:
    """Fiche d'identité COMPLÈTE et factuelle d'un partant pour l'affichage — toutes
    les infos dérivées de l'analyse réelle (aucune invention). Sert les justificatifs
    des outsiders ET des chevaux à éviter (même base de faits → zéro contradiction)."""
    exp = p.get("explanation", {}) or {}
    cote = float(p.get("cote_pmu") or 0)
    p1 = float(p.get("proba_top1") or 0)
    p3 = float(p.get("proba_top3") or 0)
    implied = 1.0 / cote if cote > 1.0 else 0.0
    pos = exp.get("facteurs_positifs", []) or []
    neg = exp.get("facteurs_negatifs", []) or []
    return {
        "numero": p.get("numero"),
        "nom": p.get("nom") or p.get("nom_cheval") or "",
        "cote": round(cote, 1) if cote else None,
        "rang_predit": p.get("rang_predit"),
        "proba_victoire": round(p1, 4),         # modèle, victoire
        "proba_top3": round(p3, 4),             # modèle, placé
        "proba_marche": round(implied, 4),      # implicite marché (victoire)
        "edge": round(p1 - implied, 4),         # avantage modèle vs marché
        "verdict": exp.get("verdict"),
        "confiance": round(float(exp.get("confiance_composite") or 0), 3),
        "nb_signaux_positifs": exp.get("nb_signaux_positifs", len(pos)),
        "nb_signaux_negatifs": exp.get("nb_signaux_negatifs", len(neg)),
        "facteurs_positifs": [
            {"label": _strip_emoji(f.get("label", "")), "detail": _strip_emoji(f.get("detail", "")),
             "categorie": f.get("categorie"), "score": round(float(f.get("score") or 0), 3)}
            for f in pos[:5]
        ],
        "facteurs_negatifs": [
            {"label": _strip_emoji(f.get("label", "")), "detail": _strip_emoji(f.get("detail", "")),
             "categorie": f.get("categorie"), "score": round(float(f.get("score") or 0), 3)}
            for f in neg[:5]
        ],
        "alertes": [
            {"label": _strip_emoji(a.get("label", "")), "detail": _strip_emoji(a.get("detail", ""))}
            for a in (exp.get("alertes", []) or [])[:3]
        ],
    }


# Poids d'affichage par catégorie : on remonte les signaux PROPRES au cheval
# (forme, ELO, vitesse, confrontation, marché) et on rétrograde ceux que tout un
# groupe partage (écurie/jockey) → moins de badges identiques d'un cheval à l'autre.
_CAT_DISPLAY_WEIGHT = {
    "marche": 1.18, "confrontation": 1.15, "forme": 1.10, "elo": 1.08,
    "vitesse": 1.05, "classe": 1.04, "conditions": 1.0, "pedigree": 0.95,
    "regularite": 0.95, "equipement": 0.9, "professionnel": 0.82, "modele": 0.8,
}


def _build_signaux(p: dict, exp: dict, field_size: int) -> list[dict]:
    """Liste UNIFIÉE et ÉQUILIBRÉE de signaux pour l'affichage (atouts ET réserves),
    100% dérivée de l'analyse réelle (aucune invention). Chaque signal porte un
    `sens` (positif / negatif / neutre) pour un rendu coloré côté front.

    Au-delà des facteurs ML déjà calculés, on ajoute deux signaux HONNÊTES tirés de
    la sortie du modèle elle-même — pour que les chevaux faibles n'affichent plus QUE
    du positif :
      - lecture marché (edge) : coté trop court (surcote) ou au contraire valeur ;
      - lecture modèle : chance limitée quand le cheval est classé loin par l'IA.
    """
    pos = exp.get("facteurs_positifs", []) or []
    neg = exp.get("facteurs_negatifs", []) or []
    alertes = exp.get("alertes", []) or []
    cote = float(p.get("cote_pmu") or 0)
    p1 = float(p.get("proba_top1") or 0)
    p3 = float(p.get("proba_top3") or 0)
    implied = 1.0 / cote if cote > 1.0 else 0.0
    edge = p1 - implied
    rang = p.get("rang_predit")

    # Verdict du modèle = vérité de référence. On s'en sert pour ne PAS afficher de
    # signal qui le contredit (ex. « Supérieur au champ » sur un cheval classé 13ᵉ).
    weak = (p1 < 0.10) or (rang and field_size and rang > math.ceil(field_size * 0.6))
    strong = (p1 >= 0.25) or (rang == 1)

    sig: list[dict] = []
    seen: set = set()

    def _add(label, detail, sens, score, cat, feature=None):
        key = (label or "").lower()
        if not label or key in seen:
            return
        seen.add(key)
        w = _CAT_DISPLAY_WEIGHT.get(cat, 1.0)
        sig.append({
            "label": _strip_emoji(label), "detail": _strip_emoji(detail or ""),
            "sens": sens, "categorie": cat,
            "score": round(float(score or 0), 3),
            "_prio": round(float(score or 0) * w, 4),
            "_feat": feature,
        })

    for f in pos:
        _add(f.get("label"), f.get("detail"), "positif", f.get("score"), f.get("categorie"), f.get("feature"))
    for f in neg:
        _add(f.get("label"), f.get("detail"), "negatif", f.get("score"), f.get("categorie"), f.get("feature"))
    for a in alertes:
        _add(a.get("label"), a.get("detail"), "neutre", 0.5, "alerte")

    # ── COHÉRENCE : on retire les claims « meilleur/moins bon que le champ » qui
    # contredisent le verdict du modèle. Ces features comparent le cheval au reste
    # du peloton (force ELO, confrontations directes) → si le modèle range le cheval
    # à l'opposé, le badge devient un mensonge visuel. Les autres signaux (forme,
    # terrain, fraîcheur, classe, poids…) sont CONDITIONNELS et peuvent coexister
    # avec n'importe quel rang sans se contredire — on les garde.
    _CONTRA = {"elo_vs_moyenne", "conf_taux_victoire"}
    sig[:] = [
        s for s in sig
        if not (s.get("_feat") in _CONTRA and (
            (s["sens"] == "positif" and weak) or (s["sens"] == "negatif" and strong)
        ))
    ]

    # ── Lecture marché (edge) — réelle, calculée sur proba modèle vs cote ──────
    if cote > 1.0 and p1 > 0:
        if edge <= -0.05 and cote <= 12.0:
            _add("Coté trop court",
                 f"Le marché lui prête ~{implied*100:.0f}% de chances, le modèle {p1*100:.0f}% — "
                 f"sa cote surévalue sa chance réelle.",
                 "negatif", min(abs(edge) * 4, 1.0), "marche")
        elif edge >= 0.05 and cote >= 5.0:
            _add("Valeur (sous-coté)",
                 f"Le modèle lui donne {p1*100:.0f}% vs ~{implied*100:.0f}% pour le marché — "
                 f"cote plus généreuse que sa vraie chance.",
                 "positif", min(edge * 4, 1.0), "marche")

    # ── Angle PLACÉ — décision de jeu : cheval bien plus solide au placé qu'au
    # gagnant. 100% tiré des proba du modèle (zéro invention). Oriente vers le
    # placé / combiné placé plutôt que le gagnant.
    if 0.55 <= p3 < 0.78 and p1 < 0.25 and (p3 - p1) >= 0.30:
        _add("Profil placé",
             f"Bien plus solide au placé ({p3*100:.0f}%) qu'au gagnant ({p1*100:.0f}%) — "
             f"à jouer placé ou en combiné placé plutôt qu'au gagnant.",
             "positif", 0.62, "modele")

    # ── Verrou de sécurité au placé (valeur sûre) ────────────────────────────
    if p3 >= 0.78:
        _add("Valeur sûre placé",
             f"Le modèle lui donne {p3*100:.0f}% de finir dans les 3 — base fiable pour sécuriser un placé.",
             "positif", 0.7, "regularite")

    # ── Lecture modèle — chance limitée pour les chevaux classés loin ─────────
    has_reserve = any(s["sens"] != "positif" for s in sig)
    if (not has_reserve and rang and field_size
            and rang > max(3, math.ceil(field_size / 2))):
        _add("Chances limitées",
             f"Classé {int(rang)}ᵉ sur {int(field_size)} par le modèle "
             f"({p1*100:.0f}% de victoire) — chance secondaire.",
             "neutre", 0.42, "modele")

    sig.sort(key=lambda x: x["_prio"], reverse=True)
    for s in sig:
        s.pop("_prio", None)
        s.pop("_feat", None)
    return sig


def _chevaux_a_eviter(enriched: list[dict], exclude_nums: Optional[set] = None) -> list[dict]:
    """Chevaux que l'analyse déconseille de jouer, avec MOTIFS réels (pas de décor) :
      - « surcoté par le public » : cote courte mais proba modèle nettement sous la
        proba implicite du marché → jouer ce cheval = payer trop cher sa chance ;
      - facteurs négatifs dominants (forme basse, terrain défavorable, ELO inférieur…).
    On ne liste que des chevaux que le public risque VRAIMENT de jouer (cote ≤ 15) —
    déconseiller un 80/1 n'apprend rien à personne.

    COHÉRENCE (zéro contradiction) : on n'inscrit JAMAIS dans « à éviter » un cheval
    qui est (1) un pick du modèle en tête (top-3) ou aimé au placé (proba top-3 ≥ 0.45),
    (2) à EDGE POSITIF (le modèle l'aime plus que le marché → c'est un outsider à valeur,
    pas un piège), ou (3) déjà listé comme candidat outsider (`exclude_nums`). Ces trois
    gardes garantissent qu'un même cheval ne peut pas être « à jouer » ET « à éviter »."""
    exclude_nums = exclude_nums or set()
    # top-3 par RANG_PREDIT (même clé que le classement affiché) — garde « ne jamais
    # évincer un pick du modèle » cohérente avec ce que l'utilisateur voit.
    ranked = sorted(enriched, key=lambda x: (x.get("rang_predit") or 99, -float(x.get("proba_top1") or 0)))
    top_nums = {p.get("numero") for p in ranked[:3]}
    out = []
    for p in enriched:
        cote = float(p.get("cote_pmu") or 0)
        if cote <= 1.0 or cote > 15.0:
            continue
        # Garde 1 : pick du modèle → on ne l'évite pas.
        if p.get("numero") in top_nums or float(p.get("proba_top3") or 0) >= 0.45:
            continue
        # Garde 2 : edge positif → outsider à VALEUR, pas un piège (contradiction évitée).
        if _market_edge(p) > 0:
            continue
        # Garde 3 : déjà recommandé comme outsider ailleurs.
        if p.get("numero") in exclude_nums:
            continue
        exp = p.get("explanation", {})
        raisons = []
        severite = 0.0
        p1 = float(p.get("proba_top1") or 0)
        implied = 1.0 / cote
        # Surcote marché : proba modèle « victoire » très en-dessous de la proba implicite.
        if p1 > 0 and p1 < implied * 0.55 and cote <= 9.0:
            raisons.append(
                f"Surcoté par le public : le marché lui donne ~{implied*100:.0f}% de chances, "
                f"le modèle {p1*100:.0f}% (×{p1/max(implied,1e-6):.1f}) — sa cote ne paie pas son vrai risque."
            )
            severite += (implied - p1) * 3
        negs = exp.get("facteurs_negatifs", [])
        if len(negs) >= 2:
            for n in negs[:3]:
                lbl = _strip_emoji(n.get("label", "")); det = _strip_emoji(n.get("detail", ""))
                raisons.append(f"{lbl} : {det}" if det else lbl)
            severite += sum(float(n.get("score", 0)) for n in negs[:3]) * 0.5
        if exp.get("verdict") == "DÉFAVORABLE":
            raisons.append("Verdict global de l'analyse : DÉFAVORABLE (faisceau de signaux négatifs).")
            severite += 0.3
        if not raisons:
            continue
        facts = _horse_facts(p)
        facts["raisons"] = raisons
        facts["justification"] = (
            f"N°{facts['numero']} {facts['nom']} (cote {facts['cote']}) — à éviter : "
            f"le modèle ne lui donne que {p1*100:.0f}% de victoire / {facts['proba_top3']*100:.0f}% de placé, "
            f"sous l'estimation du marché ({implied*100:.0f}%), avec {facts['nb_signaux_negatifs']} "
            f"signal(aux) défavorable(s). Jouer ce cheval, c'est payer une cote qui ne couvre pas son risque réel."
        )
        facts["_sev"] = severite
        out.append(facts)
    out.sort(key=lambda x: x["_sev"], reverse=True)
    for o in out:
        o.pop("_sev", None)
    return out[:4]


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

    # Fiche consolidée par partant (edge marché, proba placé/victoire, verdict,
    # confiance, tous les facteurs) → un maximum d'infos exploitables côté front,
    # sur la MÊME base de faits que les outsiders et les « à éviter ».
    n_field = len(enriched)
    for e in enriched:
        e["fiche"] = _horse_facts(e)
        # Signaux équilibrés (atouts + réserves) pour l'affichage par cheval —
        # même base de faits, exposés dans explanation ET fiche.
        signaux = _build_signaux(e, e.get("explanation", {}), n_field)
        e["explanation"]["signaux"] = signaux
        e["fiche"]["signaux"] = signaux

    # Narrative globale. top_recommendation = le « Favori IA » = le RANG 1 du modèle
    # (2026-07-13 : clé rang_predit, EXACTEMENT le #1 du classement affiché). Avant : max
    # proba_top1 → divergeait du #1 classement dès que le ranker réordonnait le rang.
    top_reco = min(
        enriched,
        key=lambda x: (x.get("rang_predit") or 99, -x.get("proba_top1", 0)),
    ) if enriched else None
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
