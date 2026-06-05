"""
Générateur de recommandations stratifiées — 4 niveaux.
Connaît les règles complètes des 13 types de paris PMU.
Respecte les contraintes (nb partants, disponibilité, Flexi min 2€).
"""
import math
import structlog
from typing import Optional

log = structlog.get_logger()

# Mise minimale par type de pari (€)
MISE_MIN = {
    "Simple Gagnant": 1.50,
    "Simple Placé": 1.50,
    "Couplé Gagnant": 2.00,
    "Couplé Placé": 2.00,
    "Couplé Ordre": 2.00,
    "2sur4": 3.00,
    "Trio": 1.50,
    "Tiercé": 2.00,
    "Quarté+": 2.00,
    "Quinté+": 2.00,
    "Multi": 3.00,
}

# TRJ 2026
TRJ = {
    "Simple Gagnant": 0.8495,
    "Simple Placé": 0.8495,
    "Couplé Gagnant": 0.74,
    "Couplé Placé": 0.74,
    "Couplé Ordre": 0.74,
    "2sur4": 0.74,
    "Trio": 0.691,
    "Tiercé": 0.6435,
    "Quarté+": 0.633,
    "Quinté+": 0.6475,
}


def disponibles_selon_course(nb_partants: int, est_quinte: bool, est_quarte: bool, est_tierce: bool) -> list[str]:
    """Retourne les types de paris disponibles selon les caractéristiques de la course."""
    paris = ["Simple Gagnant", "Simple Placé", "Couplé Gagnant", "Couplé Placé", "Couplé Ordre", "Trio"]
    if nb_partants >= 8:
        paris.append("2sur4")
    if est_tierce or est_quarte or est_quinte:
        paris.append("Tiercé")
    if est_quarte or est_quinte:
        paris.append("Quarté+")
    if est_quinte:
        paris.append("Quinté+")
    return paris


def cout_combo(type_pari: str, nb_chevaux: int, flexi_pct: float = 1.0) -> float:
    """Calcule le coût d'un pari combiné avec Flexi."""
    mise_base = MISE_MIN.get(type_pari, 2.0)
    mise_flexi = mise_base * flexi_pct

    if type_pari in ("Simple Gagnant", "Simple Placé"):
        cout = mise_flexi
    elif type_pari in ("Couplé Gagnant", "Couplé Placé", "Couplé Ordre"):
        n_combis = math.comb(nb_chevaux, 2) if type_pari != "Couplé Ordre" else nb_chevaux * (nb_chevaux - 1)
        cout = n_combis * mise_flexi
    elif type_pari == "2sur4":
        n_combis = math.comb(nb_chevaux, 2)
        cout = n_combis * mise_flexi
    elif type_pari == "Trio":
        n_combis = math.comb(nb_chevaux, 3)
        cout = n_combis * mise_flexi
    elif type_pari == "Tiercé":
        n_combis = nb_chevaux * (nb_chevaux - 1) * (nb_chevaux - 2)
        cout = n_combis * mise_flexi
    elif type_pari == "Quarté+":
        n_combis = nb_chevaux * (nb_chevaux - 1) * (nb_chevaux - 2) * (nb_chevaux - 3)
        cout = n_combis * mise_flexi
    elif type_pari == "Quinté+":
        n = nb_chevaux
        n_combis = n * (n - 1) * (n - 2) * (n - 3) * (n - 4)
        cout = n_combis * mise_flexi
    else:
        cout = mise_flexi

    # Minimum ticket 2€
    return max(cout, 2.0)


