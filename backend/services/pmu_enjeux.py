"""
Enjeux PMU PAR CHEVAL — BlackTurf.

Le PMU publie, course par course, le montant RÉELLEMENT misé sur chaque cheval :

    GET /programme/{DDMMYYYY}/R{r}/C{c}/combinaisons

renvoie, pour chaque type de pari, la liste des combinaisons jouées avec leur
`totalEnjeu` en centimes. Pour SIMPLE_GAGNANT et SIMPLE_PLACE, une « combinaison »
est un seul cheval : on lit donc directement l'argent posé sur chaque partant, en
gagnant et en placé.

Deux pièges, mesurés le 2026-08-26 sur l'API de production :

1. **La liste est plafonnée à 12 entrées par type de pari.** Une course à 16
   partants ne renvoie que les 12 chevaux les plus joués. Le reste n'est pas perdu
   pour autant : `masse-enjeu` donne la masse EXACTE du type de pari, donc la
   queue du peloton se déduit par différence (`autres_centimes`). On ne l'invente
   pas cheval par cheval — on l'annonce comme un agrégat.

2. **Ne JAMAIS déduire la mise depuis la cote.** En pari mutuel
   `cote = masse×(1−prélèvement)/mise` devrait donner un prélèvement constant ;
   mesuré sur une vraie course, le prélèvement implicite variait de −11,9 % à
   +47 % d'un cheval à l'autre. Les cotes publiées sont arrondies et décalées dans
   le temps par rapport aux enjeux. `combinaisons` est la source de vérité, la
   cote n'en est qu'un reflet différé.

Ce module ne fait que LIRE et PARSER. L'historisation vit dans le scraper, la
lecture des mouvements dans `services/enjeux_analyse.py`.
"""
from __future__ import annotations

from datetime import datetime, timezone

import httpx
import structlog

from services.pmu_cotes import parse_course_id

log = structlog.get_logger(module="pmu_enjeux")

_BASE = "https://offline.turfinfo.api.pmu.fr/rest/client/7"
_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "fr-FR,fr;q=0.9",
    "Referer": "https://www.pmu.fr/",
    "Origin": "https://www.pmu.fr",
}

# Nombre maximal d'entrées renvoyées par `combinaisons` pour un type de pari.
# Constaté identique sur SIMPLE_GAGNANT, SIMPLE_PLACE, COUPLE_*, TRIO, SUPER_QUATRE.
CAP_COMBINAISONS = 12

# Types « simples » : une combinaison = un cheval.
TYPES_SIMPLES = ("SIMPLE_GAGNANT", "SIMPLE_PLACE")

# Deux périmètres d'enjeux, et le PMU ne sert PAS le même selon la course :
#
#   • `combinaisons` sans paramètre  → la masse NATIONALE (guichets + en ligne).
#     C'est le périmètre par défaut, et le seul qu'on lisait jusqu'ici.
#   • `combinaisons?specialisation=INTERNET` → la seule masse jouée EN LIGNE,
#     types préfixés `E_` (`E_SIMPLE_GAGNANT`…).
#
# Mesuré le 2026-09-06 : l'appel par défaut répond **204 No Content** sur une
# grande partie de l'offre — toutes les réunions de soirée (aucune course après
# 23 h n'était couverte, 8 % à 22 h, 29 % à 21 h) et des réunions entières
# (Rambouillet 0/9, Laval 0/8, Saratoga 0/10, Solvalla 0/9). Sur ces mêmes
# courses, `?specialisation=INTERNET` répond 200 avec le détail par cheval.
#
# Les deux ne se confondent pas et ne s'additionnent pas : sur 06092026R8C4,
# SIMPLE_GAGNANT valait 42 658 € au national contre 8 119 € en ligne (19 %). On
# prend donc le national quand il existe, la masse en ligne SEULEMENT en repli,
# et on transporte le périmètre jusqu'à l'affichage pour ne jamais présenter
# 8 119 € comme « l'argent misé sur la course ».
PERIMETRE_TOTAL = "total"
PERIMETRE_INTERNET = "internet"

_PARAMS_INTERNET = {"specialisation": "INTERNET"}


def _normaliser_type(t: str) -> str:
    """`E_SIMPLE_GAGNANT` → `SIMPLE_GAGNANT`.

    Le préfixe `E_` ne désigne pas un autre pari, seulement le périmètre en
    ligne du MÊME pari. Le reste du code (et la base) ne connaît que les noms
    nus ; le périmètre voyage à côté, jamais dans le nom du type.
    """
    t = (t or "").upper()
    return t[2:] if t.startswith("E_") else t


def _epoch_ms_to_iso(v) -> str | None:
    if not isinstance(v, (int, float)) or v <= 0:
        return None
    try:
        return datetime.fromtimestamp(v / 1000, tz=timezone.utc).isoformat()
    except (ValueError, OSError, OverflowError):
        return None


