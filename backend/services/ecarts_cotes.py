"""
Écarts PMU / bookmakers — où le PMU paie plus (ou moins) que le marché.

Le parieur joue au PMU : la seule cote qu'il touche est la cote PMU. Les
bookmakers (Unibet, Bet365, Ladbrokes, Betfair Exchange) servent de RÉFÉRENCE :
leurs cotes, débarrassées de leur marge, donnent un « prix juste » du cheval.

    écart = P(victoire selon les bookmakers) × cote PMU − 1

  · écart > 0 : le PMU paie PLUS que le prix juste → intéressant (on gagne plus) ;
  · écart < 0 : le PMU paie MOINS → moins intéressant, à éviter.

Prix juste par source : 1/cote de chaque partant, divisé par la somme du champ
(retire la marge du bookmaker). Une source n'est retenue que si elle cote au
moins `COUVERTURE_MIN` des partants, sinon la somme du champ n'a pas de sens.
Consensus = moyenne géométrique des probas des sources retenues pour le cheval.
Geny est exclu (source non fiable, cf. `services.data_quality`) : sur 1 033
courses (21 jours, 2026-09-21 → 10-11) c'est la pire source (log-loss 1,97 contre
1,91 pour le PMU et 1,89 pour le consensus).

CE QUE L'ÉCART NE DIT PAS (mesuré, ne pas le présenter comme un pari gagnant) :
  · cotes de CLÔTURE (12/10, 11 691 partants) : écart > 10 % +4,5 %, > 20 %
    +15,1 % — mais la cote PMU de clôture EST le rapport payé : mesure biaisée ;
  · cotes AU PRONOSTIC (13/10, rejeu prod, 1 926 courses, cote figée ~T-10,
    cote bookmaker ≤ 1 h) : tout −19,9 %, écart > 10 % −19,4 %, > 20 % −20,7 %,
    > 50 % −13,9 % [−35 ; +7], ≤ −20 % −17,0 %. Aucun seuil ne sort du négatif
    de façon fiable : l'écart vu 10 min avant le départ se REFERME avant le
    départ (la cote PMU rejoint le marché).
L'écart est donc une INFORMATION de prix (« à cet instant, le PMU paie plus que
les bookmakers »), jamais une promesse de gain : le site le dit en toutes lettres.
"""
from __future__ import annotations

import math
from typing import Optional

# Colonne `participations` → nom affiché. Geny volontairement absent.
SOURCES: dict[str, str] = {
    "cote_unibet": "Unibet",
    "cote_bet365": "Bet365",
    "cote_ladbrokes": "Ladbrokes",
    "cote_betfair_exchange": "Betfair",
}
# Nom de la source dans `cotes_bookmakers.source` (fraîcheur des cotes).
SOURCE_HISTORIQUE: dict[str, str] = {
    "cote_unibet": "unibet",
    "cote_bet365": "bet365",
    "cote_ladbrokes": "ladbrokes",
    "cote_betfair_exchange": "betfair_exchange",
}

COUVERTURE_MIN = 0.80        # part des partants qu'une source doit coter
SOURCES_MIN = 2              # sous ce nombre, un écart positif n'est pas proposé
SEUIL_NET = 0.10             # PMU paie ≥ 10 % de plus que le prix juste
SEUIL_FORT = 0.20
SEUIL_DEFAVORABLE = -0.20    # PMU paie ≥ 20 % de moins
# Au-delà, l'écart est rangé « a_confirmer » et sort de la liste du jour : sur ces
# cotes, quelques euros d'enjeux déplacent la cote PMU et l'écart est surtout du
# bruit (20 gagnants sur 1 394 chevaux à écart > 10 %, cotes de clôture du 12/10).
COTE_MAX_PROPOSITION = 40.0
ECART_SUSPECT = 1.50         # PMU ≥ 2,5 × le prix juste : appariement à vérifier
DISPERSION_ACCORD = 0.15     # écart-type des log-probas entre sources
DISPERSION_DESACCORD = 0.35
FRAICHEUR_MAX_MIN = 45       # cote bookmaker plus vieille → prudence
COTE_OUTSIDER = 15.0
COTE_FAVORI = 4.0
POOL_GAGNANT_FAIBLE_EUR = 30_000
MOUVEMENT_NOTABLE = 0.15     # fraction : +15 % de cote PMU depuis l'ouverture


def _cote(v) -> Optional[float]:
    try:
        c = float(v)
    except (TypeError, ValueError):
        return None
    return c if math.isfinite(c) and c > 1.0 else None


def _fmt_pct(x: float) -> str:
    return f"{round(abs(x) * 100):d} %"


def _fmt_cote(c: float) -> str:
    return f"{c:.1f}".replace(".", ",")


