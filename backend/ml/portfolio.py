"""
BetPortfolioEngine — Moteur de portefeuille de paris multi-scénarios.

Philosophie : au lieu de proposer 1-2 paris simples, construire un
PORTEFEUILLE de paris qui couvre l'espace complet des résultats possibles
tout en maximisant l'espérance de gain globale.

5 scénarios structurés (chacun autonome et profitable seul) :

  ALPHA  — Sécurité : paris à forte probabilité, mise réduite
  BETA   — Rendement : meilleur EV par rapport au risque
  GAMMA  — Valeur : top EV sans contrainte de probabilité (outsiders potentiels)
  DELTA  — Surprise IA : signaux de marché non reflétés dans les probas
  OMEGA  — Couverture combinée : Tiercé/Quinté qui couvre les 5 scénarios

Innovation vs l'existant :
  - DELTA exploite les signaux SPI / mouvement cotes / biais contextuels
  - Allocation de mise par Kelly multi-objectif (EV × coverage)
  - Score de confiance de portfolio global
  - Détection d'outsiders "value" via valeur_latente et decote_detectee
  - Flexi adaptatif selon budget restant
"""
import math
import structlog
import numpy as np
from typing import Optional

log = structlog.get_logger(module="portfolio")

# Conversion empirique top-3 -> top-1 quand proba_top1 absente.
# P(gagner) ≈ P(top-3) / 2.85 en moyenne sur un champ ~12 partants.
_P1_FROM_P3 = 0.35


def _p1(d: dict) -> float:
    """Probabilité de victoire (top-1) d'un partant, avec repli robuste sur top-3.

    Évite l'ambiguïté de précédence `a or b * c` et centralise la conversion.
    """
    p1 = d.get("proba_top1")
    if p1 and p1 > 0:
        return float(p1)
    return float(d.get("proba_top3", 0.0)) * _P1_FROM_P3


# TRJ 2026 par type de pari
TRJ = {
    "Simple Gagnant": 0.8495,
    "Simple Placé": 0.8495,
    "Couplé Gagnant": 0.74,
    "Couplé Placé": 0.74,
    "Couplé Ordre": 0.74,
    "2sur4": 0.74,
    "Trio": 0.691,
    "Tiercé Désordre": 0.6435,
    "Tiercé Ordre": 0.6435,
    "Quarté+ Bonus": 0.633,
    "Quinté+ Flexi": 0.6475,
}

MISE_MIN = {
    "Simple Gagnant": 1.50,
    "Simple Placé": 1.50,
    "Couplé Gagnant": 2.00,
    "Couplé Placé": 2.00,
    "Couplé Ordre": 2.00,
    "2sur4": 3.00,
    "Trio": 1.50,
    "Tiercé Désordre": 2.00,
    "Tiercé Ordre": 2.00,
    "Quarté+ Bonus": 2.00,
    "Quinté+ Flexi": 2.00,
}

# Seuils de détection de signaux spéciaux
SPI_SEUIL = 0.20            # SPI > 0.20 = signal argent pro
MOUVEMENT_SEUIL = 0.12      # Cote en baisse > 12% = signal fort
VALEUR_LATENTE_SEUIL = 0.25 # PMU surcoté vs marché > 25% = value latente
DECOTE_SEUIL = 0.20         # Décote détectée > 20% = signal fort
OUTSIDER_PROBA_MAX = 0.30   # Cheval avec proba < 30% mais fort signal = "outsider IA"