def parser_enjeux(
    combinaisons: list | dict | None,
    masse_enjeu: list | dict | None,
    *,
    nb_partants: int | None = None,
) -> dict:
    """
    Transforme les deux payloads PMU en une vue exploitable.

    Retourne::

        {
          "simples": {
            "SIMPLE_GAGNANT": {
               "par_cheval": {5: 1809300, 3: 742300, ...},   # centimes
               "masse_centimes": 3855115,                    # masse exacte (masse-enjeu)
               "maj_at": "2026-08-26T18:42:30+00:00",
               "tronque": False,                             # liste plafonnée à 12 ?
               "autres_centimes": 0,                         # chevaux non listés, agrégé
               "nb_autres": 0,
            },
            "SIMPLE_PLACE": {...},
          },
          "combines": {"COUPLE_GAGNANT": [{"combinaison": [3, 5], "centimes": 141284}, ...]},
          "masses": {"SIMPLE_GAGNANT": 23155391, "MINI_MULTI": 7921022, ...},
        }

    Tolère l'absence de l'un ou l'autre payload : la masse manquante retombe sur
    la somme des enjeux listés (exacte tant que la liste n'est pas tronquée).

    `masses` porte TOUS les types cotés par le PMU, y compris ceux qui n'ont
    aucune liste de combinaisons (`MINI_MULTI`, `MULTI`…). Sans eux, « l'argent
    de la course » se résumait au simple gagnant : sur 05092026R1C1, 231 554 €
    en simple gagnant pour 721 000 € toutes formules — les deux tiers de
    l'argent étaient invisibles.
    """
    blocs: list = []
    if isinstance(combinaisons, dict):
        blocs = combinaisons.get("combinaisons") or []
    elif isinstance(combinaisons, list):
        blocs = combinaisons

    masses: dict[str, dict] = {}
    items = masse_enjeu if isinstance(masse_enjeu, list) else (masse_enjeu or {}).get("rapports") or []
    for it in items:
        if not isinstance(it, dict):
            continue
        t = _normaliser_type(str(it.get("typePari") or ""))
        if t:
            masses[t] = it

    simples: dict[str, dict] = {}
    combines: dict[str, list] = {}

    for bloc in blocs:
        if not isinstance(bloc, dict):
            continue
        type_pari = _normaliser_type(str(bloc.get("pariType") or ""))
        liste = bloc.get("listeCombinaisons") or []
        if not type_pari or not isinstance(liste, list):
            continue

        if type_pari in TYPES_SIMPLES:
            par_cheval: dict[int, int] = {}
            for it in liste:
                combi = (it or {}).get("combinaison") or []
                enjeu = (it or {}).get("totalEnjeu")
                if len(combi) != 1 or not isinstance(enjeu, (int, float)):
                    continue
                try:
                    par_cheval[int(combi[0])] = int(enjeu)
                except (TypeError, ValueError):
                    continue
            if not par_cheval:
                continue

            somme = sum(par_cheval.values())
            masse_brute = masses.get(type_pari, {}).get("totalEnjeu")
            masse = int(masse_brute) if isinstance(masse_brute, (int, float)) else somme
            reste = max(0, masse - somme)
            liste_pleine = len(liste) >= CAP_COMBINAISONS

            if nb_partants:
                tronque = liste_pleine and nb_partants > len(par_cheval)
                nb_autres = (nb_partants - len(par_cheval)) if tronque else 0
            else:
                # Sans nombre de partants (le programme PMU ne le porte pas avant
                # l'enrichissement des participants), une liste de 12 pile est
                # PRÉSUMÉE tronquée : c'est le cas le plus fréquent, et se tromper
                # dans l'autre sens ferait disparaître en silence l'argent des
                # chevaux non listés. Le reste doit toutefois peser : sous 1 % de
                # la masse, c'est l'arrondi à l'euro des montants publiés, pas un
                # peloton caché.
                tronque = liste_pleine and reste > max(100, int(masse * 0.01))
                nb_autres = None  # on sait qu'il en manque, pas combien

            # Écart masse/somme hors troncature = arrondi PMU (les enjeux listés sont
            # arrondis à l'euro) : on ne le fait pas passer pour de l'argent caché.
            autres = reste if tronque else 0

            simples[type_pari] = {
                "par_cheval": par_cheval,
                "masse_centimes": masse,
                "maj_at": _epoch_ms_to_iso(bloc.get("updateTime")),
                "tronque": tronque,
                "autres_centimes": autres,
                "nb_autres": nb_autres,
            }
        else:
            lignes = []
            for it in liste:
                combi = (it or {}).get("combinaison") or []
                enjeu = (it or {}).get("totalEnjeu")
                if not combi or not isinstance(enjeu, (int, float)):
                    continue
                try:
                    lignes.append({"combinaison": [int(n) for n in combi], "centimes": int(enjeu)})
                except (TypeError, ValueError):
                    continue
            if lignes:
                combines[type_pari] = lignes

    toutes_masses: dict[str, int] = {}
    for t, it in masses.items():
        v = it.get("totalEnjeu")
        if isinstance(v, (int, float)) and v > 0:
            toutes_masses[t] = int(v)

    return {"simples": simples, "combines": combines, "masses": toutes_masses}


