"""
Règlement de paris (bet settlement) — BlackTurf.

Règle un pari généré par le plan de mise contre le RÉSULTAT RÉEL d'une course
(ordre d'arrivée officiel + rapports PMU définitifs).

Principe d'intégrité : on ne JAMAIS invente de rapport. Depuis le 2026-09-30, le
ticket est d'abord cherché dans le détail officiel (`rapports_detail` : chaque
combinaison payée avec son rapport, « 1 NP » et ex æquo compris — cf.
_regler_par_detail) ; le calcul d'après le classement ci-dessous ne sert plus que de
repli quand ce détail manque, et de contrôle (gagné à l'arrivée mais absent du
détail → en attente). Si le pari gagne mais que le rapport n'est pas publié, on
renvoie `rapport_reel=None` et `gain=None` (gain indéterminé, pas inventé).

Repli sur le classement — les rapports agrégés sont ceux de la COMBINAISON GAGNANTE :
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
#
# ⚠️ POOLS INTERNATIONAUX : sur une course étrangère reprise par le PMU, le rapport
# est publié sous `<type>_international` et JAMAIS sous la clé habituelle. La variante
# doit donc figurer ici pour CHAQUE type offert sur ces réunions (liste de référence :
# `_CODE_FLAG` de services/bet_catalog.py ; verrou : tests/test_rapports_internationaux.py).
# Une clé manquante ne se voit pas comme une erreur, elle se lit comme « rapport pas
# encore publié » : le 2026-09-09, 09092026R6C6 a payé un `couple_ordre_international`
# de 24,6 sur un Couplé Ordre GAGNANT ; faute de la clé, le plan est resté `partial`,
# donc `journee_complete` faux, donc la story du soir n'est jamais partie.
_RAPPORT_KEYS = {
    "Simple Gagnant": ("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international"),
    "Simple Placé":   ("simple_place", "e_simple_place", "simple_place_international"),
    "Couplé Gagnant": ("couple_gagnant", "e_couple_gagnant", "couple_gagnant_international"),
    "Couplé Placé":   ("couple_place", "e_couple_place", "couple_place_international"),
    # Paris à l'ORDRE (champ réduit) — combinaison gagnante dans l'ordre exact.
    "Couplé Ordre":   ("couple_ordre", "e_couple_ordre", "couple_ordre_international"),
    "Trio":           ("trio", "e_trio", "trio_international"),
    "Trio Ordre":     ("trio_ordre", "e_trio_ordre", "trio_ordre_international"),
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


def _rapport_par_libelle(rapports_detail: Optional[dict], keys: tuple[str, ...],
                         libelle: str, numeros: set[int], *, exact: bool = True
                         ) -> Optional[float]:
    """Lit le rapport du rang payé, sans confondre Ordre, Désordre et Bonus.

    « ordre » est une sous-chaîne de « désordre » : le rang Ordre exige donc un
    libellé qui contient « ordre » SANS « désordre » (ex. « e-Quinté+ Ordre » ou
    « e-Quinté+ Ordre + e-Tirelire »).
    """
    for key in keys:
        for entry in (rapports_detail or {}).get(key, []):
            name = str(entry.get("libelle") or "").casefold()
            wanted = libelle.casefold()
            if wanted == "bonus":
                ok = name.endswith(wanted)
            elif wanted == "ordre":
                ok = "ordre" in name and "désordre" not in name
            else:
                ok = wanted in name
            if not ok:
                continue
            found = {int(n) for n in re.findall(r"\d+", str(entry.get("combinaison") or ""))}
            if (found == numeros if exact else found.issubset(numeros)) and found:
                try:
                    value = float(entry["rapport"])
                    return value if value > 0 else None
                except (TypeError, ValueError, KeyError):
                    continue
    return None


def _rapport_bonus_4sur5(rapports_detail: Optional[dict], keys: tuple[str, ...],
                         top5: set[int]) -> Optional[float]:
    """Rapport Bonus 4sur5 quand le 4-uplet EXACT du ticket n'est pas dans le détail.

    Règle PMU du e-Quinté+ : le Bonus 4sur5 paie tout ticket qui contient 4 des 5
    premiers, quels qu'ils soient. Le PMU publie une entrée par 4-uplet (les cinq
    sous-ensembles de l'arrivée, même rapport — vérifié en base sur 97 courses sur
    98, la 98ᵉ ayant un ex æquo : 9 entrées). Un détail incomplet (collecte tronquée)
    ne doit pas laisser en attente un ticket gagnant : on prend le rapport d'une
    entrée « Bonus 4sur5 » qui est bien un 4-uplet de l'arrivée réelle.
    """
    for key in keys:
        for entry in (rapports_detail or {}).get(key, []):
            if "bonus 4sur5" not in str(entry.get("libelle") or "").casefold():
                continue
            found = {int(n) for n in re.findall(r"\d+", str(entry.get("combinaison") or ""))}
            if len(found) == 4 and found.issubset(top5):
                try:
                    value = float(entry["rapport"])
                except (TypeError, ValueError, KeyError):
                    continue
                if value > 0:
                    return value
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


# ─── Règlement sur le détail officiel ──────────────────────────────────────
# Le PMU publie chaque rapport AVEC sa combinaison payée (« 4-2-12 », « 13-NP »…).
# Régler un ticket, c'est chercher sa combinaison dans cette liste : c'est ce que fait
# le PMU, ex æquo, non-partants et places payées compris. Méthode reprise du Défi du
# mois (services/defi.py, 2026-09-30). Rejoué le même jour sur 45 jours d'arrivées
# réelles : le calcul d'après le classement remboursait les tickets « 1 NP » que le
# PMU paie (et qui sont perdus si le reste est mauvais), recomptait les places payées
# d'après nb_partants − non-partants (≈190 Couplés Placés et ≈90 Simples Placés
# gagnants jamais payés), ratait les ex æquo (Multi à la 4ᵉ place réglé perdant,
# Couplé/Trio payés au rapport d'une autre combinaison) et ajoutait la Tirelire au
# rapport du Quinté+ Ordre.
_NP = -1
# Paris dont le PMU publie des rapports « N NP ». Simples, Multi, Quarté+, Quinté+ :
# aucun rapport NP publié sur 45 jours alors que des non-partants y figuraient → une
# combinaison qui contient un non-partant reste remboursée.
_FAMILLES_AVEC_NP = {"Couplé Gagnant", "Couplé Placé", "Couplé Ordre", "Trio", "Trio Ordre",
                     "2sur4", "Super 4", "Tiercé", "Pick5"}
_CLES_DETAIL: dict[str, tuple[tuple[str, ...], ...]] = {
    # Groupes de clés essayés dans l'ordre : le premier qui a des entrées est lu seul
    # (un Mini Multi ne doit pas être payé au rapport du Multi s'il a le sien).
    "Simple Gagnant": (("simple_gagnant", "e_simple_gagnant", "simple_gagnant_international"),),
    "Simple Placé": (("simple_place", "e_simple_place", "simple_place_international"),),
    "Couplé Gagnant": (("couple_gagnant", "e_couple_gagnant", "couple_gagnant_international"),),
    "Couplé Placé": (("couple_place", "e_couple_place", "couple_place_international"),),
    "Couplé Ordre": (("couple_ordre", "e_couple_ordre", "couple_ordre_international"),),
    "Trio": (("trio", "e_trio", "trio_international"),),
    "Trio Ordre": (("trio_ordre", "e_trio_ordre", "trio_ordre_international"),),
    "Super 4": (("super_quatre", "e_super_quatre"),),
    "2sur4": (("deux_sur_quatre", "e_deux_sur_quatre"),),
    "Tiercé": (("tierce", "e_tierce", "tierce_ordre", "e_tierce_ordre"),),
    "Quarté+": (("quarte_plus", "e_quarte_plus"),),
    "Quinté+": (("quinte_plus", "e_quinte_plus"),),
    "Pick5": (("pick5", "e_pick5", "pick_5"),),
    "Multi": (("multi", "e_multi"),),
    "Mini Multi": (("mini_multi", "e_mini_multi"), ("multi", "e_multi")),
}
_ORDONNES = {"Couplé Ordre", "Trio Ordre", "Super 4"}


def _famille_detail(type_pari: str) -> Optional[str]:
    t = type_pari or ""
    if t.startswith("Mini Multi en "):
        return "Mini Multi"
    if t.startswith("Multi en "):
        return "Multi"
    for f in ("Tiercé", "Quarté+", "Quinté+"):
        if t.startswith(f):
            return f
    return t if t in _CLES_DETAIL else None


def _entrees_detail(rapports_detail: Optional[dict], famille: str) -> tuple[list[dict], bool]:
    """([{libelle, comb (numéros, -1 pour NP), rapport}], remboursement_general).

    `remboursement_general` : le PMU a publié « Remboursement … / Autres Chevaux »
    (ex. Super 4 d'une course où moins de quatre chevaux ont terminé)."""
    for groupe in _CLES_DETAIL[famille]:
        out, vus, remb = [], set(), False
        for cle in groupe:
            for e in (rapports_detail or {}).get(cle) or []:
                if not isinstance(e, dict):
                    continue
                libelle = str(e.get("libelle") or "").casefold()
                brut = str(e.get("combinaison") or "")
                if libelle.startswith("remboursement") and "autre" in brut.casefold():
                    remb = True
                    continue
                try:
                    rapport = float(e.get("rapport"))
                except (TypeError, ValueError):
                    continue
                if rapport <= 0 or not brut or "autre" in brut.casefold():
                    continue
                parts = [p.strip() for p in brut.split("-")]
                if not all(p.upper() == "NP" or p.isdigit() for p in parts):
                    continue
                comb = [_NP if p.upper() == "NP" else int(p) for p in parts]
                cle_unique = (libelle, tuple(comb), rapport)
                if cle_unique not in vus:
                    vus.add(cle_unique)
                    out.append({"libelle": libelle, "comb": comb, "rapport": rapport})
        if out or remb:
            return out, remb
    return [], False


def _combinaison_payee(entrees: list[dict], ticket: list[int], np_set: set[int],
                       ordonne: bool, filtre=lambda lib: True) -> Optional[float]:
    """Rapport de l'entrée qui correspond EXACTEMENT au ticket (non-partants du ticket
    rapprochés des « NP » de la combinaison), ou None."""
    nb_np = sum(1 for n in ticket if n in np_set)
    for e in entrees:
        if not filtre(e["libelle"]):
            continue
        comb = e["comb"]
        if len(comb) != len(ticket) or comb.count(_NP) != nb_np:
            continue
        if ordonne:
            ok = all((c == _NP and t in np_set) or (c != _NP and c == t)
                     for c, t in zip(comb, ticket))
        else:
            ok = sorted(c for c in comb if c != _NP) == sorted(t for t in ticket if t not in np_set)
        if ok:
            return e["rapport"]
    return None


def _np_publie(entrees: list[dict], nb_np: int) -> bool:
    return any(e["comb"].count(_NP) == nb_np for e in entrees)


def _regler_par_detail(type_pari: str, numeros: list[int], rapports_detail: Optional[dict],
                       np_set: set[int], ordre_joue: bool,
                       positions: Optional[dict[int, int]] = None) -> Optional[dict]:
    """Règlement d'après le détail officiel ; None si le détail ne permet pas de conclure
    (rien de publié pour ce type) — settle_pari retombe alors sur le classement.

    Mêmes conventions de retour que settle_pari. Un non-partant dans une combinaison :
    payée au rapport « N NP » publié si le reste est bon, perdue sinon ; remboursée si
    le PMU ne publie aucun rapport à ce nombre de non-partants, ou si le reste est bon
    selon la règle « 1 NP » mais que SA combinaison n'est pas publiée (on ne sait pas
    ce qu'il aurait payé : jamais un gain inventé, jamais une perte inventée).

    `positions` (numéro → place à l'arrivée) sert aux Bonus du Quinté+ et à la règle
    « 1 NP » ; sans lui, seul le détail décide.
    """
    from itertools import combinations

    famille = _famille_detail(type_pari)
    if famille is None:
        return None
    positions = positions or {}
    top5 = {n for n, p in positions.items() if p <= 5} or None
    placees = _places_publiees(rapports_detail) if famille == "Couplé Placé" else None
    entrees, remb_general = _entrees_detail(rapports_detail, famille)
    rembourse = {"gagne": False, "rapport_reel": 1.0, "gain_mult": 1.0,
                 "rapport_approximatif": False, "rembourse": True,
                 "note": "Cheval non-partant — mise remboursée (rapport 1.0)."}
    if remb_general and not entrees:
        return {**rembourse, "note": "Pari remboursé par le PMU."}
    if not entrees:
        return None
    entrees = _completer_tronquees(entrees, famille, positions)
    nums = [int(n) for n in numeros]
    perd = {"gagne": False, "rapport_reel": None, "gain_mult": 1.0,
            "rapport_approximatif": False, "note": None}

    def gagne(rapport: float, mult: float = 1.0, note: Optional[str] = None) -> dict:
        return {"gagne": True, "rapport_reel": float(rapport), "gain_mult": float(mult),
                "rapport_approximatif": False, "note": note}

    def combi_remboursee(c: list[int]) -> bool:
        k = sum(1 for n in c if n in np_set)
        if k == 0:
            return False
        if famille not in _FAMILLES_AVEC_NP or not _np_publie(entrees, k):
            return True
        # Reste bon selon la règle « 1 NP » mais combinaison absente du détail
        # (vu : Couplé Placé gagnant + NP non publié quand d'autres le sont).
        return (k == 1 and _reste_bon_1np(famille, c, np_set, positions, placees)
                and _combinaison_payee(entrees, c, np_set, famille in _ORDONNES) is None)

    if famille in ("2sur4", "Pick5"):
        # Formule : C(N, k) combinaisons, la mise se répartit dessus ; chacune est
        # réglée à part (payée, perdue, ou remboursée si elle contient un NP sans
        # rapport publié) — pas tout le ticket remboursé pour un seul non-partant.
        k = 2 if famille == "2sur4" else 5
        if len(set(nums)) < k:
            return perd
        combis = [list(c) for c in combinations(nums, k)]
        payes, n_remb = [], 0
        for c in combis:
            if combi_remboursee(c):
                n_remb += 1
                continue
            r = _combinaison_payee(entrees, c, np_set, False)
            if r is not None:
                payes.append(r)
        if n_remb == len(combis):
            return rembourse
        if not payes and not n_remb:
            return perd
        if len(combis) == 1:
            return gagne(payes[0])
        retour = sum(payes) + n_remb          # pour 1 € par combinaison
        note = f"Formule {len(nums)} chevaux : {len(payes)}/{len(combis)} combinaison(s) gagnante(s)"
        if n_remb:
            note += f", {n_remb} remboursée(s) (non-partant)"
        if not payes:
            # Rien de gagnant, seulement des combinaisons remboursées : la part de la
            # mise rendue au rapport 1.0.
            return gagne(1.0, n_remb / len(combis), note + ".")
        moyen = sum(payes) / len(payes)
        return gagne(moyen, retour / (len(combis) * moyen), note + ".")

    if combi_remboursee(nums):
        return rembourse

    if famille in ("Multi", "Mini Multi"):
        # Ex æquo à la 4ᵉ place : plusieurs combinaisons de 4 publiées, chacune paie
        # le ticket qui la contient.
        n = len(nums)
        m = re.search(r"en\s+(\d+)", type_pari or "")
        if m:
            n = int(m.group(1))
        avec_libelle = False
        for e in entrees:
            mm = re.search(r"en\s+(\d+)", e["libelle"])
            avec_libelle = avec_libelle or bool(mm)
            if mm and int(mm.group(1)) == n and _NP not in e["comb"] and set(e["comb"]) <= set(nums):
                return gagne(e["rapport"])
        if not avec_libelle and 0 <= n - 4 < len(entrees):
            # Vieux scrape sans libellé : entrées ordonnées en 4, 5, 6, 7.
            e = entrees[n - 4]
            if _NP not in e["comb"] and set(e["comb"]) <= set(nums):
                return gagne(e["rapport"])
        return perd

    if famille == "Tiercé":
        est_ordre = lambda l: "ordre" in l and "désordre" not in l and " np" not in l
        if type_pari == "Tiercé Ordre" or ordre_joue:
            r = _combinaison_payee(entrees, nums, np_set, True, est_ordre)
            if r is not None:
                return gagne(r, note="Rang de gain : Ordre.")
        if type_pari == "Tiercé Ordre":
            # Pari « Ordre » du plan : payé seulement dans l'ordre exact (convention
            # du plan, jamais le Désordre à sa place) — ou au rapport « 1 NP », seul
            # rapport publié pour un ticket qui contient un non-partant.
            if not any(n in np_set for n in nums):
                return perd
            r = _combinaison_payee(entrees, nums, np_set, False, lambda l: " np" in l)
            return gagne(r) if r is not None else perd
        r = _combinaison_payee(entrees, nums, np_set, False,
                               lambda l: "désordre" in l or " np" in l)
        return gagne(r) if r is not None else perd

    if famille in ("Quarté+", "Quinté+"):
        if ordre_joue:
            est_ordre = lambda l: "ordre" in l and "désordre" not in l
            # Ordre SANS la Tirelire (jackpot à part, pas le rapport du ticket) ;
            # « Ordre + Tirelire » seulement si c'est le seul rapport Ordre publié.
            r = (_combinaison_payee(entrees, nums, np_set, True,
                                    lambda l: est_ordre(l) and "tirelire" not in l)
                 or _combinaison_payee(entrees, nums, np_set, True, est_ordre))
            if r is not None:
                return gagne(r, note="Rang de gain : Ordre.")
        r = _combinaison_payee(entrees, nums, np_set, False, lambda l: "désordre" in l)
        if r is not None:
            return gagne(r)
        # Bonus : le PMU publie la combinaison du bonus (4 ou 3 chevaux), payée à
        # tout ticket qui la contient. Un seul rang : le plus élevé.
        for filtre, taille, rang in ((lambda l: "4sur5" in l, 4, "Bonus 4sur5"),
                                     (lambda l: l.endswith("bonus") or l.endswith("bonus 3"),
                                      3, "Bonus 3" if famille == "Quinté+" else "Bonus")):
            for e in entrees:
                if (filtre(e["libelle"]) and len(e["comb"]) == taille and set(e["comb"]) <= set(nums)
                        and (top5 is None or set(e["comb"]) <= top5)):
                    return gagne(e["rapport"], note=f"Rang de gain : {rang}.")
            if taille == 4 and top5 is not None and len(set(nums) & top5) == 4:
                # Détail tronqué : le 4-uplet du ticket manque, mais le Bonus 4sur5
                # paie tout ticket qui contient 4 des 5 premiers, au même rapport.
                for e in entrees:
                    if filtre(e["libelle"]) and len(e["comb"]) == 4 and set(e["comb"]) <= top5:
                        return gagne(e["rapport"], note=f"Rang de gain : {rang}.")
        return perd

    r = _combinaison_payee(entrees, nums, np_set, famille in _ORDONNES)
    return gagne(r) if r is not None else perd


# Longueur d'une combinaison publiée, pour les paris à taille fixe.
_TAILLE_COMBI = {"Couplé Gagnant": 2, "Couplé Ordre": 2, "Trio": 3, "Trio Ordre": 3,
                 "Super 4": 4, "Pick5": 5}


def _completer_tronquees(entrees: list[dict], famille: str,
                         positions: dict[int, int]) -> list[dict]:
    """Combinaison publiée tronquée (« 5-6 » pour un Trio : vu 34 fois en septembre
    2026, au rapport de la vraie combinaison) : complétée par l'arrivée officielle
    quand elle en est bien le début et qu'aucun ex æquo ne touche les places
    concernées. Sinon laissée telle quelle (elle ne correspondra à aucun ticket)."""
    taille = _TAILLE_COMBI.get(famille)
    if not taille or not positions:
        return entrees
    par_place: dict[int, list[int]] = {}
    for n, p in positions.items():
        par_place.setdefault(p, []).append(n)
    arrivee = []
    for p in range(1, taille + 1):
        if len(par_place.get(p, [])) != 1:
            return entrees
        arrivee.append(par_place[p][0])
    out = []
    for e in entrees:
        comb = e["comb"]
        k = len(comb)
        if 0 < k < taille and _NP not in comb and (
                comb == arrivee[:k] if famille in _ORDONNES else set(comb) == set(arrivee[:k])):
            e = {**e, "comb": comb + arrivee[k:]}
        out.append(e)
    return out


# Règle « 1 NP » d'après les rapports publiés (45 jours, 2026-09-30) : places que
# doivent occuper les autres chevaux du ticket pour toucher le rapport « 1 NP ».
# Couplé Placé : l'autre placé (lu dans la liste des placés, pas ici).
_PLACES_1NP = {"Couplé Gagnant": (1,), "Trio": (1, 2), "Tiercé": (1, 2),
               "Pick5": (1, 2, 3, 4)}


def _reste_bon_1np(famille: str, combi: list[int], np_set: set[int],
                   positions: dict[int, int], placees: Optional[set[int]]) -> bool:
    reste = [n for n in combi if n not in np_set]
    if not positions or not reste:
        return False
    places = [positions.get(n) for n in reste]
    if any(p is None for p in places):
        return False
    if famille == "2sur4":
        return places[0] <= 4
    if famille == "Couplé Placé":
        return bool(placees) and reste[0] in placees
    if famille in ("Trio Ordre", "Super 4"):
        # Ordonnés : les autres, dans l'ordre du ticket, aux premières places.
        return places == list(range(1, len(reste) + 1))
    attendu = _PLACES_1NP.get(famille)
    return attendu is not None and tuple(sorted(places)) == attendu


def _places_publiees(rapports_detail: Optional[dict]) -> Optional[set[int]]:
    """Chevaux placés d'après les rapports Simple Placé publiés (la liste officielle,
    ex æquo et partants retirés compris) ; None si non publiés."""
    entrees, _ = _entrees_detail(rapports_detail, "Simple Placé")
    places = {e["comb"][0] for e in entrees if len(e["comb"]) == 1 and e["comb"][0] != _NP}
    return places or None


def settle_pari(
    type_pari: str,
    numeros: list[int],
    classement: list[dict],
    rapports: Optional[dict],
    nb_partants: int,
    rapports_detail: Optional[dict] = None,
    non_partants: Optional[set[int]] = None,
    ordre_joue: bool = True,
) -> dict:
    """
    Règle un pari unique.

    D'abord sur le détail officiel (`rapports_detail` : combinaisons payées publiées
    par le PMU, cf. _regler_par_detail). Sans détail pour ce type : calcul d'après le
    classement (_settle_par_classement). Un ticket que le classement donne gagnant
    sans ambiguïté mais que le détail publié ne paie pas (détail incomplet ?) reste
    en attente (gagne=True, rapport_reel=None), jamais perdu ni inventé.

    `ordre_joue` (Tiercé, Quarté+, Quinté+ « désordre ») : le ticket a été joué dans
    l'ordre de `numeros` — cas d'un ticket unitaire. Arrivé dans cet ordre exact, il
    paie alors le rapport Ordre. False pour une combinaison issue d'un champ, réglée au
    Désordre (on ne suppose pas un ordre que la formule n'a pas forcément couvert :
    jamais de surpaiement).

    Retourne :
        {
          "gagne": bool,
          "rapport_reel": float | None,   # rapport PMU base 1€ (None si indispo)
          "gain_mult": float,             # part de la mise payée au rapport
          "rapport_approximatif": bool,
          "rembourse": True,              # (seulement si la mise est rendue)
          "note": str | None,
        }
    Le gain monétaire est calculé par l'appelant : mise * rapport_reel * gain_mult.
    """
    # Un cheval payé en Simple Gagnant/Placé a couru : le drapeau non_partant posé en
    # base à tort (vu sur 3 courses depuis juin, ex. 06082026R6C4 : le « NP » a gagné)
    # ne doit ni rembourser ni régler au rapport « NP » un ticket qui l'a joué.
    payes_simples = {e["comb"][0] for f in ("Simple Gagnant", "Simple Placé")
                     for e in _entrees_detail(rapports_detail, f)[0]
                     if len(e["comb"]) == 1 and e["comb"][0] != _NP}
    np_set = set(int(n) for n in (non_partants or [])) - payes_simples
    calcul = _settle_par_classement(type_pari, numeros, classement, rapports, nb_partants,
                                    rapports_detail, np_set, ordre_joue)
    if calcul.get("note") == "Résultat indisponible":
        return calcul
    positions: dict[int, int] = {}
    for e in classement or []:
        try:
            p = int(e["position"])
            if p >= 1:
                positions.setdefault(int(e["numero"]), p)
        except (TypeError, ValueError, KeyError):
            continue
    par_detail = _regler_par_detail(type_pari, numeros, rapports_detail, np_set, ordre_joue,
                                    positions)
    if par_detail is None:
        return calcul
    if (par_detail["gagne"] and ordre_joue
            and _famille_detail(type_pari) in ("Tiercé", "Quarté+", "Quinté+")
            and not str(par_detail.get("note") or "").endswith("Ordre.")
            and _dans_l_ordre_exact(numeros, classement)):
        # Arrivée dans l'ordre exact du ticket mais rapport Ordre pas publié : on
        # attend plutôt que de payer le Désordre à un ticket qui vaut l'Ordre.
        return {**par_detail, "rapport_reel": None, "gain_mult": 1.0,
                "note": "Rapport Ordre pas encore publié — gain en attente."}
    if (not par_detail["gagne"] and not par_detail.get("rembourse")
            and calcul["gagne"] and _gagne_sans_ambiguite(type_pari, numeros, classement,
                                                          np_set, rapports_detail)):
        return {"gagne": True, "rapport_reel": None, "gain_mult": 1.0,
                "rapport_approximatif": False,
                "note": "Rapport de cette combinaison pas encore publié — gain en attente."}
    return par_detail


def _dans_l_ordre_exact(numeros: list[int], classement: list[dict]) -> bool:
    par_pos: dict[int, list[int]] = {}
    for e in classement or []:
        try:
            par_pos.setdefault(int(e["position"]), []).append(int(e["numero"]))
        except (TypeError, ValueError, KeyError):
            continue
    return bool(numeros) and all(par_pos.get(i + 1) == [int(n)] for i, n in enumerate(numeros))


def _gagne_sans_ambiguite(type_pari: str, numeros: list[int], classement: list[dict],
                          np_set: set[int], rapports_detail: Optional[dict]) -> bool:
    """Le classement suffit-il à dire le ticket gagnant ? Non s'il contient un
    non-partant, si un ex æquo touche les places qui comptent, ou pour un placé dont
    la liste officielle des placés n'est pas publiée (nombre de places incertain)."""
    if any(int(n) in np_set for n in numeros):
        return False
    positions = [e.get("position") for e in classement or [] if e.get("position") is not None]
    try:
        positions = [int(p) for p in positions]
    except (TypeError, ValueError):
        return False
    famille = _famille_detail(type_pari) or type_pari
    utiles = {"Simple Gagnant": 1, "Couplé Gagnant": 2, "Couplé Ordre": 2, "Trio": 3,
              "Trio Ordre": 3, "Tiercé": 3, "Super 4": 4, "2sur4": 4, "Quarté+": 4,
              "Multi": 4, "Mini Multi": 4}.get(famille, 5)
    tete = [p for p in positions if p <= utiles]
    if len(tete) != len(set(tete)) and famille not in ("Multi", "Mini Multi"):
        # Ex æquo sur une place qui compte. Pas pour le Multi : le classement y exige
        # TOUS les ex æquo des quatre premières places, il ne se trompe pas en gagnant.
        return False
    if type_pari in ("Simple Placé", "Couplé Placé"):
        return _places_publiees(rapports_detail) is not None
    return True


def _settle_par_classement(
    type_pari: str,
    numeros: list[int],
    classement: list[dict],
    rapports: Optional[dict],
    nb_partants: int,
    rapports_detail: Optional[dict] = None,
    non_partants: Optional[set[int]] = None,
    ordre_joue: bool = True,
) -> dict:
    """Calcul d'avant le 2026-09-30, d'après le classement : repli quand le détail
    officiel n'est pas publié pour ce type, et contrôle du règlement sur le détail."""
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
    #
    # Sémantique (vérifiée 2026-10-07) : `courses.nb_partants` = champ DÉCLARÉ, NP
    # compris (scraper PMU : len(participants), statut NON_PARTANT inclus — cf.
    # data_quality et mise_calculator.champ_reel). Mais les appelants se replient
    # sur `len(classement)` quand il manque — or le classement ne contient QUE les
    # chevaux qui ont couru (arrivée + disqualifiés) : y retrancher les NP les
    # retirait DEUX FOIS (9 coureurs dont 1 NP → 7 → 2 places payées au lieu de 3).
    # Garde-fou : le champ réel ne peut jamais être inférieur au nombre de chevaux
    # distincts, hors NP, présents dans le classement officiel.
    coureurs_classement = set()
    for e in classement or []:
        try:
            coureurs_classement.add(int(e.get("numero")))
        except (TypeError, ValueError):
            continue
    coureurs_classement -= np_set
    if nb_partants:
        eff_partants = max(0, int(nb_partants) - len(np_set))
    else:
        eff_partants = len(coureurs_classement)
    eff_partants = max(eff_partants, len(coureurs_classement))
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
    # Liste officielle des placés quand le PMU l'a publiée (Simple Placé) : elle
    # prime toujours sur le recompte (ex æquo, retirés tardifs).
    placed = _places_publiees(rapports_detail) or _topset(nb_pl)
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
        gagne = len(sel) == 4 and (sel.issubset(top4) or
                                   (len(top3) == 3 and top3.issubset(sel)))
    elif type_pari in ("Quinté+ Désordre", "Quinté+ Flexi", "Quinté+"):
        gagne = len(sel) == 5 and (sel.issubset(top5) or len(sel & top5) == 4
                                   or (len(top3) == 3 and top3.issubset(sel)))
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
        elif type_pari in ("Tiercé Désordre", "Quarté+ Désordre", "Quarté+",
                           "Quinté+ Désordre", "Quinté+ Flexi", "Quinté+"):
            # Le rapport agrégé est souvent le premier rapport publié : Ordre.
            # Pour les tickets désordre, seul le détail de la bonne combinaison
            # permet de déterminer un gain fiable.
            # Ticket UNITAIRE joué dans l'ordre de `numeros` : arrivé dans cet ordre
            # exact, le PMU paie le rang Ordre (même règle que le Quinté+ ci-dessous,
            # audit du 2026-09-28). Le payer au Désordre sous-évaluait le gain.
            def _dans_l_ordre(n: int) -> bool:
                return (ordre_joue and len(numeros) == n and all(
                    num_by_pos.get(i + 1) == int(numeros[i]) for i in range(n)))

            if type_pari == "Tiercé Désordre":
                label, combination = ("Ordre" if _dans_l_ordre(3) else "Désordre"), sel
            elif type_pari in ("Quarté+ Désordre", "Quarté+"):
                if sel.issubset(top4):
                    label, combination = ("Ordre" if _dans_l_ordre(4) else "Désordre"), sel
                else:
                    label, combination = "Bonus", sel & top3
            elif sel.issubset(top5):
                # Règle PMU du e-Quinté+ : Ordre = les 5 premiers dans l'ordre exact
                # du ticket, Désordre = les 5 premiers dans un autre ordre.
                ordre_exact = (ordre_joue and len(numeros) == 5 and all(
                    num_by_pos.get(i + 1) == int(numeros[i]) for i in range(5)))
                label, combination = ("Ordre" if ordre_exact else "Désordre"), sel
            elif len(sel & top5) == 4:
                # Bonus 4sur5 : 4 chevaux QUELCONQUES du ticket parmi les 5 premiers.
                label, combination = "Bonus 4sur5", sel & top5
            else:
                # Bonus 3 : les 3 PREMIERS de l'arrivée (publié sur la seule
                # combinaison du podium) — 3 chevaux sur 5 hors podium ne paient rien,
                # c'est la condition de `gagne` plus haut.
                label, combination = "Bonus 3", sel & top3
            val = _rapport_par_libelle(rapports_detail, keys, label, combination)
            if val is None and label == "Bonus 4sur5":
                val = _rapport_bonus_4sur5(rapports_detail, keys, top5)
            if label.startswith("Bonus") or label == "Ordre":
                note = f"Rang de gain : {label}."
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


def settle_module_quinte(module: Optional[dict], classement: list[dict],
                         rapports: Optional[dict], nb_partants: int,
                         rapports_detail: Optional[dict] = None,
                         non_partants: Optional[set[int]] = None) -> Optional[dict]:
    """Règle le module Quinté+ d'un plan, À PART du plan principal.

    Le module est un champ de N chevaux joué en C(N, 5) combinaisons, chacune à
    `cout_total / C(N, 5)` € (mise de base × Flexi). Chaque combinaison est réglée
    par `settle_pari` — donc au rapport détaillé du rang exact (Désordre, Bonus
    4sur5, Bonus 3), jamais à l'agrégat Ordre — et rapporte mise × rapport pour 1 €.
    Plusieurs combinaisons d'un même champ peuvent gagner (un Désordre et des
    Bonus 4sur5, par exemple) : c'est la règle du champ réduit.

    Limites connues : dans un CHAMP, une combinaison arrivée dans l'ordre exact
    est payée au Désordre (sous-estime, jamais surpaie) — seul le tendu, ticket
    unitaire joué dans l'ordre affiché, peut toucher l'Ordre ; une combinaison
    contenant un non-partant est remboursée (la règle PMU du cheval de complément
    n'est pas représentée).

    None si le plan n'a pas de module joué (course non Quinté+, module
    indisponible ou non finançable).
    """
    if not module or not module.get("disponible"):
        return None
    try:
        cout = float(module.get("cout_total") or 0.0)
    except (TypeError, ValueError):
        return None
    numeros = [int(c["numero"]) for c in (module.get("chevaux") or [])
               if c.get("numero") is not None]
    # Combinaisons EXPLICITES (profil risqué : plusieurs tickets tendus distincts) :
    # chacune est un ticket unitaire joué dans l'ordre affiché — Ordre possible.
    explicites = [[int(x) for x in c] for c in (module.get("combinaisons") or [])
                  if len(set(c)) == 5]
    if cout <= 0 or (not explicites and len(numeros) < 5):
        return None
    from itertools import combinations
    combis = [tuple(c) for c in explicites] if explicites else list(combinations(numeros, 5))
    tendus = bool(explicites) or len(combis) == 1
    mise_combi = cout / len(combis)
    mise = gain = 0.0
    nb_gagnantes = nb_attente = nb_rembourse = 0
    gagnantes: list[dict] = []
    for combi in combis:
        res = settle_pari(module.get("type_pari") or "Quinté+ Désordre", list(combi),
                          classement, rapports, nb_partants, rapports_detail, non_partants,
                          # Tendu = ticket unitaire joué dans l'ordre affiché (Ordre
                          # possible) ; champ = combinaisons réglées au Désordre.
                          ordre_joue=tendus)
        if res.get("rembourse"):
            nb_rembourse += 1          # neutre, comme dans settle_plan
            continue
        mise += mise_combi
        if not res["gagne"]:
            continue
        if res["rapport_reel"] is None:
            nb_attente += 1
            continue
        g = mise_combi * res["rapport_reel"] * res.get("gain_mult", 1.0)
        gain += g
        nb_gagnantes += 1
        gagnantes.append({"combinaison": sorted(combi), "rapport_reel": res["rapport_reel"],
                          "gain": round(g, 2), "note": res.get("note"),
                          "rang": _rang_quinte(res.get("note"))})
    mise, gain = round(mise, 2), round(gain, 2)
    net = round(gain - mise, 2)
    return {
        "type": module.get("type_pari") or "Quinté+ Désordre",
        "couverture": module.get("couverture"),
        "chevaux": numeros or sorted({x for c in combis for x in c}),
        "nb_combinaisons": len(combis),
        "mise_par_combinaison": round(mise_combi, 4),
        "total_mise": mise,
        "total_gain": gain,
        "net": net,
        "roi": round(net / mise * 100, 1) if mise > 0 else 0.0,
        "nb_gagnantes": nb_gagnantes,
        # Combinaisons payées à un rang Bonus (4sur5 ou 3) — un retour partiel,
        # pas les cinq premiers.
        "nb_bonus": sum(1 for g in gagnantes if g["rang"].startswith("Bonus")),
        "nb_en_attente": nb_attente,
        "nb_rembourse": nb_rembourse,
        "en_attente": nb_attente > 0,
        "gagnantes": gagnantes,
    }


def _rang_quinte(note: Optional[str]) -> str:
    """Rang payé d'une combinaison Quinté+ gagnante, lu dans la note de settle_pari
    (« Rang de gain : Bonus 4sur5. ») — sans note, c'est le Désordre."""
    m = re.search(r"Rang de gain : ([^.]+)\.", note or "")
    return m.group(1).strip() if m else "Désordre"


# ─────────────────────────────────────────────────────────────
# Ticket Quinté+ ENREGISTRÉ dans le capital (bankroll_entries)
# ─────────────────────────────────────────────────────────────
# « Enregistrer ce plan » (retiré le 2026-09-25 au profit du Défi du mois ; ne
# sert plus qu'à régler les lignes historiques) écrivait le ticket Quinté+ du plan
# comme UNE ligne de capital : type « Quinté+ Désordre », tous les chevaux du champ, mise = coût
# total du ticket. Le préfixe de `notes` le distingue des lignes du plan
# principal : `ml.bet_performance.compute_type_roi_weights` exclut ces lignes de
# l'apprentissage des poids par type (le Quinté+ systématique est une couverture
# de divertissement, pas une recommandation apprise du plan principal).
MARQUEUR_MODULE_QUINTE = "Plan de mise IA · Quinté+"
TYPES_QUINTE = frozenset({"Quinté+ Désordre", "Quinté+ Flexi", "Quinté+"})


def note_ligne_module_quinte(profil: str, couverture: Optional[str] = None) -> str:
    base = f"{MARQUEUR_MODULE_QUINTE} · {profil}"
    return f"{base} · {couverture}" if couverture else base


def est_ligne_module_quinte(notes: Optional[str]) -> bool:
    return bool(notes) and str(notes).startswith(MARQUEUR_MODULE_QUINTE)


def regler_ligne_quinte(type_pari: str, numeros: list[int], mise: float,
                        classement: list[dict], rapports: Optional[dict],
                        nb_partants: int, rapports_detail: Optional[dict] = None,
                        non_partants: Optional[set[int]] = None) -> Optional[dict]:
    """Règle une ligne de capital Quinté+ — tendu (5 chevaux) ou champ (6, 7…).

    `settle_pari` ne sait régler qu'UNE combinaison de 5 : un champ de 6 chevaux
    y serait toujours perdant. On passe donc par `settle_module_quinte` (le même
    règlement que le bilan du plan) : C(N, 5) combinaisons à `mise / C(N, 5)`,
    chacune au rapport de son rang réel (Ordre pour le seul tendu, Désordre,
    Bonus 4sur5, Bonus 3). Pour un tendu, le résultat est identique à settle_pari.

    Retourne {"resultat", "gain_perte" (net), "cote" (retour / mise engagée),
    "bilan"}, ou None tant qu'un rapport gagnant n'est pas publié (jamais inventé)
    ou si la ligne n'est pas réglable comme un Quinté+.
    """
    if type_pari not in TYPES_QUINTE or len(set(numeros)) < 5:
        return None
    try:
        mise = float(mise or 0.0)
    except (TypeError, ValueError):
        return None
    if mise <= 0:
        return None
    module = {"disponible": True, "type_pari": type_pari, "cout_total": mise,
              "chevaux": [{"numero": int(n)} for n in dict.fromkeys(numeros)]}
    bilan = settle_module_quinte(module, classement, rapports, nb_partants,
                                 rapports_detail, non_partants)
    if bilan is None or bilan["en_attente"]:
        return None
    engage = bilan["total_mise"]
    if engage <= 0:
        # Toutes les combinaisons contiennent un non-partant : mise rendue.
        return {"resultat": "rembourse", "gain_perte": 0.0, "cote": 1.0, "bilan": bilan}
    # Net = retour − part réellement engagée : les combinaisons remboursées
    # (non-partant) reviennent au joueur, elles ne sont ni perdues ni gagnées.
    gain_perte = round(bilan["total_gain"] - engage, 2)
    if bilan["nb_gagnantes"] > 0:
        return {"resultat": "gagne", "gain_perte": gain_perte,
                "cote": round(bilan["total_gain"] / engage, 2), "bilan": bilan}
    return {"resultat": "perd", "gain_perte": gain_perte, "cote": None, "bilan": bilan}


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
            })

    total_mise = round(total_mise, 2)
    total_gain = round(total_gain, 2)
    net = round(total_gain - total_mise, 2)
    roi = round(net / total_mise * 100, 1) if total_mise > 0 else 0.0
    nb_gagnes = sum(1 for p in paris_bilan if p["statut"] == "gagne")

    # Module Quinté+ : réglé À PART. Il n'entre ni dans `paris` (que
    # bet_plan_performance recale par index sur les tickets du plan, et dont
    # l'apprentissage par type se nourrit) ni dans total_mise/net/roi (ROI du plan
    # principal, inchangé) : son ROI se lit dans `module_quinte`, et l'argent
    # réellement engagé au total dans `total_avec_quinte`. Un rapport Quinté+ en
    # attente ne rend pas le plan principal provisoire.
    quinte = settle_module_quinte(plan.get("module_quinte"), classement, rapports,
                                  nb_partants, rapports_detail, non_partants)
    extra: dict = {}
    if quinte is not None:
        mise_t = round(total_mise + quinte["total_mise"], 2)
        gain_t = round(total_gain + quinte["total_gain"], 2)
        extra = {
            "module_quinte": quinte,
            "total_avec_quinte": {
                "total_mise": mise_t, "total_gain": gain_t,
                "net": round(gain_t - mise_t, 2),
                "roi": round((gain_t - mise_t) / mise_t * 100, 1) if mise_t > 0 else 0.0,
                "provisoire": nb_en_attente > 0 or quinte["en_attente"],
            },
        }

    return {
        **extra,
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