class BetPortfolioEngine:
    """
    Moteur principal de génération de portefeuilles de paris.
    """

    def build_portfolio(
        self,
        predictions: list[dict],
        course_info: dict,
        bankroll: float = 100.0,
        budget_course: Optional[float] = None,
        profil: str = "equilibre",
        adaptive_weights: Optional[dict] = None,
        bias_correction: float = 0.0,
    ) -> dict:
        """
        Construit le portefeuille complet pour une course.

        predictions : [{
            participation_id, numero, nom,
            proba_top3, proba_top1,
            cote_pmu, cote_geny, cote_bzh,
            ev_max, niveau_vb,
            spi_score, mouvement_30min, valeur_latente, decote_detectee,
            features_snapshot,
        }]

        course_info : {
            course_id, nb_partants, est_quinte, est_quarte, est_tierce,
            hippodrome, discipline, terrain, distance
        }

        Retourne : {
            scenarios: {alpha, beta, gamma, delta, omega},
            resume_portfolio, allocation_recommandee,
            paris_immediats,  # Les 3 paris prioritaires à placer maintenant
            warnings,
        }
        """
        if not predictions:
            return {}

        budget = budget_course or max(bankroll * 0.05, 10.0)
        nb_partants = course_info.get("nb_partants", 10)

        # Appliquer correction de biais sur les probas si fournie
        if bias_correction != 0.0:
            predictions = self._apply_bias_correction(predictions, bias_correction)

        # Trier par proba décroissante
        by_proba = sorted(predictions, key=lambda x: x.get("proba_top3", 0), reverse=True)
        # Trier par EV décroissant
        by_ev = sorted(predictions, key=lambda x: x.get("ev_max", -1), reverse=True)

        top1, top2, top3 = (by_proba + [None, None, None])[:3]
        top5 = by_proba[:5]

        # Détecter les outsiders à signal fort (DELTA candidates)
        outsiders_signal = self._detect_delta_candidates(predictions)

        paris_dispo = _types_disponibles(nb_partants, course_info)

        # ── Construire les 5 scénarios ────────────────────────────────────
        alpha = self._scenario_alpha(top1, top2, by_proba, paris_dispo, budget)
        beta  = self._scenario_beta(by_ev, by_proba, paris_dispo, budget)
        gamma = self._scenario_gamma(by_ev, paris_dispo, budget)
        delta = self._scenario_delta(outsiders_signal, predictions, paris_dispo, budget)
        omega = self._scenario_omega(top5, outsiders_signal, paris_dispo, budget, course_info)

        scenarios = {
            "alpha": alpha,
            "beta": beta,
            "gamma": gamma,
            "delta": delta,
            "omega": omega,
        }

        # ── Allocation budgétaire optimale ────────────────────────────────
        allocation = self._compute_allocation(scenarios, budget, profil)

        # ── 3 paris prioritaires (action immédiate) ───────────────────────
        paris_immediats = self._select_priority_bets(scenarios, allocation)

        # ── Métriques du portefeuille ─────────────────────────────────────
        resume = self._compute_portfolio_metrics(scenarios, allocation, predictions)

        # ── Warnings ─────────────────────────────────────────────────────
        warnings = self._generate_warnings(predictions, course_info, outsiders_signal)

        return {
            "scenarios": scenarios,
            "allocation_recommandee": allocation,
            "paris_immediats": paris_immediats,
            "resume_portfolio": resume,
            "outsiders_signal": [
                {"numero": o["numero"], "nom": o["nom"],
                 "signal": o["signal_principal"], "force": round(o["force_signal"], 2)}
                for o in outsiders_signal[:3]
            ],
            "warnings": warnings,
            "nb_scenarios_actifs": sum(1 for s in scenarios.values() if s),
        }

    def _scenario_alpha(
        self, top1, top2, by_proba, paris_dispo, budget
    ) -> Optional[dict]:
        """
        ALPHA — Sécurité absolue.
        Top-1/2 en placé. Haute probabilité, faible gain mais presque sûr.
        """
        if not top1:
            return None

        paris = []
        cout_total = 0.0

        # Simple Placé top-1
        if top1.get("proba_top3", 0) >= 0.45:
            cote = float(top1.get("cote_pmu") or 3.0)
            mise = min(_kelly(top1.get("ev_max", 0), cote, budget, fraction=0.4), budget * 0.15)
            mise = max(mise, MISE_MIN["Simple Placé"])
            paris.append({
                "type": "Simple Placé",
                "chevaux": [_cheval(top1)],
                "mise": round(mise, 2),
                "ev": round(top1.get("ev_max", 0), 3),
                "proba": round(top1.get("proba_top3", 0), 3),
                "explication": f"N°{top1['numero']} {top1['nom']} — {top1.get('proba_top3',0)*100:.0f}% top-3",
            })
            cout_total += mise

        # Couplé Placé top1+top2 si disponible
        if top2 and "Couplé Placé" in paris_dispo and top2.get("proba_top3", 0) >= 0.40:
            mise_couple = MISE_MIN["Couplé Placé"]
            paris.append({
                "type": "Couplé Placé",
                "chevaux": [_cheval(top1), _cheval(top2)],
                "mise": mise_couple,
                "ev": round((top1.get("ev_max", 0) + top2.get("ev_max", 0)) / 2, 3),
                "proba": round((top1.get("proba_top3", 0) * top2.get("proba_top3", 0)) ** 0.5, 3),
                "explication": f"N°{top1['numero']}+N°{top2['numero']} dans le top-3",
            })
            cout_total += mise_couple

        if not paris:
            return None

        confidence = float(np.mean([p.get("proba", 0) for p in paris]))
        return {
            "nom": "ALPHA — Sécurité",
            "description": "Paris à forte probabilité. Mise réduite, résultat quasi-certain.",
            "paris": paris,
            "cout_total": round(cout_total, 2),
            "ev_moyen": round(float(np.mean([p.get("ev", 0) for p in paris])), 3),
            "confidence": round(confidence, 3),
            "risque": "très faible",
            "couleur": "#059669",
        }

    def _scenario_beta(
        self, by_ev, by_proba, paris_dispo, budget
    ) -> Optional[dict]:
        """
        BETA — Rendement standard.
        Meilleurs EV absolus avec contrainte de proba > 40%.
        Simple Gagnant + Couplé Gagnant.
        """
        # Filtrer par proba > 40% ET ev > 0
        vbs_qual = [
            p for p in by_ev
            if p.get("proba_top3", 0) >= 0.40 and p.get("ev_max", 0) > 0.02
        ]

        if not vbs_qual:
            return None

        paris = []
        cout_total = 0.0

        # Meilleur EV gagnant
        best = vbs_qual[0]
        cote = float(best.get("cote_pmu") or 5.0)
        mise = min(_kelly(best.get("ev_max", 0), cote, budget, fraction=0.5), budget * 0.12)
        mise = max(mise, MISE_MIN["Simple Gagnant"])
        paris.append({
            "type": "Simple Gagnant",
            "chevaux": [_cheval(best)],
            "mise": round(mise, 2),
            "ev": round(best.get("ev_max", 0), 3),
            "proba": round(_p1(best), 3),
            "explication": f"N°{best['numero']} {best['nom']} — EV +{best.get('ev_max',0)*100:.0f}% | Cote {cote:.1f}",
        })
        cout_total += mise

        # Couplé Gagnant top-2 EV
        if len(vbs_qual) >= 2 and "Couplé Gagnant" in paris_dispo:
            sec = vbs_qual[1]
            p1 = _p1(by_proba[0]) if by_proba else 0.2
            p2 = _p1(sec)
            proba_couple = p1 * p2 * 2  # ordre quelconque
            mise_c = MISE_MIN["Couplé Gagnant"] + 2.0
            paris.append({
                "type": "Couplé Gagnant",
                "chevaux": [_cheval(best), _cheval(sec)],
                "mise": mise_c,
                "ev": round((best.get("ev_max", 0) + sec.get("ev_max", 0)) / 2, 3),
                "proba": round(proba_couple, 3),
                "explication": f"N°{best['numero']}+N°{sec['numero']} dans les 2 premiers",
            })
            cout_total += mise_c

        confidence = float(np.mean([p.get("proba", 0) for p in paris]))
        return {
            "nom": "BETA — Rendement",
            "description": "Meilleure espérance de gain calculée. Équilibre risque/rendement optimal.",
            "paris": paris,
            "cout_total": round(cout_total, 2),
            "ev_moyen": round(float(np.mean([p.get("ev", 0) for p in paris])), 3),
            "confidence": round(confidence, 3),
            "risque": "modéré",
            "couleur": "#2563EB",
        }

    def _scenario_gamma(
        self, by_ev, paris_dispo, budget
    ) -> Optional[dict]:
        """
        GAMMA — Chasse à la valeur.
        Top EV sans filtre de probabilité. Peut inclure outsiders à très haute valeur.
        2sur4 ou Trio couvrant les meilleurs EV.
        """
        vbs_ev = [p for p in by_ev if p.get("ev_max", 0) > 0.08]

        if len(vbs_ev) < 2:
            return None

        paris = []
        cout_total = 0.0
        sel = vbs_ev[:4]

        # 2sur4 si 4 candidats EV disponibles
        if len(sel) >= 4 and "2sur4" in paris_dispo:
            cout = 6 * 3.0  # C(4,2) × 3€
            paris.append({
                "type": "2sur4",
                "chevaux": [_cheval(p) for p in sel[:4]],
                "mise": cout,
                "ev": round(float(np.mean([p.get("ev_max", 0) for p in sel[:4]])), 3),
                "proba": round(float(np.mean([p.get("proba_top3", 0) for p in sel[:4]])), 3),
                "explication": f"2 parmi N°{','.join(str(p['numero']) for p in sel[:4])} dans les 4 premiers | Couverture large",
            })
            cout_total += cout
        elif len(sel) >= 3 and "Trio" in paris_dispo:
            cout = MISE_MIN["Trio"] + 1.5
            paris.append({
                "type": "Trio",
                "chevaux": [_cheval(p) for p in sel[:3]],
                "mise": cout,
                "ev": round(float(np.mean([p.get("ev_max", 0) for p in sel[:3]])), 3),
                "proba": round(float(np.mean([p.get("proba_top3", 0) for p in sel[:3]])), 3),
                "explication": f"N°{sel[0]['numero']}+N°{sel[1]['numero']}+N°{sel[2]['numero']} top-3 sans ordre",
            })
            cout_total += cout

        if not paris:
            return None

        confidence = float(np.mean([p.get("proba", 0) for p in paris]))
        return {
            "nom": "GAMMA — Valeur",
            "description": "Meilleure espérance mathématique absolue. Couvre les outsiders à fort EV.",
            "paris": paris,
            "cout_total": round(cout_total, 2),
            "ev_moyen": round(float(np.mean([p.get("ev", 0) for p in paris])), 3),
            "confidence": round(confidence, 3),
            "risque": "modéré-élevé",
            "couleur": "#D97706",
        }

    def _scenario_delta(
        self, outsiders: list[dict], predictions, paris_dispo, budget
    ) -> Optional[dict]:
        """
        DELTA — Surprise IA.
        Paris sur les chevaux que le modèle n'a pas mis en avant MAIS
        qui ont des signaux de marché forts (SPI, décote, momentum).

        C'est le scénario "le marché sait quelque chose que le modèle ne sait pas".
        Mise faible, gain potentiel très élevé.
        """
        if not outsiders:
            return None

        # Prendre les 2 meilleurs outsiders
        sel = outsiders[:2]
        paris = []
        cout_total = 0.0

        for o in sel:
            cote = float(o.get("cote_pmu") or 10.0)
            # Mise réduite car incertitude élevée — mais EV positif via les signaux
            mise = min(_kelly_outsider(o.get("force_signal", 0.3), cote, budget), budget * 0.06)
            mise = max(mise, MISE_MIN["Simple Gagnant"])

            paris.append({
                "type": "Simple Gagnant",
                "chevaux": [_cheval(o)],
                "mise": round(mise, 2),
                "ev": round(o.get("ev_max", 0), 3),
                "proba": round(o.get("proba_top3", 0), 3),
                "signal": o.get("signal_principal", ""),
                "force_signal": round(o.get("force_signal", 0), 3),
                "explication": (
                    f"N°{o['numero']} {o['nom']} — Signal : {o.get('signal_principal','')} "
                    f"| Force : {o.get('force_signal',0)*100:.0f}% | Cote : {cote:.1f}"
                ),
            })
            cout_total += mise

        if not paris:
            return None

        avg_force = float(np.mean([o.get("force_signal", 0) for o in sel]))
        return {
            "nom": "DELTA — Surprise IA",
            "description": (
                "Signaux de marché non reflétés dans les probas IA. "
                "Mise faible sur outsiders avec fort momentum ou SPI détecté."
            ),
            "paris": paris,
            "cout_total": round(cout_total, 2),
            "ev_moyen": round(float(np.mean([p.get("ev", 0) for p in paris if p.get("ev", 0) > 0])), 3),
            "confidence": round(avg_force * 0.4, 3),  # Confidence réduite car outsider
            "risque": "élevé — potentiel multiplicateur",
            "couleur": "#7C3AED",
        }

    def _scenario_omega(
        self, top5, outsiders, paris_dispo, budget, course_info
    ) -> Optional[dict]:
        """
        OMEGA — Couverture combinée.
        Tiercé désordre ou Quinté qui inclut les top-5 + 1-2 outsiders.
        Couvre le maximum de scénarios de résultat en une seule combinaison.
        """
        est_quinte = course_info.get("est_quinte", False)
        est_tierce = course_info.get("est_tierce", False) or course_info.get("est_quarte", False)

        if not top5 or len(top5) < 3:
            return None

        paris = []
        cout_total = 0.0

        # Construire la sélection élargie : top5 + meilleur outsider DELTA
        selection_omega = list(top5[:5])
        if outsiders:
            best_outsider = outsiders[0]
            # Ajouter si pas déjà dans la sélection
            existing_nums = {p["numero"] for p in selection_omega}
            if best_outsider["numero"] not in existing_nums:
                selection_omega.append(best_outsider)

        if "Quinté+" in paris_dispo and est_quinte and len(selection_omega) >= 5:
            # Quinté+ Flexi 10% avec 5 chevaux
            # 5! = 120 combis × 10% = 0.20€ × 120 = 24€
            # Ou Flexi adapté au budget
            cout_flexi = min(24.0, budget * 0.25)
            paris.append({
                "type": "Quinté+ Flexi",
                "chevaux": [_cheval(p) for p in selection_omega[:5]],
                "mise": round(cout_flexi, 2),
                "ev": 0.35,
                "proba": float(np.mean([p.get("proba_top3", 0) for p in selection_omega[:5]])),
                "nb_combinaisons": 120,
                "explication": (
                    f"Quinté+ Flexi N°{','.join(str(p['numero']) for p in selection_omega[:5])} "
                    f"— 120 combis couvrant tous les scénarios"
                ),
            })
            cout_total += cout_flexi

        elif "Tiercé Désordre" in paris_dispo and len(selection_omega) >= 3:
            # Tiercé désordre avec les 4 meilleurs + outsider
            # C(5,3) = 10 combinaisons × 2€ = 20€
            sel_tierce = selection_omega[:min(5, len(selection_omega))]
            n = len(sel_tierce)
            nb_combis = math.comb(n, 3)
            cout_t = min(nb_combis * 2.0, budget * 0.20)
            paris.append({
                "type": "Tiercé Désordre",
                "chevaux": [_cheval(p) for p in sel_tierce],
                "mise": round(cout_t, 2),
                "ev": 0.25,
                "proba": float(np.mean([p.get("proba_top3", 0) for p in sel_tierce])),
                "nb_combinaisons": nb_combis,
                "explication": (
                    f"Tiercé désordre {nb_combis} combis — "
                    f"N°{','.join(str(p['numero']) for p in sel_tierce)} "
                    f"(top-5 IA + outsider potentiel)"
                ),
            })
            cout_total += cout_t

        elif len(selection_omega) >= 4 and "2sur4" in paris_dispo:
            # Fallback : 2sur4 élargi
            sel4 = selection_omega[:4]
            cout_2s4 = 6 * 3.0
            paris.append({
                "type": "2sur4",
                "chevaux": [_cheval(p) for p in sel4],
                "mise": cout_2s4,
                "ev": 0.15,
                "proba": float(np.mean([p.get("proba_top3", 0) for p in sel4])),
                "nb_combinaisons": 6,
                "explication": f"2sur4 — N°{','.join(str(p['numero']) for p in sel4)}",
            })
            cout_total += cout_2s4

        if not paris:
            return None

        return {
            "nom": "OMEGA — Couverture Totale",
            "description": (
                "Combinaison large couvrant tous les scénarios en un seul pari. "
                "Intègre les candidats IA + les outsiders à signal fort."
            ),
            "paris": paris,
            "cout_total": round(cout_total, 2),
            "ev_moyen": round(float(np.mean([p.get("ev", 0) for p in paris])), 3),
            "confidence": round(float(np.mean([p.get("proba", 0) for p in paris])) * 0.6, 3),
            "risque": "variable — couverture maximale",
            "couleur": "#0891B2",
        }

    def _detect_delta_candidates(self, predictions: list[dict]) -> list[dict]:
        """
        Identifie les outsiders avec signaux de marché forts.

        Un candidat DELTA = cheval avec proba < 30% mais :
        - SPI élevé (argent professionnel détecté)
        - Cote en forte baisse
        - Valeur latente élevée (PMU surcoté vs marché)
        - Décote détectée (gap entre sources)
        """
        candidates = []

        for p in predictions:
            proba = float(p.get("proba_top3", 0))
            if proba >= OUTSIDER_PROBA_MAX:
                continue  # Pas un outsider

            spi = float(p.get("spi_score") or 0)
            mouvement = float(p.get("mouvement_30min") or 0)
            valeur_latente = float(p.get("valeur_latente") or 0)
            decote = float(p.get("decote_detectee") or 0)

            # Score composé de force du signal
            force = (
                spi * 0.35
                + mouvement * 0.30
                + valeur_latente * 0.20
                + decote * 0.15
            )

            if force < 0.08:
                continue  # Signal trop faible

            # Identifier le signal principal
            signals = [
                ("SPI — Argent professionnel détecté", spi),
                ("Cote en forte baisse (momentum)", mouvement),
                ("PMU surcoté vs marché", valeur_latente),
                ("Décote multi-sources", decote),
            ]
            signal_principal = max(signals, key=lambda x: x[1])[0]

            cote = float(p.get("cote_pmu") or 10.0)
            ev_signal = (cote * max(proba + force * 0.3, 0.05)) - 1.0

            candidates.append({
                **p,
                "force_signal": round(force, 4),
                "signal_principal": signal_principal,
                "ev_max": round(ev_signal, 4),
                "spi_score": spi,
                "mouvement_30min": mouvement,
            })

        # Trier par force de signal
        candidates.sort(key=lambda x: x["force_signal"], reverse=True)
        return candidates

    def _apply_bias_correction(
        self, predictions: list[dict], bias_correction: float
    ) -> list[dict]:
        """Applique la correction de biais contextuelle sur les probas."""
        corrected = []
        for p in predictions:
            p_copy = dict(p)
            proba = float(p.get("proba_top3", 0))
            p_copy["proba_top3"] = float(np.clip(proba * (1 + bias_correction), 0.01, 0.99))
            corrected.append(p_copy)
        return corrected

    def _compute_allocation(
        self, scenarios: dict, budget: float, profil: str
    ) -> dict:
        """
        Calcule l'allocation budgétaire optimale entre les scénarios.

        Profils :
        - conservateur : 60% ALPHA, 30% BETA, 10% GAMMA
        - equilibre    : 30% ALPHA, 35% BETA, 20% GAMMA, 10% DELTA, 5% OMEGA
        - agressif     : 20% ALPHA, 30% BETA, 25% GAMMA, 15% DELTA, 10% OMEGA
        """
        allocs = {
            "conservateur": {"alpha": 0.60, "beta": 0.30, "gamma": 0.08, "delta": 0.02, "omega": 0.0},
            "equilibre":    {"alpha": 0.30, "beta": 0.35, "gamma": 0.20, "delta": 0.10, "omega": 0.05},
            "agressif":     {"alpha": 0.20, "beta": 0.28, "gamma": 0.22, "delta": 0.17, "omega": 0.13},
        }.get(profil, {
                             "alpha": 0.30, "beta": 0.35, "gamma": 0.20, "delta": 0.10, "omega": 0.05,
        })

        allocation = {}
        for sc_name, pct in allocs.items():
            sc = scenarios.get(sc_name)
            if sc:
                montant = round(budget * pct, 2)
                cout_sc = sc.get("cout_total", 0)
                allocation[sc_name] = {
                    "budget_alloue": montant,
                    "cout_scenario": cout_sc,
                    "active": cout_sc > 0 and montant >= cout_sc * 0.5,
                    "pct_budget": round(pct * 100, 0),
                }
            else:
                allocation[sc_name] = {"budget_alloue": 0, "active": False, "pct_budget": 0}

        return allocation

    def _select_priority_bets(
        self, scenarios: dict, allocation: dict
    ) -> list[dict]:
        """
        Sélectionne les 3 paris les plus prioritaires à placer IMMÉDIATEMENT.
        Critères : meilleur EV × confidence × disponibilité budget.
        """
        all_paris = []

        for sc_name, scenario in scenarios.items():
            if not scenario:
                continue
            alloc = allocation.get(sc_name, {})
            if not alloc.get("active", False):
                continue

            sc_confidence = float(scenario.get("confidence", 0))
            sc_ev = float(scenario.get("ev_moyen", 0))
            priority_score = (sc_ev + 0.3) * sc_confidence

            for pari in scenario.get("paris", []):
                all_paris.append({
                    "scenario": sc_name,
                    "scenario_nom": scenario["nom"],
                    "type": pari["type"],
                    "chevaux": pari["chevaux"],
                    "mise": pari["mise"],
                    "ev": pari.get("ev", 0),
                    "proba": pari.get("proba", 0),
                    "explication": pari.get("explication", ""),
                    "signal": pari.get("signal", ""),
                    "priority_score": round(priority_score, 4),
                    "couleur": scenario.get("couleur", "#374151"),
                })

        # Trier par priority_score et dédupliquer par type de pari
        all_paris.sort(key=lambda x: x["priority_score"], reverse=True)
        seen_types = set()
        prioritaires = []
        for p in all_paris:
            key = (p["type"], tuple(c["numero"] for c in p["chevaux"]))
            if key not in seen_types:
                seen_types.add(key)
                prioritaires.append(p)
            if len(prioritaires) >= 3:
                break

        return prioritaires

    def _compute_portfolio_metrics(
        self, scenarios, allocation, predictions
    ) -> dict:
        """Métriques globales du portefeuille."""
        cout_total = sum(
            s.get("cout_total", 0)
            for s in scenarios.values()
            if s and allocation.get(list(scenarios.keys())[list(scenarios.values()).index(s)], {}).get("active", False)
        )

        ev_scenarios = [
            s.get("ev_moyen", 0)
            for s in scenarios.values()
            if s and s.get("ev_moyen", 0) > 0
        ]

        avg_proba_top1 = float(np.mean([
            _p1(p)
            for p in predictions
            if p.get("proba_top1", 0) or p.get("proba_top3", 0)
        ])) if predictions else 0.0

        nb_actifs = sum(1 for s in scenarios.values() if s)

        return {
            "cout_total_portefeuille": round(cout_total, 2),
            "ev_moyen_actif": round(float(np.mean(ev_scenarios)), 3) if ev_scenarios else 0,
            "nb_scenarios_couverts": nb_actifs,
            "couverture_outsider": bool([s for s in scenarios.values() if s and s.get("nom", "").startswith("DELTA")]),
            "score_diversification": round(nb_actifs / 5, 2),
            "note_globale": _note_globale(ev_scenarios, nb_actifs),
        }

    def _generate_warnings(
        self, predictions, course_info, outsiders
    ) -> list[str]:
        """Génère les avertissements pertinents pour l'utilisateur."""
        warnings = []

        nb_partants = course_info.get("nb_partants", 10)
        if nb_partants < 6:
            warnings.append("⚠️ Petit champ (<6 partants) — les combinés sont limités")

        # Tous les favoris très proches en proba
        top3 = sorted(predictions, key=lambda x: x.get("proba_top3", 0), reverse=True)[:3]
        if top3 and len(top3) == 3:
            probas = [p.get("proba_top3", 0) for p in top3]
            if max(probas) - min(probas) < 0.05:
                warnings.append("⚠️ Probabilités très serrées entre les 3 premiers — course ouverte, outsider probable")

        # Fort signal DELTA détecté
        if outsiders:
            best_o = outsiders[0]
            if best_o.get("force_signal", 0) > 0.35:
                warnings.append(f"🔔 Signal fort détecté sur N°{best_o['numero']} {best_o['nom']} — {best_o.get('signal_principal','')}")

        # Terrain lourd avec chevaux peu habitués
        terrain = (course_info.get("terrain") or "").lower()
        if "lourd" in terrain or "bourbeux" in terrain:
            warnings.append("⚠️ Terrain lourd — les habitudes terrain pèsent davantage que d'habitude")

        return warnings


