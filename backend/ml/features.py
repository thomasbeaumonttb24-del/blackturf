"""
Feature engineering — 80+ variables pour le modèle ML BlackTurf.
Adapté de BlackTurf_learning_pipeline.py pour PostgreSQL.

Groupes de features :
  A. ELO et force relative (6 features)
  B. Forme récente (8 features)
  C. Repos et fraîcheur (4 features)
  D. Distance (5 features)
  E. Terrain (5 features)
  F. Hippodrome (4 features)
  G. Cotes et marché (8 features)
  H. Équipement (4 features)
  I. Jockey (6 features)
  J. Entraîneur (6 features)
  K. Cheval identité (6 features)
  L. Contexte course (8 features)
  M. Populaire / sagesse (5 features)
  N. Signal avancé (5 features)
"""
import math
import numpy as np
import structlog
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from ml.race_dynamics import aggregate_dynamics
from ml.confrontation_features import compute_confrontation_features, CONFRONTATION_FEATURE_KEYS

log = structlog.get_logger()

ELO_INITIAL = 1500.0

# Les chevaux portent un ELO PAR DISCIPLINE (plat / trot / obstacle). Toute
# comparaison « ce cheval vs le champ » doit rester dans la même colonne, sinon on
# soustrait deux échelles différentes. Ces deux constantes sont la source unique de
# la correspondance discipline → colonne ELO.
_IDX_ELO_DISC = {"plat": 3, "trot": 4, "obstacle": 5}


def _cle_discipline(discipline) -> str:
    """Discipline PMU (« Attelé », « Steeple-chase »…) → clé ELO (plat/trot/obstacle)."""
    d = (discipline or "plat").lower()
    if "trot" in d or "attel" in d or "mont" in d:
        return "trot"
    if "haies" in d or "steeple" in d or "obstacle" in d or "cross" in d:
        return "obstacle"
    return "plat"

TERRAIN_CATEGORIES = {
    "bon": ["bon", "ferme", "dur", "très bon"],
    "souple": ["bon souple", "souple", "assez souple"],
    "lourd": ["lourd", "très lourd", "collant", "bourbeux"],
}

DISCIPLINE_CODE = {
    "plat": 0, "attelé": 1, "monté": 2, "haies": 3, "steeple": 4, "cross": 5
}

SEXE_CODE = {"H": 0, "E": 1, "M": 1, "F": 2, "JP": 2}

DISTANCE_BUCKET = {
    "courte": (0, 1400),
    "moyenne": (1400, 2100),
    "longue": (2100, 9999),
}


def parse_musique(musique_str: Optional[str]) -> list[int]:
    """
    Extrait positions de la musique PMU.
    Format: chiffre(s) + lettre_discipline (ex: "1a2h3s5p")
    Incidents standalone MAJUSCULES (T/A/R/D) → 20 (pénalité).
    Lettres discipline minuscules (a/p/h/s/m) après un chiffre → ignorées.
    """
    if not musique_str:
        return []
    positions = []
    s = str(musique_str)
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit():
            # Lire tous les chiffres consécutifs (ex: "12" = 12ème)
            j = i + 1
            while j < len(s) and s[j].isdigit():
                j += 1
            positions.append(int(s[i:j]))
            # Sauter la lettre de discipline optionnelle (a/p/h/s/m)
            if j < len(s) and s[j].isalpha():
                j += 1
            i = j
        elif ch in ("T", "A", "R", "D"):
            # Incident standalone MAJUSCULE → pénalité 20
            positions.append(20)
            i += 1
        else:
            i += 1
    return positions[:10]


def score_position(pos: int, nb_partants: int = 10) -> float:
    """Normalise position → score 0-1 (1=victoire)."""
    if pos >= 20:
        return 0.0
    return max(0.0, 1.0 - (pos - 1) / max(nb_partants - 1, 1))


def compute_allure_regularite(musique_str: Optional[str], max_courses: int = 10) -> tuple[float, float, int]:
    """Régularité d'allure depuis la musique — CRITIQUE en trot (un trotteur qui se
    met au galop est disqualifié). Compte les sorties terminées sur une faute
    disqualifiante (D=disqualifié pour allure, T=tombé, A=arrêté, R=rétif/dérobé)
    vs le nombre de sorties lues.

    Retourne (taux_faute, faute_derniere_course, nb_sorties_lues).
    Les tokens chiffres = course terminée et classée (0 = non-placé, PAS une faute).
    Lettres discipline minuscules (a/p/h/s/m) après un chiffre → ignorées.
    Même logique de parsing que parse_musique (casse préservée : incidents en
    MAJUSCULE, discipline en minuscule)."""
    if not musique_str:
        return 0.0, 0.0, 0
    s = str(musique_str)
    incidents: list[bool] = []  # True = sortie terminée sur faute disqualifiante
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit():
            j = i + 1
            while j < len(s) and s[j].isdigit():
                j += 1
            incidents.append(False)  # course classée (0 inclus = non-placé ≠ faute)
            if j < len(s) and s[j].isalpha():
                j += 1  # saute la lettre de discipline
            i = j
        elif ch in ("T", "A", "R", "D"):
            incidents.append(True)   # incident disqualifiant standalone
            i += 1
        else:
            i += 1
    incidents = incidents[:max_courses]
    if not incidents:
        return 0.0, 0.0, 0
    taux = sum(1 for x in incidents if x) / len(incidents)
    return float(taux), (1.0 if incidents[0] else 0.0), len(incidents)


# Lexique de déroulé de course (trip notes) — termes hippiques FR.
_COMMENT_POS = (  # a gagné/fini en ayant de la marge → valeur réelle ≥ résultat
    "facilement", "aisément", "aisement", "nettement", "détaché", "detache",
    "sans forcer", "autorité", "autorite", "impressionnant",
    "brillant", "souqué", "souque", "contenu", "à l'aise", "a l'aise",
    "se promène", "se promene", "domine", "facile", "impose")
_COMMENT_UNLUCKY = (  # malchanceux → forme cachée, souvent sous-coté au coup suivant
    "gêné", "gene", "gêne", "enfermé", "enferme", "malchance", "pas de chance",
    "fermé", "ferme la route", "mal parti", "manqué le départ", "manque le depart",
    "victime", "bousculé", "boucle", "boxé", "boxe", "cafouillage", "trafic",
    "perd toute chance", "sans pouvoir s'exprimer", "à refaire", "a refaire")
_COMMENT_NEG = (  # faiblesse réelle → sur-évalué
    "fatigue", "fatigué", "distancé", "distance dans", "lâche", "lache pied",
    "rétrograde", "retrograde", "à la peine", "a la peine", "sans réaction",
    "sans reaction", "décevant", "decevant", "faiblit", "n'a jamais", "se met au galop",
    "dérobé", "derobe", "fautif", "loin du compte")


def compute_commentaire_signal(textes: list[str]) -> tuple[float, float, float, int]:
    """Score les déroulés de course récents (#9). Retourne
    (signal_moyen[-1..1], a_ete_malchanceux[0/1], a_gagne_facile[0/1], nb_lus).
    Positif/malchanceux = potentiel sous-évalué ; négatif = faiblesse réelle.
    Liste vide (commentaires non scrapés) → neutre 0, pas de bruit."""
    scores = []
    malchance = 0.0
    facile = 0.0
    for t in textes:
        if not t:
            continue
        s = t.lower()
        pos = sum(1 for k in _COMMENT_POS if k in s)
        unl = sum(1 for k in _COMMENT_UNLUCKY if k in s)
        neg = sum(1 for k in _COMMENT_NEG if k in s)
        if pos or unl:
            if pos:
                facile = 1.0
            if unl:
                malchance = 1.0
        raw = (pos + unl) - neg
        scores.append(float(max(-1.0, min(1.0, raw / 2.0))))
    if not scores:
        return 0.0, 0.0, 0.0, 0
    return float(sum(scores) / len(scores)), malchance, facile, len(scores)


def get_terrain_cat(terrain: Optional[str]) -> str:
    terrain_lower = (terrain or "bon").lower()
    for cat, values in TERRAIN_CATEGORIES.items():
        if any(v in terrain_lower for v in values):
            return cat
    return "bon"


def get_dist_cat(dist: int) -> str:
    for cat, (lo, hi) in DISTANCE_BUCKET.items():
        if lo <= dist < hi:
            return cat
    return "longue"


# ─────────────────────────────────────────────────────────────────────────────
# Données dormantes réveillées (terrain/corde/vitesse/poids historiques + géo)
# ─────────────────────────────────────────────────────────────────────────────
# Familles de terrain pour les libellés PMU de l'historique (etatTerrain) —
# plus larges que TERRAIN_CATEGORIES (libellés bruts type "TRES_SOUPLE").
def get_terrain_famille(terrain: Optional[str]) -> str:
    """Mappe un libellé terrain (courses ou historique PMU) vers 3 familles :
    ferme / intermediaire / lourd. Inconnu → 'inconnu' (pas de fausse famille)."""
    t = (terrain or "").lower().replace("_", " ").strip()
    if not t:
        return "inconnu"
    if any(k in t for k in ("très lourd", "tres lourd", "lourd", "collant", "bourbeux")):
        return "lourd"
    if any(k in t for k in ("très souple", "tres souple", "souple", "léger", "leger")):
        return "intermediaire"
    if any(k in t for k in ("bon", "ferme", "dur", "rapide", "standard", "sec")):
        return "ferme"
    return "inconnu"


def corde_zone(num: Optional[int]) -> str:
    """Zone de corde (numéro de départ) : intérieure 1-4 / milieu 5-8 / extérieure 9+."""
    if num is None or num <= 0:
        return "inconnu"
    if num <= 4:
        return "interieure"
    if num <= 8:
        return "milieu"
    return "exterieure"


def compute_vitesse_relative(vitesses_recentes: list[float], mediane_ref: Optional[float]) -> float:
    """Niveau de vitesse des courses récentes du cheval vs la référence
    (médiane d'indice_vitesse à même discipline/distance). indice_vitesse =
    vitesse du VAINQUEUR de chaque course historique → proxy du NIVEAU des
    courses fréquentées (qualité d'opposition), pas la vitesse propre du cheval.
    Ratio 0.95→1.05 mappé sur 0→1 ; données absentes → 0.5 neutre."""
    vs = [v for v in (vitesses_recentes or []) if v and v > 0]
    if not vs or not mediane_ref or mediane_ref <= 0:
        return 0.5
    ratio = (sum(vs) / len(vs)) / mediane_ref
    return float(np.clip((ratio - 0.95) / 0.10, 0.0, 1.0))


def compute_delta_poids(poids_jour: Optional[float], poids_hist: list[float]) -> float:
    """Écart de poids porté aujourd'hui vs la moyenne des dernières courses
    (plat/obstacle). Négatif = allègement (souvent favorable). Normalisé sur
    ±5 kg → [-1, +1]. Données absentes → 0 neutre."""
    ph = [p for p in (poids_hist or []) if p and 30.0 <= p <= 80.0]
    if not poids_jour or not (30.0 <= float(poids_jour) <= 80.0) or not ph:
        return 0.0
    delta = float(poids_jour) - (sum(ph) / len(ph))
    return float(np.clip(delta / 5.0, -1.0, 1.0))