def generer_recommandations_course(
    predictions: list[dict],
    course_info: dict,
    bankroll: float = 100.0,
    profil_risque: str = "equilibre",
) -> list[dict]:
    """
    Génère les recommandations pour une course.

    predictions : [{participation_id, numero, nom, proba_top3, proba_top1,
                    cote_pmu, cote_geny, ev_max, niveau_vb}, ...]
    course_info : {course_id, nb_partants, est_quinte, est_quarte, est_tierce,
                   hippodrome, heure, discipline, distance, terrain}
    """
    nb_partants = course_info.get("nb_partants", 10)
    est_quinte = course_info.get("est_quinte", False)
    est_quarte = course_info.get("est_quarte", False)
    est_tierce = course_info.get("est_tierce", False)

    paris_dispo = disponibles_selon_course(nb_partants, est_quinte, est_quarte, est_tierce)

    # Trier par proba_top3 décroissante
    pred_sorted = sorted(predictions, key=lambda x: x.get("proba_top3", 0), reverse=True)

    top1 = pred_sorted[0] if pred_sorted else None
    top2 = pred_sorted[1] if len(pred_sorted) > 1 else None
    top3 = pred_sorted[2] if len(pred_sorted) > 2 else None
    top5 = pred_sorted[:5]

    recos = []

    # ── 🟢 SAFE — Simple Placé ────────────────────────────────────────────
    if top1 and top1.get("proba_top3", 0) >= 0.50:
        cote = top1.get("cote_pmu", 3.0)
        mise = _kelly_mise(top1.get("ev_max", 0), cote, bankroll, fraction=0.5)
        mise = max(mise, 1.50)
        recos.append({
            "niveau": "safe",
            "type_pari": "Simple Placé",
            "chevaux": [{"numero": top1["numero"], "nom": top1["nom"]}],
            "mise_suggeree": round(mise, 2),
            "ev_calcule": top1.get("ev_max", 0),
            "confidence": top1.get("proba_top3", 0),
            "cout_total": round(mise, 2),
            "nb_combinaisons": 1,
            "texte_explication": (
                f"N°{top1['numero']} {top1['nom']} — Proba top-3 : {top1.get('proba_top3', 0)*100:.0f}% "
                f"| Cote : {cote:.1f}"
            ),
        })

    if top2 and top2.get("proba_top3", 0) >= 0.45:
        if "Couplé Placé" in paris_dispo:
            mise = 2.00
            recos.append({
                "niveau": "safe",
                "type_pari": "Couplé Placé",
                "chevaux": [
                    {"numero": top1["numero"], "nom": top1["nom"]},
                    {"numero": top2["numero"], "nom": top2["nom"]},
                ],
                "mise_suggeree": mise,
                "ev_calcule": (top1.get("ev_max", 0) + top2.get("ev_max", 0)) / 2,
                "confidence": (top1.get("proba_top3", 0) + top2.get("proba_top3", 0)) / 2,
                "cout_total": 2.0,
                "nb_combinaisons": 1,
                "texte_explication": (
                    f"N°{top1['numero']}+N°{top2['numero']} tous dans le top-3 — Pari de sécurité"
                ),
            })

    # ── 🔵 ÉQUILIBRÉ — Simple Gagnant + Couplé Gagnant + 2sur4 + Trio ────
    # Value bets avec EV > 0.10
    vbs = [p for p in pred_sorted if p.get("ev_max", 0) > 0.10]
    if vbs:
        best_vb = vbs[0]
        cote = best_vb.get("cote_pmu", 5.0)
        mise = _kelly_mise(best_vb.get("ev_max", 0), cote, bankroll)
        mise = max(mise, 1.50)
        recos.append({
            "niveau": "equilibre",
            "type_pari": "Simple Gagnant",
            "chevaux": [{"numero": best_vb["numero"], "nom": best_vb["nom"]}],
            "mise_suggeree": round(mise, 2),
            "ev_calcule": best_vb.get("ev_max", 0),
            "confidence": best_vb.get("proba_top1", 0),
            "cout_total": round(mise, 2),
            "nb_combinaisons": 1,
            "texte_explication": (
                f"N°{best_vb['numero']} {best_vb['nom']} — EV : +{best_vb.get('ev_max',0)*100:.0f}% "
                f"| Cote : {cote:.1f}"
            ),
        })

    if top1 and top2 and "Couplé Gagnant" in paris_dispo:
        recos.append({
            "niveau": "equilibre",
            "type_pari": "Couplé Gagnant",
            "chevaux": [
                {"numero": top1["numero"], "nom": top1["nom"]},
                {"numero": top2["numero"], "nom": top2["nom"]},
            ],
            "mise_suggeree": 4.0,
            "ev_calcule": max(top1.get("ev_max", 0), top2.get("ev_max", 0)),
            "confidence": (top1.get("proba_top1", 0) + top2.get("proba_top1", 0)) / 2,
            "cout_total": 4.0,
            "nb_combinaisons": 1,
            "texte_explication": f"N°{top1['numero']}+N°{top2['numero']} dans les 2 premiers",
        })

    if len(top5) >= 4 and "2sur4" in paris_dispo:
        sel = top5[:4]
        cout = 6 * 3.0  # C(4,2)=6 combinaisons × 3€
        recos.append({
            "niveau": "equilibre",
            "type_pari": "2sur4",
            "chevaux": [{"numero": p["numero"], "nom": p["nom"]} for p in sel],
            "mise_suggeree": cout,
            "ev_calcule": float(sum(p.get("ev_max", 0) for p in sel)) / 4,
            "confidence": float(sum(p.get("proba_top3", 0) for p in sel)) / 4,
            "cout_total": cout,
            "nb_combinaisons": 6,
            "texte_explication": f"2 chevaux parmi N°{','.join(str(p['numero']) for p in sel)} dans les 4 premiers",
        })

    if top1 and top2 and top3 and "Trio" in paris_dispo:
        recos.append({
            "niveau": "equilibre",
            "type_pari": "Trio",
            "chevaux": [
                {"numero": top1["numero"], "nom": top1["nom"]},
                {"numero": top2["numero"], "nom": top2["nom"]},
                {"numero": top3["numero"], "nom": top3["nom"]},
            ],
            "mise_suggeree": 3.0,
            "ev_calcule": 0.15,
            "confidence": top3.get("proba_top3", 0),
            "cout_total": 3.0,
            "nb_combinaisons": 1,
            "texte_explication": (
                f"N°{top1['numero']}+N°{top2['numero']}+N°{top3['numero']} dans le top-3 sans ordre"
            ),
        })

    # ── 🟡 AUDACIEUX — Tiercé désordre + Quarté+ Bonus ───────────────────
    vbs_forts = [p for p in pred_sorted if p.get("ev_max", 0) > 0.20]
    if vbs_forts and top3:
        if "Tiercé" in paris_dispo:
            recos.append({
                "niveau": "audacieux",
                "type_pari": "Tiercé Désordre",
                "chevaux": [
                    {"numero": top1["numero"], "nom": top1["nom"]},
                    {"numero": top2["numero"], "nom": top2["nom"]},
                    {"numero": top3["numero"], "nom": top3["nom"]},
                ],
                "mise_suggeree": 2.0,
                "ev_calcule": vbs_forts[0].get("ev_max", 0.20),
                "confidence": top3.get("proba_top3", 0),
                "cout_total": 2.0,
                "nb_combinaisons": 1,
                "texte_explication": (
                    f"N°{top1['numero']}+N°{top2['numero']}+N°{top3['numero']} — 1er/2e/3e dans le désordre"
                ),
            })

    if "Quarté+" in paris_dispo and len(top5) >= 4:
        # Champ réduit : 1 cheval base + 5 autres
        cout = 5 * 2.0  # 5 combinaisons × 2€
        recos.append({
            "niveau": "audacieux",
            "type_pari": "Quarté+ Bonus",
            "chevaux": [{"numero": p["numero"], "nom": p["nom"]} for p in top5[:4]],
            "mise_suggeree": cout,
            "ev_calcule": 0.25,
            "confidence": top5[3].get("proba_top3", 0) if len(top5) > 3 else 0,
            "cout_total": cout,
            "nb_combinaisons": 4,
            "texte_explication": f"Quarté Bonus N°{','.join(str(p['numero']) for p in top5[:4])}",
        })

    # ── 🔴 JACKPOT — Quinté+ Flexi 10% ───────────────────────────────────
    if "Quinté+" in paris_dispo and len(top5) >= 5:
        # 5 chevaux Flexi 10% → 5!/(5-5)! = 120 combis × 0.20€ = 24€
        cout = 120 * 0.20
        recos.append({
            "niveau": "jackpot",
            "type_pari": "Quinté+ Flexi 10%",
            "chevaux": [{"numero": p["numero"], "nom": p["nom"]} for p in top5],
            "mise_suggeree": cout,
            "ev_calcule": 0.35,
            "confidence": top5[4].get("proba_top3", 0),
            "cout_total": cout,
            "nb_combinaisons": 120,
            "texte_explication": (
                f"Quinté+ Flexi 10% N°{','.join(str(p['numero']) for p in top5)} — "
                f"120 combis × 0,20€ = {cout:.0f}€"
            ),
        })
    elif "Tiercé" in paris_dispo and top3:
        # Fallback jackpot : Tiercé en ordre
        recos.append({
            "niveau": "jackpot",
            "type_pari": "Tiercé Ordre",
            "chevaux": [
                {"numero": top1["numero"], "nom": top1["nom"]},
                {"numero": top2["numero"], "nom": top2["nom"]},
                {"numero": top3["numero"], "nom": top3["nom"]},
            ],
            "mise_suggeree": 2.0,
            "ev_calcule": 0.40,
            "confidence": top3.get("proba_top3", 0) * 0.3,
            "cout_total": 2.0,
            "nb_combinaisons": 1,
            "texte_explication": f"Tiercé Ordre N°{top1['numero']}-N°{top2['numero']}-N°{top3['numero']}",
        })

    return recos