# ── Helpers ──────────────────────────────────────────────────────────────────

def _cheval(p: dict) -> dict:
    return {"numero": p.get("numero", 0), "nom": p.get("nom", "?")}


def _kelly(ev: float, cote: float, budget: float, fraction: float = 0.5) -> float:
    if ev <= 0 or cote <= 1.0:
        return MISE_MIN.get("Simple Gagnant", 1.50)
    mise = (ev * budget / cote) * fraction
    return max(mise, 1.50)


def _kelly_outsider(force_signal: float, cote: float, budget: float) -> float:
    """Kelly adapté aux outsiders DELTA — mise très conservative."""
    if cote <= 1.0:
        return 1.50
    # EV synthétique basé sur la force du signal
    ev_synth = force_signal * 0.8
    mise = (ev_synth * budget / cote) * 0.25  # fraction très faible
    return max(mise, 1.50)


def _types_disponibles(nb_partants: int, course_info: dict) -> list[str]:
    paris = ["Simple Gagnant", "Simple Placé", "Couplé Gagnant", "Couplé Placé", "Couplé Ordre", "Trio"]
    if nb_partants >= 8:
        paris.append("2sur4")
    if course_info.get("est_tierce") or course_info.get("est_quarte") or course_info.get("est_quinte"):
        paris.extend(["Tiercé Désordre", "Tiercé Ordre"])
    if course_info.get("est_quarte") or course_info.get("est_quinte"):
        paris.append("Quarté+ Bonus")
    if course_info.get("est_quinte"):
        paris.append("Quinté+ Flexi")
    return paris