# Lat/lon des principaux hippodromes français (+ quelques étrangers fréquents).
# Sert au PROXY de déplacement : distance entre l'hippodrome « domicile » du
# cheval (mode de son historique) et l'hippodrome du jour. On n'a PAS l'adresse
# des écuries → c'est un proxy honnête du dépaysement, documenté comme tel.
HIPPODROME_GEO: dict[str, tuple[float, float]] = {
    "VINCENNES": (48.821, 2.452), "PARIS-VINCENNES": (48.821, 2.452),
    "LONGCHAMP": (48.861, 2.233), "PARISLONGCHAMP": (48.861, 2.233),
    "SAINT-CLOUD": (48.853, 2.205), "AUTEUIL": (48.854, 2.258),
    "CHANTILLY": (49.182, 2.470), "DEAUVILLE": (49.357, 0.086),
    "ENGHIEN": (48.975, 2.302), "ENGHIEN SOISY": (48.975, 2.302),
    "MAISONS-LAFFITTE": (48.952, 2.146), "COMPIEGNE": (49.400, 2.893),
    "FONTAINEBLEAU": (48.420, 2.673), "EVREUX": (49.017, 1.142),
    "CAGNES-SUR-MER": (43.663, 7.139), "MARSEILLE-BORELY": (43.260, 5.379),
    "MARSEILLE BORELY": (43.260, 5.379), "MARSEILLE-VIVAUX": (43.276, 5.413),
    "HYERES": (43.105, 6.143), "SALON-DE-PROVENCE": (43.640, 5.094),
    "VICHY": (46.117, 3.439), "LYON-PARILLY": (45.715, 4.900),
    "LYON PARILLY": (45.715, 4.900), "LYON-LA SOIE": (45.761, 4.972),
    "TOULOUSE": (43.575, 1.478), "BORDEAUX-LE BOUSCAT": (44.866, -0.610),
    "BORDEAUX LE BOUSCAT": (44.866, -0.610), "PAU": (43.320, -0.339),
    "TARBES": (43.246, 0.040), "MONT-DE-MARSAN": (43.886, -0.498),
    "STRASBOURG": (48.553, 7.703), "NANCY": (48.633, 6.207),
    "REIMS": (49.222, 4.000), "AMIENS": (49.873, 2.260),
    "LE CROISE-LAROCHE": (50.679, 3.085), "LE CROISÉ-LAROCHE": (50.679, 3.085),
    "CAEN": (49.176, -0.378), "GRAIGNES": (49.243, -1.205),
    "ARGENTAN": (48.752, -0.014), "LISIEUX": (49.137, 0.234),
    "CABOURG": (49.286, -0.122), "CLAIREFONTAINE": (49.348, 0.062),
    "LAVAL": (48.060, -0.787), "LE MANS": (47.945, 0.225),
    "NANTES": (47.255, -1.593), "ANGERS": (47.456, -0.594),
    "CHOLET": (47.052, -0.890), "CORDEMAIS": (47.292, -1.866),
    "MESLAY-DU-MAINE": (47.951, -0.546), "SABLE-SUR-SARTHE": (47.838, -0.346),
    "RAMBOUILLET": (48.652, 1.821), "CHARTRES": (48.464, 1.503),
    "LA CAPELLE": (49.965, 3.921), "ROYAN": (45.625, -1.043),
    "LA TESTE": (44.640, -1.130), "LA TESTE DE BUCH": (44.640, -1.130),
    "AGEN": (44.190, 0.598), "BEAUMONT-DE-LOMAGNE": (43.882, 0.984),
    "CASTERA-VERDUZAN": (43.806, 0.428), "DAX": (43.694, -1.057),
    "NIMES": (43.812, 4.351), "AVIGNON": (43.921, 4.876),
    "BEAUCAIRE": (43.797, 4.633), "CAVAILLON": (43.835, 5.025),
    "FEURS": (45.733, 4.232), "SAINT-GALMIER": (45.595, 4.301),
    "MOULINS": (46.561, 3.341), "CHATILLON-SUR-CHALARONNE": (46.116, 4.955),
    "DIVONNE-LES-BAINS": (46.357, 6.133), "AIX-LES-BAINS": (45.694, 5.896),
    "CHATEAUBRIANT": (47.706, -1.392), "PORNICHET": (47.262, -2.343),
    "SAINT-MALO": (48.633, -1.975), "MAURE-DE-BRETAGNE": (47.890, -1.997),
    "VITRE": (48.118, -1.204), "RANES": (48.640, -0.211),
    "MAUQUENCHY": (49.589, 1.392), "ROUEN-MAUQUENCHY": (49.589, 1.392),
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance haversine en km entre deux points (lat/lon en degrés)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bucket_distance_km(km: Optional[float]) -> float:
    """Bucketise une distance de déplacement en [0,1] : <50km→0 (local),
    600km+→1 (très loin). None → 0.5 neutre (géo inconnue)."""
    if km is None:
        return 0.5
    return float(np.clip((km - 50.0) / 550.0, 0.0, 1.0))


def _geo_lookup(nom: Optional[str]) -> Optional[tuple[float, float]]:
    """Résout un nom d'hippodrome (formats variés : « HIPPODROME DE PARIS-VINCENNES »,
    « Vincennes », « TOULOUSE LA CEPIERE ») vers ses coordonnées. None si inconnu."""
    if not nom:
        return None
    k = nom.upper().strip()
    # Retire le préfixe administratif PMU
    for pref in ("HIPPODROME DE LA ", "HIPPODROME DE L'", "HIPPODROME DU ",
                 "HIPPODROME DES ", "HIPPODROME DE ", "HIPPODROME D'", "HIPPODROME "):
        if k.startswith(pref):
            k = k[len(pref):].strip()
            break
    if k in HIPPODROME_GEO:
        return HIPPODROME_GEO[k]
    # Match par inclusion (« TOULOUSE LA CEPIERE » contient « TOULOUSE »)
    for key, geo in HIPPODROME_GEO.items():
        if key in k or k in key:
            return geo
    return None


def compute_distance_deplacement(hippodrome_jour: Optional[str],
                                 hippos_historique: list[str]) -> float:
    """PROXY de déplacement : distance entre l'hippodrome le plus fréquenté du
    cheval (« domicile ») et celui du jour. Hippodrome(s) hors référentiel géo
    ou historique vide → 0.5 neutre (jamais inventé)."""
    if not hippodrome_jour or not hippos_historique:
        return 0.5
    freq: dict[str, int] = {}
    for h in hippos_historique:
        if h:
            k = h.upper().strip()
            freq[k] = freq.get(k, 0) + 1
    if not freq:
        return 0.5
    domicile = max(freq, key=lambda k: freq[k])
    g1 = _geo_lookup(domicile)
    g2 = _geo_lookup(hippodrome_jour)
    if not g1 or not g2:
        return 0.5
    return bucket_distance_km(haversine_km(g1[0], g1[1], g2[0], g2[1]))


async def compute_features_for_participation(
    session: AsyncSession,
    participation_id: str,
    course_id: str,
    cheval_id: str,
    jockey_id: Optional[str],
    entraineur_id: Optional[str],
) -> Optional[dict]:
    """
    Calcule les 80+ features ML pour un partant donné.
    Retourne None si données insuffisantes.
    """
    # Données basiques participation + course
    row = await session.execute(text("""
        SELECT
            p.numero, p.cote_pmu, p.cote_geny, p.cote_bzh,
            p.rang_pronostic_pmu, p.rang_pronostic_geny,
            p.poids_porte, p.decharge, p.retard_gains, p.musique,
            c.discipline, c.distance, c.terrain_officiel, c.hippodrome_nom,
            c.nb_partants, c.allocation, c.niveau_course, c.est_quinte,
            -- categorie_particularite porte la CLASSE de la course (GROUPE_I,
            -- HANDICAP, A_RECLAMER...). niveau_course, lui, porte les conditions
            -- d'engagement en texte libre : il ne dit pas le niveau. Cf. _encode_niveau.
            c.categorie_particularite,
            c.date_heure, c.corde,
            ch.age, ch.sexe,
            ch.elo_score_global, ch.elo_score_plat, ch.elo_score_trot, ch.elo_score_obstacle,
            pc.gains_carriere_total, pc.nb_courses_total, pc.nb_victoires_total
        FROM participations p
        JOIN courses c ON p.course_id = c.course_id
        JOIN chevaux ch ON p.cheval_id = ch.cheval_id
        LEFT JOIN performances_carriere pc ON pc.cheval_id = ch.cheval_id
        WHERE p.participation_id = :pid
    """), {"pid": participation_id})
    base = row.fetchone()

    if not base:
        return None

    (
        numero, cote_pmu, cote_geny, cote_bzh,
        rang_prono_pmu, rang_prono_geny,
        poids, decharge, retard_gains, musique,
        discipline, distance, terrain, hippodrome,
        nb_partants, allocation, niveau_course, est_quinte, categorie_particularite,
        date_heure, corde,
        age, sexe,
        elo_global, elo_plat, elo_trot, elo_obstacle,
        gains_carriere, nb_courses_total, nb_victoires_total,
    ) = base

    # ── A. ELO ────────────────────────────────────────────────────────────
    disc_lower = (discipline or "plat").lower()
    if "trot" in disc_lower or "attelé" in disc_lower or "monté" in disc_lower:
        elo_score = float(elo_trot or ELO_INITIAL)
    elif "haies" in disc_lower or "steeple" in disc_lower or "obstacle" in disc_lower:
        elo_score = float(elo_obstacle or ELO_INITIAL)
    else:
        elo_score = float(elo_plat or ELO_INITIAL)

    # ELO moyen et max de la course
    elo_stats = await session.execute(text("""
        SELECT AVG(ch.elo_score_global), MAX(ch.elo_score_global), MIN(ch.elo_score_global),
               AVG(ch.elo_score_plat), AVG(ch.elo_score_trot), AVG(ch.elo_score_obstacle)
        FROM participations p
        JOIN chevaux ch ON p.cheval_id = ch.cheval_id
        WHERE p.course_id = :cid AND p.non_partant = false
    """), {"cid": course_id})
    _elo_row = elo_stats.fetchone()
    elo_avg, elo_max, elo_min = (
        (_elo_row[0], _elo_row[1], _elo_row[2]) if _elo_row
        else (ELO_INITIAL, ELO_INITIAL, ELO_INITIAL))
    elo_avg = float(elo_avg or ELO_INITIAL)
    elo_max = float(elo_max or ELO_INITIAL)
    # Moyennes du champ PAR DISCIPLINE : comparer un ELO d'attelé à la moyenne
    # GLOBALE du champ mélange deux échelles (cf. "elo_vs_champ" plus bas).
    elo_avg_disc = float(
        (_elo_row[_IDX_ELO_DISC[_cle_discipline(discipline)]] if _elo_row else None)
        or elo_avg)

    # Évolution ELO sur 5 dernières courses
    elo_hist = await session.execute(text("""
        SELECT delta_elo FROM elo_historique
        WHERE cheval_id = :cid
        ORDER BY date_course DESC LIMIT 5
    """), {"cid": cheval_id})
    delta_elos = [r[0] for r in elo_hist.fetchall()]
    delta_elo_5 = float(np.mean(delta_elos)) if delta_elos else 0.0

    feat_elo = {
        "elo_global": float(elo_global or ELO_INITIAL),
        "elo_discipline": elo_score,
        "elo_vs_moyenne": elo_score - elo_avg,
        # Affichage seul (hors modèle) : `elo_vs_moyenne` retranche la moyenne GLOBALE
        # du champ d'un ELO de DISCIPLINE — deux échelles différentes. Le badge
        # « Supérieur / Inférieur au champ » s'appuyait donc sur un écart biaisé
        # (+101 points en moyenne sur un champ d'attelé), assez pour inverser le signe
        # des chevaux proches de la moyenne. Ici les deux termes sont homogènes.
        "elo_vs_champ": elo_score - elo_avg_disc,
        "elo_vs_max": elo_score - elo_max,
        "elo_pct_rank": elo_score / elo_max if elo_max > 0 else 0.5,
        "delta_elo_5courses": delta_elo_5,
    }

    # ── B. Forme récente ──────────────────────────────────────────────────
    hist_courses = await session.execute(text("""
        SELECT h.position_arrivee, h.distance, h.terrain, h.hippodrome, h.date_course,
               h.nb_partants, h.cote_depart, h.discipline, h.allocation,
               h.acceleration_label, h.reduction_km,
               -- ALLOCATION NORMALISÉE EN EUROS, en DERNIÈRE colonne (lue par h[-1])
               -- pour ne décaler aucun index positionnel existant.
               -- `historique_courses` mélange DEUX unités : les lignes issues du
               -- pipeline PMU (course_id renseigné) sont en CENTIMES, celles du
               -- scraper d'historique externe (course_id NULL) sont en EUROS.
               -- Moyenner les deux telles quelles gonfle class_drop_ratio d'un
               -- facteur ~2 (médiane observée 1,96 au lieu de ~1,0).
               CASE WHEN h.course_id IS NOT NULL THEN h.allocation / 100.0
                    ELSE h.allocation::float END AS allocation_eur
        FROM historique_courses h
        WHERE h.cheval_id = :cid AND h.date_course < :today
        ORDER BY h.date_course DESC
        LIMIT 20
    """), {"cid": cheval_id, "today": date_heure.date() if hasattr(date_heure, "date") else str(date_heure)[:10]})
    historique = hist_courses.fetchall()

    musique_positions = parse_musique(musique)
    nb_partants_int = int(nb_partants or 10)

    def get_scores(positions, n=None):
        pos_slice = positions[:n] if n else positions
        return [score_position(p, nb_partants_int) for p in pos_slice]

    scores = get_scores(musique_positions)

    if len(scores) >= 1:
        f1 = scores[0]
        f3 = float(np.mean(scores[:3])) if len(scores) >= 3 else f1
        f5 = float(np.mean(scores[:5])) if len(scores) >= 5 else f3
        f10 = float(np.mean(scores[:10])) if len(scores) >= 10 else f5
        tendance = 0.0
        if len(scores) >= 3:
            x = np.arange(min(len(scores), 5))
            y = scores[:5]
            tendance = float(np.clip(np.polyfit(x, y, 1)[0] * 5, -1, 1))
        regularite = float(1.0 - min(np.std(scores[:5]), 1.0)) if len(scores) >= 3 else 0.5
        taux_top3 = sum(1 for p in musique_positions[:5] if 0 < p <= 3) / min(len(musique_positions), 5) if musique_positions else 0
        taux_vict = sum(1 for p in musique_positions[:5] if p == 1) / min(len(musique_positions), 5) if musique_positions else 0
    else:
        f1 = f3 = f5 = f10 = 0.5
        tendance = regularite = taux_top3 = taux_vict = 0.0

    feat_forme = {
        "forme_1_course": f1,
        "forme_3_courses": f3,
        "forme_5_courses": f5,
        "forme_10_courses": f10,
        "forme_tendance": tendance,
        "regularite": regularite,
        "taux_top3": taux_top3,
        "taux_victoire_5c": taux_vict,
    }

    # ── B-bis. Dynamique de course (accélération finale, réduction km) ─────
    # h[9]=acceleration_label, h[10]=reduction_km (cf. SELECT ci-dessus).
    feat_dynamics = aggregate_dynamics([(h[9], h[10]) for h in historique])

    # ── C. Repos et fraîcheur ─────────────────────────────────────────────
    if historique:
        from datetime import date as date_type, timedelta
        try:
            last_date = historique[0][4]
            today_date = date_heure.date() if hasattr(date_heure, "date") else date_type.fromisoformat(str(date_heure)[:10])
            if isinstance(last_date, str):
                last_date = date_type.fromisoformat(last_date)
            jours_repos = (today_date - last_date).days
        except Exception:
            jours_repos = 30
    else:
        jours_repos = 90

    # Fraîcheur optimale 14-35 jours
    if 14 <= jours_repos <= 35:
        fraicheur = 1.0
    elif jours_repos < 14:
        fraicheur = jours_repos / 14.0
    elif jours_repos <= 60:
        fraicheur = max(0.1, 1.0 - (jours_repos - 35) / 50.0)
    else:
        fraicheur = max(0.05, 1.0 - (jours_repos - 35) / 120.0)

    # Surmenage : courses sur 90 derniers jours
    nb_courses_90j = sum(1 for h in historique if h[4] and _days_diff(h[4], date_heure) <= 90)
    surmenage = min(1.0, nb_courses_90j / 15.0) if nb_courses_90j > 8 else 0.0

    feat_repos = {
        "jours_repos": int(jours_repos),
        "fraicheur_score": float(fraicheur),
        "nb_courses_90j": int(nb_courses_90j),
        "surmenage_score": float(surmenage),
    }

    # ── D. Distance ───────────────────────────────────────────────────────
    dist_int = int(distance or 2000)
    dist_cat = get_dist_cat(dist_int)

    dist_hist = [h for h in historique if h[1] and abs(h[1] - dist_int) <= 200]
    dist_scores = [score_position(parse_musique("")[0] if not h[0] else h[0], nb_partants_int)
                   for h in dist_hist if h[0] and h[0] < 20]
    pref_dist = float(np.mean(dist_scores)) if dist_scores else 0.5

    dist_moyennes = [h[1] for h in historique if h[1]]
    delta_dist = abs(dist_int - float(np.mean(dist_moyennes))) if dist_moyennes else 0.0

    feat_distance = {
        f"pref_dist_{dist_cat}": pref_dist,
        "nb_courses_distance": len(dist_hist),
        "delta_dist_prefere": float(delta_dist),
        "pref_distance_actuelle": pref_dist,
        "dist_code": list(DISTANCE_BUCKET.keys()).index(dist_cat),
    }

    # ── E. Terrain ────────────────────────────────────────────────────────
    terrain_cat = get_terrain_cat(terrain)
    terrain_hist = [h for h in historique if get_terrain_cat(h[2]) == terrain_cat and h[0]]
    terrain_scores = [score_position(h[0], nb_partants_int) for h in terrain_hist if h[0] < 20]
    pref_terrain = float(np.mean(terrain_scores)) if terrain_scores else 0.5

    # humidite_piste — depuis meteo_courses si disponible
    meteo_r = await session.execute(text("""
        SELECT pluie_24h, humidite
        FROM meteo_courses
        WHERE course_id = :cid
        LIMIT 1
    """), {"cid": course_id})
    meteo_row = meteo_r.fetchone()
    humidite_piste = 0.0
    if meteo_row:
        precip = float(meteo_row[0] or 0)
        humidite = float(meteo_row[1] or 50)
        humidite_piste = float(np.clip((precip * 0.3 + (humidite - 50) * 0.01), 0.0, 1.0))

    # Pénétromètre officiel France Galop
    penetro_row = await session.execute(text("""
        SELECT penetrometre_coef FROM courses WHERE course_id = :cid
    """), {"cid": course_id})
    penetro = penetro_row.scalar()
    penetrometre_coef = float(penetro) if penetro else None

    feat_terrain = {
        f"pref_terrain_{terrain_cat}": pref_terrain,
        "nb_courses_terrain": len(terrain_hist),
        "pref_terrain_actuel": pref_terrain,
        "terrain_code": {"bon": 0, "souple": 1, "lourd": 2}.get(terrain_cat, 0),
        "humidite_piste": humidite_piste,
        "penetrometre_coef": float(penetrometre_coef) if penetrometre_coef else (
            # Estimation depuis terrain_code si pas de pénétromètre
            {"bon": 3.0, "souple": 5.0, "lourd": 7.5}.get(terrain_cat, 4.0)
        ),
    }

    # ── F. Hippodrome ─────────────────────────────────────────────────────
    hippo_hist = [h for h in historique
                  if h[3] and hippodrome and h[3].upper() == hippodrome.upper() and h[0]]
    hippo_scores = [score_position(h[0], nb_partants_int) for h in hippo_hist if h[0] < 20]
    pref_hippo = float(np.mean(hippo_scores)) if hippo_scores else 0.5

    # record_hippodrome — ratio de victoires sur cet hippodrome
    hippo_wins = sum(1 for h in hippo_hist if h[0] and h[0] == 1)
    record_hippodrome = hippo_wins / len(hippo_hist) if hippo_hist else 0.0

    # corde_preference — corde gagnante historiquement vs corde actuelle
    corde_match = 0.5  # default neutre
    if corde:
        corde_r = await session.execute(text("""
            SELECT c.corde, COUNT(*) as nb
            FROM participations p
            JOIN courses c ON p.course_id = c.course_id
            JOIN historique_courses h ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
            WHERE p.cheval_id = :cid
              AND h.position_arrivee <= 3
              AND c.corde IS NOT NULL
              AND h.date_course < (:as_of)::date
            GROUP BY c.corde
            ORDER BY nb DESC
            LIMIT 1
        """), {"cid": cheval_id, "as_of": date_heure})
        best_corde_row = corde_r.fetchone()
        if best_corde_row and best_corde_row[0]:
            corde_match = 1.0 if best_corde_row[0].lower() == corde.lower() else 0.2

    feat_hippodrome = {
        "pref_hippodrome": pref_hippo,
        "nb_courses_hippodrome": len(hippo_hist),
        "record_hippodrome": float(record_hippodrome),
        "corde_preference": float(corde_match),
    }

    # ── G. Cotes et marché ────────────────────────────────────────────────
    cote = float(cote_pmu or 5.0)
    prob_implicite = 1.0 / max(cote, 1.01)

    # Rang cote dans la course
    rang_cote = int(rang_prono_pmu or 99)
    est_favori = int(rang_cote == 1)

    # Mouvement de cote sur 30 min depuis cotes_historique (TimescaleDB hypertable)
    cotes_hist_r = await session.execute(text("""
        SELECT cote FROM cotes_historique
        WHERE participation_id = :pid
          AND source = 'pmu'
          AND time >  (:as_of)::timestamptz - INTERVAL '45 minutes'
          AND time <= (:as_of)::timestamptz
          AND cote > 1.0
        ORDER BY time ASC
    """), {"pid": participation_id, "as_of": date_heure})
    cotes_hist = [float(r[0]) for r in cotes_hist_r.fetchall()]

    mouvement_30min = 0.0
    if len(cotes_hist) >= 2:
        debut, fin = cotes_hist[0], cotes_hist[-1]
        if debut > 0:
            mouvement_30min = float(np.clip((debut - fin) / debut, -1.0, 1.0))  # Positive = cote en baisse

    spi_score_val = compute_spi_from_cotes_history(cotes_hist) if len(cotes_hist) >= 2 else 0.0

    # Cotes bookmakers alternatifs
    bm_row = await session.execute(text("""
        SELECT cote_winamax, cote_betclic, cote_betclic_ouverture,
               cote_unibet, cote_betfair_exchange, mouvement_cote_pct,
               changement_jockey, jours_depuis_derniere
        FROM participations
        WHERE participation_id = :pid
    """), {"pid": participation_id})
    bm = bm_row.fetchone()
    cote_winamax = float(bm[0]) if bm and bm[0] else None
    cote_betclic  = float(bm[1]) if bm and bm[1] else None
    cote_betclic_ouv = float(bm[2]) if bm and bm[2] else None
    cote_unibet   = float(bm[3]) if bm and bm[3] else None
    cote_betfair  = float(bm[4]) if bm and bm[4] else None
    mouvement_bm_pct = float(bm[5]) if bm and bm[5] else 0.0
    changement_jockey_flag = bool(bm[6]) if bm else False
    jours_depuis = int(bm[7]) if bm and bm[7] is not None else None

    # Meilleure cote du marché (toutes sources)
    all_cotes = [c for c in [cote, float(cote_geny or 0), cote_winamax, cote_betclic, cote_unibet, cote_betfair]
                 if c and c > 1.0]
    cote_marche_min = min(all_cotes) if all_cotes else cote
    cote_marche_max = max(all_cotes) if all_cotes else cote
    spread_bookmakers = (cote_marche_max - cote_marche_min) / max(cote_marche_min, 0.01) if len(all_cotes) >= 2 else 0.0

    # PMU vs Betfair Exchange : gap = efficience du marché
    gap_pmu_betfair = (cote - cote_betfair) / cote_betfair if cote_betfair and cote_betfair > 1.0 else 0.0

    # Signal d'ouverture Betclic
    steam_move_betclic = 0.0
    if cote_betclic_ouv and cote_betclic and cote_betclic_ouv > 1.0:
        steam_move_betclic = float(np.clip(
            (cote_betclic_ouv - cote_betclic) / cote_betclic_ouv, -1.0, 1.0
        ))  # Positif = cote baissée = argent dessus

    feat_cotes = {
        "cote_pmu": cote,
        "cote_geny": float(cote_geny or cote),
        "cote_bzh": float(cote_bzh or cote),
        "cote_winamax": float(cote_winamax or cote),
        "cote_betclic": float(cote_betclic or cote),
        "cote_unibet": float(cote_unibet or cote),
        "cote_betfair_exchange": float(cote_betfair or cote),
        "cote_marche_min": float(cote_marche_min),
        "spread_bookmakers": float(spread_bookmakers),
        "gap_pmu_betfair": float(np.clip(gap_pmu_betfair, -2.0, 2.0)),
        "steam_move_betclic": float(steam_move_betclic),
        "ratio_pmu_geny": cote / max(float(cote_geny or cote), 0.01),
        "mouvement_30min": mouvement_30min,
        "mouvement_bm_pct": float(np.clip(mouvement_bm_pct, -1.0, 1.0)),  # déjà un ratio (direct-ref)/ref
        "rang_cote": rang_cote,
        "est_favori": est_favori,
        "prob_implicite": prob_implicite,
    }

    # ── H. Équipement ─────────────────────────────────────────────────────
    equip_row = await session.execute(text("""
        SELECT deferre_change, premier_deferre, oeilleres_change, equipement_nouveau
        FROM equipements
        WHERE participation_id = :pid
        LIMIT 1
    """), {"pid": participation_id})
    equip = equip_row.fetchone()

    feat_equip = {
        "changement_equipement": float(equip[0] if equip else 0),
        "premier_deferre": float(equip[1] if equip else 0),
        "nouvelles_oeilleres": float(equip[2] if equip else 0),
        "equipement_score": float(equip[3] if equip else 0),
    }

    # ── I. Jockey ─────────────────────────────────────────────────────────
    if jockey_id:
        j_stats = await session.execute(text("""
            SELECT taux_victoire_global, taux_place_global, roi_global, montes_30j,
                   victoires_saison, courses_saison
            FROM stats_jockeys
            WHERE jockey_id = :jid
            ORDER BY saison DESC LIMIT 1
        """), {"jid": jockey_id})
        js = j_stats.fetchone()
    else:
        js = None

    # jockey_forme_30j — taux de victoire réel sur 30 jours depuis historique_courses
    # null-guard : la ligne stats_jockeys peut exister avec des colonnes NULL.
    jockey_forme_30j = float(js[0]) if (js and js[0] is not None) else 0.12  # fallback global
    if jockey_id:
        j30_r = await session.execute(text("""
            SELECT
                COUNT(*) as courses,
                SUM(CASE WHEN h.position_arrivee = 1 THEN 1 ELSE 0 END) as wins
            FROM historique_courses h
            JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
            WHERE p.jockey_id = :jid
              AND h.date_course >  (:as_of)::timestamptz - INTERVAL '30 days'
              AND h.date_course <  (:as_of)::timestamptz
        """), {"jid": jockey_id, "as_of": date_heure})
        j30 = j30_r.fetchone()
        if j30 and j30[0] and j30[0] >= 3:
            jockey_forme_30j = float(j30[1] or 0) / float(j30[0])

    # Association jockey × entraîneur (table dédiée)
    asso_taux = 0.0
    asso_nb = 0
    if jockey_id and entraineur_id:
        from datetime import datetime as dt_mod
        # saison = ANNÉE DE LA COURSE (pas l'année courante) — sinon une course passée
        # lirait les stats d'asso de l'année en cours = fuite de données futures.
        saison = date_heure.year if hasattr(date_heure, "year") else dt_mod.now().year
        asso_r = await session.execute(text("""
            SELECT taux_victoire, nb_courses
            FROM associations_jockey_entraineur
            WHERE jockey_id = :jid AND entraineur_id = :eid AND saison = :s
            LIMIT 1
        """), {"jid": jockey_id, "eid": entraineur_id, "s": saison})
        asso_row = asso_r.fetchone()
        if asso_row:
            asso_taux = float(asso_row[0] or 0)
            asso_nb = int(asso_row[1] or 0)

    feat_jockey = {
        "jockey_taux_victoire_global": float(js[0]) if (js and js[0] is not None) else 0.12,
        "jockey_taux_place_global": float(js[1]) if (js and js[1] is not None) else 0.30,
        "jockey_roi": float(js[2]) if (js and js[2] is not None) else 0.0,
        "jockey_montes_30j": int(js[3]) if (js and js[3] is not None) else 0,
        "jockey_victoires_saison": int(js[4]) if (js and js[4] is not None) else 0,
        "jockey_forme_30j": jockey_forme_30j,
        "changement_jockey": int(changement_jockey_flag),
        "asso_jockey_entraineur_taux": float(asso_taux),
        "asso_jockey_entraineur_nb": int(asso_nb),
        "asso_jockey_entraineur_fiable": int(asso_nb >= 5),
    }

    # ── J. Entraîneur ─────────────────────────────────────────────────────
    if entraineur_id:
        e_stats = await session.execute(text("""
            SELECT taux_victoire_global, taux_place_global, roi_global,
                   victoires_saison, courses_saison
            FROM stats_entraineurs
            WHERE entraineur_id = :eid
            ORDER BY saison DESC LIMIT 1
        """), {"eid": entraineur_id})
        es = e_stats.fetchone()
    else:
        es = None

    # Combo jockey + entraîneur (win% quand ce duo)
    combo_rate = 0.0
    if jockey_id and entraineur_id:
        combo_r = await session.execute(text("""
            SELECT COUNT(*) FILTER (WHERE h.position_arrivee = 1)::float / NULLIF(COUNT(*), 0)
            FROM historique_courses h
            JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
            WHERE p.jockey_id = :jid AND p.entraineur_id = :eid
              AND h.date_course < (:as_of)::date
        """), {"jid": jockey_id, "eid": entraineur_id, "as_of": date_heure})
        combo_rate = float(combo_r.scalar() or 0.0)

    feat_entraineur = {
        "entraineur_taux_global": float(es[0]) if (es and es[0] is not None) else 0.12,
        "entraineur_taux_place": float(es[1]) if (es and es[1] is not None) else 0.30,
        "entraineur_roi": float(es[2]) if (es and es[2] is not None) else 0.0,
        "entraineur_victoires_saison": int(es[3]) if (es and es[3] is not None) else 0,
        "combo_jockey_entraineur": combo_rate,
        "entraineur_forme_30j": float(es[0]) if (es and es[0] is not None) else 0.12,
    }

    # ── K. Identité cheval ────────────────────────────────────────────────
    age_int = int(age or 4)
    gains = int(gains_carriere or 0)
    # Running style
    rs_row = await session.execute(text("""
        SELECT running_style, taux_en_tete, prix_vente_yearling FROM chevaux WHERE cheval_id = :cid
    """), {"cid": cheval_id})
    rs = rs_row.fetchone()
    RUNNING_STYLE_CODE = {"mene": 0, "suit_tete": 1, "placier": 2, "ferme": 3, "irregulier": 4}
    running_style_code = RUNNING_STYLE_CODE.get(rs[0] or "", 4) if rs else 4
    taux_en_tete = float(rs[1] or 0.0) if rs else 0.0
    prix_vente_log = float(math.log1p(rs[2] or 0)) if rs and rs[2] else 0.0

    # Freshness depuis DB (plus précis que calcul manuel)
    freshness_jours = jours_depuis if jours_depuis is not None else (
        feat_repos["jours_repos"] if "feat_repos" in dir() else 30
    )

    feat_cheval = {
        "age": age_int,
        "age_squared": age_int ** 2,
        "sexe_code": SEXE_CODE.get(str(sexe or "H"), 0),
        "gains_log": float(math.log1p(gains)),
        "retard_gains": float(retard_gains or 0),
        "indice_valeur": 0.0,
        "running_style_code": running_style_code,
        "taux_en_tete": taux_en_tete,
        "prix_vente_log": prix_vente_log,
        "jours_depuis_derniere_db": int(freshness_jours),
    }

    # ── L. Contexte course ────────────────────────────────────────────────
    import datetime as dt
    heure_course = date_heure.hour if hasattr(date_heure, "hour") else 14
    dot_log = float(math.log1p(allocation or 0))

    feat_course = {
        "nb_partants": nb_partants_int,
        "log_nb_partants": float(math.log(max(nb_partants_int, 2))),
        "discipline_code": DISCIPLINE_CODE.get(disc_lower.split()[0], 0),
        "niveau_course_code": _encode_niveau(niveau_course, categorie_particularite),
        "dotation_log": dot_log,
        "course_designee": int(est_quinte or False),
        "heure_course": int(heure_course),
        "nb_courses_reunion": 0,  # Calculé séparément
    }

    # ── M. Popularité & sagesse ───────────────────────────────────────────
    # Pronostics presse — combien d'experts ont sélectionné ce cheval (rang ≤ 4)
    presse_row = await session.execute(text("""
        SELECT COUNT(*) as nb_experts,
               SUM(CASE WHEN sel->>'rang' = '1' THEN 1 ELSE 0 END) as nb_premier
        FROM pronostics_presse pp,
             json_array_elements(pp.selection::json) sel
        WHERE pp.course_id = :cid
          AND (sel->>'numero')::int = (
              SELECT p.numero FROM participations p WHERE p.participation_id = :pid
          )
    """), {"cid": course_id, "pid": participation_id})
    presse = presse_row.fetchone()
    nb_experts_presse = int(presse[0] or 0) if presse else 0
    nb_premier_presse = int(presse[1] or 0) if presse else 0

    # Pool PMU — ratio pool gagnant / pool total (signal sur ce cheval)
    pool_row = await session.execute(text("""
        SELECT pool_total_centimes, pool_gagnant_centimes FROM courses WHERE course_id = :cid
    """), {"cid": course_id})
    pool_data = pool_row.fetchone()
    pool_ratio = 0.0
    if pool_data and pool_data[0] and pool_data[1] and pool_data[0] > 0:
        pool_ratio = float(pool_data[1]) / float(pool_data[0])  # part du gagnant dans le pool

    feat_populaire = {
        "rang_popularite": int(rang_prono_pmu or 10),
        "rang_pronostic_geny": int(rang_prono_geny or 10),
        "pronostic_expert_rang": int(rang_prono_geny or 10),
        "sagesse_foules_score": 1.0 / max(int(rang_prono_pmu or 10), 1),
        "consensus_sources": _consensus_score(rang_prono_pmu, rang_prono_geny),
        "nb_experts_presse": nb_experts_presse,
        "nb_premier_presse": nb_premier_presse,
        "presse_consensus_score": float(min(nb_experts_presse / 3.0, 1.0)),  # 0-1
        "pool_gagnant_ratio": float(np.clip(pool_ratio, 0.0, 1.0)),
    }

    # ── N. Signaux avancés ────────────────────────────────────────────────
    # variance_cotes_7j — spread des cotes PMU sur 7 jours
    cotes_7j_r = await session.execute(text("""
        SELECT cote FROM cotes_historique
        WHERE participation_id = :pid AND source = 'pmu'
          AND time >  (:as_of)::timestamptz - INTERVAL '7 days'
          AND time <= (:as_of)::timestamptz AND cote > 1.0
        ORDER BY time ASC
    """), {"pid": participation_id, "as_of": date_heure})
    cotes_7j = [float(r[0]) for r in cotes_7j_r.fetchall()]
    variance_cotes = float(np.var(cotes_7j)) if len(cotes_7j) >= 3 else 0.0

    # momentum_3j — direction moyenne des cotes sur 3 jours
    momentum_3j = 0.0
    if len(cotes_7j) >= 4:
        mid = len(cotes_7j) // 2
        early_mean = float(np.mean(cotes_7j[:mid]))
        late_mean = float(np.mean(cotes_7j[mid:]))
        if early_mean > 0:
            momentum_3j = float(np.clip((early_mean - late_mean) / early_mean, -1.0, 1.0))

    feat_signal = {
        "momentum_3j": momentum_3j,
        "variance_cotes_7j": float(np.clip(variance_cotes, 0.0, 100.0)),
        "spi_score": spi_score_val,
        "decote_detectee": _decote_detectee(cote_pmu, cote_geny, cote_bzh),
        "valeur_latente": _valeur_latente(
            cote_pmu, cote_geny, cote_bzh,
            cote_betfair=cote_betfair,
            cote_winamax=cote_winamax,
            cote_betclic=cote_betclic,
        ),
        # Nouveaux signaux bookmakers
        "steam_move_betclic": steam_move_betclic,
        "gap_pmu_betfair": float(np.clip(gap_pmu_betfair, -2.0, 2.0)),
        "spread_bookmakers": float(np.clip(spread_bookmakers, 0.0, 2.0)),
        "mouvement_bm_pct": float(np.clip(mouvement_bm_pct, -1.0, 1.0)),  # déjà un ratio (direct-ref)/ref
    }

    # ── O. Velocity ELO — vitesse de progression sur 30 jours ─────────────
    elo_velocity_r = await session.execute(text("""
        SELECT delta_elo, date_course
        FROM elo_historique
        WHERE cheval_id = :cid
        ORDER BY date_course DESC LIMIT 10
    """), {"cid": cheval_id})
    elo_hist_rows = elo_velocity_r.fetchall()

    velocity_elo = 0.0
    elo_trend_30j = 0.0
    if len(elo_hist_rows) >= 2:
        recent_deltas = [r[0] for r in elo_hist_rows[:5] if r[0] is not None]
        velocity_elo = float(np.mean(recent_deltas)) if recent_deltas else 0.0
        # Trend linéaire sur les 10 dernières entrées
        deltas = [r[0] for r in elo_hist_rows if r[0] is not None]
        if len(deltas) >= 3:
            x = np.arange(len(deltas))
            elo_trend_30j = float(np.polyfit(x, deltas, 1)[0]) * 5

    feat_velocity_elo = {
        "velocity_elo": float(velocity_elo),
        "elo_trend_30j": float(elo_trend_30j),
    }

    # ── P. Course fingerprint — taux de réussite sur cette combinaison exacte ──
    # Distance ± 200m × terrain_cat × hippodrome × discipline
    fingerprint_r = await session.execute(text("""
        SELECT COUNT(*) as nb, SUM(CASE WHEN h.position_arrivee <= 3 THEN 1 ELSE 0 END) as top3
        FROM historique_courses h
        WHERE h.cheval_id = :cid
          AND h.discipline = :disc
          AND ABS(h.distance - :dist) <= 200
          AND h.hippodrome ILIKE :hippo
          AND h.date_course < (:as_of)::date
    """), {
        "cid": cheval_id, "disc": discipline or "plat",
        "dist": dist_int, "hippo": f"%{(hippodrome or '')}%",
        "as_of": date_heure,
    })
    fp = fingerprint_r.fetchone()
    fp_nb = int(fp[0] or 0) if fp else 0
    fp_top3 = int(fp[1] or 0) if fp else 0
    course_fingerprint_score = fp_top3 / fp_nb if fp_nb >= 2 else 0.5

    feat_fingerprint = {
        "course_fingerprint_nb": fp_nb,
        "course_fingerprint_score": float(course_fingerprint_score),
    }

    # ── Q. Jockey-cheval synergy — taux victoire SPÉCIFIQUE ce duo ────────
    synergy_score = 0.0
    synergy_nb = 0
    if jockey_id:
        syn_r = await session.execute(text("""
            SELECT
                COUNT(*) as nb,
                SUM(CASE WHEN h.position_arrivee = 1 THEN 1 ELSE 0 END) as wins,
                SUM(CASE WHEN h.position_arrivee <= 3 THEN 1 ELSE 0 END) as top3
            FROM historique_courses h
            JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
            WHERE h.cheval_id = :cid AND p.jockey_id = :jid
              AND h.date_course < (:as_of)::date
        """), {"cid": cheval_id, "jid": jockey_id, "as_of": date_heure})
        syn = syn_r.fetchone()
        if syn and syn[0] and syn[0] >= 2:
            synergy_nb = int(syn[0])
            synergy_score = float(syn[2] or 0) / synergy_nb  # top3 rate

    feat_synergy = {
        "jockey_cheval_synergy_nb": synergy_nb,
        "jockey_cheval_synergy_score": float(synergy_score),
    }

    # ── R. Time-decay form score — courses récentes pèsent plus ──────────
    # 0.95^n par course en arrière
    decay_score = 0.0
    if historique:
        weights = [0.95 ** i for i in range(len(historique))]
        positions = [h[0] for h in historique if h[0] is not None]
        if positions:
            w = weights[:len(positions)]
            scores_hist = [score_position(p, nb_partants_int) for p in positions]
            decay_score = float(np.average(scores_hist, weights=w[:len(scores_hist)]))

    # ── S. Opposition quality — qualité des adversaires battus ────────────
    opp_quality = 0.0
    if historique:
        # Average ELO of opponents in races where this horse finished top3
        opp_r = await session.execute(text("""
            SELECT AVG(ch2.elo_score_global)
            FROM historique_courses h1
            JOIN participations p1 ON h1.course_id = p1.course_id AND h1.cheval_id = p1.cheval_id
            JOIN participations p2 ON p2.course_id = p1.course_id AND p2.cheval_id != :cid
            JOIN chevaux ch2 ON ch2.cheval_id = p2.cheval_id
            WHERE h1.cheval_id = :cid
              AND h1.position_arrivee <= 3
              AND h1.date_course >  (:as_of)::timestamptz - INTERVAL '18 months'
              AND h1.date_course <  (:as_of)::timestamptz
        """), {"cid": cheval_id, "as_of": date_heure})
        opp_row = opp_r.fetchone()
        if opp_row and opp_row[0]:
            opp_quality = float(np.clip(opp_row[0] / ELO_INITIAL - 1.0, -0.5, 1.0))

    feat_advanced = {
        "time_decay_form": float(decay_score),
        "opposition_quality": float(opp_quality),
    }

    # ── T. Pace analysis — vitesse théorique & profil d'allure ─────────────
    # Temps de référence par discipline + distance (vitesse en m/s)
    VITESSE_REF = {
        "plat": {1000: 16.5, 1400: 15.8, 1600: 15.5, 2000: 15.0, 2400: 14.5, 3000: 14.0},
        "trot":  {1000: 13.0, 1700: 12.5, 2100: 12.0, 2700: 11.5},
        "haies": {2800: 11.5, 3200: 11.2, 4000: 10.8},
    }
    def get_vitesse_ref(disc: str, dist_m: int) -> float:
        d = disc.lower() if disc else "plat"
        key = "plat"
        if "trot" in d or "attelé" in d or "monté" in d:
            key = "trot"
        elif "haies" in d or "steeple" in d:
            key = "haies"
        refs = VITESSE_REF.get(key, VITESSE_REF["plat"])
        # Interpolation linéaire
        dists = sorted(refs.keys())
        if dist_m <= dists[0]:
            return refs[dists[0]]
        if dist_m >= dists[-1]:
            return refs[dists[-1]]
        for i in range(len(dists) - 1):
            if dists[i] <= dist_m <= dists[i + 1]:
                t = (dist_m - dists[i]) / (dists[i + 1] - dists[i])
                return refs[dists[i]] * (1 - t) + refs[dists[i + 1]] * t
        return 14.0

    vitesse_theorique = get_vitesse_ref(discipline, dist_int)

    # Profil stamina — cheval performe-t-il mieux sur courses longues ?
    # Compare score moyen sur courses > distance actuelle vs < distance actuelle
    hist_long = [score_position(h[0], nb_partants_int) for h in historique
                 if h[0] and h[0] < 20 and h[1] and int(h[1]) > dist_int + 200]
    hist_court = [score_position(h[0], nb_partants_int) for h in historique
                  if h[0] and h[0] < 20 and h[1] and int(h[1]) < dist_int - 200]
    stamina_index = float(np.mean(hist_long) - np.mean(hist_court)) if hist_long and hist_court else 0.0

    # Cohérence discipline — cheval a-t-il déjà couru cette discipline ?
    hist_same_disc = [h for h in historique if h[7] and discipline and h[7].lower() == discipline.lower()]
    disc_cohérence = len(hist_same_disc) / max(len(historique), 1) if historique else 0.5

    feat_pace = {
        "vitesse_theorique": float(vitesse_theorique),
        "stamina_index": float(np.clip(stamina_index, -1.0, 1.0)),
        "discipline_coherence": float(disc_cohérence),
    }

    # ── U. Pedigree affinity — performances lignée à cette distance/terrain ─
    sire_dist_winrate = 0.0
    sire_terrain_winrate = 0.0
    try:
        sire_r = await session.execute(text("""
            SELECT ch2.cheval_id
            FROM chevaux ch
            JOIN chevaux ch2 ON ch2.nom = ch.pere
            WHERE ch.cheval_id = :cid LIMIT 1
        """), {"cid": cheval_id})
        sire_row = sire_r.fetchone()
        if sire_row:
            sire_id = sire_row[0]
            # Progéniture du père à cette distance
            sire_dist_r = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE h.position_arrivee <= 3)::float / NULLIF(COUNT(*), 0)
                FROM historique_courses h
                JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
                JOIN chevaux c_child ON c_child.cheval_id = p.cheval_id
                JOIN chevaux c_sire ON c_sire.nom = c_child.pere
                WHERE c_sire.cheval_id = :sid
                  AND ABS(h.distance - :dist) <= 300
                  AND h.date_course < (:as_of)::date
            """), {"sid": sire_id, "dist": dist_int, "as_of": date_heure})
            sire_dist_row = sire_dist_r.fetchone()
            sire_dist_winrate = float(sire_dist_row[0] or 0.0) if sire_dist_row else 0.0

            # Progéniture du père sur ce terrain
            sire_terrain_r = await session.execute(text("""
                SELECT
                    COUNT(*) FILTER (WHERE h.position_arrivee <= 3)::float / NULLIF(COUNT(*), 0)
                FROM historique_courses h
                JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
                JOIN chevaux c_child ON c_child.cheval_id = p.cheval_id
                JOIN chevaux c_sire ON c_sire.nom = c_child.pere
                WHERE c_sire.cheval_id = :sid
                  AND h.terrain ILIKE :terr
                  AND h.date_course < (:as_of)::date
            """), {"sid": sire_id, "terr": f"%{terrain_cat}%", "as_of": date_heure})
            sire_terrain_row = sire_terrain_r.fetchone()
            sire_terrain_winrate = float(sire_terrain_row[0] or 0.0) if sire_terrain_row else 0.0
    except Exception:
        pass  # Pedigree data optional

    feat_pedigree = {
        "sire_dist_winrate": float(np.clip(sire_dist_winrate, 0.0, 1.0)),
        "sire_terrain_winrate": float(np.clip(sire_terrain_winrate, 0.0, 1.0)),
    }

    # ── V. Contextual stats — jockey×hippo, entraîneur×hippo, prep pattern ─
    jockey_hippo_winrate = 0.0
    if jockey_id and hippodrome:
        jh_r = await session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE h.position_arrivee = 1)::float / NULLIF(COUNT(*), 0)
            FROM historique_courses h
            JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
            WHERE p.jockey_id = :jid
              AND h.hippodrome ILIKE :hippo
              AND h.date_course >  (:as_of)::timestamptz - INTERVAL '24 months'
              AND h.date_course <  (:as_of)::timestamptz
        """), {"jid": jockey_id, "hippo": f"%{hippodrome}%", "as_of": date_heure})
        jh_row = jh_r.fetchone()
        jockey_hippo_winrate = float(jh_row[0] or 0.0) if jh_row else 0.0

    entraineur_hippo_winrate = 0.0
    if entraineur_id and hippodrome:
        eh_r = await session.execute(text("""
            SELECT
                COUNT(*) FILTER (WHERE h.position_arrivee = 1)::float / NULLIF(COUNT(*), 0)
            FROM historique_courses h
            JOIN participations p ON h.course_id = p.course_id AND h.cheval_id = p.cheval_id
            WHERE p.entraineur_id = :eid
              AND h.hippodrome ILIKE :hippo
              AND h.date_course >  (:as_of)::timestamptz - INTERVAL '24 months'
              AND h.date_course <  (:as_of)::timestamptz
        """), {"eid": entraineur_id, "hippo": f"%{hippodrome}%", "as_of": date_heure})
        eh_row = eh_r.fetchone()
        entraineur_hippo_winrate = float(eh_row[0] or 0.0) if eh_row else 0.0

    # Trainer prep pattern — intervalle entre dernières courses (signal d'une prépa calculée)
    # Interval régulier entre 3 dernières courses = cheval bien préparé
    trainer_prep_score = 0.5
    if len(historique) >= 3:
        try:
            dates = []
            for h in historique[:3]:
                d = h[4]
                if isinstance(d, str):
                    from datetime import date as date_t
                    d = date_t.fromisoformat(d)
                dates.append(d)
            intervals = [_days_diff(dates[i + 1], dates[i]) for i in range(len(dates) - 1)]
            mean_interval = float(np.mean(intervals))
            std_interval = float(np.std(intervals))
            # Score élevé si intervalles réguliers (std faible vs mean)
            if mean_interval > 0:
                cv = std_interval / mean_interval  # coefficient of variation
                trainer_prep_score = float(np.clip(1.0 - cv, 0.0, 1.0))
        except Exception:
            pass

    # Dotation par kg porté (qualité relative au poids)
    allocation_per_kg = float((allocation or 10000) / max(float(poids or 56), 50.0))

    feat_contextual = {
        "jockey_hippo_winrate": float(jockey_hippo_winrate),
        "entraineur_hippo_winrate": float(entraineur_hippo_winrate),
        "trainer_prep_score": float(trainer_prep_score),
        "allocation_per_kg": float(np.clip(allocation_per_kg, 0.0, 5000.0)),
        # Poids porté (kg) — signal handicap direct (plus de poids = pénalisé).
        "poids_porte": float(poids) if poids else 0.0,
    }

    # ── W. Field dynamics — concentration, outsider density ────────────────
    # Herfindahl-Hirschman Index des probabilités implicites du champ
    # HHI élevé = champ dominé par 1-2 chevaux (outsider moins chanceux)
    # HHI bas = champ ouvert (outsider a une vraie chance)
    field_cotes_r = await session.execute(text("""
        SELECT cote_pmu FROM participations
        WHERE course_id = :cid AND non_partant = false AND cote_pmu > 1.0
    """), {"cid": course_id})
    field_cotes = [float(r[0]) for r in field_cotes_r.fetchall()]

    hhi = 0.0
    nb_outsiders = 0
    ecart_top2 = 0.0
    if field_cotes:
        # Proba implicites normalisées (sum to 1)
        probs_impl = np.array([1.0 / c for c in field_cotes])
        probs_impl = probs_impl / probs_impl.sum()
        hhi = float(np.sum(probs_impl ** 2))  # 1/n (uniforme) à 1 (monopole)
        # Nb outsiders (cote > 10.0)
        nb_outsiders = sum(1 for c in field_cotes if c > 10.0)
        # Écart top-2 probas
        sorted_probs = sorted(probs_impl, reverse=True)
        if len(sorted_probs) >= 2:
            ecart_top2 = float(sorted_probs[0] - sorted_probs[1])

    # Rang cote relatif (normalisé par taille du champ)
    rang_relatif = float(rang_cote) / max(nb_partants_int, 1)

    feat_field = {
        "field_hhi": float(hhi),
        "nb_outsiders": int(nb_outsiders),
        "ecart_proba_top2": float(ecart_top2),
        "rang_cote_relatif": float(rang_relatif),
    }

    # ── X. Temporal/seasonal signals ──────────────────────────────────────
    # Mois et saison
    import datetime as dt_mod
    try:
        if hasattr(date_heure, "month"):
            mois_course = date_heure.month
        else:
            mois_course = int(str(date_heure)[5:7])
    except Exception:
        mois_course = 6

    saison_code = {12: 0, 1: 0, 2: 0,   # hiver
                   3: 1, 4: 1, 5: 1,    # printemps
                   6: 2, 7: 2, 8: 2,    # été
                   9: 3, 10: 3, 11: 3}  # automne
    saison = saison_code.get(mois_course, 2)

    # Performance saisonnière — win rate dans cette saison historiquement
    saison_form = 0.0
    if historique:
        saison_months = {0: [12, 1, 2], 1: [3, 4, 5], 2: [6, 7, 8], 3: [9, 10, 11]}
        target_months = saison_months.get(saison, [])
        saison_perf = []
        for h in historique:
            if h[4] and h[0]:
                try:
                    h_date = h[4]
                    if isinstance(h_date, str):
                        from datetime import date as date_t
                        h_date = date_t.fromisoformat(h_date)
                    if hasattr(h_date, "month") and h_date.month in target_months:
                        saison_perf.append(score_position(h[0], nb_partants_int))
                except Exception:
                    pass
        saison_form = float(np.mean(saison_perf)) if saison_perf else 0.5

    # Signal temporal de marché — heure de mise en jeu (matin vs après-midi)
    # Les paris matinaux proviennent plus souvent de pros
    market_timing_score = 0.0
    if len(cotes_hist) >= 2:
        # Si grosse variation tôt le matin (avant 10h) → signal pro
        try:
            h_now = date_heure.hour if hasattr(date_heure, "hour") else 14
            if h_now < 10 and mouvement_30min > 0.05:
                market_timing_score = mouvement_30min * 1.5
            else:
                market_timing_score = mouvement_30min
        except Exception:
            market_timing_score = mouvement_30min

    feat_temporal = {
        "mois_course": int(mois_course),
        "saison_code": int(saison),
        "saison_form": float(saison_form),
        "market_timing_score": float(np.clip(market_timing_score, -1.0, 1.0)),
    }

    # ── Assemblage final ──────────────────────────────────────────────────
    features = {
        "participation_id": participation_id,
        "course_id": course_id,
        **feat_elo,
        **feat_forme,
        **feat_dynamics,
        **feat_repos,
        **feat_distance,
        **feat_terrain,
        **feat_hippodrome,
        **feat_cotes,
        **feat_equip,
        **feat_jockey,
        **feat_entraineur,
        **feat_cheval,
        **feat_course,
        **feat_populaire,
        **feat_signal,
        **feat_velocity_elo,
        **feat_fingerprint,
        **feat_synergy,
        **feat_advanced,
        **feat_pace,
        **feat_pedigree,
        **feat_contextual,
        **feat_field,
        **feat_temporal,
    }

    return features