def _kelly_mise(ev: float, cote: float, bankroll: float, fraction: float = 0.5) -> float:
    """Mise Kelly demi-fraction, plafonnée à 5% bankroll."""
    if ev <= 0 or cote <= 1.0:
        return 2.0
    mise = (ev * bankroll / cote) * fraction
    return min(mise, bankroll * 0.05)


def formater_fiche_recommandation(
    course_info: dict,
    predictions: list[dict],
    recos: list[dict],
    alertes_equipement: list[str],
    alertes_marche: list[str],
    confidence_globale: float,
    auc_modele: float,
) -> dict:
    """Format de sortie complet pour une fiche de recommandation."""
    pred_sorted = sorted(predictions, key=lambda x: x.get("proba_top3", 0), reverse=True)
    top5 = pred_sorted[:5]

    mise_totale = sum(r.get("cout_total", 0) for r in recos)

    return {
        "course_info": course_info,
        "confidence_globale": round(confidence_globale * 100),
        "etoiles_modele": _score_to_stars(confidence_globale, auc_modele),
        "auc_modele": round(auc_modele, 3),
        "selection_ia_principale": [
            {"numero": p["numero"], "nom": p["nom"], "proba": round(p.get("proba_top3", 0) * 100, 1)}
            for p in top5[:3]
        ],
        "selection_ia_elargie": [
            {"numero": p["numero"], "nom": p["nom"]}
            for p in top5
        ],
        "alertes_equipement": alertes_equipement,
        "alertes_marche": alertes_marche,
        "recommandations": recos,
        "value_bets": [
            {
                "numero": p["numero"],
                "nom": p["nom"],
                "cote_pmu": p.get("cote_pmu"),
                "proba_ia": round(p.get("proba_top3", 0) * 100, 1),
                "ev": round(p.get("ev_max", 0) * 100, 1),
                "niveau": p.get("niveau_vb", 0),
            }
            for p in pred_sorted
            if p.get("ev_max", 0) > 0.05
        ][:5],
        "mise_totale_suggeree": round(mise_totale, 2),
        "disclaimer": "Prédiction statistique — Pas de garantie de gain. Jouer comporte des risques.",
    }


def _score_to_stars(confidence: float, auc: float) -> int:
    score = (confidence + auc) / 2
    if score >= 0.75:
        return 5
    if score >= 0.68:
        return 4
    if score >= 0.62:
        return 3
    if score >= 0.55:
        return 2
    return 1
