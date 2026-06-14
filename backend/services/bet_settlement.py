"""
Règlement de paris (bet settlement) — BlackTurf.

Règle un pari généré par le plan de mise contre le RÉSULTAT RÉEL d'une course
(ordre d'arrivée officiel + rapports PMU définitifs).

Principe d'intégrité : on ne JAMAIS invente de rapport. Le gagné/perdu est
déterminé exactement depuis le classement ; le gain est calculé avec le rapport
PMU réel (`rapports.e_*`, base 1€) quand il est disponible pour le type de pari.
Si le pari gagne mais que le rapport n'est pas publié pour ce type, on renvoie
`rapport_reel=None` et `gain=None` (gain indéterminé, pas inventé).

Les rapports PMU stockés sont les rapports de la COMBINAISON GAGNANTE réelle :
- Pour les paris « gagnant/ordre exact » (Simple Gagnant, Couplé Gagnant, Trio,
  2sur4), si notre sélection == la combinaison gagnante, le rapport stocké est
  exactement notre rapport → gain exact.
- Pour les paris « placé » (Simple Placé, Couplé Placé), le PMU publie un rapport
  par cheval placé ; un seul est stocké → le gagné/perdu reste exact mais le
  rapport est approximatif (signalé via `note`).
"""
from __future__ import annotations

import math
import re
from typing import Optional

# type_pari -> clés candidates du rapport PMU (base 1€). On essaie chaque clé et on
# prend la première publiée. ⚠️ NE PAS mélanger des paris DIFFÉRENTS : le « 2sur4 »
# (≥2 de 4 dans le top-4) n'a RIEN à voir avec le « Super 4 » (super_quatre, top-4
# exact en ordre) dont le rapport est ~100× plus gros. Utiliser super_quatre pour
# régler un 2sur4 crédite un gain fictif énorme → bankroll faussée. Si le vrai
# rapport 2sur4 (deux_sur_quatre) n'est pas publié, on laisse en attente (None).
#
# ⚠️ CLÉS RÉELLES = typePari PMU mis en minuscules par le scraper (cf.
# scraper/sources/pmu.py : `rapports[item["typePari"].lower()]`). Ex. "deux_sur_quatre",
# "simple_gagnant"… PAS de préfixe `e_` (celui-ci est le codePari des COTES live, jamais
# stocké dans les rapports définitifs). On garde les variantes `e_*` en second pour
# rétro-compat avec d'éventuelles vieilles lignes. Mettre la clé réelle EN PREMIER.
_RAPPORT_KEYS = {
    "Simple Gagnant": ("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international"),
    "Simple Placé":   ("simple_place", "e_simple_place", "simple_place_international"),
    "Couplé Gagnant": ("couple_gagnant", "e_couple_gagnant"),
    "Couplé Placé":   ("couple_place", "e_couple_place"),
    # Paris à l'ORDRE (champ réduit) — combinaison gagnante dans l'ordre exact.
    "Couplé Ordre":   ("couple_ordre", "e_couple_ordre"),
    "Trio":           ("trio", "e_trio"),
    "Trio Ordre":     ("trio_ordre", "e_trio_ordre"),
    "Super 4":        ("super_quatre", "e_super_quatre"),
    "2sur4":          ("deux_sur_quatre", "e_deux_sur_quatre"),
    # Jackpots désordre — vrais rapports PMU (base 1€). Le rapport publié est celui
    # de la combinaison gagnante ; si notre sélection == arrivée exacte, c'est le nôtre.
    "Tiercé Désordre": ("tierce", "e_tierce"),
    "Tiercé Ordre":    ("tierce_ordre", "e_tierce_ordre", "tierce", "e_tierce"),
    "Quarté+ Désordre": ("quarte_plus", "e_quarte_plus"),
    "Quarté+":          ("quarte_plus", "e_quarte_plus"),
    "Quinté+ Désordre": ("quinte_plus", "e_quinte_plus"),
    "Quinté+ Flexi":    ("quinte_plus", "e_quinte_plus"),
    "Quinté+":          ("quinte_plus", "e_quinte_plus"),
}

_APPROX_NOTE = "Rapport placé approximatif (le PMU publie un rapport par cheval placé)."


def _nb_places(nb_partants: int) -> int:
    """Nombre de chevaux « placés » selon la règle PMU."""
    if nb_partants >= 8:
        return 3
    if nb_partants >= 4:
        return 2
    return 1