def _days_diff(d1, d2) -> int:
    """Différence en jours entre deux dates."""
    from datetime import date as date_t
    try:
        if isinstance(d1, str):
            d1 = date_t.fromisoformat(d1)
        if isinstance(d2, str):
            d2 = date_t.fromisoformat(d2)
        if hasattr(d2, "date"):
            d2 = d2.date()
        if hasattr(d1, "date"):
            d1 = d1.date()
        return abs((d2 - d1).days)
    except Exception:
        return 999


def _encode_niveau(niveau: Optional[str], categorie: Optional[str] = None) -> int:
    """Classe de la course. Lit d'ABORD le champ structuré du PMU.

    Défaut corrigé le 2026-09-01 : `niveau_course_code` figurait parmi les
    features à variance strictement nulle, et pour une raison qui n'est pas un
    manque de donnée — c'est la mauvaise colonne qui était lue.

    `courses.niveau_course` est alimentée par `conditions` du PMU, et ce champ ne
    décrit PAS le niveau de la course : il décrit qui a le droit d'y courir.
    Valeurs réelles en production, 19 183 courses sur un an, remplies à 100 %,
    7 869 libellés distincts — « Pour pur sang males, hongres et femelles de
    trois ans… », « Pour juments de 4 ans et au-dessus… ». Aucune ne contient
    « group1 », « listed » ni « reclam » : les six branches anglaises étaient
    mortes-nées et TOUTES les courses tombaient sur le `return 3` final. Une
    constante, donc du bruit pour le modèle.

    Le vrai champ existe déjà, il est scrapé et stocké depuis longtemps :
    `courses.categorie_particularite` (`categorieParticularite` du PMU) —
    GROUPE_I (227), GROUPE_II (155), GROUPE_III (227), COURSE_A_CONDITIONS
    (4 312), HANDICAP et ses variantes (4 226), A_RECLAMER (1 004), AMATEURS et
    APPRENTIS_LADS_JOCKEYS (~800), INCONNU (3 483).

    Échelle : elle ordonne le prestige de 0 (Groupe I) vers le bas, mais elle
    reste une ÉCHELLE DE CLASSES, pas une mesure — un modèle à arbres n'y lit
    que des seuils. Deux choix méritent d'être explicites :

    - `INCONNU`, vide, et tout libellé non reconnu gardent la valeur **3**,
      exactement celle que produisait l'ancien code pour l'intégralité du champ.
      Le cas « on ne sait pas » ne change donc pas de valeur : ce qui bouge,
      c'est uniquement ce qu'on sait désormais nommer.
    - `AUTOSTART`, `NATIONALE`, `EUROPEENNE`, `INTERNATIONALE` ne sont PAS des
      niveaux (mode de départ, recrutement géographique) : ils ne sont pas
      encodés, sous peine de faire dire à l'échelle ce qu'elle ne mesure pas.

    Le texte libre reste lu en repli : une source non-PMU qui écrirait
    « Listed » ou « Group 2 » garde son encodage.

    Aucun risque de décalage train/serve pour le modèle EN SERVICE : la feature
    lui a été présentée constante, aucun arbre ne peut donc porter de coupure
    dessus. C'est le prochain entraînement qui décidera si elle vaut quelque
    chose, arbitré par le head-to-head champion/challenger.
    """
    cat = (categorie or "").strip().upper()
    if cat and cat != "INCONNU":
        # L'ordre compte : `A_RECLAMER_APPRENTIS_LADS_JOCKEYS` et
        # `HANDICAP_A_RECLAMER` existent, et c'est la classe la plus
        # DISCRIMINANTE qui doit gagner, pas la première rencontrée.
        if "GROUPE_I" in cat and "GROUPE_II" not in cat and "GROUPE_III" not in cat:
            return 0
        if "GROUPE_II" in cat or "GROUPE_III" in cat:
            return 1
        if "LISTED" in cat:
            return 2
        if "RECLAMER" in cat:
            return 4
        if "HANDICAP" in cat:
            return 5
        if "AMATEURS" in cat or "APPRENTIS" in cat:
            return 6
        if "CONDITION" in cat:
            return 7

    if not niveau:
        return 3
    n = niveau.lower()
    if "group1" in n or "grade1" in n:
        return 0
    if "group2" in n or "group3" in n:
        return 1
    if "listed" in n:
        return 2
    if "reclam" in n:
        return 4
    return 3