def _note_globale(ev_scenarios: list[float], nb_actifs: int) -> str:
    """Note qualitative du portefeuille."""
    if not ev_scenarios:
        return "—"
    avg_ev = float(np.mean(ev_scenarios))
    if avg_ev > 0.25 and nb_actifs >= 3:
        return "★★★★★ Exceptionnel"
    if avg_ev > 0.15 and nb_actifs >= 3:
        return "★★★★ Très bon"
    if avg_ev > 0.08 and nb_actifs >= 2:
        return "★★★ Bon"
    if avg_ev > 0.03:
        return "★★ Acceptable"
    return "★ Faible"


# ── Markowitz portfolio optimizer ────────────────────────────────────────────
class MarkowitzBetOptimizer:
    """
    Optimisation Markowitz appliquée aux paris hippiques.

    Dans une course : les chevaux sont mutuellement exclusifs
    → corrélation -1/(n-1) entre chaque paire.
    Entre courses différentes : indépendants → corrélation 0.

    Maximise le ratio Sharpe = (EV_portef - 0) / volatilité_portef
    sous contrainte de budget total.

    Retourne les mises optimales normalisées.
    """

    def optimize_single_race(
        self,
        predictions: list[dict],
        budget: float,
        min_proba: float = 0.10,
    ) -> list[dict]:
        """
        Optimise les mises sur une seule course.
        predictions : [{numero, nom, proba_top1, ev_max, cote_pmu}]
        Retourne liste avec 'mise_optimale' calculée.
        """
        # Filtrer les candidats avec EV positif
        candidates = [p for p in predictions
                      if p.get("ev_max", 0) > 0 and p.get("proba_top1", 0) >= min_proba
                      and p.get("cote_pmu", 0) > 1.0]
        if not candidates:
            return predictions

        n = len(candidates)
        if n == 1:
            # Un seul candidat → Kelly standard
            p = candidates[0]
            ev = p.get("ev_max", 0)
            cote = p.get("cote_pmu", 5.0)
            mise = min(budget * 0.5, budget * ev / max(cote - 1, 0.1) * 0.5)
            p["mise_optimale"] = round(max(mise, 1.5), 2)
            return predictions

        # Vecteur EV
        evs = np.array([p.get("ev_max", 0) for p in candidates])
        cotes = np.array([p.get("cote_pmu", 5.0) for p in candidates])
        probas = np.array([p.get("proba_top1", 1/n) for p in candidates])

        # Matrice de covariance : chevaux mutuellement exclusifs
        # Var(X_i) = proba_i * (1-proba_i) * (cote_i-1)^2
        # Cov(X_i, X_j) ≈ -proba_i * proba_j * cote_i * cote_j  (exclusion mutuelle approximée)
        gains = cotes - 1
        var_diag = probas * (1 - probas) * gains ** 2
        cov_matrix = np.outer(-probas * gains, probas * gains) + np.diag(var_diag + 1e-8)

        try:
            # Résoudre : max w^T * ev - 0.5 * lambda * w^T * cov * w
            # sous contrainte sum(w) <= budget, w >= 0
            # Simplification : méthode du gradient projeté
            inv_cov = np.linalg.inv(cov_matrix)
            raw_mises = inv_cov @ evs
            raw_mises = np.maximum(raw_mises, 0)  # Pas de mises négatives

            if raw_mises.sum() > 0:
                # Normaliser au budget
                mises_normalized = raw_mises / raw_mises.sum() * budget * 0.6
                for i, p in enumerate(candidates):
                    p["mise_optimale"] = round(max(float(mises_normalized[i]), 1.5), 2)
            else:
                # Fallback Kelly
                for p in candidates:
                    ev = p.get("ev_max", 0)
                    cote = p.get("cote_pmu", 5.0)
                    p["mise_optimale"] = round(max(budget * ev / max(cote - 1, 0.1) * 0.3, 1.5), 2)
        except np.linalg.LinAlgError:
            # Fallback si matrice singulière
            for p in candidates:
                p["mise_optimale"] = round(budget / max(n * 2, 2), 2)

        return predictions

    def optimize_multi_race_portfolio(
        self,
        races: list[dict],
        total_bankroll: float,
        budget_per_race: Optional[float] = None,
    ) -> dict:
        """
        Optimise un portefeuille multi-course pour une réunion complète.
        Les courses sont indépendantes → peut allouer budget selon EV attendu.

        races : [{course_id, hippodrome, heure, predictions: [...]}, ...]
        Retourne allocation optimale par course + paris recommandés.
        """
        if not races:
            return {}

        budget = budget_per_race or total_bankroll * 0.05

        # EV global par course (somme des EV × probas des candidats)
        race_scores = []
        for race in races:
            preds = race.get("predictions", [])
            vb_candidates = [p for p in preds if p.get("ev_max", 0) > 0.05]
            if vb_candidates:
                total_ev = sum(p.get("ev_max", 0) * p.get("proba_top1", 0) for p in vb_candidates)
                race_scores.append({"race": race, "score": total_ev})

        if not race_scores:
            return {"message": "Aucune course avec EV positif", "allocations": []}

        total_score = sum(r["score"] for r in race_scores)
        max_budget_total = total_bankroll * 0.15  # Max 15% bankroll sur une réunion

        allocations = []
        for rs in sorted(race_scores, key=lambda x: x["score"], reverse=True):
            race = rs["race"]
            pct = rs["score"] / max(total_score, 0.01)
            alloc = round(min(pct * max_budget_total, budget * 1.5), 2)

            optimized_preds = self.optimize_single_race(
                race.get("predictions", []), alloc
            )

            # Paris recommandés (EV > 0.05 avec mise)
            paris = [
                {
                    "numero": p.get("numero"),
                    "nom": p.get("nom"),
                    "cote": p.get("cote_pmu"),
                    "ev": round(p.get("ev_max", 0), 3),
                    "mise": p.get("mise_optimale", 1.5),
                    "type": "Simple Gagnant",
                }
                for p in optimized_preds if p.get("mise_optimale", 0) > 0
            ]

            allocations.append({
                "course_id": race.get("course_id"),
                "hippodrome": race.get("hippodrome"),
                "heure": race.get("heure"),
                "budget_alloue": alloc,
                "ev_score": round(rs["score"], 3),
                "paris_recommandes": paris[:3],
            })

        total_investi = sum(a["budget_alloue"] for a in allocations)
        return {
            "allocations": allocations,
            "total_investi": round(total_investi, 2),
            "bankroll_pct": round(total_investi / total_bankroll * 100, 1),
            "nb_courses_selectionnees": len(allocations),
        }