def _place_rapport_exact(rapports_detail: Optional[dict], key: str,
                         numeros: list[int]) -> Optional[float]:
    """Rapport placé EXACT du cheval/de la combinaison depuis rapports_detail
    (le PMU publie un rapport par cheval placé). Match par numéro(s) dans la
    `combinaison`. None si introuvable → l'appelant retombe sur l'agrégat."""
    if not rapports_detail:
        return None
    entries = rapports_detail.get(key) or []
    want = sorted(str(int(n)) for n in numeros)
    for e in entries:
        combi = str(e.get("combinaison") or "")
        nums = sorted(re.findall(r"\d+", combi))
        if nums == want and e.get("rapport"):
            try:
                return float(e["rapport"])
            except (TypeError, ValueError):
                return None
    return None


def settle_pari(
    type_pari: str,
    numeros: list[int],
    classement: list[dict],
    rapports: Optional[dict],
    nb_partants: int,
    rapports_detail: Optional[dict] = None,
) -> dict:
    """
    Règle un pari unique.

    Retourne :
        {
          "gagne": bool,
          "rapport_reel": float | None,   # rapport PMU base 1€ (None si indispo)
          "rapport_approximatif": bool,
          "note": str | None,
        }
    Le gain monétaire est calculé par l'appelant : mise * rapport_reel.

    `rapports_detail` (optionnel) = détail PMU {type: [{combinaison, rapport}]} :
    permet le rapport placé EXACT du cheval précis (sinon agrégat approximatif).
    """
    rapports = rapports or {}

    # Construire les positions depuis le classement officiel
    num_by_pos: dict[int, int] = {}
    pos_by_num: dict[int, int] = {}
    for e in classement or []:
        try:
            num = int(e.get("numero"))
            pos = e.get("position")
            if pos is None:
                continue
            pos = int(pos)
        except (TypeError, ValueError):
            continue
        num_by_pos.setdefault(pos, num)
        pos_by_num.setdefault(num, pos)

    if not num_by_pos:
        return {"gagne": False, "rapport_reel": None, "gain_mult": 1.0,
                "rapport_approximatif": False, "note": "Résultat indisponible"}

    nb_pl = _nb_places(nb_partants or len(pos_by_num))
    gain_mult = 1.0   # part de la mise payée au rapport (formules combinées : <1 possible)
    placed = {num_by_pos[p] for p in range(1, nb_pl + 1) if p in num_by_pos}
    top2 = {num_by_pos[p] for p in (1, 2) if p in num_by_pos}
    top3 = {num_by_pos[p] for p in (1, 2, 3) if p in num_by_pos}
    top4 = {num_by_pos[p] for p in (1, 2, 3, 4) if p in num_by_pos}
    top5 = {num_by_pos[p] for p in (1, 2, 3, 4, 5) if p in num_by_pos}
    sel = set(int(n) for n in numeros)

    approx = False
    note: Optional[str] = None

    if type_pari == "Simple Gagnant":
        gagne = pos_by_num.get(next(iter(sel))) == 1 if len(sel) == 1 else (sel == {num_by_pos.get(1)})
    elif type_pari == "Simple Placé":
        gagne = len(sel) == 1 and next(iter(sel)) in placed
        approx = gagne
        note = _APPROX_NOTE if gagne else None
    elif type_pari == "Couplé Gagnant":
        gagne = sel == top2 and len(sel) == 2
    elif type_pari == "Couplé Placé":
        gagne = len(sel) == 2 and sel.issubset(placed)
        approx = gagne
        note = _APPROX_NOTE if gagne else None
    elif type_pari == "Couplé Ordre":
        # Ordre EXACT : 1er cheval joué = 1er arrivé, 2e = 2e arrivé.
        gagne = (len(numeros) == 2
                 and num_by_pos.get(1) == int(numeros[0])
                 and num_by_pos.get(2) == int(numeros[1]))
    elif type_pari == "Trio":
        gagne = sel == top3 and len(sel) == 3
    elif type_pari == "Trio Ordre":
        gagne = (len(numeros) == 3
                 and num_by_pos.get(1) == int(numeros[0])
                 and num_by_pos.get(2) == int(numeros[1])
                 and num_by_pos.get(3) == int(numeros[2]))
    elif type_pari == "Super 4":
        gagne = (len(numeros) == 4
                 and num_by_pos.get(1) == int(numeros[0])
                 and num_by_pos.get(2) == int(numeros[1])
                 and num_by_pos.get(3) == int(numeros[2])
                 and num_by_pos.get(4) == int(numeros[3]))
    elif type_pari == "2sur4":
        # Formule combinée : jouer N chevaux en 2sur4 = C(N,2) combinaisons, la mise
        # se répartit dessus. Le rapport PMU paie PAR combinaison gagnante →
        # gain = mise × rapport × C(n_dans_top4, 2) / C(N, 2). Avec 4 chevaux dont
        # 2 placés : 1/6 de la mise au rapport (PAS la mise entière — c'était
        # l'erreur qui gonflait les gains 2sur4).
        n_in = len(sel & top4)
        gagne = n_in >= 2
        if gagne and len(sel) > 2:
            n_combis = math.comb(len(sel), 2)
            n_win = math.comb(n_in, 2)
            gain_mult = n_win / n_combis
            note = f"Formule {len(sel)} chevaux : {n_win}/{n_combis} combinaison(s) gagnante(s)."
    elif type_pari in ("Tiercé Désordre", "Tiercé Ordre"):
        gagne = sel == top3 and len(sel) == 3        # désordre : 3 premiers, ordre indifférent
    elif type_pari in ("Quarté+ Désordre", "Quarté+"):
        gagne = sel == top4 and len(sel) == 4
    elif type_pari in ("Quinté+ Désordre", "Quinté+ Flexi", "Quinté+"):
        gagne = sel == top5 and len(sel) == 5
    else:
        # Type vraiment non géré → gagné déterminé sur top3, rapport indispo.
        gagne = sel == top3 and len(sel) == 3
        note = "Rapport non publié pour ce type de pari."

    rapport_reel: Optional[float] = None
    if gagne:
        val = None
        keys = _RAPPORT_KEYS.get(type_pari, ())
        # Placé : tenter le rapport EXACT du cheval/combi via rapports_detail.
        if type_pari in ("Simple Placé", "Couplé Placé") and keys:
            exact = _place_rapport_exact(rapports_detail, keys[0], list(sel))
            if exact and exact > 0:
                val = exact
                approx = False
                note = None
        if val is None:
            for k in keys:
                if rapports.get(k) is not None:
                    val = rapports.get(k)
                    break
        try:
            rapport_reel = float(val) if val is not None and float(val) > 0 else None
        except (TypeError, ValueError):
            rapport_reel = None
        if rapport_reel is None and note is None:
            note = "Rapport PMU pas encore publié — gain en attente."

    return {
        "gagne": bool(gagne),
        "rapport_reel": rapport_reel,
        "gain_mult": float(gain_mult),
        "rapport_approximatif": approx,
        "note": note,
    }