def _consensus_score(rang_pmu: Optional[int], rang_geny: Optional[int]) -> float:
    """Score consensus : 1.0 si les deux sources accordent le même rang."""
    if rang_pmu is None or rang_geny is None:
        return 0.5
    diff = abs(rang_pmu - rang_geny)
    return max(0.0, 1.0 - diff * 0.15)


def _decote_detectee(cote_pmu: Optional[float], cote_geny: Optional[float], cote_bzh: Optional[float]) -> float:
    """Détecte si une cote est significativement basse vs les autres sources (argent intelligent)."""
    cotes = [c for c in [cote_pmu, cote_geny, cote_bzh] if c and c > 1.0]
    if len(cotes) < 2:
        return 0.0
    min_c = min(cotes)
    max_c = max(cotes)
    if max_c <= 0:
        return 0.0
    ecart = (max_c - min_c) / max_c
    return float(min(1.0, ecart * 3))  # Normalisé 0-1


def _valeur_latente(
    cote_pmu: Optional[float],
    cote_geny: Optional[float],
    cote_bzh: Optional[float],
    cote_betfair: Optional[float] = None,
    cote_winamax: Optional[float] = None,
    cote_betclic: Optional[float] = None,
) -> float:
    """
    Market efficiency gap — écart entre cote PMU et cote 'juste' calculée
    comme la médiane des sources alternatives (Geny, BZH, Betfair, Winamax, Betclic).
    Betfair Exchange = source la plus efficiente, poids × 2.
    Valeur positive = PMU surcoté = value bet potentiel.
    """
    # Betfair compte double (plus efficient)
    alt_cotes = []
    for c, w in [(cote_geny, 1), (cote_bzh, 1), (cote_winamax, 1), (cote_betclic, 1), (cote_betfair, 2)]:
        if c and c > 1.0:
            alt_cotes.extend([c] * w)

    if not alt_cotes or not cote_pmu or cote_pmu <= 1.0:
        return 0.0
    cote_marche = float(np.median(alt_cotes))
    return float(np.clip((cote_pmu - cote_marche) / cote_marche, -1.0, 2.0))


def compute_spi_from_cotes_history(cotes_history: list[float], window_minutes: int = 30) -> float:
    """
    Steam Money Indicator (SPI) — calcule depuis l'historique des cotes.
    Si cote baisse > 15% sur la dernière fenêtre → argent professionnel détecté.
    Retourne score 0-1 (1 = forte probabilité d'argent pro).
    cotes_history : liste de cotes dans l'ordre chronologique, la plus récente en dernier.
    """
    if len(cotes_history) < 2:
        return 0.0
    cote_debut = cotes_history[0]
    cote_fin = cotes_history[-1]
    if cote_debut <= 0:
        return 0.0
    variation = (cote_debut - cote_fin) / cote_debut  # Positif = baisse de cote
    if variation >= 0.15:
        return float(min(1.0, variation * 3))
    return 0.0


