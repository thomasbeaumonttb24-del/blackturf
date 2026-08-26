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
        }

    Tolère l'absence de l'un ou l'autre payload : la masse manquante retombe sur
    la somme des enjeux listés (exacte tant que la liste n'est pas tronquée).
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
        t = str(it.get("typePari") or "").upper()
        if t:
            masses[t] = it

    simples: dict[str, dict] = {}
    combines: dict[str, list] = {}

    for bloc in blocs:
        if not isinstance(bloc, dict):
            continue
        type_pari = str(bloc.get("pariType") or "").upper()
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

    return {"simples": simples, "combines": combines}


async def fetch_enjeux(course_id: str, *, nb_partants: int | None = None,
                       timeout: float = 4.0) -> dict | None:
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

    try:
        async with httpx.AsyncClient(headers=_HEADERS, timeout=timeout, follow_redirects=True) as client:
            r_comb = await client.get(f"{base}/combinaisons")
            r_comb.raise_for_status()
            combinaisons = r_comb.json() if r_comb.content else None
            try:
                r_masse = await client.get(f"{base}/masse-enjeu")
                masse = r_masse.json() if (r_masse.status_code == 200 and r_masse.content) else None
            except Exception:
                masse = None  # la masse n'est qu'un affinage : la somme des listés suffit
    except Exception as e:
        log.warning("pmu_enjeux.fetch_failed", course_id=course_id, error=str(e)[:140])
        return None

    vue = parser_enjeux(combinaisons, masse, nb_partants=nb_partants)
    return vue if vue.get("simples") else None
