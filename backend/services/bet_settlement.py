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
    # Multi / Mini Multi : le PMU publie UN SEUL rapport (`e_multi` / `e_mini_multi`),
    # pas un par nombre de chevaux joués (clés réelles vérifiées en base 2026-06-17).
    # Mise PLATE → gain = mise × rapport. Les clés par-N (multi_en_4…) n'existent PAS
    # côté PMU → ne pas s'y fier. La sélection de clé Multi se fait dans settle_pari
    # (selon Multi vs Mini Multi), ces entrées servent de repli générique.
    "Multi":       ("e_multi", "multi"),
    "Mini Multi":  ("e_mini_multi", "mini_multi", "e_multi", "multi"),
    # Pick5 (top-5 désordre, base 1€) — clé réelle `e_pick5`.
    "Pick5":       ("e_pick5", "pick5", "pick_5"),
}

_APPROX_NOTE = "Rapport placé approximatif (le PMU publie un rapport par cheval placé)."


def _nb_places(nb_partants: int) -> int:
    """Nombre de chevaux « placés » selon la règle PMU."""
    if nb_partants >= 8:
        return 3
    if nb_partants >= 4:
        return 2
    return 1


def _place_rapport_exact(rapports_detail: Optional[dict], keys: tuple[str, ...],
                         numeros: list[int]) -> Optional[float]:
    """Rapport placé EXACT du cheval/de la combinaison depuis rapports_detail
    (le PMU publie un rapport par cheval placé). Match par numéro(s) dans la
    `combinaison`. None si introuvable.

    ⚠️ Comparaison par ENTIERS (pas par chaînes) : le PMU peut renvoyer des
    numéros zéro-paddés ("08") → "08" != "8" en chaîne ferait échouer le match
    et l'appelant créditerait alors le rapport du 1er cheval placé (le gagnant),
    PAS celui du cheval réellement joué. C'était la cause du Simple Placé réglé
    au rapport du vainqueur. On essaie aussi toutes les clés candidates."""
    if not rapports_detail:
        return None
    want = sorted(int(n) for n in numeros)
    for key in keys:
        for e in (rapports_detail.get(key) or []):
            combi = str(e.get("combinaison") or "")
            nums = sorted(int(x) for x in re.findall(r"\d+", combi))
            if nums == want and e.get("rapport"):
                try:
                    return float(e["rapport"])
                except (TypeError, ValueError):
                    return None
    return None


def _multi_rapport_by_n(rapports_detail: Optional[dict], keys: tuple[str, ...],
                        n: int) -> Optional[float]:
    """Rapport Multi/Mini Multi pour la formule « en N » RÉELLEMENT jouée.

    Le PMU publie une entrée PAR formule (libellé « … en 4/5/6/7 »), même
    combinaison gagnante, rapports décroissants (en 4 = le plus élevé). On matche
    par le N du libellé ; à défaut (vieux scrapes sans libellé) par position, les
    entrées étant ordonnées en 4, 5, 6, 7. None si rien d'exploitable.

    ⚠️ Ne PAS retomber sur l'agrégat `rapports[clé]` = detail[0] = « en 4 » : un
    « Multi en 6 » gagnant serait payé au rapport « en 4 » (surpaie massive — bug
    R3C1 du 18/06 : en 6 réglé à 120 € au lieu de 8 €)."""
    if not rapports_detail:
        return None
    for key in keys:
        arr = rapports_detail.get(key) or []
        if not arr:
            continue
        # 1) match par libellé « en N »
        for e in arr:
            m = re.search(r"en\s+(\d+)", str(e.get("libelle") or ""), re.I)
            if m and int(m.group(1)) == n and e.get("rapport"):
                try:
                    return float(e["rapport"])
                except (TypeError, ValueError):
                    pass
        # 2) repli positionnel : index 0 = en 4, 1 = en 5, …
        idx = n - 4
        if 0 <= idx < len(arr) and arr[idx].get("rapport"):
            try:
                return float(arr[idx]["rapport"])
            except (TypeError, ValueError):
                pass
    return None