async def _load_course_batch_data(session: AsyncSession, course_id: str) -> dict:
    """
    Charge en 6 requêtes toutes les données nécessaires pour une course entière.
    Retourne un dict indexé par participation_id / cheval_id / jockey_id pour accès O(1).

    Réduit de ~320 requêtes à 6 pour un champ de 16 partants.
    """
    # 1. Partants + course + chevaux + jockeys + entraîneurs + équipements + nouvelles colonnes
    partants_r = await session.execute(text("""
        SELECT
            p.participation_id, p.course_id, p.cheval_id, p.jockey_id, p.entraineur_id,
            p.numero, p.cote_pmu, p.cote_geny, p.cote_bzh,
            p.cote_winamax, p.cote_betclic, p.cote_betclic_ouverture,
            p.cote_unibet, p.cote_betfair_exchange, p.mouvement_cote_pct,
            p.rang_pronostic_pmu, p.rang_pronostic_geny,
            p.poids_porte, p.decharge, p.retard_gains, p.musique,
            p.non_partant, p.changement_jockey, p.jours_depuis_derniere,
            -- Course
            c.discipline, c.distance, c.terrain_officiel, c.hippodrome_nom,
            c.nb_partants, c.allocation, c.niveau_course, c.est_quinte, c.date_heure,
            -- Cf. _encode_niveau : la classe est dans categorie_particularite,
            -- pas dans niveau_course (conditions d'engagement en texte libre).
            c.categorie_particularite,
            c.corde, c.penetrometre_coef, c.pool_total_centimes, c.pool_gagnant_centimes,
            -- Cheval
            ch.age, ch.sexe, ch.running_style, ch.taux_en_tete, ch.prix_vente_yearling,
            -- ELO POINT-IN-TIME : ELO avant cette course (snapshot) si dispo, sinon ELO
            -- courant (= pré-course pour une course à venir). Évite la fuite temporelle
            -- (entraîner sur l'ELO final qui inclut les courses futures).
            COALESCE(p.elo_avant_global, ch.elo_score_global) AS elo_g,
            COALESCE(p.elo_avant_plat, ch.elo_score_plat) AS elo_p,
            COALESCE(p.elo_avant_trot, ch.elo_score_trot) AS elo_t,
            COALESCE(p.elo_avant_obstacle, ch.elo_score_obstacle) AS elo_o,
            ch.pere, ch.mere, ch.pere_de_mere,
            -- Perf carrière
            pc.gains_carriere_total, pc.nb_courses_total, pc.nb_victoires_total,
            -- Jockey stats
            sj.taux_victoire_global AS j_win, sj.taux_place_global AS j_place,
            sj.roi_global AS j_roi, sj.montes_30j AS j_30j, sj.victoires_saison AS j_vic_s,
            -- Entraîneur stats
            se.taux_victoire_global AS e_win, se.taux_place_global AS e_place,
            se.roi_global AS e_roi, se.victoires_saison AS e_vic_s,
            -- Équipement
            eq.deferre_change, eq.premier_deferre, eq.oeilleres_change, eq.equipement_nouveau,
            -- Association J×E
            aje.taux_victoire AS asso_win, aje.nb_courses AS asso_nb,
            -- Avis entraîneur + tendance cote + smart money (enrichissements PMU, en
            -- fin pour ne pas décaler les index positionnels existants)
            p.avis_entraineur, p.tendance_force, c.pool_gagnant_evolution,
            -- Données PMU dispo mais non exploitées : débutant + profil de places
            p.indicateur_inedit, p.nb_places_second, p.nb_places_troisieme,
            -- Identité (en FIN pour ne pas décaler les index positionnels existants)
            ch.nom AS cheval_nom, j.nom AS jockey_nom, ent.nom AS entraineur_nom,
            -- Recul / distance de handicap trot (mètres) — scrapé+stocké (migration 0015)
            -- mais jamais exploité. AJOUTÉ EN DERNIER → aucun index positionnel décalé.
            p.handicap_distance,
            -- Ferrure détaillée (Aucun/Avant/Arrière/Complet) — scrapée PMU, stockée
            -- equipements.deferre, jamais exploitée (seuls les flags _change l'étaient).
            eq.deferre AS deferre_detail,
            -- Valeur de handicap (#10) — note du handicapeur (courses à handicap).
            p.valeur_handicap
        FROM participations p
        JOIN courses c ON c.course_id = p.course_id
        JOIN chevaux ch ON ch.cheval_id = p.cheval_id
        LEFT JOIN jockeys j ON j.jockey_id = p.jockey_id
        LEFT JOIN entraineurs ent ON ent.entraineur_id = p.entraineur_id
        LEFT JOIN performances_carriere pc ON pc.cheval_id = p.cheval_id
        LEFT JOIN stats_jockeys sj ON sj.jockey_id = p.jockey_id
            AND sj.saison = EXTRACT(YEAR FROM c.date_heure)
        LEFT JOIN stats_entraineurs se ON se.entraineur_id = p.entraineur_id
            AND se.saison = EXTRACT(YEAR FROM c.date_heure)
        LEFT JOIN equipements eq ON eq.participation_id = p.participation_id
        LEFT JOIN associations_jockey_entraineur aje
            ON aje.jockey_id = p.jockey_id AND aje.entraineur_id = p.entraineur_id
            AND aje.saison = EXTRACT(YEAR FROM c.date_heure)
        WHERE p.course_id = :cid AND p.non_partant = false
        ORDER BY p.numero
    """), {"cid": course_id})
    partants_raw = partants_r.fetchall()

    if not partants_raw:
        return {}

    cheval_ids = [r[2] for r in partants_raw]
    pid_list = [r[0] for r in partants_raw]
    jockey_ids = [r[3] for r in partants_raw if r[3]]
    date_heure = partants_raw[0][32]  # date_heure de la course (index aligné sur le SELECT)

    # 2. Historique des courses (max 20 par cheval) — une seule requête
    hist_r = await session.execute(text("""
        SELECT h.cheval_id, h.position_arrivee, h.distance, h.terrain,
               h.hippodrome, h.date_course, h.nb_partants, h.cote_depart,
               h.discipline, h.allocation,
               h.acceleration_label, h.reduction_km,
               -- Données dormantes réveillées (backfill API PMU) — en FIN pour ne
               -- pas décaler les index positionnels existants :
               h.corde, h.poids_porte_course, h.indice_vitesse,
               -- Écart à l'arrivée (longueurs derrière le vainqueur) — scrapé PMU
               -- (distanceAvecPrecedent). EN FIN → index 14. 0 = vainqueur.
               h.ecart_longueurs,
               -- Déroulé / trip note de la course passée (#9). EN FIN → index 15.
               h.commentaire_course,
               -- ALLOCATION NORMALISÉE EN EUROS — DERNIÈRE colonne, lue par h[-1].
               -- Voir le commentaire de la requête mono-cheval : la table mélange
               -- centimes (lignes PMU) et euros (scraper d'historique externe).
               CASE WHEN h.course_id IS NOT NULL THEN h.allocation / 100.0
                    ELSE h.allocation::float END AS allocation_eur
        FROM historique_courses h
        WHERE h.cheval_id = ANY(:cids)
          AND h.date_course < :today
        ORDER BY h.cheval_id, h.date_course DESC
    """), {"cids": cheval_ids, "today": date_heure.date() if hasattr(date_heure, "date") else str(date_heure)[:10]})
    hist_rows = hist_r.fetchall()
    hist_by_cheval: dict = {}
    for row in hist_rows:
        cid = row[0]
        if cid not in hist_by_cheval:
            hist_by_cheval[cid] = []
        if len(hist_by_cheval[cid]) < 20:
            # (0 position, 1 distance, 2 terrain, 3 hippodrome, 4 date, 5 nb_partants,
            #  6 cote, 7 discipline, 8 allocation, 9 acceleration_label, 10 reduction_km,
            #  11 corde, 12 poids_porte_course, 13 indice_vitesse, 14 ecart_longueurs,
            #  15 commentaire_course)
            hist_by_cheval[cid].append(row[1:])

    # 3. ELO history (max 10 par cheval) — POINT-IN-TIME : uniquement les deltas ELO
    # des courses ANTÉRIEURES à celle-ci (anti-fuite : sinon delta_elo_5/velocity voient
    # les variations ELO des courses futures du cheval). Pour une course à venir, tout
    # son historique est antérieur → comportement correct.
    elo_r = await session.execute(text("""
        SELECT cheval_id, delta_elo, date_course
        FROM elo_historique
        WHERE cheval_id = ANY(:cids)
          AND date_course < (SELECT date_heure FROM courses WHERE course_id = :cid)
        ORDER BY cheval_id, date_course DESC
        LIMIT 200
    """), {"cids": cheval_ids, "cid": course_id})
    elo_by_cheval: dict = {}
    for row in elo_r.fetchall():
        if row[0] not in elo_by_cheval:
            elo_by_cheval[row[0]] = []
        if len(elo_by_cheval[row[0]]) < 10:
            elo_by_cheval[row[0]].append(row[1])

    # 4. Cotes historique (last 45 min, pour mouvement)
    cotes_hist_r = await session.execute(text("""
        SELECT participation_id, cote
        FROM cotes_historique
        WHERE participation_id = ANY(:pids)
          AND source = 'pmu'
          AND time >  (:as_of)::timestamptz - INTERVAL '45 minutes'
          AND time <= (:as_of)::timestamptz
          AND cote > 1.0
        ORDER BY participation_id, time ASC
    """), {"pids": pid_list, "as_of": date_heure})
    cotes_hist_by_pid: dict = {}
    for row in cotes_hist_r.fetchall():
        if row[0] not in cotes_hist_by_pid:
            cotes_hist_by_pid[row[0]] = []
        cotes_hist_by_pid[row[0]].append(float(row[1]))

    # 5. Cotes sur 7 jours (pour variance + momentum)
    cotes_7j_r = await session.execute(text("""
        SELECT participation_id, cote
        FROM cotes_historique
        WHERE participation_id = ANY(:pids)
          AND source = 'pmu'
          AND time >  (:as_of)::timestamptz - INTERVAL '7 days'
          AND time <= (:as_of)::timestamptz
          AND cote > 1.0
        ORDER BY participation_id, time ASC
    """), {"pids": pid_list, "as_of": date_heure})
    cotes_7j_by_pid: dict = {}
    for row in cotes_7j_r.fetchall():
        if row[0] not in cotes_7j_by_pid:
            cotes_7j_by_pid[row[0]] = []
        cotes_7j_by_pid[row[0]].append(float(row[1]))

    # 6. Météo course
    meteo_r = await session.execute(text("""
        SELECT pluie_24h, humidite FROM meteo_courses WHERE course_id = :cid
    """), {"cid": course_id})
    meteo_row = meteo_r.fetchone()

    # 7. Pronostics presse — comptes ET rangs par numéro de partant.
    #    Le rang était jeté : chaque journaliste publie une sélection ORDONNÉE, et on
    #    n'en gardait que « combien de journalistes le citent ». Le rang moyen et le
    #    score de Borda sont ce qui distingue un cheval donné 1er par deux sources
    #    d'un cheval cité 6e par les deux.
    presse_r = await session.execute(text("""
        SELECT
            (sel->>'numero')::int AS numero,
            COUNT(*) AS nb_experts,
            SUM(CASE WHEN (sel->>'rang')::int = 1 THEN 1 ELSE 0 END) AS nb_premier,
            AVG((sel->>'rang')::float) AS rang_moyen,
            MIN((sel->>'rang')::int) AS rang_min
        FROM pronostics_presse pp,
             json_array_elements(pp.selection::json) sel
        WHERE pp.course_id = :cid
          AND (sel->>'numero') ~ '^[0-9]+$' AND (sel->>'rang') ~ '^[0-9]+$'
        GROUP BY (sel->>'numero')::int
    """), {"cid": course_id})
    presse_by_numero: dict = {
        r[0]: {"nb_experts": int(r[1]), "nb_premier": int(r[2]),
               "rang_moyen": float(r[3]) if r[3] is not None else None,
               "rang_min": int(r[4]) if r[4] is not None else None}
        for r in presse_r.fetchall()
    }

    # 8. ELO stats de la course (moyenne, max, min)
    elo_course_r = await session.execute(text("""
        SELECT AVG(ch.elo_score_global), MAX(ch.elo_score_global), MIN(ch.elo_score_global),
               AVG(ch.elo_score_plat), AVG(ch.elo_score_trot), AVG(ch.elo_score_obstacle)
        FROM participations p
        JOIN chevaux ch ON p.cheval_id = ch.cheval_id
        WHERE p.course_id = :cid AND p.non_partant = false
    """), {"cid": course_id})
    elo_avg_row = elo_course_r.fetchone()
    elo_avg = float(elo_avg_row[0] or ELO_INITIAL)
    elo_max = float(elo_avg_row[1] or ELO_INITIAL)
    # Moyennes du champ PAR DISCIPLINE — cf. "elo_vs_champ".
    elo_avg_disc_map = {
        cle: float(elo_avg_row[idx] or elo_avg) for cle, idx in _IDX_ELO_DISC.items()
    }

    # 9. Cotes de tous les partants pour HHI
    field_cotes_r = await session.execute(text("""
        SELECT cote_pmu FROM participations
        WHERE course_id = :cid AND non_partant = false AND cote_pmu > 1.0
    """), {"cid": course_id})
    field_cotes = [float(r[0]) for r in field_cotes_r.fetchall()]

    # 10. Pedigree affinity (batché) — top3-rate de la progéniture du PÈRE à la
    #     distance de la course (±300m). `chevaux.pere` rempli ~100% ; distance
    #     remplie. (terrain/corde non scrapés en historique → non exploitables.)
    #     Une seule requête pour tout le peloton ; min 10 courses de lignée sinon neutre.
    sire_dist_by_cheval: dict = {}
    try:
        sire_r = await session.execute(text("""
            WITH field AS (
                SELECT p.cheval_id, c.pere
                FROM participations p
                JOIN chevaux c ON c.cheval_id = p.cheval_id
                WHERE p.course_id = :cid AND c.pere IS NOT NULL AND c.pere <> ''
            ), d AS (SELECT distance FROM courses WHERE course_id = :cid)
            SELECT f.cheval_id,
                   COUNT(*) FILTER (WHERE h.position_arrivee <= 3)::float / NULLIF(COUNT(*), 0) AS rate,
                   COUNT(*) AS n
            FROM field f
            JOIN chevaux sib ON sib.pere = f.pere
            JOIN historique_courses h ON h.cheval_id = sib.cheval_id
            JOIN d ON ABS(h.distance - d.distance) <= 300
            WHERE h.position_arrivee IS NOT NULL
            GROUP BY f.cheval_id
        """), {"cid": course_id})
        for cid_, rate, n in sire_r.fetchall():
            if n and int(n) >= 10 and rate is not None:
                sire_dist_by_cheval[cid_] = float(max(0.0, min(1.0, rate)))
    except Exception as e:  # noqa: BLE001
        log.warning("features.sire_dist_failed", err=str(e)[:120])


    # 11. Référence de vitesse (médiane indice_vitesse à même discipline + distance
    #     ±200m sur tout l'historique) — pour situer le NIVEAU des courses récentes
    #     du cheval. indice_vitesse = vitesse du vainqueur (proxy qualité d'opposition).
    course_disc = partants_raw[0][24]
    course_dist = partants_raw[0][25]
    course_terrain = partants_raw[0][26]
    vitesse_ref_median = None
    try:
        vref_r = await session.execute(text("""
            SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY h.indice_vitesse)
            FROM historique_courses h
            WHERE h.indice_vitesse IS NOT NULL AND h.indice_vitesse > 0
              AND lower(h.discipline) = lower(:disc)
              AND h.distance IS NOT NULL AND ABS(h.distance - :dist) <= 200
        """), {"disc": course_disc or "plat", "dist": int(course_dist or 2000)})
        v = vref_r.scalar()
        vitesse_ref_median = float(v) if v else None
    except Exception as e:  # noqa: BLE001
        log.warning("features.vitesse_ref_failed", err=str(e)[:120])

    # 12. Pedigree × TERRAIN (réveillé : terrain historique backfillé) — top3-rate de
    #     la progéniture du père par libellé terrain, agrégé en familles côté Python.
    sire_terrain_by_cheval: dict = {}
    try:
        famille_jour = get_terrain_famille(course_terrain)
        if famille_jour != "inconnu":
            sire_t_r = await session.execute(text("""
                WITH field AS (
                    SELECT p.cheval_id, c.pere
                    FROM participations p
                    JOIN chevaux c ON c.cheval_id = p.cheval_id
                    WHERE p.course_id = :cid AND c.pere IS NOT NULL AND c.pere <> ''
                )
                SELECT f.cheval_id, lower(h.terrain) AS t,
                       COUNT(*) FILTER (WHERE h.position_arrivee <= 3) AS top3,
                       COUNT(*) AS n
                FROM field f
                JOIN chevaux sib ON sib.pere = f.pere
                JOIN historique_courses h ON h.cheval_id = sib.cheval_id
                WHERE h.position_arrivee IS NOT NULL
                  AND h.terrain IS NOT NULL AND h.terrain <> ''
                GROUP BY f.cheval_id, lower(h.terrain)
            """), {"cid": course_id})
            acc: dict = {}
            for cid_, t_label, top3, n in sire_t_r.fetchall():
                if get_terrain_famille(t_label) != famille_jour:
                    continue
                a = acc.setdefault(cid_, [0, 0])
                a[0] += int(top3 or 0)
                a[1] += int(n or 0)
            for cid_, (top3, n) in acc.items():
                if n >= 10:
                    sire_terrain_by_cheval[cid_] = float(max(0.0, min(1.0, top3 / n)))
    except Exception as e:  # noqa: BLE001
        log.warning("features.sire_terrain_failed", err=str(e)[:120])

    # 13. FORME RÉCENTE jockey (7j) / entraîneur (14j) — fenêtre AVANT la course
    #     (point-in-time, pas de fuite même en recompute sur courses passées).
    #     Top-3 réel depuis resultats.classement. Min 5 montes sinon absent (fallback
    #     taux global dans le compute).
    jockey_forme_7j_map: dict = {}
    entr_forme_14j_map: dict = {}
    entraineur_ids = [r[4] for r in partants_raw if r[4]]
    try:
        from datetime import timedelta
        # Bornes calculées en Python (asyncpg exige des params datetime, pas str).
        dref = date_heure
        d7 = dref - timedelta(days=7)
        d14 = dref - timedelta(days=14)
        if jockey_ids:
            jf_r = await session.execute(text("""
                SELECT p2.jockey_id, COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM json_array_elements(r2.classement::json) e
                           WHERE (e->>'numero')::int = p2.numero
                             AND COALESCE((e->>'position')::int, 99) <= 3
                       )) AS top3
                FROM participations p2
                JOIN courses c2 ON c2.course_id = p2.course_id
                JOIN resultats r2 ON r2.course_id = c2.course_id
                WHERE p2.jockey_id = ANY(:jids)
                  AND c2.date_heure >= :d7
                  AND c2.date_heure < :dref
                GROUP BY p2.jockey_id
            """), {"jids": jockey_ids, "d7": d7, "dref": dref})
            for jid, n, top3 in jf_r.fetchall():
                if n and int(n) >= 5:
                    jockey_forme_7j_map[jid] = float(int(top3 or 0) / int(n))
        if entraineur_ids:
            ef_r = await session.execute(text("""
                SELECT p2.entraineur_id, COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM json_array_elements(r2.classement::json) e
                           WHERE (e->>'numero')::int = p2.numero
                             AND COALESCE((e->>'position')::int, 99) <= 3
                       )) AS top3
                FROM participations p2
                JOIN courses c2 ON c2.course_id = p2.course_id
                JOIN resultats r2 ON r2.course_id = c2.course_id
                WHERE p2.entraineur_id = ANY(:eids)
                  AND c2.date_heure >= :d14
                  AND c2.date_heure < :dref
                GROUP BY p2.entraineur_id
            """), {"eids": entraineur_ids, "d14": d14, "dref": dref})
            for eid, n, top3 in ef_r.fetchall():
                if n and int(n) >= 5:
                    entr_forme_14j_map[eid] = float(int(top3 or 0) / int(n))
    except Exception as e:  # noqa: BLE001
        log.warning("features.forme_recente_failed", err=str(e)[:120])

    # 16. STATS J / E / ASSO POINT-IN-TIME (trailing 365j, date < départ) — ANTI-FUITE.
    #     Les colonnes stats_jockeys/entraineurs/associations sont des agrégats SAISON
    #     (taux calculé sur la saison ENTIÈRE) : recomputer une course passée tire alors
    #     le FUTUR (reste de la saison) → fuite prouvée (audit 2026-06-17 : retirer ces
    #     features fait chuter win-AUC 0.863→0.811 + ROI +79→+29%). On recalcule donc
    #     les TAUX victoire/place du jockey, de l'entraîneur et du DUO sur participations
    #     ⋈ resultats.classement avec date_heure < départ. Min 20 partances sinon fallback
    #     (= valeur table, neutre). Point-in-time → honnête même en recompute historique.
    jockey_pit: dict = {}
    entr_pit: dict = {}
    asso_pit: dict = {}
    try:
        from datetime import timedelta
        dref2 = date_heure
        d365 = dref2 - timedelta(days=365)
        _pos1 = ("EXISTS (SELECT 1 FROM json_array_elements(r2.classement::json) e "
                 "WHERE (e->>'numero')::int = p2.numero AND COALESCE((e->>'position')::int,99) = 1)")
        _pos3 = ("EXISTS (SELECT 1 FROM json_array_elements(r2.classement::json) e "
                 "WHERE (e->>'numero')::int = p2.numero AND COALESCE((e->>'position')::int,99) <= 3)")
        if jockey_ids:
            jr = await session.execute(text(f"""
                SELECT p2.jockey_id, COUNT(*) n,
                       COUNT(*) FILTER (WHERE {_pos1}) w,
                       COUNT(*) FILTER (WHERE {_pos3}) pl
                FROM participations p2
                JOIN courses c2 ON c2.course_id = p2.course_id
                JOIN resultats r2 ON r2.course_id = c2.course_id
                WHERE p2.jockey_id = ANY(:jids) AND c2.date_heure >= :d365 AND c2.date_heure < :dref
                GROUP BY p2.jockey_id
            """), {"jids": jockey_ids, "d365": d365, "dref": dref2})
            for jid, n, w, pl in jr.fetchall():
                if n and int(n) >= 20:
                    jockey_pit[jid] = (float(int(w) / int(n)), float(int(pl) / int(n)))
        if entraineur_ids:
            er = await session.execute(text(f"""
                SELECT p2.entraineur_id, COUNT(*) n,
                       COUNT(*) FILTER (WHERE {_pos1}) w,
                       COUNT(*) FILTER (WHERE {_pos3}) pl
                FROM participations p2
                JOIN courses c2 ON c2.course_id = p2.course_id
                JOIN resultats r2 ON r2.course_id = c2.course_id
                WHERE p2.entraineur_id = ANY(:eids) AND c2.date_heure >= :d365 AND c2.date_heure < :dref
                GROUP BY p2.entraineur_id
            """), {"eids": entraineur_ids, "d365": d365, "dref": dref2})
            for eid, n, w, pl in er.fetchall():
                if n and int(n) >= 20:
                    entr_pit[eid] = (float(int(w) / int(n)), float(int(pl) / int(n)))
        # Duo jockey×entraîneur (trailing 24 mois, plus rare → fenêtre plus large)
        pairs2 = [(r[3], r[4]) for r in partants_raw if r[3] and r[4]]
        if pairs2:
            d730 = dref2 - timedelta(days=730)
            ar = await session.execute(text(f"""
                SELECT p2.jockey_id, p2.entraineur_id, COUNT(*) n,
                       COUNT(*) FILTER (WHERE {_pos1}) w
                FROM participations p2
                JOIN courses c2 ON c2.course_id = p2.course_id
                JOIN resultats r2 ON r2.course_id = c2.course_id
                WHERE p2.jockey_id = ANY(:jids) AND p2.entraineur_id = ANY(:eids)
                  AND c2.date_heure >= :d730 AND c2.date_heure < :dref
                GROUP BY p2.jockey_id, p2.entraineur_id
            """), {"jids": list({p[0] for p in pairs2}), "eids": list({p[1] for p in pairs2}),
                   "d730": d730, "dref": dref2})
            for jid, eid, n, w in ar.fetchall():
                n = int(n or 0)
                asso_pit[(jid, eid)] = (float(int(w) / n) if n else 0.0, n)
    except Exception as e:  # noqa: BLE001
        log.warning("features.pit_stats_failed", err=str(e)[:120])

    # 14. SYNERGIE jockey × cheval — top3-rate du DUO sur leurs courses communes
    #     ANTÉRIEURES (point-in-time, pas de fuite même en recompute). Réveille
    #     jockey_cheval_synergy_nb/score (était stub 0). Min 1 monte commune sinon absent.
    synergy_by_pair: dict = {}
    try:
        pairs = [(r[3], r[2]) for r in partants_raw if r[3] and r[2]]
        if pairs:
            jids_s = list({p[0] for p in pairs})
            cids_s = list({p[1] for p in pairs})
            syn_r = await session.execute(text("""
                SELECT p2.jockey_id, p2.cheval_id, COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE EXISTS (
                           SELECT 1 FROM json_array_elements(r2.classement::json) e
                           WHERE (e->>'numero')::int = p2.numero
                             AND COALESCE((e->>'position')::int, 99) <= 3
                       )) AS top3
                FROM participations p2
                JOIN courses c2 ON c2.course_id = p2.course_id
                JOIN resultats r2 ON r2.course_id = c2.course_id
                WHERE p2.jockey_id = ANY(:jids) AND p2.cheval_id = ANY(:cids)
                  AND c2.date_heure < :dref
                GROUP BY p2.jockey_id, p2.cheval_id
            """), {"jids": jids_s, "cids": cids_s, "dref": date_heure})
            for jid, cid_, n, top3 in syn_r.fetchall():
                n = int(n or 0)
                synergy_by_pair[(jid, cid_)] = (n, float(int(top3 or 0) / n) if n else 0.0)
    except Exception as e:  # noqa: BLE001
        log.warning("features.synergy_failed", err=str(e)[:120])

    # 15. NB COURSES DE LA RÉUNION (contexte début/fin de réunion). Réveille
    #     nb_courses_reunion (était stub 0). Préfixe course_id PMU = {ddmmyyyy}R{r}.
    nb_courses_reunion = 0
    try:
        if "C" in course_id:
            pfx = course_id.rsplit("C", 1)[0]  # "17062026R8C9" -> "17062026R8"
            nbr_r = await session.execute(
                text("SELECT COUNT(*) FROM courses WHERE course_id LIKE :p"),
                {"p": pfx + "C%"},
            )
            nb_courses_reunion = int(nbr_r.scalar() or 0)
    except Exception as e:  # noqa: BLE001
        log.warning("features.nb_courses_reunion_failed", err=str(e)[:120])

    # 17. DRAW BIAS data-driven — avantage réel d'une ZONE DE CORDE sur CET hippodrome
    #     à cette distance (±400m), mesuré sur tout l'historique. Remplace l'heuristique
    #     en dur (numero<=4 → +0.15…). On agrège le top3-rate par zone (int 1-4 /
    #     milieu 5-8 / ext 9+) et on le centre sur le top3-rate global de l'échantillon :
    #     biais = rate_zone − rate_global (positif = zone avantagée ici). Plat/obstacle
    #     seulement (le trot n'a pas de corde). Min 30 sorties/zone et 100 au total
    #     sinon zone absente → fallback 0.0 neutre (no-fake).
    draw_bias_by_zone: dict = {}
    try:
        _disc_l = (course_disc or "").lower()
        _is_trot = "trot" in _disc_l or "attelé" in _disc_l or "monté" in _disc_l
        course_hippo = partants_raw[0][27]
        if not _is_trot and course_hippo and course_dist:
            draw_r = await session.execute(text("""
                SELECT h.corde,
                       COUNT(*) AS n,
                       COUNT(*) FILTER (WHERE h.position_arrivee <= 3) AS top3
                FROM historique_courses h
                WHERE h.hippodrome ILIKE :hippo
                  AND h.corde IS NOT NULL
                  AND h.position_arrivee IS NOT NULL
                  AND h.distance IS NOT NULL AND ABS(h.distance - :dist) <= 400
                GROUP BY h.corde
            """), {"hippo": f"%{course_hippo}%", "dist": int(course_dist or 2000)})
            zone_acc: dict = {}  # zone -> [top3, n]
            tot_top3 = tot_n = 0
            for corde_val, n, top3 in draw_r.fetchall():
                try:
                    z = corde_zone(int(corde_val))
                except (TypeError, ValueError):
                    continue
                if z == "inconnu":
                    continue
                a = zone_acc.setdefault(z, [0, 0])
                a[0] += int(top3 or 0)
                a[1] += int(n or 0)
                tot_top3 += int(top3 or 0)
                tot_n += int(n or 0)
            if tot_n >= 100:
                base_rate = tot_top3 / tot_n
                for z, (t3, n) in zone_acc.items():
                    if n >= 30:
                        draw_bias_by_zone[z] = float(np.clip((t3 / n) - base_rate, -0.3, 0.3))
    except Exception as e:  # noqa: BLE001
        log.warning("features.draw_bias_failed", err=str(e)[:120])

    # 18. STATS DU CHAMP sur les colonnes ajoutées EN FIN du SELECT. Ordre final des
    #     dernières colonnes : …, handicap_distance (r[-3]), deferre_detail (r[-2]),
    #     valeur_handicap (r[-1]). (Référencées par index négatif → si on en rajoute,
    #     mettre à jour ces offsets.)
    field_recul = [int(r[-3]) for r in partants_raw if r[-3] is not None and int(r[-3]) > 0]
    recul_mean = float(np.mean(field_recul)) if field_recul else 0.0
    recul_max = float(max(field_recul)) if field_recul else 0.0
    field_valeur = [int(r[-1]) for r in partants_raw if r[-1] is not None and int(r[-1]) > 0]
    valeur_mean = float(np.mean(field_valeur)) if field_valeur else 0.0
    valeur_max = float(max(field_valeur)) if field_valeur else 0.0

    return {
        "partants": partants_raw,
        "draw_bias_by_zone": draw_bias_by_zone,
        "recul_mean": recul_mean,
        "recul_max": recul_max,
        "valeur_mean": valeur_mean,
        "valeur_max": valeur_max,
        "hist_by_cheval": hist_by_cheval,
        "confrontations": compute_confrontation_features(hist_by_cheval, cheval_ids),
        "elo_by_cheval": elo_by_cheval,
        "cotes_hist_by_pid": cotes_hist_by_pid,
        "cotes_7j_by_pid": cotes_7j_by_pid,
        "meteo_row": meteo_row,
        "presse_by_numero": presse_by_numero,
        "elo_avg": elo_avg,
        "elo_avg_disc_map": elo_avg_disc_map,
        "elo_max": elo_max,
        "field_cotes": field_cotes,
        "sire_dist_by_cheval": sire_dist_by_cheval,
        "sire_terrain_by_cheval": sire_terrain_by_cheval,
        "vitesse_ref_median": vitesse_ref_median,
        "jockey_forme_7j": jockey_forme_7j_map,
        "entraineur_forme_14j": entr_forme_14j_map,
        "synergy_by_pair": synergy_by_pair,
        "nb_courses_reunion": nb_courses_reunion,
        "jockey_pit": jockey_pit,
        "entr_pit": entr_pit,
        "asso_pit": asso_pit,
    }