def settle_plan(plan: dict, classement: list[dict], rapports: Optional[dict],
                nb_partants: int, rapports_detail: Optional[dict] = None) -> dict:
    """
    Règle un plan de mise complet (dict issu de plan_to_dict) contre le résultat.

    Retourne le bilan agrégé + le détail par pari (avec gagné/gain).
    `rapports_detail` → rapport placé EXACT (sinon agrégat).
    """
    paris_bilan: list[dict] = []
    total_mise = 0.0
    total_gain = 0.0
    nb_en_attente = 0

    for niveau in plan.get("niveaux", []):
        for pari in niveau.get("paris", []):
            numeros = [c["numero"] for c in pari.get("chevaux", [])]
            mise = float(pari.get("mise", 0) or 0)
            res = settle_pari(pari["type"], numeros, classement, rapports, nb_partants, rapports_detail)
            gain = None
            # statut : "gagne" | "perdu" | "en_attente" (gagné mais rapport pas publié)
            if res["gagne"]:
                if res["rapport_reel"] is not None:
                    gain = round(mise * res["rapport_reel"] * res.get("gain_mult", 1.0), 2)
                    total_gain += gain
                    statut = "gagne"
                else:
                    statut = "en_attente"
                    nb_en_attente += 1
            else:
                statut = "perdu"
            total_mise += mise
            paris_bilan.append({
                "type": pari["type"],
                "niveau": niveau.get("niveau"),
                "chevaux": pari.get("chevaux", []),
                "mise": mise,
                "gagne": res["gagne"],
                "statut": statut,
                "rapport_reel": res["rapport_reel"],
                "gain": gain,
                "rapport_approximatif": res["rapport_approximatif"],
                "note": res["note"],
            })

    total_mise = round(total_mise, 2)
    total_gain = round(total_gain, 2)
    net = round(total_gain - total_mise, 2)
    roi = round(net / total_mise * 100, 1) if total_mise > 0 else 0.0
    nb_gagnes = sum(1 for p in paris_bilan if p["statut"] == "gagne")

    return {
        "paris": paris_bilan,
        "nb_paris": len(paris_bilan),
        "nb_gagnes": nb_gagnes,
        "nb_en_attente": nb_en_attente,
        "en_attente": nb_en_attente > 0,
        "total_mise": total_mise,
        "total_gain": total_gain,
        "net": net,
        "roi": roi,
        # net/ROI provisoires tant que des rapports manquent
        "provisoire": nb_en_attente > 0,
        "gain_indetermine": nb_en_attente > 0,  # rétro-compat
    }