def settle_pari(
    type_pari: str,
    numeros: list[int],
    classement: list[dict],
    rapports: Optional[dict],
    nb_partants: int,
    rapports_detail: Optional[dict] = None,
    non_partants: Optional[set[int]] = None,
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
    # « Mini Multi en N » (10-13 partants) = même pari/règlement que « Multi en N ».
    tp_norm = type_pari.replace("Mini Multi", "Multi") if type_pari else type_pari

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

    # Non-partants : un cheval déclaré NP après la prise du pari → mise remboursée
    # (rapport 1.0, statut neutre). On ne le compte JAMAIS perdant : ça fausserait
    # le ROI à la baisse et polluerait l'apprentissage avec de fausses pertes.
    np_set = set(int(n) for n in (non_partants or []))
    sel_nums = set(int(n) for n in numeros)
    if np_set and (sel_nums & np_set):
        return {"gagne": False, "rapport_reel": 1.0, "gain_mult": 1.0,
                "rapport_approximatif": False, "rembourse": True,
                "note": "Cheval non-partant — mise remboursée (rapport 1.0)."}

    # Places payées = sur le nombre de PARTANTS RÉELS (déclarés − non-partants).
    eff_partants = nb_partants or len(pos_by_num)
    if np_set:
        eff_partants = max(0, eff_partants - len(np_set))
    nb_pl = _nb_places(eff_partants)
    gain_mult = 1.0   # part de la mise payée au rapport (formules combinées : <1 possible)

    # Ensembles top-N « dead-heat aware » : un ex-aequo (photo-finish) peut placer
    # PLUSIEURS numéros à la même position. `num_by_pos` n'en garde qu'un (setdefault)
    # → un Couplé/Trio légitime serait réglé perdant. On construit donc les top-N
    # depuis TOUS les numéros dont la position ≤ N (le PMU paie alors toutes les
    # combinaisons concernées par le rabattement).
    def _topset(k: int) -> set:
        s = set()
        for e in classement or []:
            try:
                p = int(e.get("position")); nn = int(e.get("numero"))
            except (TypeError, ValueError):
                continue
            if 1 <= p <= k:
                s.add(nn)
        return s
    placed = _topset(nb_pl)
    top2 = _topset(2)
    top3 = _topset(3)
    top4 = _topset(4)
    top5 = _topset(5)
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
        # issubset (pas ==) → gère le dead-heat (top2 peut contenir 3 ex-aequo).
        gagne = len(sel) == 2 and sel.issubset(top2)
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
        gagne = len(sel) == 3 and sel.issubset(top3)
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
    elif type_pari == "Tiercé Ordre":
        # ORDRE EXACT 1-2-3 (rapport tierce_ordre, ~3-5× le désordre). Régler un
        # Tiercé Ordre en désordre = surpaie massive au rapport ordre. Cf. Trio Ordre.
        gagne = (len(numeros) == 3
                 and num_by_pos.get(1) == int(numeros[0])
                 and num_by_pos.get(2) == int(numeros[1])
                 and num_by_pos.get(3) == int(numeros[2]))
    elif type_pari == "Tiercé Désordre":
        gagne = len(sel) == 3 and sel.issubset(top3)  # 3 premiers, ordre indifférent
    elif type_pari in ("Quarté+ Désordre", "Quarté+"):
        gagne = len(sel) == 4 and sel.issubset(top4)
    elif type_pari in ("Quinté+ Désordre", "Quinté+ Flexi", "Quinté+"):
        gagne = len(sel) == 5 and sel.issubset(top5)
    elif tp_norm.startswith("Multi en "):
        # Multi : les 4 PREMIERS (désordre) doivent TOUS être dans la sélection (4→7
        # chevaux). Mise plate → pas de division par combinaisons (gain_mult reste 1).
        gagne = len(top4) >= 4 and top4.issubset(sel)
    elif tp_norm == "Pick5":
        # Pick5 : les 5 premiers (désordre) tous dans la sélection. Champ > 5 = formule
        # combinée C(N,5) → la mise se répartit, 1 seule combinaison gagne.
        n_in = len(sel & top5)
        gagne = len(top5) >= 5 and n_in >= 5
        if gagne and len(sel) > 5:
            n_combis = math.comb(len(sel), 5)
            gain_mult = 1.0 / n_combis
            note = f"Pick5 champ {len(sel)} : 1/{n_combis} combinaison gagnante."
    else:
        # Type vraiment non géré → gagné déterminé sur top3, rapport indispo.
        gagne = sel == top3 and len(sel) == 3
        note = "Rapport non publié pour ce type de pari."

    rapport_reel: Optional[float] = None
    if gagne:
        val = None
        # Multi/Mini Multi : clé unique PMU (e_multi / e_mini_multi) quel que soit le N
        # joué — pas de rapport par-N en base. On choisit selon le label d'origine.
        if type_pari.startswith("Mini Multi en "):
            keys = _RAPPORT_KEYS["Mini Multi"]
        elif tp_norm.startswith("Multi en "):
            keys = _RAPPORT_KEYS["Multi"]
        else:
            keys = _RAPPORT_KEYS.get(type_pari) or _RAPPORT_KEYS.get(tp_norm, ())
        is_place = type_pari in ("Simple Placé", "Couplé Placé")
        if is_place:
            # Placé : le PMU publie UN rapport PAR cheval/combi placé. On prend
            # EXACTEMENT celui du cheval réellement joué. On ne retombe JAMAIS sur
            # l'agrégat `rapports[...]` (= 1er placé = le gagnant) : ce serait le
            # rapport d'un AUTRE cheval (bug Simple Placé réglé au rapport du
            # vainqueur). Si le rapport exact n'est pas publié → gain en attente.
            exact = _place_rapport_exact(rapports_detail, keys, list(sel))
            if exact and exact > 0:
                val = exact
                approx = False
                note = None
            else:
                # Pas d'agrégat de secours pour un placé → on clarifie l'attente.
                approx = False
                note = None
        elif tp_norm.startswith("Multi en "):
            # Multi/Mini Multi : rapport de la formule « en N » jouée (PAS detail[0]
            # = en 4). N = nombre de chevaux du ticket (== le N du libellé du pari).
            m = re.search(r"en\s+(\d+)", type_pari or "")
            n = int(m.group(1)) if m else (len(sel) or 4)
            val = _multi_rapport_by_n(rapports_detail, keys, n)
            if val is None and n == 4:
                # agrégat = 1er = « en 4 » → exact UNIQUEMENT pour en 4.
                for k in keys:
                    if rapports.get(k) is not None:
                        val = rapports.get(k)
                        break
            if val is None:
                # en 5/6/7 sans détail re-scrapé → gain en attente plutôt que surpaie.
                note = f"Rapport « Multi en {n} » non publié — gain en attente."
        else:
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
                nb_partants: int, rapports_detail: Optional[dict] = None,
                non_partants: Optional[set[int]] = None) -> dict:
    """
    Règle un plan de mise complet (dict issu de plan_to_dict) contre le résultat.

    Retourne le bilan agrégé + le détail par pari (avec gagné/gain).
    `rapports_detail` → rapport placé EXACT (sinon agrégat).
    `non_partants` → numéros déclarés non-partants → paris remboursés (neutres).
    """
    paris_bilan: list[dict] = []
    total_mise = 0.0
    total_gain = 0.0
    nb_en_attente = 0
    nb_rembourse = 0

    for niveau in plan.get("niveaux", []):
        for pari in niveau.get("paris", []):
            numeros = [c["numero"] for c in pari.get("chevaux", [])]
            mise = float(pari.get("mise", 0) or 0)
            res = settle_pari(pari["type"], numeros, classement, rapports, nb_partants,
                              rapports_detail, non_partants)
            gain = None
            # statut : "gagne" | "perdu" | "en_attente" (rapport pas publié) | "rembourse" (NP)
            if res.get("rembourse"):
                # Pari remboursé : neutre pour le ROI (ni mise, ni gain comptés) et
                # exclu du win-rate. Comme si le pari n'avait jamais été pris.
                statut = "rembourse"
                gain = mise
                nb_rembourse += 1
            elif res["gagne"]:
                if res["rapport_reel"] is not None:
                    gain = round(mise * res["rapport_reel"] * res.get("gain_mult", 1.0), 2)
                    total_gain += gain
                    total_mise += mise
                    statut = "gagne"
                else:
                    statut = "en_attente"
                    nb_en_attente += 1
                    total_mise += mise
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
                # Ticket de couverture : reporté tel quel dans le bilan pour que le
                # joueur retrouve à l'arrivée la nature du pari qu'on lui a proposé
                # (petite mise « chance en plus », pas le multiplicateur du profil).
                "couverture": bool(pari.get("couverture")),
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
        "nb_rembourse": nb_rembourse,
        "en_attente": nb_en_attente > 0,
        "total_mise": total_mise,
        "total_gain": total_gain,
        "net": net,
        "roi": roi,
        # net/ROI provisoires tant que des rapports manquent
        "provisoire": nb_en_attente > 0,
        "gain_indetermine": nb_en_attente > 0,  # rétro-compat
    }