async def compute_all_features_for_course(
    session: AsyncSession,
    course_id: str,
) -> list[dict]:
    """
    Calcule les features pour tous les partants d'une course.
    Version optimisée : 9 requêtes batch pour toute la course
    au lieu de ~20 requêtes individuelles par partant.
    """
    batch = await _load_course_batch_data(session, course_id)
    if not batch:
        return []

    features_list = []
    for row in batch["partants"]:
        feat = await _compute_features_from_batch(session, row, batch)
        if feat:
            features_list.append(feat)

    # ── FIX FEATURES MORTES : rang par COTE réelle (course-level) ──────────────
    # rang_cote/est_favori/rang_popularite étaient dérivés de rang_pronostic_pmu (NULL à
    # 100% → constants, variance nulle, inexploitables par le modèle). Ici on a TOUT le
    # peloton → on classe par cote_pmu croissante (favori = rang 1). Signal FORT (la
    # favori-itude prédit), enfin vivant. indice_valeur = proba implicite déviggée − uniforme.
    valides = [f for f in features_list if (f.get("cote_pmu") or 0) > 1]
    n_cl = len(valides)
    if n_cl >= 2:
        inv_sum = sum(1.0 / float(f["cote_pmu"]) for f in valides)
        for rang, f in enumerate(sorted(valides, key=lambda x: float(x["cote_pmu"])), 1):
            f["rang_cote"] = rang
            f["est_favori"] = 1 if rang == 1 else 0
            f["rang_popularite"] = rang
            f["rang_cote_relatif"] = round(rang / n_cl, 4)
            imp = (1.0 / float(f["cote_pmu"])) / inv_sum if inv_sum > 0 else 1.0 / n_cl
            f["indice_valeur"] = round(imp - 1.0 / n_cl, 4)

    _appliquer_consensus_presse(features_list, batch.get("presse_by_numero") or {})

    return features_list


# Rang attribué à un cheval qu'AUCUN journaliste ne cite. La sélection de presse
# porte sur ~8 chevaux : au-delà, on ne sait pas si le cheval est mauvais ou juste
# hors sélection. On le place derrière tous les cités, sans exagérer l'écart.
PRESSE_RANG_NON_CITE = 12


def _appliquer_consensus_presse(features_list: list[dict], presse_by_numero: dict) -> None:
    """Rend leur sens aux features presse, mortes depuis un an.

    `participations.rang_pronostic_pmu` / `rang_pronostic_geny` sont NULL à 100 %
    (mesuré le 2026-09-01 sur 24 988 participations de 45 jours), donc
    `pronostic_expert_rang`, `consensus_sources` et `sagesse_foules_score`
    tombaient sur leur défaut et n'avaient qu'UNE valeur distincte sur 218 640
    lignes de features. On les recalcule ici, où tout le peloton est connu :

    - `pronostic_expert_rang` : rang du cheval dans le consensus de presse
      (score de Borda décroissant). Non cité → PRESSE_RANG_NON_CITE.
    - `presse_score_borda`    : score normalisé 0-1 du même consensus.
    - `presse_rang_moyen`     : rang moyen donné par les journalistes qui le citent.
    - `consensus_sources`     : accord PRESSE ↔ MARCHÉ (1 = les deux le classent au
      même niveau, 0 = désaccord complet). C'est l'intention d'origine de la
      feature, qui comparait deux sources dont aucune n'était alimentée.
    - `sagesse_foules_score`  : 1/rang de popularité, en repartant du rang par COTE
      (vivant) au lieu du rang de pronostic PMU (NULL).

    Ne lève jamais : sans presse, les features gardent des valeurs neutres et
    `presse_nb_sources` vaut 0 — le modèle sait que le signal est absent.
    """
    if not features_list:
        return
    n = len(features_list)
    # Borda : un cheval cité 1er par 2 journalistes marque plus qu'un cheval cité 5e
    # par 3. On somme (rang_non_cité − rang) sur les journalistes qui le citent.
    borda: dict = {}
    for f in features_list:
        num = f.get("numero")
        p = presse_by_numero.get(num) or {}
        nb = int(p.get("nb_experts") or 0)
        rmoy = p.get("rang_moyen")
        if nb > 0 and rmoy is not None:
            borda[num] = nb * max(PRESSE_RANG_NON_CITE - float(rmoy), 0.0)
        else:
            borda[num] = 0.0
    max_borda = max(borda.values()) if borda else 0.0
    cites = [num for num, b in borda.items() if b > 0]
    # Rang de consensus : 1 = le mieux noté par la presse. Les non cités partagent
    # PRESSE_RANG_NON_CITE plutôt qu'un rang inventé.
    rang_presse: dict = {}
    for i, num in enumerate(sorted(cites, key=lambda x: -borda[x]), start=1):
        rang_presse[num] = i

    for f in features_list:
        num = f.get("numero")
        p = presse_by_numero.get(num) or {}
        nb = int(p.get("nb_experts") or 0)
        rp = rang_presse.get(num, PRESSE_RANG_NON_CITE)
        f["pronostic_expert_rang"] = int(rp)
        f["presse_rang_moyen"] = round(float(p["rang_moyen"]), 2) if p.get("rang_moyen") is not None else 0.0
        f["presse_score_borda"] = round(borda.get(num, 0.0) / max_borda, 4) if max_borda > 0 else 0.0
        f["presse_nb_sources"] = nb
        # Accord presse ↔ marché : 1 quand les deux placent le cheval au même rang,
        # décroît avec l'écart, rapporté à la taille du peloton. Neutre (0.5) quand
        # la presse ne couvre pas la course : ni accord ni désaccord constatable.
        rc = f.get("rang_cote")
        if not cites or not rc:
            f["consensus_sources"] = 0.5
        else:
            f["consensus_sources"] = round(1.0 - min(abs(int(rc) - rp), n) / max(n, 1), 4)
        # Sagesse des foules : repart du rang par COTE, vivant, au lieu du rang de
        # pronostic PMU qui est NULL partout.
        if rc:
            f["sagesse_foules_score"] = round(1.0 / max(int(rc), 1), 4)


