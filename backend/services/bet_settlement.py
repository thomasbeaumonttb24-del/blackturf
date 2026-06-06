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

from typing import Optional

# type_pari -> clé du rapport PMU (base 1€)
_RAPPORT_KEY = {
    "Simple Gagnant": "e_simple_gagnant",
    "Simple Placé": "e_simple_place",
    "Couplé Gagnant": "e_couple_gagnant",
    "Couplé Placé": "e_couple_place",
    "Trio": "e_trio",
    "2sur4": "e_super_quatre",
}

_APPROX_NOTE = "Rapport placé approximatif (le PMU publie un rapport par cheval placé)."


def _nb_places(nb_partants: int) -> int:
    """Nombre de chevaux « placés » selon la règle PMU."""
    if nb_partants >= 8:
        return 3
    if nb_partants >= 4:
        return 2
    return 1


def settle_pari(
    type_pari: str,
    numeros: list[int],
    classement: list[dict],
    rapports: Optional[dict],
    nb_partants: int,
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
        return {"gagne": False, "rapport_reel": None, "rapport_approximatif": False,
                "note": "Résultat indisponible"}

    nb_pl = _nb_places(nb_partants or len(pos_by_num))
    placed = {num_by_pos[p] for p in range(1, nb_pl + 1) if p in num_by_pos}
    top2 = {num_by_pos[p] for p in (1, 2) if p in num_by_pos}
    top3 = {num_by_pos[p] for p in (1, 2, 3) if p in num_by_pos}
    top4 = {num_by_pos[p] for p in (1, 2, 3, 4) if p in num_by_pos}
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
    elif type_pari == "Trio":
        gagne = sel == top3 and len(sel) == 3
    elif type_pari == "2sur4":
        gagne = len(sel & top4) >= 2
    else:
        # Type non géré (ex: Tiercé) → gagné déterminé sur top3 mais rapport indispo
        gagne = sel == top3 and len(sel) == 3
        note = "Rapport non publié pour ce type de pari."

    rapport_reel: Optional[float] = None
    if gagne:
        key = _RAPPORT_KEY.get(type_pari)
        val = rapports.get(key) if key else None
        try:
            rapport_reel = float(val) if val is not None and float(val) > 0 else None
        except (TypeError, ValueError):
            rapport_reel = None
        if rapport_reel is None and note is None:
            note = "Pari gagné mais rapport PMU indisponible."

    return {
        "gagne": bool(gagne),
        "rapport_reel": rapport_reel,
        "rapport_approximatif": approx,
        "note": note,
    }


def settle_plan(plan: dict, classement: list[dict], rapports: Optional[dict],
                nb_partants: int) -> dict:
    """
    Règle un plan de mise complet (dict issu de plan_to_dict) contre le résultat.

    Retourne le bilan agrégé + le détail par pari (avec gagné/gain).
    """
    paris_bilan: list[dict] = []
    total_mise = 0.0
    total_gain = 0.0
    gain_indetermine = False

    for niveau in plan.get("niveaux", []):
        for pari in niveau.get("paris", []):
            numeros = [c["numero"] for c in pari.get("chevaux", [])]
            mise = float(pari.get("mise", 0) or 0)
            res = settle_pari(pari["type"], numeros, classement, rapports, nb_partants)
            gain = None
            if res["gagne"]:
                if res["rapport_reel"] is not None:
                    gain = round(mise * res["rapport_reel"], 2)
                    total_gain += gain
                else:
                    gain_indetermine = True
            total_mise += mise
            paris_bilan.append({
                "type": pari["type"],
                "niveau": niveau.get("niveau"),
                "chevaux": pari.get("chevaux", []),
                "mise": mise,
                "gagne": res["gagne"],
                "rapport_reel": res["rapport_reel"],
                "gain": gain,
                "rapport_approximatif": res["rapport_approximatif"],
                "note": res["note"],
            })

    total_mise = round(total_mise, 2)
    total_gain = round(total_gain, 2)
    net = round(total_gain - total_mise, 2)
    roi = round(net / total_mise * 100, 1) if total_mise > 0 else 0.0
    nb_gagnes = sum(1 for p in paris_bilan if p["gagne"])

    return {
        "paris": paris_bilan,
        "nb_paris": len(paris_bilan),
        "nb_gagnes": nb_gagnes,
        "total_mise": total_mise,
        "total_gain": total_gain,
        "net": net,
        "roi": roi,
        "gain_indetermine": gain_indetermine,
    }