def agreger_par_cheval(vue: dict | None) -> dict[int, dict]:
    """Argent engagé SUR CHAQUE CHEVAL, toutes formules confondues.

    Le simple gagnant ne représente qu'une fraction de l'argent d'une course :
    sur 05092026R1C1, 231 554 € de simple gagnant pour 721 000 € toutes
    formules. Un cheval peut être discret au simple et porter la moitié des
    couplés — c'est exactement le mouvement qu'on cherche à voir.

    Pour chaque cheval::

        {5: {"detail": {"SIMPLE_GAGNANT": 1809300, "COUPLE_GAGNANT": 412000, ...},
             "simple_centimes": 2551600,     # gagnant + placé
             "combine_centimes": 998400,     # sa part des paris à plusieurs chevaux
             "engage_centimes": 3550000}}    # tout l'argent dont le sort dépend de lui

    Un couplé 3-5 de 1 412 € est compté ENTIER pour le 3 et ENTIER pour le 5 :
    c'est bien la somme qui dépend de chacun d'eux. La somme des `engage_*` d'une
    course dépasse donc la masse totale, et ce n'est pas une erreur — on ne
    présente jamais ce total comme « l'argent de la course ».
    """
    par_cheval: dict[int, dict] = {}

    def _ligne(n: int) -> dict:
        return par_cheval.setdefault(
            int(n), {"detail": {}, "simple_centimes": 0, "combine_centimes": 0, "engage_centimes": 0}
        )

    for type_pari, bloc in ((vue or {}).get("simples") or {}).items():
        for n, centimes in (bloc.get("par_cheval") or {}).items():
            l = _ligne(n)
            l["detail"][type_pari] = l["detail"].get(type_pari, 0) + int(centimes)
            l["simple_centimes"] += int(centimes)
            l["engage_centimes"] += int(centimes)

    for type_pari, lignes in ((vue or {}).get("combines") or {}).items():
        for it in lignes or []:
            centimes = int(it.get("centimes") or 0)
            if centimes <= 0:
                continue
            # Un même cheval listé deux fois dans une combinaison (le PMU ne le
            # fait pas, mais rien ne l'interdit dans le format) ne doit pas
            # compter double.
            for n in {int(x) for x in (it.get("combinaison") or [])}:
                l = _ligne(n)
                l["detail"][type_pari] = l["detail"].get(type_pari, 0) + centimes
                l["combine_centimes"] += centimes
                l["engage_centimes"] += centimes

    return par_cheval


async def fetch_enjeux(course_id: str, *, nb_partants: int | None = None,
                       timeout: float = 4.0,
                       client: "httpx.AsyncClient | None" = None) -> dict | None:
    """
    Lit les enjeux par cheval EN DIRECT chez le PMU pour une course.

    Best-effort : renvoie None si le PMU ne répond pas ou ne publie pas encore
    d'enjeux (course lointaine, réunion étrangère). Jamais d'exception au chemin
    d'appel — cette lecture est un bonus d'affichage, pas un prérequis.
    """
    parsed = parse_course_id(course_id)
    if not parsed:
        return None
    d, reunion, course = parsed
    base = f"{_BASE}/programme/{d}/R{reunion}/C{course}"

    # Un appelant qui enchaîne des milliers de courses (le backfill) fournit son
    # propre client : ouvrir une connexion TLS par course coûtait plus cher que
    # la lecture elle-même.
    ferme_client = client is None

    try:
        if client is None:
            client = httpx.AsyncClient(headers=_HEADERS, timeout=timeout, follow_redirects=True)
        try:

            async def _lire(params: dict | None) -> tuple[object | None, object | None]:
                r_comb = await client.get(f"{base}/combinaisons", params=params)
                r_comb.raise_for_status()
                # 204 = « pas ce périmètre sur cette course », pas une panne :
                # `.content` est vide et `.json()` léverait.
                comb = r_comb.json() if r_comb.content else None
                if not comb:
                    return None, None
                try:
                    r_masse = await client.get(f"{base}/masse-enjeu", params=params)
                    m = r_masse.json() if (r_masse.status_code == 200 and r_masse.content) else None
                except Exception:
                    m = None  # la masse n'est qu'un affinage : la somme des listés suffit
                return comb, m

            perimetre = PERIMETRE_TOTAL
            combinaisons, masse = await _lire(None)
            if not combinaisons:
                # Repli en ligne. Il ne dégrade jamais un relevé national existant
                # puisqu'on n'y vient que si le national est vide.
                perimetre = PERIMETRE_INTERNET
                combinaisons, masse = await _lire(_PARAMS_INTERNET)
        finally:
            if ferme_client:
                await client.aclose()
    except Exception as e:
        log.warning("pmu_enjeux.fetch_failed", course_id=course_id, error=str(e)[:140])
        return None

    if not combinaisons:
        return None

    vue = parser_enjeux(combinaisons, masse, nb_partants=nb_partants)
    if not vue.get("simples"):
        return None
    vue["perimetre"] = perimetre
    return vue