async def _compute_features_from_batch(session: AsyncSession, row, batch: dict) -> Optional[dict]:
    """
    Calcule les features d'un partant depuis les données pré-chargées.
    Minimise les requêtes supplémentaires (seulement pour les données contextualles rares).
    """
    (
        participation_id, course_id, cheval_id, jockey_id, entraineur_id,
        numero, cote_pmu, cote_geny, cote_bzh,
        cote_winamax, cote_betclic, cote_betclic_ouv, cote_unibet, cote_betfair, mouvement_bm_raw,
        rang_prono_pmu, rang_prono_geny,
        poids, decharge, retard_gains, musique,
        non_partant, changement_jockey_flag, jours_depuis,
        discipline, distance, terrain, hippodrome,
        nb_partants, allocation, niveau_course, est_quinte, date_heure,
        categorie_particularite,
        corde, penetrometre_coef, pool_total_c, pool_gagnant_c,
        age, sexe, running_style_raw, taux_en_tete_raw, prix_vente_yl,
        elo_global, elo_plat, elo_trot, elo_obstacle,
        pere, mere, pere_de_mere,
        gains_carriere, nb_courses_total, nb_victoires_total,
        j_win, j_place, j_roi, j_30j, j_vic_s,
        e_win, e_place, e_roi, e_vic_s,
        deferre_change, premier_deferre, oeilleres_change, equipement_nouveau,
        asso_win, asso_nb,
        avis_entraineur_raw, tendance_force_raw, pool_gagnant_evol_raw,
        indicateur_inedit_raw, nb_places_2_raw, nb_places_3_raw,
        cheval_nom, jockey_nom, entraineur_nom,
        handicap_distance_raw, deferre_detail_raw, valeur_handicap_raw,
    ) = row

    # ── ANTI-FUITE : taux J/E/asso POINT-IN-TIME (trailing, date<départ) ──────
    # Remplacent les agrégats saison-complète (stats_jockeys/entraineurs/associations)
    # qui fuitent le futur au recompute d'une course passée. Fallback = valeur table
    # (variables j_win/e_win/asso_win issues du SELECT) si <20 (jockey/entr) partances.
    _jp = batch.get("jockey_pit", {}).get(jockey_id)
    if _jp is not None:
        j_win, j_place = _jp
    _ep = batch.get("entr_pit", {}).get(entraineur_id)
    if _ep is not None:
        e_win, e_place = _ep
    _ap = batch.get("asso_pit", {}).get((jockey_id, entraineur_id))
    if _ap is not None:
        asso_win, asso_nb = _ap

    # ── Données PMU nouvellement exploitées ──────────────────────────────────
    # Débutant (n'a jamais couru) : pas d'historique → le modèle doit le savoir.
    est_inedit = 1.0 if indicateur_inedit_raw else 0.0
    _nbc = float(nb_courses_total or 0)
    _v = float(nb_victoires_total or 0)
    _p2 = float(nb_places_2_raw or 0)
    _p3 = float(nb_places_3_raw or 0)
    # Profil de places carrière (régularité podium) : taux de 2e/3e + taux podium global.
    taux_place_2 = float(_p2 / _nbc) if _nbc > 0 else 0.0
    taux_place_3 = float(_p3 / _nbc) if _nbc > 0 else 0.0
    taux_podium_carriere = float((_v + _p2 + _p3) / _nbc) if _nbc > 0 else 0.0

    # Avis entraîneur PMU → score numérique (POSITIF=1, NEUTRE=0.5, NEGATIF=0)
    _avis_map = {"POSITIF": 1.0, "TRES_POSITIF": 1.0, "NEUTRE": 0.5, "NEGATIF": 0.0, "TRES_NEGATIF": 0.0}
    avis_entraineur_score = _avis_map.get((avis_entraineur_raw or "").upper(), 0.5)
    tendance_force_val = float(tendance_force_raw) if isinstance(tendance_force_raw, (int, float)) else 0.0
    # Smart money : croissance du pool gagnant (afflux de mises)
    pool_evol_val = float(pool_gagnant_evol_raw) if isinstance(pool_gagnant_evol_raw, (int, float)) else 0.0

    nb_partants_int = int(nb_partants or 10)
    disc_lower = (discipline or "plat").lower()
    age_int = int(age or 4)

    # ── A. ELO ───────────────────────────────────────────────────────────────
    elo_avg = batch["elo_avg"]
    elo_max = batch["elo_max"]
    if "trot" in disc_lower or "attelé" in disc_lower or "monté" in disc_lower:
        elo_score = float(elo_trot or ELO_INITIAL)
    elif "haies" in disc_lower or "steeple" in disc_lower:
        elo_score = float(elo_obstacle or ELO_INITIAL)
    else:
        elo_score = float(elo_plat or ELO_INITIAL)

    delta_elos = batch["elo_by_cheval"].get(cheval_id, [])
    delta_elo_5 = float(np.mean(delta_elos[:5])) if delta_elos else 0.0
    velocity_elo = float(np.mean(delta_elos[:5])) if delta_elos else 0.0
    elo_trend_30j = float(np.polyfit(np.arange(len(delta_elos)), delta_elos, 1)[0] * 5) if len(delta_elos) >= 3 else 0.0

    elo_avg_disc = (batch.get("elo_avg_disc_map") or {}).get(
        _cle_discipline(discipline), elo_avg)

    feat_elo = {
        "elo_global": float(elo_global or ELO_INITIAL),
        "elo_discipline": elo_score,
        "elo_vs_moyenne": elo_score - elo_avg,
        # Affichage seul (hors modèle) — écart au champ à échelle homogène.
        "elo_vs_champ": elo_score - elo_avg_disc,
        "elo_vs_max": elo_score - elo_max,
        "elo_pct_rank": elo_score / max(elo_max, 1),
        "delta_elo_5courses": delta_elo_5,
        "velocity_elo": velocity_elo,
        "elo_trend_30j": elo_trend_30j,
    }

    # ── B. Forme + repos + distance + terrain + hippodrome (depuis historique pré-chargé) ──
    historique = batch["hist_by_cheval"].get(cheval_id, [])
    musique_positions = parse_musique(musique)

    # Confrontations directes vs les autres partants (pré-calculé pour le champ)
    feat_confrontation = batch.get("confrontations", {}).get(
        cheval_id, {k: 0.0 for k in CONFRONTATION_FEATURE_KEYS}
    )

    def get_scores(positions, n=None):
        return [score_position(p, nb_partants_int) for p in (positions[:n] if n else positions)]

    scores = get_scores(musique_positions)
    if scores:
        f1 = scores[0]
        f3 = float(np.mean(scores[:3])) if len(scores) >= 3 else f1
        f5 = float(np.mean(scores[:5])) if len(scores) >= 5 else f3
        f10 = float(np.mean(scores[:10])) if len(scores) >= 10 else f5
        tendance = float(np.clip(np.polyfit(np.arange(min(len(scores), 5)), scores[:5], 1)[0] * 5, -1, 1)) if len(scores) >= 3 else 0.0
        regularite = float(1.0 - min(np.std(scores[:5]), 1.0)) if len(scores) >= 3 else 0.5
        taux_top3 = sum(1 for p in musique_positions[:5] if 0 < p <= 3) / min(len(musique_positions), 5) if musique_positions else 0
        taux_vict = sum(1 for p in musique_positions[:5] if p == 1) / min(len(musique_positions), 5) if musique_positions else 0
    else:
        f1 = f3 = f5 = f10 = 0.5
        tendance = regularite = taux_top3 = taux_vict = 0.0

    feat_forme = {"forme_1_course": f1, "forme_3_courses": f3, "forme_5_courses": f5,
                  "forme_10_courses": f10, "forme_tendance": tendance, "regularite": regularite,
                  "taux_top3": taux_top3, "taux_victoire_5c": taux_vict}

    # ── FF. Régularité d'allure — taux de fautes/disqualifications (trot ++) ────
    # Trotteur qui se met au galop = disqualifié. Signal de risque que le modèle
    # ignorait totalement. Dérivé de la musique (zéro data nouvelle). Hors trot les
    # incidents (T/A/R/D) restent rares → taux ~0 = neutre, pas de bruit.
    _is_trot_allure = "trot" in disc_lower or "attelé" in disc_lower or "monté" in disc_lower
    taux_faute, faute_derniere, nb_musique_lues = compute_allure_regularite(musique)
    feat_allure = {
        "taux_disqualification": float(taux_faute),
        "faute_derniere_course": float(faute_derniere),
        # Régularité = complément du taux de faute, pondéré trot (en plat ~toujours 1).
        "regularite_allure": float(1.0 - taux_faute),
        # Interaction explicite trot × faute : faute en trot = bien plus pénalisante.
        "risque_galop_trot": float(taux_faute) if _is_trot_allure else 0.0,
        "nb_courses_lues_musique": int(nb_musique_lues),
    }

    # ── GG. Écart à l'arrivée (beaten lengths) — qualité réelle vs musique ──────
    # La musique donne la POSITION, pas la MARGE : battu d'une tête ≠ battu de 15
    # longueurs. Une défaite courte = cheval compétitif/malchanceux (souvent sous-coté).
    # h[14]=ecart_longueurs (0 = vainqueur). On lit les sorties TERMINÉES récentes
    # (position 1..19). Vide (résultats pas encore scrapés) → neutre, pas de bruit.
    ecarts_recents = [float(h[14]) for h in historique[:6]
                      if len(h) > 14 and h[14] is not None and h[0] and 0 < h[0] < 20]
    if ecarts_recents:
        ecart_moyen = float(np.mean(ecarts_recents))
        # Proximité moyenne : 1.0 = colle au vainqueur, →0 quand battu loin (échelle 8 long.)
        proximite_vainqueur = float(np.clip(1.0 - ecart_moyen / 8.0, 0.0, 1.0))
        # Combien de sorties récentes finies à ≤2 longueurs (compétitif).
        nb_defaites_courtes = sum(1 for e in ecarts_recents if e <= 2.0)
        # Dernière sortie perdue mais de peu (≤1.5 long.) = malchance/forme cachée.
        _last = next(((float(h[14]), h[0]) for h in historique
                      if len(h) > 14 and h[14] is not None and h[0] and 0 < h[0] < 20), None)
        defaite_courte_derniere = 1.0 if (_last and _last[1] > 1 and _last[0] <= 1.5) else 0.0
    else:
        ecart_moyen = 0.0
        proximite_vainqueur = 0.5  # neutre si pas de data marge
        nb_defaites_courtes = 0
        defaite_courte_derniere = 0.0
    feat_ecart = {
        "ecart_moyen_recent": float(np.clip(ecart_moyen, 0.0, 30.0)),
        "proximite_vainqueur": float(proximite_vainqueur),
        "nb_defaites_courtes": int(nb_defaites_courtes),
        "defaite_courte_derniere": float(defaite_courte_derniere),
    }

    # ── GG-bis. Commentaires / trip notes (#9) — déroulé des courses passées ────
    # Lexique hippique FR : "facilement/souqué" = marge cachée (valeur ≥ résultat),
    # "gêné/enfermé/malchance" = forme cachée (souvent sous-coté ensuite), "fatigue/
    # distancé" = faiblesse réelle. h[15]=commentaire_course (rempli au fil du scrape
    # PMU ; vide au début → neutre, zéro bruit).
    _comments = [h[15] for h in historique[:6] if len(h) > 15 and h[15]]
    comm_signal, comm_malchance, comm_facile, nb_comments = compute_commentaire_signal(_comments)
    feat_commentaire = {
        "commentaire_signal": float(comm_signal),
        "commentaire_malchance_recente": float(comm_malchance),
        "commentaire_gagne_facile": float(comm_facile),
        "nb_commentaires_lus": int(nb_comments),
    }

    # Dynamique de course — h[9]=acceleration_label, h[10]=reduction_km
    feat_dynamics = aggregate_dynamics([
        (h[9] if len(h) > 9 else None, h[10] if len(h) > 10 else None)
        for h in historique
    ])

    # Repos/fraîcheur
    jours_repos = jours_depuis if jours_depuis is not None else (
        _jours_depuis_hist(historique, date_heure)
    )
    if 14 <= jours_repos <= 35: fraicheur = 1.0
    elif jours_repos < 14: fraicheur = jours_repos / 14.0
    elif jours_repos <= 60: fraicheur = max(0.1, 1.0 - (jours_repos - 35) / 50.0)
    else: fraicheur = max(0.05, 1.0 - (jours_repos - 35) / 120.0)
    nb_courses_90j = sum(1 for h in historique if h[4] and _days_diff(h[4], date_heure) <= 90)
    surmenage = min(1.0, nb_courses_90j / 15.0) if nb_courses_90j > 8 else 0.0

    feat_repos = {"jours_repos": int(jours_repos), "fraicheur_score": float(fraicheur),
                  "nb_courses_90j": int(nb_courses_90j), "surmenage_score": float(surmenage),
                  "jours_depuis_derniere_db": int(jours_repos)}

    # Distance
    dist_int = int(distance or 2000)
    dist_cat = get_dist_cat(dist_int)
    dist_hist = [h for h in historique if h[1] and abs(int(h[1]) - dist_int) <= 200]
    dist_scores = [score_position(h[0], nb_partants_int) for h in dist_hist if h[0] and h[0] < 20]
    pref_dist = float(np.mean(dist_scores)) if dist_scores else 0.5
    dist_moyennes = [h[1] for h in historique if h[1]]
    delta_dist = abs(dist_int - float(np.mean(dist_moyennes))) if dist_moyennes else 0.0
    feat_distance = {f"pref_dist_{dist_cat}": pref_dist, "nb_courses_distance": len(dist_hist),
                     "delta_dist_prefere": float(delta_dist), "pref_distance_actuelle": pref_dist,
                     "dist_code": list(DISTANCE_BUCKET.keys()).index(dist_cat)}

    # Terrain
    terrain_cat = get_terrain_cat(terrain)
    terrain_hist = [h for h in historique if get_terrain_cat(h[2]) == terrain_cat and h[0]]
    terrain_scores = [score_position(h[0], nb_partants_int) for h in terrain_hist if h[0] < 20]
    pref_terrain = float(np.mean(terrain_scores)) if terrain_scores else 0.5
    meteo_row = batch["meteo_row"]
    humidite_piste = 0.0
    if meteo_row:
        humidite_piste = float(np.clip((float(meteo_row[0] or 0) * 0.3 + (float(meteo_row[1] or 50) - 50) * 0.01), 0.0, 1.0))
    pen_coef = float(penetrometre_coef) if penetrometre_coef else {"bon": 3.0, "souple": 5.0, "lourd": 7.5}.get(terrain_cat, 4.0)
    feat_terrain = {f"pref_terrain_{terrain_cat}": pref_terrain, "nb_courses_terrain": len(terrain_hist),
                    "pref_terrain_actuel": pref_terrain, "terrain_code": {"bon": 0, "souple": 1, "lourd": 2}.get(terrain_cat, 0),
                    "humidite_piste": humidite_piste, "penetrometre_coef": pen_coef}

    # Hippodrome
    hippo_hist = [h for h in historique if h[3] and hippodrome and h[3].upper() == hippodrome.upper() and h[0]]
    hippo_scores = [score_position(h[0], nb_partants_int) for h in hippo_hist if h[0] < 20]
    pref_hippo = float(np.mean(hippo_scores)) if hippo_scores else 0.5
    hippo_wins = sum(1 for h in hippo_hist if h[0] == 1)
    record_hippodrome = hippo_wins / len(hippo_hist) if hippo_hist else 0.0

    # corde_preference RÉVEILLÉE : taux de top-3 du cheval quand il partait dans la
    # MÊME zone de corde (int. 1-4 / milieu 5-8 / ext. 9+) que son numéro du jour.
    # Plat/obstacle uniquement (trot : pas de corde) ; min 3 obs sinon 0.5 neutre.
    corde_pref = 0.5
    if "trot" not in disc_lower and "attelé" not in disc_lower and "monté" not in disc_lower:
        zone_jour = corde_zone(int(numero) if numero else None)
        if zone_jour != "inconnu":
            same_zone = []
            for h in historique:
                c_h = h[11] if len(h) > 11 else None
                try:
                    z_h = corde_zone(int(str(c_h))) if c_h not in (None, "") else "inconnu"
                except (TypeError, ValueError):
                    z_h = "inconnu"
                if z_h == zone_jour and h[0] and h[0] < 20:
                    same_zone.append(1 if h[0] <= 3 else 0)
            if len(same_zone) >= 3:
                corde_pref = float(sum(same_zone) / len(same_zone))

    feat_hippodrome = {"pref_hippodrome": pref_hippo, "nb_courses_hippodrome": len(hippo_hist),
                       "record_hippodrome": float(record_hippodrome),
                       "corde_preference": float(np.clip(corde_pref, 0.0, 1.0))}

    # ── G. Cotes ─────────────────────────────────────────────────────────────
    cote = float(cote_pmu or 5.0)
    prob_implicite = 1.0 / max(cote, 1.01)
    rang_cote = int(rang_prono_pmu or 99)
    est_favori = int(rang_cote == 1)

    cotes_hist_pid = batch["cotes_hist_by_pid"].get(participation_id, [])
    mouvement_30min = 0.0
    if len(cotes_hist_pid) >= 2:
        debut, fin = cotes_hist_pid[0], cotes_hist_pid[-1]
        if debut > 0:
            mouvement_30min = float(np.clip((debut - fin) / debut, -1.0, 1.0))
    spi_score_val = compute_spi_from_cotes_history(cotes_hist_pid) if len(cotes_hist_pid) >= 2 else 0.0

    cotes_7j = batch["cotes_7j_by_pid"].get(participation_id, [])
    variance_cotes = float(np.var(cotes_7j)) if len(cotes_7j) >= 3 else 0.0
    momentum_3j = 0.0
    if len(cotes_7j) >= 4:
        mid = len(cotes_7j) // 2
        early, late = float(np.mean(cotes_7j[:mid])), float(np.mean(cotes_7j[mid:]))
        if early > 0: momentum_3j = float(np.clip((early - late) / early, -1.0, 1.0))

    all_cotes = [c for c in [cote_pmu, cote_geny, cote_bzh, cote_winamax, cote_betclic, cote_unibet, cote_betfair] if c and c > 1.0]
    cote_min = min(all_cotes) if all_cotes else cote
    spread_bm = (max(all_cotes) - min(all_cotes)) / max(cote_min, 0.01) if len(all_cotes) >= 2 else 0.0
    gap_pmu_bf = (cote - float(cote_betfair)) / float(cote_betfair) if cote_betfair and cote_betfair > 1.0 else 0.0
    steam_bm = float(np.clip(float(mouvement_bm_raw or 0), -1.0, 1.0))  # déjà ratio (direct-ref)/ref
    steam_betclic = 0.0
    if cote_betclic_ouv and cote_betclic and cote_betclic_ouv > 1.0:
        steam_betclic = float(np.clip((cote_betclic_ouv - float(cote_betclic)) / cote_betclic_ouv, -1.0, 1.0))

    # Pool smart money
    pool_ratio = float(pool_gagnant_c) / float(pool_total_c) if pool_total_c and pool_gagnant_c and pool_total_c > 0 else 0.0

    feat_cotes = {
        "cote_pmu": cote, "cote_geny": float(cote_geny or cote), "cote_bzh": float(cote_bzh or cote),
        "cote_winamax": float(cote_winamax or cote), "cote_betclic": float(cote_betclic or cote),
        "cote_unibet": float(cote_unibet or cote), "cote_betfair_exchange": float(cote_betfair or cote),
        "cote_marche_min": float(cote_min), "spread_bookmakers": float(spread_bm),
        "gap_pmu_betfair": float(np.clip(gap_pmu_bf, -2.0, 2.0)),
        "steam_move_betclic": steam_betclic, "ratio_pmu_geny": cote / max(float(cote_geny or cote), 0.01),
        "mouvement_30min": mouvement_30min, "mouvement_bm_pct": steam_bm,
        "rang_cote": rang_cote, "est_favori": est_favori, "prob_implicite": prob_implicite,
        "pool_gagnant_ratio": float(np.clip(pool_ratio, 0.0, 1.0)),
    }

    # ── H. Équipement ─────────────────────────────────────────────────────────
    feat_equip = {
        "changement_equipement": float(deferre_change or 0), "premier_deferre": float(premier_deferre or 0),
        "nouvelles_oeilleres": float(oeilleres_change or 0), "equipement_score": float(equipement_nouveau or 0),
    }

    # ── H-bis. Ferrure détaillée (déferrage) — signal de vitesse trot ──────────
    # Déferrer = pied nu = moins de poids = plus de vitesse. En trot, le « déferré
    # des 4 » (complet) est une intention forte de performance ; les antérieurs
    # comptent surtout pour l'action. Libellés PMU variés (DEFERRE_ANTERIEURS,
    # _POSTERIEURS, _ANTERIEURS_POSTERIEURS, REFERRE_*, PROTEGE_*, Aucun…) → on teste
    # par mots-clés ant/post. Vide/aucun → 0 neutre.
    _def = (deferre_detail_raw or "").lower()
    _has_ant = "anter" in _def or "avant" in _def
    _has_post = "poster" in _def or "arrier" in _def or "arrière" in _def
    # On ignore les états « protégé / referré » (pas un déferrage) pour le code de niveau.
    _is_deferre = "deferr" in _def or "déferr" in _def or _def in ("avant", "arriere", "arrière", "complet")
    if _is_deferre and _has_ant and _has_post:
        deferre_code = 2
    elif _is_deferre and (_has_ant or _has_post) or _def == "complet":
        deferre_code = 2 if _def == "complet" else 1
    else:
        deferre_code = 0
    feat_ferrure = {
        "deferre_code": int(deferre_code),
        "deferre_complet": 1.0 if deferre_code >= 2 else 0.0,
        "deferre_anterieurs": 1.0 if (_is_deferre and _has_ant) else 0.0,
        # Premier déferrage complet en trot = signal d'intention maximal.
        "premier_deferre_trot": 1.0 if (premier_deferre and deferre_code >= 1 and _is_trot_allure) else 0.0,
    }

    # ── I. Jockey ─────────────────────────────────────────────────────────────
    jockey_forme_30j = float(j_win or 0.12)
    feat_jockey = {
        "jockey_taux_victoire_global": float(j_win or 0.12), "jockey_taux_place_global": float(j_place or 0.30),
        "jockey_roi": float(j_roi or 0.0), "jockey_montes_30j": int(j_30j or 0),
        "jockey_victoires_saison": int(j_vic_s or 0), "jockey_forme_30j": jockey_forme_30j,
        "changement_jockey": int(changement_jockey_flag or 0),
        "asso_jockey_entraineur_taux": float(asso_win or 0.0),
        "asso_jockey_entraineur_nb": int(asso_nb or 0),
        "asso_jockey_entraineur_fiable": int((asso_nb or 0) >= 5),
    }

    # ── J. Entraîneur ─────────────────────────────────────────────────────────
    combo_rate = float(asso_win or 0.0)   # déjà dans asso_jockey_entraineur
    feat_entraineur = {
        "entraineur_taux_global": float(e_win or 0.12), "entraineur_taux_place": float(e_place or 0.30),
        "entraineur_roi": float(e_roi or 0.0), "entraineur_victoires_saison": int(e_vic_s or 0),
        "combo_jockey_entraineur": combo_rate, "entraineur_forme_30j": float(e_win or 0.12),
    }

    # ── K. Cheval ─────────────────────────────────────────────────────────────
    RUNNING_STYLE_CODE = {"mene": 0, "suit_tete": 1, "placier": 2, "ferme": 3, "irregulier": 4}
    rs_code = RUNNING_STYLE_CODE.get(running_style_raw or "", 4)
    # Poids porté RELATIF au champ du jour (toutes disciplines) : porter plus que la
    # moyenne = handicap, moins = avantage. delta_poids (plat) compare à SA propre
    # histoire ; ici on compare aux ADVERSAIRES d'aujourd'hui. col 17 = poids_porte.
    weight_relative_field = 0.0
    try:
        _fpoids = [float(r[17]) for r in batch["partants"] if r[17] and float(r[17]) > 0]
        if _fpoids and poids and float(poids) > 0:
            _mp = float(np.mean(_fpoids))
            if _mp > 0:
                weight_relative_field = float(np.clip((float(poids) - _mp) / _mp, -0.5, 0.5))
    except Exception:
        weight_relative_field = 0.0
    feat_cheval = {
        "age": age_int, "age_squared": age_int ** 2,
        "sexe_code": SEXE_CODE.get(str(sexe or "H"), 0),
        "gains_log": float(math.log1p(int(gains_carriere or 0))),
        # Gains rapportés à la carrière (qualité par sortie) + nouveaux signaux PMU
        "gains_par_course_log": float(math.log1p((int(gains_carriere or 0)) / max(_nbc, 1.0))),
        "est_inedit": est_inedit,
        "taux_place_2": float(np.clip(taux_place_2, 0.0, 1.0)),
        "taux_place_3": float(np.clip(taux_place_3, 0.0, 1.0)),
        "taux_podium_carriere": float(np.clip(taux_podium_carriere, 0.0, 1.0)),
        "retard_gains": float(retard_gains or 0), "indice_valeur": 0.0,
        "running_style_code": rs_code, "taux_en_tete": float(taux_en_tete_raw or 0.0),
        "prix_vente_log": float(math.log1p(prix_vente_yl or 0)),
        "jours_depuis_derniere_db": int(jours_repos),
        "weight_relative_field": weight_relative_field,
    }

    # ── L. Contexte course ────────────────────────────────────────────────────
    heure_course = date_heure.hour if hasattr(date_heure, "hour") else 14
    feat_course = {
        "nb_partants": nb_partants_int, "log_nb_partants": float(math.log(max(nb_partants_int, 2))),
        "discipline_code": DISCIPLINE_CODE.get(disc_lower.split()[0], 0),
        "niveau_course_code": _encode_niveau(niveau_course, categorie_particularite),
        "dotation_log": float(math.log1p(allocation or 0)),
        "course_designee": int(est_quinte or False), "heure_course": int(heure_course),
        "nb_courses_reunion": int(batch.get("nb_courses_reunion", 0)),
    }

    # ── M. Popularité + presse ────────────────────────────────────────────────
    presse = batch["presse_by_numero"].get(numero, {})
    nb_experts = presse.get("nb_experts", 0)
    nb_premier = presse.get("nb_premier", 0)
    feat_populaire = {
        "rang_popularite": int(rang_prono_pmu or 10), "rang_pronostic_geny": int(rang_prono_geny or 10),
        "pronostic_expert_rang": int(rang_prono_geny or 10),
        "sagesse_foules_score": 1.0 / max(int(rang_prono_pmu or 10), 1),
        "consensus_sources": _consensus_score(rang_prono_pmu, rang_prono_geny),
        "nb_experts_presse": nb_experts, "nb_premier_presse": nb_premier,
        "presse_consensus_score": float(min(nb_experts / 3.0, 1.0)),
        "pool_gagnant_ratio": float(np.clip(pool_ratio, 0.0, 1.0)),
    }

    # ── N. Signaux avancés ────────────────────────────────────────────────────
    feat_signal = {
        "momentum_3j": momentum_3j, "variance_cotes_7j": float(np.clip(variance_cotes, 0.0, 100.0)),
        "spi_score": spi_score_val,
        "decote_detectee": _decote_detectee(cote_pmu, cote_geny, cote_bzh),
        "valeur_latente": _valeur_latente(cote_pmu, cote_geny, cote_bzh, cote_betfair, cote_winamax, cote_betclic),
        "steam_move_betclic": steam_betclic,
        "gap_pmu_betfair": float(np.clip(gap_pmu_bf, -2.0, 2.0)),
        "spread_bookmakers": float(np.clip(spread_bm, 0.0, 2.0)),
        "mouvement_bm_pct": steam_bm,
    }

    # ── Field dynamics ────────────────────────────────────────────────────────
    field_cotes = batch["field_cotes"]
    hhi = ecart_top2 = 0.0
    nb_outsiders = 0
    rang_relatif = float(rang_cote) / max(nb_partants_int, 1)
    if field_cotes:
        probs = np.array([1.0 / c for c in field_cotes])
        probs = probs / probs.sum()
        hhi = float(np.sum(probs ** 2))
        nb_outsiders = sum(1 for c in field_cotes if c > 10.0)
        sorted_p = sorted(probs, reverse=True)
        if len(sorted_p) >= 2: ecart_top2 = float(sorted_p[0] - sorted_p[1])
    feat_field = {"field_hhi": hhi, "nb_outsiders": nb_outsiders,
                  "ecart_proba_top2": ecart_top2, "rang_cote_relatif": rang_relatif}

    # ── Temporal ──────────────────────────────────────────────────────────────
    mois_course = date_heure.month if hasattr(date_heure, "month") else 6
    saison_code_map = {12:0,1:0,2:0,3:1,4:1,5:1,6:2,7:2,8:2,9:3,10:3,11:3}
    saison = saison_code_map.get(mois_course, 2)
    # saison_form RECÂBLÉ 2026-06-17 : forme moyenne (score de position) sur les
    # courses de l'ANNÉE en cours. Avant = constante 0.5 (feature fantôme). Calculé
    # depuis l'historique déjà chargé en batch (idx 0=position, idx 4=date_course).
    # Gardé : tout aléa → fallback 0.5 (= comportement actuel, zéro régression).
    saison_form = 0.5
    try:
        annee = date_heure.year if hasattr(date_heure, "year") else None
        if annee and historique:
            sc_saison = [score_position(h[0], nb_partants_int) for h in historique
                         if h[0] is not None and getattr(h[4], "year", None) == annee]
            if sc_saison:
                saison_form = float(np.mean(sc_saison))
    except Exception:
        saison_form = 0.5
    feat_temporal = {"mois_course": mois_course, "saison_code": saison,
                     "saison_form": float(saison_form), "market_timing_score": mouvement_30min}

    # ── Pace conflict (running style × terrain × adversaires) ──────────────────
    nb_meneurs = sum(1 for r in batch["partants"] if r[39] == "mene")  # col 39 = running_style
    pace_conflict = 0.0
    rs_terrain_fit = 0.5
    if running_style_raw == "mene":
        if nb_meneurs >= 3: pace_conflict = 0.8   # 3+ meneurs = guerre de vitesse
        elif nb_meneurs == 2: pace_conflict = 0.4
        if terrain_cat == "lourd": rs_terrain_fit = 0.3  # mène sur lourd = mauvais
        elif terrain_cat == "bon": rs_terrain_fit = 0.8
    elif running_style_raw == "ferme":
        if dist_int >= 2400: rs_terrain_fit = 0.85  # ferme + longue = bon
        if terrain_cat == "lourd": rs_terrain_fit = min(rs_terrain_fit + 0.2, 1.0)  # sol lourd favorise ceux qui ferment
        if nb_meneurs >= 3: pace_conflict = 0.1   # guerre de vitesse = opportunité pour les fermeurs
    feat_pace_conflict = {"pace_conflict_score": float(pace_conflict), "running_style_terrain_fit": float(rs_terrain_fit),
                          "nb_meneurs_course": nb_meneurs}

    # ── Pedigree — affinité lignée du PÈRE à la distance + au TERRAIN (batch) ──
    # sire_dist_winrate = top3-rate réel de la progéniture du père à cette distance.
    # sire_terrain_winrate RÉVEILLÉ : idem sur la famille de terrain du jour
    # (terrain historique backfillé). 0.5 = neutre si lignée inconnue ou < 10 courses.
    feat_pedigree = {
        "sire_dist_winrate": float(batch.get("sire_dist_by_cheval", {}).get(cheval_id, 0.5)),
        "sire_terrain_winrate": float(batch.get("sire_terrain_by_cheval", {}).get(cheval_id, 0.5)),
    }

    # ── Synergy jockey × cheval ───────────────────────────────────────────────
    # RÉVEILLÉ : top3-rate du duo (j_id, ch_id) sur leurs courses communes passées,
    # batché dans _load_course_batch_data. Avant = stub 0. Neutre si jamais couru ensemble.
    _syn = batch.get("synergy_by_pair", {}).get((jockey_id, cheval_id))
    feat_synergy = {
        "jockey_cheval_synergy_nb": int(_syn[0]) if _syn else 0,
        "jockey_cheval_synergy_score": float(_syn[1]) if _syn else 0.0,
    }

    # ── Fingerprint ───────────────────────────────────────────────────────────
    fp_hist = [h for h in historique if h[7] and discipline and str(h[7]).lower() == discipline.lower()
               and h[1] and abs(int(h[1]) - dist_int) <= 200
               and hippodrome and h[3] and h[3].upper() == hippodrome.upper()]
    fp_top3 = sum(1 for h in fp_hist if h[0] and h[0] <= 3)
    feat_fingerprint = {"course_fingerprint_nb": len(fp_hist),
                        "course_fingerprint_score": fp_top3 / len(fp_hist) if fp_hist else 0.5}

    # ── Advanced ──────────────────────────────────────────────────────────────
    decay_score = 0.0
    if historique:
        weights = [0.95 ** i for i in range(len(historique))]
        positions = [h[0] for h in historique if h[0] is not None]
        if positions:
            w = weights[:len(positions)]
            sc = [score_position(p, nb_partants_int) for p in positions]
            decay_score = float(np.average(sc, weights=w[:len(sc)]))
    # opposition_quality RECÂBLÉ 2026-06-17 : force du champ affronté aujourd'hui =
    # ELO moyen des AUTRES partants (col 42=elo_g, col 2=cheval_id), normalisé comme
    # la version legacy (avg/1500 - 1, clip [-0.5, 1.0]). Avant = constante 0.5
    # (fantôme). N'impacte PAS le modèle v493 (entraîné constant → aucun split) ;
    # signal réel dès le prochain retrain. Gardé : tout aléa → fallback 0.5.
    opp_quality = 0.5
    try:
        opp_elos = [r[42] for r in batch["partants"]
                    if r[2] != cheval_id and r[42] is not None and r[42] > 0]
        if opp_elos:
            opp_quality = float(np.clip(float(np.mean(opp_elos)) / ELO_INITIAL - 1.0, -0.5, 1.0))
    except Exception:
        opp_quality = 0.5
    feat_advanced = {"time_decay_form": float(decay_score), "opposition_quality": float(opp_quality)}

    # ── Pace (vitesse théorique) ───────────────────────────────────────────────
    VITESSE_REF = {"plat": {1000:16.5,1400:15.8,1600:15.5,2000:15.0,2400:14.5,3000:14.0},
                   "trot": {1000:13.0,1700:12.5,2100:12.0,2700:11.5},
                   "haies": {2800:11.5,3200:11.2,4000:10.8}}
    def get_vitesse_ref(disc, dist_m):
        key = "plat"
        d = (disc or "").lower()
        if "trot" in d or "attelé" in d: key = "trot"
        elif "haies" in d or "steeple" in d: key = "haies"
        refs = VITESSE_REF.get(key, VITESSE_REF["plat"])
        dists = sorted(refs.keys())
        if dist_m <= dists[0]: return refs[dists[0]]
        if dist_m >= dists[-1]: return refs[dists[-1]]
        for i in range(len(dists)-1):
            if dists[i] <= dist_m <= dists[i+1]:
                t = (dist_m-dists[i])/(dists[i+1]-dists[i])
                return refs[dists[i]]*(1-t)+refs[dists[i+1]]*t
        return 14.0
    vitesse_theorique = get_vitesse_ref(discipline, dist_int)
    hist_long = [score_position(h[0],nb_partants_int) for h in historique if h[0] and h[0]<20 and h[1] and int(h[1])>dist_int+200]
    hist_court = [score_position(h[0],nb_partants_int) for h in historique if h[0] and h[0]<20 and h[1] and int(h[1])<dist_int-200]
    stamina_index = float(np.mean(hist_long)-np.mean(hist_court)) if hist_long and hist_court else 0.0
    hist_same_disc = [h for h in historique if h[7] and discipline and str(h[7]).lower()==discipline.lower()]
    disc_coherence = len(hist_same_disc)/max(len(historique),1) if historique else 0.5
    feat_pace = {"vitesse_theorique": vitesse_theorique, "stamina_index": float(np.clip(stamina_index,-1,1)),
                 "discipline_coherence": float(disc_coherence)}

    # ── HH. Speed figures — vitesse PROPRE du cheval (chrono réel) ─────────────
    # Avant : seul indice_vitesse (= vitesse du VAINQUEUR de ses courses passées =
    # proxy du NIVEAU d'opposition) était utilisé. Ici on calcule la vitesse PROPRE
    # du cheval dans chaque sortie :
    #   - Trot : reduction_km (sec/km) → m/s = 1000/rk  (chrono direct du cheval)
    #   - Plat/obstacle : vitesse_vainqueur × distance/(distance + écart_mètres),
    #     l'écart en longueurs (~2.5 m) reconstituant le temps perdu sur le 1er.
    # Puis normalisé par la vitesse de référence (get_vitesse_ref) → figure de vitesse
    # (>1 = plus rapide que la normale distance/discipline). Données absentes (résultats
    # pas scrapés, ni chrono ni écart) → 1.0 neutre, pas de bruit.
    # h: 0 pos, 1 dist, 7 disc, 10 reduction_km, 13 indice_vitesse(vainqueur), 14 ecart.
    LONGUEUR_M = 2.5
    speed_figs = []
    for h in historique[:6]:
        if not (h[0] and 0 < h[0] < 20 and h[1]):
            continue
        h_dist = int(h[1])
        h_disc = str(h[7] or discipline or "plat")
        h_disc_l = h_disc.lower()
        own_ms = None
        rk = h[10] if len(h) > 10 else None
        if rk and rk > 0 and ("trot" in h_disc_l or "attel" in h_disc_l or "mont" in h_disc_l):
            own_ms = 1000.0 / float(rk)            # reduction_km = sec/km → m/s
        else:
            winner_ms = h[13] if len(h) > 13 else None
            if winner_ms and winner_ms > 0 and h_dist > 0:
                ecart_m = (float(h[14]) * LONGUEUR_M) if (len(h) > 14 and h[14] is not None) else 0.0
                own_ms = float(winner_ms) * h_dist / (h_dist + ecart_m)
        if own_ms and h_dist > 0:
            ref = get_vitesse_ref(h_disc, h_dist)
            if ref and ref > 0:
                speed_figs.append(own_ms / ref)
    if speed_figs:
        sf_best = float(max(speed_figs))
        sf_recent = float(speed_figs[0])
        sf_mean = float(np.mean(speed_figs))
        sf_consistency = float(1.0 - min(float(np.std(speed_figs)), 0.2) / 0.2)  # 1=régulier
    else:
        sf_best = sf_recent = sf_mean = 1.0
        sf_consistency = 0.5
    feat_speed = {
        "speed_figure_best": float(np.clip(sf_best, 0.7, 1.3)),
        "speed_figure_recent": float(np.clip(sf_recent, 0.7, 1.3)),
        "speed_figure_mean": float(np.clip(sf_mean, 0.7, 1.3)),
        "speed_consistency": float(np.clip(sf_consistency, 0.0, 1.0)),
        "nb_speed_figures": int(len(speed_figs)),
    }

    # ── Y. Class drop / raise — descente ou montée en catégorie ──────────────
    # Dotation cette course vs moyenne des 5 dernières courses
    # class_drop_ratio < 1.0 = descend = AVANTAGE (cheval surclassé)
    # class_drop_ratio > 1.0 = monte = RISQUE (cheval dépassé)
    class_drop_ratio = 1.0
    class_jump_score = 0.0
    if historique and allocation:
        hist_allocations = [int(h[8]) for h in historique[:5] if h[8] and int(h[8]) > 0]
        if hist_allocations:
            mean_alloc = float(np.mean(hist_allocations))
            if mean_alloc > 0:
                class_drop_ratio = float(allocation) / mean_alloc
                # Descente = ratio < 0.7 = signal fort
                if class_drop_ratio < 0.7:
                    class_jump_score = float(np.clip(1.0 - class_drop_ratio, 0, 1)) * 1.0  # positif
                elif class_drop_ratio > 1.4:
                    class_jump_score = -float(np.clip(class_drop_ratio - 1.0, 0, 1)) * 0.8  # négatif

    # Version CORRIGÉE du ratio de classe — AFFICHAGE / narratif uniquement.
    # `class_drop_ratio` ci-dessus compare une allocation en CENTIMES
    # (courses.allocation) à une moyenne d'historique qui mélange centimes et euros :
    # le ratio en sort gonflé ~2x, et le badge « Montée de catégorie » se déclenchait
    # sur 71 % des partants — jusqu'à annoncer une montée là où le cheval DESCEND
    # réellement de catégorie. Ici les deux termes sont ramenés en euros.
    # La feature ML d'origine n'est pas touchée (parité train/serve) ; celle-ci est
    # exclue du modèle via META_COLS.
    class_drop_ratio_reel = None
    if historique and allocation:
        _alloc_eur = [float(h[-1]) for h in historique[:5] if h[-1] and float(h[-1]) > 0]
        if _alloc_eur:
            _moy_eur = float(np.mean(_alloc_eur))
            if _moy_eur > 0:
                class_drop_ratio_reel = float(
                    np.clip((float(allocation) / 100.0) / _moy_eur, 0.2, 5.0))

    feat_class = {
        "class_drop_ratio": float(np.clip(class_drop_ratio, 0.2, 5.0)),
        "class_jump_score": float(np.clip(class_jump_score, -1.0, 1.0)),
        "class_drop_flag": int(class_drop_ratio < 0.75),   # descente significative
        "class_rise_flag": int(class_drop_ratio > 1.40),   # montée significative
        # Affichage seul (hors modèle) — None si l'historique ne permet pas de conclure.
        "class_drop_ratio_reel": class_drop_ratio_reel,
    }

    # ── GG. Recul trot (distance de handicap) ─────────────────────────────────
    # En trot à handicap de DISTANCE, les meilleurs chevaux sont reculés (+25m/+50m…) :
    # ils couvrent plus de terrain (désavantage physique) MAIS le recul = label de
    # qualité (handicapé pour sa valeur). Signal à deux faces que le modèle apprendra.
    # handicap_distance scrapé (PMU) + stocké (migration 0015), jamais exploité jusqu'ici.
    # 0/None = ligne de base (autostart, non-reculé, ou plat/obstacle). Toujours fourni
    # mais ~0 hors trot → neutre, pas de bruit.
    recul_m = float(handicap_distance_raw) if handicap_distance_raw else 0.0
    _recul_mean = float(batch.get("recul_mean", 0.0))
    _recul_max = float(batch.get("recul_max", 0.0))
    # Recul relatif au champ : >0 = plus reculé que la moyenne (meilleur cheval mais
    # plus de terrain). Normalisé sur ±50m. Centré sur 0 si champ non reculé.
    recul_vs_champ = float(np.clip((recul_m - _recul_mean) / 50.0, -1.0, 2.0)) if _recul_mean > 0 else 0.0
    # Est-il sur la première ligne (0) alors que d'autres sont reculés ? = avantage tactique.
    en_premiere_ligne = 1.0 if (recul_m == 0.0 and _recul_max > 0.0) else 0.0
    # Ratio de terrain réel à couvrir vs la distance nominale de la course.
    distance_reelle_ratio = float((dist_int + recul_m) / dist_int) if dist_int > 0 else 1.0
    feat_recul = {
        "recul_metres": recul_m,
        "recul_vs_champ": recul_vs_champ,
        "est_recule": 1.0 if recul_m > 0.0 else 0.0,
        "recul_premiere_ligne": en_premiere_ligne,
        "distance_reelle_ratio": float(np.clip(distance_reelle_ratio, 1.0, 1.5)),
    }

    # ── GG-ter. Valeur de handicap (#10) — note officielle du handicapeur ──────
    # En course à handicap, le handicapeur attribue une « valeur » (note de qualité) ;
    # le poids porté en découle. C'est un classement d'expert directement comparable
    # entre partants. Champ PMU valeurHandicap (scrapé, migration 0025). Le SIGNAL clé
    # est RELATIF au champ (être mieux noté que les rivaux). Absent hors handicap / si
    # le PMU ne publie pas → 0 neutre (le poids relatif weight_relative_field couvre déjà
    # le handicap par le poids).
    valeur_h = float(valeur_handicap_raw) if valeur_handicap_raw else 0.0
    _val_mean = float(batch.get("valeur_mean", 0.0))
    _val_max = float(batch.get("valeur_max", 0.0))
    valeur_vs_champ = float(np.clip((valeur_h - _val_mean) / 15.0, -2.0, 2.0)) if (valeur_h > 0 and _val_mean > 0) else 0.0
    valeur_rang_relatif = float(valeur_h / _val_max) if (valeur_h > 0 and _val_max > 0) else 0.0
    feat_valeur = {
        "valeur_handicap": float(np.clip(valeur_h, 0.0, 120.0)),
        "valeur_vs_champ": valeur_vs_champ,
        "valeur_rang_relatif": valeur_rang_relatif,
        "est_mieux_note": 1.0 if (valeur_h > 0 and _val_max > 0 and valeur_h >= _val_max) else 0.0,
    }

    # ── Z. Bounce factor — rebond après course exceptionnelle ─────────────────
    # Un cheval qui vient de faire sa meilleure course peut "rebondir" (fatigue/pic)
    # Signal fort quand ELO a fait un grand bond la dernière course
    bounce_score = 0.0
    if delta_elos:
        last_delta = delta_elos[0]
        avg_delta = float(np.mean(delta_elos))
        if last_delta > avg_delta * 2.0 and last_delta > 20:  # Saut ELO exceptionnel
            bounce_score = float(np.clip((last_delta - avg_delta) / max(abs(avg_delta) + 10, 10), 0, 1)) * 0.5
        elif last_delta < avg_delta * 2.0 and last_delta < -15:  # Grosse chute → rebond possible
            bounce_score = -float(np.clip(abs(last_delta) / 50, 0, 0.5))

    # Best performance score — score de la meilleure course de carrière
    best_score = max(scores) if scores else 0.5
    current_form_vs_best = f1 / best_score if best_score > 0 else 0.5

    feat_bounce = {
        "bounce_score": float(bounce_score),
        "current_form_vs_best": float(np.clip(current_form_vs_best, 0, 2.0)),
        "career_trajectory": float(np.clip(tendance, -1, 1)),  # alias avec label plus clair
    }

    # ── AA. Draw bias DATA-DRIVEN — avantage réel de la zone de corde du jour ──
    # Remplace l'ancienne heuristique (numero<=4 → +0.15 + record perso, qui mêlait
    # biais de piste et forme du cheval). On lit le biais PRÉ-CALCULÉ par zone pour
    # cet hippodrome+distance (cf. _load_course_batch_data #17), indexé par la zone
    # de corde du numéro du jour. Plat/obstacle seulement ; trot/zone inconnue/échantillon
    # insuffisant → 0.0 neutre. Le sens du rail (courses.corde "int"/"ext") sert juste
    # de flag de cohérence, plus de barème en dur.
    draw_bias = 0.0
    if not _is_trot_allure and numero:
        _zone_jour = corde_zone(int(numero))
        draw_bias = float(batch.get("draw_bias_by_zone", {}).get(_zone_jour, 0.0))

    feat_draw = {"draw_bias_score": float(np.clip(draw_bias, -1, 1))}

    # ── BB. Trainer return specialist ─────────────────────────────────────────
    # Entraîneur avec fort taux de victoire quand retour de longue absence (60j+)
    trainer_return_rate = float(e_win or 0.12)  # default = taux global
    if jours_repos >= 60 and asso_nb and asso_nb >= 5:
        # Si l'association J×E a fonctionné = signal positif sur retour
        trainer_return_rate = float(asso_win or trainer_return_rate) * 1.15
    trainer_return_bonus = float(np.clip((trainer_return_rate - 0.12) * 3, -0.5, 0.5)) if jours_repos >= 60 else 0.0

    feat_trainer = {"trainer_return_bonus": float(trainer_return_bonus)}

    # ── CC. Career trajectory ─────────────────────────────────────────────────
    # Tendance long terme: ELO en progression sur 6 dernières courses vs 6 précédentes
    career_momentum = 0.0
    if len(delta_elos) >= 6:
        recent_6 = float(np.mean(delta_elos[:6]))
        older_6 = float(np.mean(delta_elos[6:12])) if len(delta_elos) >= 12 else recent_6
        career_momentum = float(np.clip((recent_6 - older_6) / 10, -1, 1))

    # Ratio victoires jeune vs carrière total — cheval en montée de forme?
    recent_wins = sum(1 for p in musique_positions[:5] if p == 1)
    all_wins = nb_victoires_total or 0
    all_races = nb_courses_total or 1
    recent_win_rate = recent_wins / 5 if len(musique_positions) >= 5 else 0
    career_win_rate = all_wins / max(all_races, 1)
    form_vs_career = recent_win_rate - career_win_rate  # positif = en forme

    feat_career = {
        "career_momentum": float(career_momentum),
        "form_vs_career_rate": float(np.clip(form_vs_career, -0.5, 0.5)),
        "career_win_rate": float(career_win_rate),
        "recent_win_rate": float(recent_win_rate),
    }

    # ── DD. Composite confidence score ───────────────────────────────────────
    # Score multi-facteur qui donne une mesure de fiabilité de la prédiction
    # Tient compte: qualité des données, cohérence des signaux, nb sources
    nb_sources = sum(
        1 for c in (cote_pmu, cote_geny, cote_bzh, cote_winamax, cote_betclic, cote_unibet, cote_betfair)
        if c
    )
    data_completeness = min(
        1.0,
        (1 if cote_pmu else 0) * 0.2 +
        (1 if nb_sources >= 3 else nb_sources / 3) * 0.2 +
        (min(len(historique), 10) / 10) * 0.3 +
        (1 if j_win else 0) * 0.15 +
        (1 if pere else 0) * 0.05 +
        (1 if asso_nb and asso_nb >= 3 else 0) * 0.1,
    )

    # Cohérence des signaux: ELO, forme, cotes tous dans le même sens?
    signal_agreement = 0.5
    signals = []
    if elo_score > elo_avg: signals.append(1)
    else: signals.append(0)
    if f5 > 0.5: signals.append(1)
    else: signals.append(0)
    if prob_implicite > 1 / max(nb_partants_int, 2): signals.append(1)
    else: signals.append(0)
    if gap_pmu_bf > 0.05: signals.append(1)
    elif gap_pmu_bf < -0.05: signals.append(0)
    else: signals.append(None)

    valid_signals = [s for s in signals if s is not None]
    if valid_signals:
        agreement = sum(valid_signals) / len(valid_signals)
        signal_agreement = float(abs(agreement - 0.5) * 2)  # 0 = 50/50, 1 = tous d'accord

    composite_confidence = float(np.clip(
        data_completeness * 0.4 + signal_agreement * 0.4 + (1 - float(np.clip(variance_cotes, 0, 10)) / 10) * 0.2,
        0.0, 1.0
    ))

    feat_confidence = {
        "data_completeness": float(data_completeness),
        "signal_agreement": float(signal_agreement),
        "composite_confidence": float(composite_confidence),
    }

    # ── Enrichissements PMU (avis entraîneur, ampleur tendance cote) ──────────
    feat_pmu = {
        "avis_entraineur_score": float(avis_entraineur_score),
        "tendance_cote_force": float(np.clip(tendance_force_val, 0.0, 50.0)),
        "pool_gagnant_evolution": float(np.clip(pool_evol_val, -1.0, 1.0)),
    }

    # ── EE. Données dormantes réveillées (vitesse, poids, forme J/E, dépaysement) ──
    # h[12]=poids_porte_course, h[13]=indice_vitesse (vitesse du vainqueur = proxy du
    # NIVEAU des courses fréquentées). Toutes neutres si données absentes (no-fake).
    vitesses_recentes = [h[13] for h in historique[:3] if len(h) > 13 and h[13]]
    poids_hist = [h[12] for h in historique[:3] if len(h) > 12 and h[12]]
    is_trot = "trot" in disc_lower or "attelé" in disc_lower or "monté" in disc_lower
    feat_dormant = {
        "vitesse_relative": compute_vitesse_relative(vitesses_recentes,
                                                     batch.get("vitesse_ref_median")),
        "delta_poids": compute_delta_poids(poids, poids_hist) if not is_trot else 0.0,
        "jockey_forme_7j": float(batch.get("jockey_forme_7j", {}).get(jockey_id, j_win or 0.12)),
        "entraineur_forme_14j": float(batch.get("entraineur_forme_14j", {}).get(entraineur_id, e_win or 0.12)),
        "distance_deplacement": compute_distance_deplacement(
            hippodrome, [h[3] for h in historique if h[3]]
        ),
    }

    # ── Assemblage final ──────────────────────────────────────────────────────
    return {
        "participation_id": participation_id, "course_id": course_id,
        # Identité réelle du partant (dossard + noms) — sert aux tickets de paris,
        # recommandations, narratif et vérif suspensions. NE PAS confondre numero
        # (dossard officiel) avec rang_cote (rang par cote).
        "numero": int(numero) if numero is not None else None,
        "nom": cheval_nom or "",
        "jockey_nom": jockey_nom or "",
        "entraineur_nom": entraineur_nom or "",
        **feat_elo, **feat_forme, **feat_allure, **feat_ecart, **feat_commentaire, **feat_dynamics, **feat_confrontation, **feat_repos, **feat_distance, **feat_terrain,
        **feat_hippodrome, **feat_cotes, **feat_equip, **feat_ferrure, **feat_jockey, **feat_entraineur,
        **feat_cheval, **feat_course, **feat_populaire, **feat_signal,
        **feat_field, **feat_temporal, **feat_pace_conflict, **feat_pedigree,
        **feat_synergy, **feat_fingerprint, **feat_advanced, **feat_pace, **feat_speed,
        **feat_class, **feat_recul, **feat_valeur, **feat_bounce, **feat_draw, **feat_trainer,
        **feat_career, **feat_confidence, **feat_pmu, **feat_dormant,
    }


def _jours_depuis_hist(historique, date_heure) -> int:
    """Calcule jours depuis dernière course depuis l'historique pré-chargé."""
    if not historique:
        return 90
    from datetime import date as dt
    try:
        last_date = historique[0][4]
        today_date = date_heure.date() if hasattr(date_heure, "date") else dt.fromisoformat(str(date_heure)[:10])
        if isinstance(last_date, str): last_date = dt.fromisoformat(last_date)
        return (today_date - last_date).days
    except Exception:
        return 30