def probas_par_source(partants: list[dict]) -> dict[str, dict[int, float]]:
    """{colonne: {index partant: proba sans marge}} pour les sources assez couvrantes."""
    n = len(partants)
    out: dict[str, dict[int, float]] = {}
    if n == 0:
        return out
    for col in SOURCES:
        cotes = {i: c for i, p in enumerate(partants) if (c := _cote(p.get(col)))}
        if len(cotes) < max(2, math.ceil(COUVERTURE_MIN * n)):
            continue
        somme = sum(1.0 / c for c in cotes.values())
        out[col] = {i: (1.0 / c) / somme for i, c in cotes.items()}
    return out


def detecter_ecarts(
    partants: list[dict],
    *,
    etranger: bool = False,
    pool_gagnant_eur: Optional[float] = None,
    fraicheur_min: Optional[dict] = None,
    course_terminee: bool = False,
) -> list[dict]:
    """Un dict par partant ACTIF ayant une cote PMU et au moins une source.

    `partants` : dicts portant `numero`, `participation_id`, `non_partant`,
    `cote_pmu`, les colonnes de `SOURCES` et, si connu, `mouvement_cote_pct`
    (fraction, positif = la cote PMU MONTE — convention de la base).
    `fraicheur_min` : {participation_id: {colonne: minutes depuis le relevé}}.
    Trié par écart décroissant (le plus intéressant pour le parieur d'abord).
    """
    actifs = [p for p in partants if not p.get("non_partant")]
    probas = probas_par_source(actifs)
    if not probas:
        return []
    cote_fav = min((c for p in actifs if (c := _cote(p.get("cote_pmu")))), default=None)
    resultats = []
    for i, p in enumerate(actifs):
        cote_pmu = _cote(p.get("cote_pmu"))
        dispo = {col: pr[i] for col, pr in probas.items() if i in pr}
        if cote_pmu is None or not dispo:
            continue
        logs = [math.log(v) for v in dispo.values()]
        moy = sum(logs) / len(logs)
        p_cons = math.exp(moy)
        dispersion = (math.sqrt(sum((x - moy) ** 2 for x in logs) / len(logs))
                      if len(logs) > 1 else None)
        ecart = p_cons * cote_pmu - 1.0
        nb = len(dispo)

        proposable = nb >= SOURCES_MIN and cote_pmu < COTE_MAX_PROPOSITION
        if ecart >= SEUIL_FORT and proposable:
            niveau = "fort"
        elif ecart >= SEUIL_NET and proposable:
            niveau = "net"
        elif ecart >= SEUIL_NET:
            niveau = "a_confirmer"       # une seule source : affiché, pas proposé
        elif ecart <= SEUIL_DEFAVORABLE:
            niveau = "defavorable"
        else:
            niveau = None

        raisons, prudence = _expliquer(
            p, ecart=ecart, cote_pmu=cote_pmu, cote_fav=cote_fav, dispo=dispo,
            dispersion=dispersion, etranger=etranger, pool_gagnant_eur=pool_gagnant_eur,
            fraicheur=(fraicheur_min or {}).get(p.get("participation_id"), {}),
            course_terminee=course_terminee, niveau=niveau,
        )
        resultats.append({
            "numero": p.get("numero"),
            "participation_id": p.get("participation_id"),
            "nom": p.get("nom"),
            "cote_pmu": round(cote_pmu, 2),
            "cote_juste_bookmakers": round(1.0 / p_cons, 2),
            "proba_bookmakers": round(p_cons, 4),
            "ecart": round(ecart, 4),
            "niveau": niveau,
            "sources": [SOURCES[c] for c in dispo],
            "nb_sources": nb,
            "accord": (None if dispersion is None else
                       "accord" if dispersion < DISPERSION_ACCORD else
                       "desaccord" if dispersion > DISPERSION_DESACCORD else "partiel"),
            "cotes_bookmakers": {SOURCES[c]: round(float(p[c]), 2) for c in dispo},
            "raisons": raisons,
            "prudence": prudence,
        })
    resultats.sort(key=lambda r: r["ecart"], reverse=True)
    return resultats