def dutching_calculator(
    selections: list[dict],
    budget: float,
    target_profit: Optional[float] = None,
) -> dict:
    """
    Calcule les mises pour un Dutch bet (garantir un gain fixe quel que soit le gagnant).

    selections : [{numero, nom, cote, proba}]
    budget : budget total à répartir
    target_profit : profit cible (si None, maximise le ROI attendu)

    Formule Dutch :
    mise_i = budget × (1/cote_i) / sum(1/cote_j for j)
    Garantit un retour = budget × 1 / (sum of implied probas inverse)

    Intéressant quand la somme des probas implicites < 0.85 (value global).
    """
    if not selections:
        return {}

    cotes = [s.get("cote", 5.0) for s in selections]
    probas_impl = [1.0 / max(c, 1.01) for c in cotes]
    sum_probas = sum(probas_impl)

    # Vérifier si le Dutch est profitable
    # sum_probas < 1 = value (bookmakers en désavantage sur ce sous-ensemble)
    dutch_value = 1.0 / sum_probas  # retour garanti pour chaque euro misé
    is_profitable = dutch_value > 1.0

    # Calculer les mises
    mises = []
    total_cost = 0
    for i, sel in enumerate(selections):
        cote = cotes[i]
        mise = budget * (1.0 / cote) / sum_probas
        retour_si_gagne = mise * cote
        mises.append({
            "numero": sel.get("numero"),
            "nom": sel.get("nom"),
            "cote": cote,
            "mise": round(mise, 2),
            "retour_si_gagne": round(retour_si_gagne, 2),
            "profit_si_gagne": round(retour_si_gagne - budget, 2),
        })
        total_cost += mise

    profit_garanti = total_cost * dutch_value - total_cost

    return {
        "mises": mises,
        "budget_total": round(total_cost, 2),
        "retour_garanti": round(total_cost * dutch_value, 2),
        "profit_garanti": round(profit_garanti, 2),
        "roi_garanti": round(profit_garanti / total_cost * 100, 1),
        "is_profitable": is_profitable,
        "dutch_value": round(dutch_value, 3),
        "note": (
            "✅ Dutch profitable — les cotes offrent une valeur globale" if is_profitable
            else "⚠️ Dutch non profitable — somme des probas > 1.0"
        ),
    }


