"""
Lecture des mouvements d'argent PAR CHEVAL — BlackTurf.

Entrée : la suite des relevés d'enjeux d'une course (cf. `services/pmu_enjeux.py`).
Sortie : ce que le parieur veut savoir — combien est misé sur chaque cheval en
gagnant et en placé, et QUI vient de recevoir de l'argent.

Deux règles de méthode, sans lesquelles ces chiffres mentent :

1. **On juge une part de masse, pas un montant brut.** La masse d'une course
   monte pour tout le monde à l'approche du départ : « +3 000 € sur le 5 » ne
   dit rien tant qu'on ne sait pas si la masse totale a pris +30 000 € dans le
   même temps. Le signal d'afflux porte donc sur la PART (`enjeu_i / masse`),
   exprimée en points.

2. **On juge contre la population de la course, pas contre zéro.** Une « grosse
   mise » n'est pas un gros montant dans l'absolu (une course à 400 000 € n'a
   pas la même échelle qu'une course à 12 000 €) : c'est un montant hors norme
   *par rapport aux autres chevaux de la même course, sur la même fenêtre*, et
   qui pèse une fraction notable de l'argent entré.

Aucune alerte n'est émise sur un seul relevé : sans point de comparaison, il n'y
a pas de mouvement, seulement un état.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from statistics import median

# ── Seuils de détection ──────────────────────────────────────────────────────
FENETRE_DEFAUT_MIN = 15          # fenêtre de comparaison (minutes)
AFFLUX_PART_PTS = 1.5            # gain de part de masse (en points) → afflux
AFFLUX_EUR_MIN = 200.0           # ...à condition que l'argent entré soit réel
GROSSE_MISE_EUR_MIN = 500.0      # plancher absolu d'une « grosse mise »
GROSSE_MISE_FACTEUR = 4.0        # ...et au moins 4× la hausse médiane de la course
GROSSE_MISE_PART_FLUX = 0.25     # ...et au moins 25 % de l'argent entré sur la course


def _eur(centimes) -> float:
    return round((centimes or 0) / 100.0, 2)


def _part(centimes: int | None, masse: int | None) -> float | None:
    if not masse or masse <= 0 or centimes is None:
        return None
    return centimes / masse


def _snapshot_reference(snapshots: list[dict], fenetre_min: int) -> dict | None:
    """Relevé le plus récent antérieur d'au moins `fenetre_min` au dernier.

    À défaut (historique plus court que la fenêtre), le tout premier relevé :
    mieux vaut comparer sur 4 minutes en le disant que ne rien comparer.
    """
    if len(snapshots) < 2:
        return None
    dernier = snapshots[-1]
    limite = dernier["t"] - timedelta(minutes=fenetre_min)
    candidats = [s for s in snapshots[:-1] if s["t"] <= limite]
    return candidats[-1] if candidats else snapshots[0]


def analyser_enjeux(
    snapshots: list[dict],
    *,
    fenetre_min: int = FENETRE_DEFAUT_MIN,
    noms: dict[int, str] | None = None,
) -> dict | None:
    """
    Construit la vue « où va l'argent, cheval par cheval ».

    `snapshots` : liste ordonnée dans le temps de dicts::

        {"t": datetime, "sg": {numero: centimes}, "sp": {numero: centimes},
         "masse_sg": int|None, "masse_sp": int|None,
         "autres_sg": int, "autres_sp": int, "nb_autres": int}

    Retourne None si aucun relevé exploitable.
    """
    snapshots = [s for s in (snapshots or []) if s.get("sg") or s.get("sp")]
    if not snapshots:
        return None
    snapshots = sorted(snapshots, key=lambda s: s["t"])
    dernier = snapshots[-1]
    ref = _snapshot_reference(snapshots, fenetre_min)

    sg = dernier.get("sg") or {}
    sp = dernier.get("sp") or {}
    masse_sg = dernier.get("masse_sg") or sum(sg.values()) or None
    masse_sp = dernier.get("masse_sp") or sum(sp.values()) or None

    ref_sg = (ref or {}).get("sg") or {}
    ref_masse_sg = (ref or {}).get("masse_sg") or (sum(ref_sg.values()) if ref_sg else None)
    flux_total_eur = _eur((masse_sg or 0) - (ref_masse_sg or 0)) if ref else 0.0

    # Hausses individuelles sur la fenêtre — la population contre laquelle on juge.
    deltas: dict[int, float] = {}
    if ref:
        for num, val in sg.items():
            avant = ref_sg.get(num)
            if avant is None:
                continue  # cheval absent du top 12 au relevé de référence : rien de fiable
            deltas[num] = _eur(val - avant)
    hausses = [d for d in deltas.values() if d > 0]
    mediane_hausse = median(hausses) if hausses else 0.0

    lignes = []
    for num in sorted(set(sg) | set(sp), key=lambda n: -(sg.get(n, 0) + sp.get(n, 0))):
        part_sg = _part(sg.get(num), masse_sg)
        part_sp = _part(sp.get(num), masse_sp)
        part_sg_ref = _part(ref_sg.get(num), ref_masse_sg) if ref else None
        delta_part_pts = (
            round((part_sg - part_sg_ref) * 100, 2)
            if part_sg is not None and part_sg_ref is not None else None
        )
        delta_eur = deltas.get(num)

        afflux = bool(
            delta_part_pts is not None and delta_eur is not None
            and delta_part_pts >= AFFLUX_PART_PTS and delta_eur >= AFFLUX_EUR_MIN
        )
        grosse_mise = bool(
            delta_eur is not None
            and delta_eur >= GROSSE_MISE_EUR_MIN
            and delta_eur >= GROSSE_MISE_FACTEUR * mediane_hausse
            and flux_total_eur > 0
            and delta_eur >= GROSSE_MISE_PART_FLUX * flux_total_eur
        )

        lignes.append({
            "numero": num,
            "nom": (noms or {}).get(num),
            "enjeu_gagnant_eur": _eur(sg.get(num)) if num in sg else None,
            "enjeu_place_eur": _eur(sp.get(num)) if num in sp else None,
            "part_gagnant": round(part_sg, 5) if part_sg is not None else None,
            "part_place": round(part_sp, 5) if part_sp is not None else None,
            # Beaucoup de placé pour peu de gagnant = argent prudent ; l'inverse =
            # argent qui vise la victoire. Rapporté aux masses, donc comparable.
            "ratio_place_gagnant": (
                round(part_sp / part_sg, 3)
                if part_sg and part_sp else None
            ),
            "delta_eur": delta_eur,
            "delta_part_pts": delta_part_pts,
            "afflux": afflux,
            "grosse_mise": grosse_mise,
            # Le cheval vient d'entrer dans le top 12 publié par le PMU : il reçoit
            # de l'argent, mais on ne peut pas chiffrer depuis combien.
            "entre_dans_classement": bool(ref and num in sg and num not in ref_sg),
        })

    alertes = sorted(
        [
            {
                "numero": ligne["numero"],
                "nom": ligne["nom"],
                "type": "grosse_mise" if ligne["grosse_mise"] else "afflux",
                "delta_eur": ligne["delta_eur"],
                "delta_part_pts": ligne["delta_part_pts"],
            }
            for ligne in lignes if ligne["afflux"] or ligne["grosse_mise"]
        ],
        key=lambda a: -(a["delta_eur"] or 0),
    )

    fenetre_reelle = (
        round((dernier["t"] - ref["t"]).total_seconds() / 60.0, 1) if ref else None
    )

    return {
        "instant": dernier["t"].isoformat() if isinstance(dernier["t"], datetime) else dernier["t"],
        "masse_gagnant_eur": _eur(masse_sg),
        "masse_place_eur": _eur(masse_sp),
        "autres": {
            "gagnant_eur": _eur(dernier.get("autres_sg")),
            "place_eur": _eur(dernier.get("autres_sp")),
            "nb_chevaux": dernier.get("nb_autres") or 0,
        },
        # Tronqué se juge sur l'ARGENT non détaillé, pas sur le nombre de chevaux :
        # quand le nombre de partants n'est pas connu au moment du relevé, on sait
        # qu'il manque des chevaux sans savoir combien (nb_autres = 0/None), et la
        # somme manquante doit rester annoncée.
        "tronque": bool(dernier.get("nb_autres") or dernier.get("autres_sg") or dernier.get("autres_sp")),
        "fenetre_min": fenetre_reelle,
        "flux_fenetre_eur": flux_total_eur if ref else None,
        "par_cheval": lignes,
        "alertes": alertes,
        "nb_releves": len(snapshots),
    }