def _expliquer(p, *, ecart, cote_pmu, cote_fav, dispo, dispersion, etranger,
               pool_gagnant_eur, fraicheur, course_terminee, niveau):
    """(raisons, prudence) en français simple. Règles fixes, aucune invention :
    chaque phrase s'appuie sur une donnée de la course."""
    raisons: list[str] = []
    prudence: list[str] = []
    cote_juste = 1.0 / math.exp(sum(math.log(v) for v in dispo.values()) / len(dispo))
    noms = [SOURCES[c] for c in dispo]

    if ecart > 0:
        raisons.append(
            f"Le PMU paie {_fmt_cote(cote_pmu)} quand le prix juste des bookmakers "
            f"({', '.join(noms)}, marge retirée) est {_fmt_cote(cote_juste)} : "
            f"{_fmt_pct(ecart)} de gain en plus à mise égale.")
    else:
        raisons.append(
            f"Le PMU paie {_fmt_cote(cote_pmu)} contre un prix juste de "
            f"{_fmt_cote(cote_juste)} chez les bookmakers : {_fmt_pct(ecart)} de gain "
            f"en moins à mise égale.")

    mv = p.get("mouvement_cote_pct")
    try:
        mv = float(mv) if mv is not None else None
    except (TypeError, ValueError):
        mv = None
    if mv is not None and ecart > 0 and mv >= MOUVEMENT_NOTABLE:
        raisons.append(f"Sa cote PMU a monté de {_fmt_pct(mv)} depuis l'ouverture : les "
                       "parieurs PMU l'ont délaissé, pas les bookmakers.")
    elif mv is not None and ecart < 0 and mv <= -MOUVEMENT_NOTABLE:
        raisons.append(f"Sa cote PMU a baissé de {_fmt_pct(mv)} depuis l'ouverture : "
                       "l'argent PMU s'est massé dessus, plus que chez les bookmakers.")

    if ecart > 0 and cote_pmu >= COTE_OUTSIDER:
        raisons.append("Outsider : les bookmakers raccourcissent les grosses cotes pour "
                       "se protéger, le PMU redistribue simplement les mises. C'est sur "
                       "ces chevaux que le PMU paie le plus souvent davantage.")
        prudence.append("Un outsider gagne rarement : écart réel, mais à petite mise.")
    elif ecart > 0 and (cote_pmu <= COTE_FAVORI or cote_pmu == cote_fav):
        raisons.append("Les parieurs PMU jouent moins ce cheval que ne l'estiment les "
                       "bookmakers.")
    elif ecart < 0 and (cote_pmu <= COTE_FAVORI or cote_pmu == cote_fav):
        raisons.append("Favori très joué au PMU : sa cote y est écrasée par rapport au "
                       "marché.")

    if etranger:
        raisons.append("Course étrangère : peu de parieurs français, la cote PMU "
                       "s'écarte plus facilement du marché international.")

    bf = dispo.get("cote_betfair_exchange")
    if bf is not None and ecart > 0 and bf * cote_pmu - 1.0 >= SEUIL_NET:
        raisons.append("Betfair (bourse entre parieurs, sans marge) confirme l'écart.")

    if dispersion is not None and dispersion < DISPERSION_ACCORD:
        raisons.append(f"Les {len(dispo)} bookmakers sont d'accord entre eux.")
    elif dispersion is not None and dispersion > DISPERSION_DESACCORD:
        prudence.append("Les bookmakers ne sont pas d'accord entre eux : écart moins fiable.")

    if niveau == "a_confirmer" and len(dispo) < SOURCES_MIN:
        prudence.append("Une seule source bookmaker : écart à confirmer.")
    if niveau == "a_confirmer" and cote_pmu >= COTE_MAX_PROPOSITION:
        prudence.append(f"Cote PMU de {_fmt_cote(cote_pmu)} : au-delà de 40, trop peu de "
                        "chevaux gagnent pour que l'écart se vérifie.")
    if ecart >= ECART_SUSPECT:
        prudence.append("Écart très grand : vérifier qu'il s'agit bien du même cheval "
                        "chez les bookmakers avant de jouer.")

    vieilles = [(SOURCES[c], m) for c, m in fraicheur.items()
                if c in dispo and m is not None and m > FRAICHEUR_MAX_MIN]
    if vieilles:
        src, m = max(vieilles, key=lambda x: x[1])
        prudence.append(f"Cote {src} relevée il y a {int(m)} min : le marché a pu bouger.")

    if not course_terminee:
        if pool_gagnant_eur is not None and pool_gagnant_eur < POOL_GAGNANT_FAIBLE_EUR:
            prudence.append(f"Peu d'enjeux en simple gagnant ({int(pool_gagnant_eur):,} €)"
                            .replace(",", " ") + " : la cote PMU peut encore beaucoup bouger.")
        if ecart > 0:
            prudence.append("L'écart se referme souvent avant le départ : la cote PMU "
                            "rejoint le marché. Mesuré sur 1 926 courses, jouer un écart "
                            "vu 10 minutes avant le départ n'a pas rapporté.")
    return raisons, prudence


def resume_course(ecarts: list[dict]) -> dict:
    """Comptes par niveau, pour un badge ou une liste du jour."""
    return {
        "nb_fort": sum(1 for e in ecarts if e["niveau"] == "fort"),
        "nb_net": sum(1 for e in ecarts if e["niveau"] == "net"),
        "nb_defavorable": sum(1 for e in ecarts if e["niveau"] == "defavorable"),
        "meilleur": next((e for e in ecarts if e["niveau"] in ("fort", "net")), None),
    }