def kelly_fraction_adaptatif(
    ev: float,
    cote: float,
    bankroll: float,
    roi_recent: float = 0.0,
    brier_ema: float = 0.18,
    temperature: float = 1.0,
) -> float:
    """
    Kelly adaptatif : fraction Kelly ajustée selon les performances récentes.

    Plus le modèle a bien prédit récemment (brier bas, ROI positif) →
    fraction Kelly plus élevée (plus de confiance).

    Plus le modèle est incertain (brier élevé, temperature élevée) →
    fraction Kelly plus faible (demi-Kelly ou quart-Kelly).

    Bornes : [0.02 × bankroll, 0.08 × bankroll]
    """
    if cote <= 1.0 or ev <= 0:
        return 0.0

    # Kelly brut
    b = cote - 1.0  # gain si victoire
    p_win = ev / b + 1 / cote  # approximation depuis EV
    p_win = min(max(p_win, 0.05), 0.95)
    kelly_brut = (b * p_win - (1 - p_win)) / b

    # Fraction adaptative basée sur la qualité du modèle
    # Brier score [0, 1] : 0.18 = modèle bien calibré
    brier_factor = 1.0 - max(0, (brier_ema - 0.15) / 0.15)  # 1.0 si brier=0.15, 0 si brier=0.30
    brier_factor = np.clip(brier_factor, 0.2, 1.0)

    # Temperature factor : T=1.0 → 0.5 (demi-Kelly), T=1.5 → 0.33, T=0.7 → 0.7
    temp_factor = 1.0 / (temperature + 0.5)
    temp_factor = np.clip(temp_factor, 0.25, 0.8)

    # ROI récent factor : si ROI positif récent → légère augmentation
    roi_factor = 1.0 + min(roi_recent * 2, 0.3)
    roi_factor = np.clip(roi_factor, 0.7, 1.3)

    fraction = float(kelly_brut * brier_factor * temp_factor * roi_factor)
    fraction = max(0.01, min(fraction, 0.12))  # jamais plus de 12% bankroll

    mise = bankroll * fraction
    mise = max(1.5, min(mise, bankroll * 0.08))  # plancher 1.5€, plafond 8% bankroll
    return round(mise, 2)


# ── Instance globale ─────────────────────────────────────────────────────────
_portfolio_engine = BetPortfolioEngine()
_markowitz_optimizer = MarkowitzBetOptimizer()


def get_portfolio_engine() -> BetPortfolioEngine:
    return _portfolio_engine


def get_markowitz_optimizer() -> MarkowitzBetOptimizer:
    return _markowitz_optimizer
