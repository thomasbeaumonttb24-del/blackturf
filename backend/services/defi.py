"""
Défi du mois — BlackTurf.

Concours en POINTS : chaque joueur reçoit un capital de points le 1er du mois,
engage des paris avant le départ (1 pari = 10 à 100 points), et chaque pari
gagnant rapporte ``points × rapport PMU officiel à l'arrivée``. Le meilleur
solde en fin de mois gagne.

Ce qui rend le classement non trichable :
  - le dépôt ferme avant le départ PRÉVU, à l'heure du serveur ;
  - un pari engagé ne se modifie ni ne se supprime ;
  - le rapport et le résultat viennent de l'arrivée officielle (settle_pari),
    jamais d'une saisie du joueur ;
  - l'origine « plan » / « perso » est déduite des plans réellement émis
    (bet_plan_snapshots), pas cochée par le joueur.
"""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError

from db.models import (
    BetPlanSnapshot, Course, DefiPari, DefiRecompense, Participation, Resultat, User,
)
from services.bet_catalog import derive_bet_flags
from services.bet_settlement import settle_pari

log = structlog.get_logger()

PARIS_TZ = ZoneInfo("Europe/Paris")

CAPITAL_MENSUEL = 1000
POINTS_MIN = 10
POINTS_MAX = 100
MIN_PARIS_CLASSEMENT = 10
# Au-delà, on n'est plus dans le pronostic mais dans l'arrosage de la course.
MAX_PARIS_PAR_COURSE = 3
VERROU_AVANT_DEPART = timedelta(minutes=2)
# Un pari gagnant dont le PMU n'a toujours pas publié le rapport 72 h après la
# course est remboursé : sans cela il resterait « en attente » à vie et bloquerait
# la remise des récompenses du mois (qui exige zéro pari en attente).
DELAI_RAPPORT_MAX = timedelta(hours=72)

# Rang → (plan offert, durée). Remis par l'admin après vérification du compte.
RECOMPENSES: dict[int, tuple[str, int]] = {
    1: ("expert", 30),
    2: ("standard", 30),
    3: ("standard", 30),
}
_NIVEAU_PLAN = {"free": 0, "decouverte": 0, "standard": 1, "starter": 1, "expert": 2, "pro": 2}

# Catalogue des paris du défi : TOUS les paris PMU que la course propose (d'après
# `courses.paris_disponibles`, cf. bet_catalog), chacun avec son nombre de chevaux
# et le rôle de l'ordre de sélection. Chaque ligne est réglable exactement par
# `settle_pari` sur les rapports officiels (base 1 € = base 1 point).
#
#   ordre=True  : l'ordre de sélection est l'ordre d'arrivée joué (Couplé Ordre,
#                 Trio Ordre, Super 4) ou l'ordre du ticket (Tiercé, Quarté+,
#                 Quinté+ : Ordre si exact, sinon Désordre, sinon Bonus — comme un
#                 ticket PMU unitaire).
#   min < max   : formule à plusieurs chevaux (2sur4 et Pick5 en champ réduit,
#                 Multi en 4 à 7) : la mise se répartit, le rapport suit la formule.
CATALOGUE_DEFI: tuple[dict, ...] = (
    {"type": "Simple Gagnant", "famille": "Simples", "min": 1, "max": 1, "ordre": False,
     "drapeau": "est_simple_gagnant", "aide": "Votre cheval termine 1er."},
    {"type": "Simple Placé", "famille": "Simples", "min": 1, "max": 1, "ordre": False,
     "drapeau": "est_simple_place",
     "aide": "Votre cheval finit dans les places payées (3 premiers, 2 sous 8 partants)."},
    {"type": "Couplé Gagnant", "famille": "Couplés", "min": 2, "max": 2, "ordre": False,
     "drapeau": "est_couple_gagnant", "aide": "Vos 2 chevaux font les 2 premiers, dans n'importe quel ordre."},
    {"type": "Couplé Placé", "famille": "Couplés", "min": 2, "max": 2, "ordre": False,
     "drapeau": "est_couple_place", "aide": "Vos 2 chevaux finissent tous deux dans les 3 premiers."},
    {"type": "Couplé Ordre", "famille": "Couplés", "min": 2, "max": 2, "ordre": True,
     "drapeau": "est_couple_ordre", "aide": "Vos 2 chevaux font 1er et 2e, dans l'ordre choisi."},
    {"type": "Trio", "famille": "Trios & Tiercé", "min": 3, "max": 3, "ordre": False,
     "drapeau": "est_trio", "aide": "Vos 3 chevaux font le podium, dans n'importe quel ordre."},
    {"type": "Trio Ordre", "famille": "Trios & Tiercé", "min": 3, "max": 3, "ordre": True,
     "drapeau": "est_trio_ordre", "aide": "Vos 3 chevaux font le podium, dans l'ordre choisi."},
    {"type": "Tiercé", "famille": "Trios & Tiercé", "min": 3, "max": 3, "ordre": True,
     "drapeau": "est_tierce",
     "aide": "Les 3 premiers : rapport Ordre si l'ordre choisi est exact, sinon Désordre."},
    {"type": "2sur4", "famille": "2sur4 & Multi", "min": 2, "max": 4, "ordre": False,
     "drapeau": "est_2sur4",
     "aide": "2 de vos chevaux dans les 4 premiers. Jusqu'à 4 chevaux : la mise se répartit sur les combinaisons."},
    {"type": "Multi", "famille": "2sur4 & Multi", "min": 4, "max": 7, "ordre": False,
     "drapeau": "est_multi",
     "aide": "Les 4 premiers parmi vos 4 à 7 chevaux, dans n'importe quel ordre. Moins de chevaux, plus gros rapport."},
    {"type": "Quarté+", "famille": "Quarté+, Quinté+ & plus", "min": 4, "max": 4, "ordre": True,
     "drapeau": "est_quarte",
     "aide": "Les 4 premiers : Ordre si exact, sinon Désordre ; Bonus si vos 3 premiers font le podium."},
    {"type": "Quinté+", "famille": "Quarté+, Quinté+ & plus", "min": 5, "max": 5, "ordre": True,
     "drapeau": "est_quinte",
     "aide": "Les 5 premiers : Ordre, Désordre, puis Bonus 4sur5 et Bonus 3."},
    {"type": "Super 4", "famille": "Quarté+, Quinté+ & plus", "min": 4, "max": 4, "ordre": True,
     "drapeau": "est_super4", "aide": "Les 4 premiers dans l'ordre exact choisi."},
    {"type": "Pick5", "famille": "Quarté+, Quinté+ & plus", "min": 5, "max": 7, "ordre": False,
     "drapeau": "est_pick5",
     "aide": "Les 5 premiers parmi vos chevaux, dans n'importe quel ordre. Au-delà de 5, la mise se répartit."},
)
TYPES_DEFI = {t["type"]: t for t in CATALOGUE_DEFI}


def _libelle_multi(course: Course) -> str:
    """« Mini Multi » sur les courses qui l'offrent à la place du Multi (champ
    moyen), « Multi » sinon : les deux ont leur propre pool et leur propre rapport."""
    codes = [str(c).upper() for c in (course.paris_disponibles or [])]
    if any("MINI_MULTI" in c for c in codes):
        return "Mini Multi"
    if any("MULTI" in c for c in codes):
        return "Multi"
    return "Mini Multi" if 10 <= int(course.nb_partants or 0) <= 13 else "Multi"


def types_disponibles(course: Course) -> list[dict]:
    """Les paris du défi réellement ouverts par le PMU sur cette course."""
    flags = derive_bet_flags(course.paris_disponibles, est_tierce=bool(course.est_tierce),
                             est_quarte=bool(course.est_quarte), est_quinte=bool(course.est_quinte),
                             est_2sur4=bool(course.est_2sur4), nb_partants=course.nb_partants)
    out = []
    for t in CATALOGUE_DEFI:
        if not flags.get(t["drapeau"]):
            continue
        ligne = {k: v for k, v in t.items() if k != "drapeau"}
        if t["type"] == "Multi":
            ligne["libelle"] = _libelle_multi(course)
        out.append(ligne)
    return out


def type_stocke(type_defi: str, nb_chevaux: int, course: Course) -> str:
    """Libellé enregistré et réglé : « Multi en 5 » / « Mini Multi en 5 » pour le Multi."""
    if type_defi == "Multi":
        return f"{_libelle_multi(course)} en {nb_chevaux}"
    return type_defi


def famille_type(type_pari: str) -> str:
    """Type du défi d'un libellé de pari (défi ou plan de mise)."""
    t = type_pari or ""
    if "Multi en" in t:
        return "Multi"
    for f in ("Tiercé", "Quarté+", "Quinté+"):
        if t.startswith(f):
            return f
    return t

STATUTS_COURSE_SANS_ARRIVEE = {"annule", "sans_resultat"}

# Le classement s'affiche sur l'accueil, le programme et chaque course : on le
# recalcule au plus toutes les CACHE_CLASSEMENT secondes par processus, et tout
# pari engagé ou réglé l'invalide aussitôt dans le processus qui l'a écrit.
CACHE_CLASSEMENT = 30.0
_cache_classement: dict[str, tuple[float, list[dict]]] = {}


def invalider_classement() -> None:
    _cache_classement.clear()


class DefiErreur(ValueError):
    """Pari refusé : le message est destiné au joueur."""


def _utc(dt: datetime) -> datetime:
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def mois_de(dt: datetime) -> str:
    """Mois du défi auquel appartient un instant (calendrier de Paris)."""
    return _utc(dt).astimezone(PARIS_TZ).strftime("%Y-%m")


def mois_courant(now: Optional[datetime] = None) -> str:
    return mois_de(now or datetime.now(timezone.utc))


def limite_depot(course: Course) -> datetime:
    return _utc(course.date_heure) - VERROU_AVANT_DEPART


def depot_ouvert(course: Course, now: Optional[datetime] = None) -> bool:
    now = now or datetime.now(timezone.utc)
    return course.statut == "a_venir" and now < limite_depot(course)


def hors_concours(user: User) -> bool:
    """Les comptes d'administration jouent pour tester, jamais pour le prix."""
    return bool(user.is_admin)


def nom_public(user: User) -> str:
    """Pseudo du salon s'il existe, sinon un alias stable — jamais l'e-mail."""
    if user.pseudo:
        return user.pseudo
    return "Joueur " + hashlib.sha256(user.user_id.encode()).hexdigest()[:4].upper()


def points_nets(p: DefiPari) -> float:
    """Contribution d'un pari au solde : mise engagée retirée, retour ajouté."""
    return (p.points_retour or 0.0) - p.points


async def solde(session, user_id: str, mois: str) -> float:
    row = (await session.execute(text("""
        SELECT COALESCE(SUM(COALESCE(points_retour, 0) - points), 0)
        FROM defi_paris WHERE user_id = :u AND mois = :m
    """), {"u": user_id, "m": mois})).scalar()
    return CAPITAL_MENSUEL + float(row or 0.0)


async def _plans_emis(session, user_id: str, course_id: str) -> list[dict]:
    from api.config import get_settings
    from services.bet_plan_snapshots import subject_hash

    # Uniquement les plans montrés À CE JOUEUR : « gagné grâce au plan » veut dire
    # le plan qu'il a consulté. Inclure les plans système laisserait un compte sans
    # quota deviner le plan en regardant l'étiquette de ses propres paris.
    rows = (await session.execute(
        select(BetPlanSnapshot.plan).where(
            BetPlanSnapshot.course_id == course_id,
            BetPlanSnapshot.subject_hash == subject_hash(user_id, get_settings().secret_key),
            BetPlanSnapshot.is_pre_course == True,  # noqa: E712
        )
    )).scalars().all()
    return [r for r in rows if isinstance(r, dict)]


def _meme_pari(type_plan: str, nums_plan: list[int], type_defi: str, nums: list[int]) -> bool:
    """Le pari du défi reprend-il ce pari du plan ?

    Même famille (« Tiercé Ordre » et « Tiercé Désordre » du plan → « Tiercé »,
    « Multi en 5 » → « Multi »…) et mêmes chevaux ; dans le même ordre quand
    l'ordre compte des deux côtés (pari du plan à l'ordre et pari du défi à l'ordre).
    """
    if famille_type(type_plan) != famille_type(type_defi):
        return False
    if "Multi en" in type_plan and "Multi en" in type_defi and type_plan.split(" en ")[-1] != type_defi.split(" en ")[-1]:
        return False
    ordre_plan = type_plan in ("Couplé Ordre", "Trio Ordre", "Super 4", "Tiercé Ordre", "Quinté+")
    ordre_defi = TYPES_DEFI.get(famille_type(type_defi), {}).get("ordre", False)
    if ordre_plan and ordre_defi:
        return nums_plan == nums
    return sorted(nums_plan) == sorted(nums)


async def detecter_origine(session, user_id: str, course_id: str,
                           type_pari: str, chevaux: list[int]) -> str:
    """« plan » si ce pari figure dans un plan de mise montré à ce joueur sur cette course."""
    for plan in await _plans_emis(session, user_id, course_id):
        for niveau in plan.get("niveaux") or []:
            for pari in niveau.get("paris") or []:
                nums = [int(c["numero"]) for c in (pari.get("chevaux") or [])
                        if c.get("numero") is not None]
                if _meme_pari(str(pari.get("type") or ""), nums, type_pari, chevaux):
                    return "plan"
    return "perso"


async def engager_pari(session, user: User, course_id: str, type_pari: str,
                       chevaux: list[int], points: int,
                       now: Optional[datetime] = None) -> DefiPari:
    now = now or datetime.now(timezone.utc)

    if not user.pseudo:
        raise DefiErreur("Choisissez un pseudo pour apparaître au classement avant de jouer.")
    type_pari = famille_type(type_pari)
    if type_pari not in TYPES_DEFI:
        raise DefiErreur("Type de pari non proposé dans le défi.")
    spec = TYPES_DEFI[type_pari]
    if not isinstance(points, int) or not POINTS_MIN <= points <= POINTS_MAX:
        raise DefiErreur(f"Mise entre {POINTS_MIN} et {POINTS_MAX} points.")
    nums = [int(n) for n in chevaux]
    if len(set(nums)) != len(nums) or not spec["min"] <= len(nums) <= spec["max"]:
        if spec["min"] == spec["max"]:
            attendu = f"{spec['min']} cheva{'l' if spec['min'] == 1 else 'ux'}"
        else:
            attendu = f"{spec['min']} à {spec['max']} chevaux différents"
        raise DefiErreur(f"{type_pari} : choisissez {attendu}.")

    # Verrou sur la ligne du joueur jusqu'au commit : ses paris s'engagent l'un
    # après l'autre, donc deux clics simultanés ne peuvent pas dépasser ensemble le
    # solde ou la limite par course (sans lui, chacun ne voit pas le pari de
    # l'autre, pas encore validé). Sans effet sous SQLite, qui sérialise déjà.
    await session.execute(select(User.user_id).where(User.user_id == user.user_id).with_for_update())

    course = await session.get(Course, course_id)
    if course is None:
        raise DefiErreur("Course introuvable.")
    # Une arrivée déjà en base ferme le dépôt même si l'heure stockée est en retard
    # sur la réalité (course avancée, horaire PMU corrigé tardivement).
    if not depot_ouvert(course, now) or await session.get(Resultat, course_id) is not None:
        raise DefiErreur("Les paris sont fermés pour cette course.")

    deja = (await session.execute(text("""
        SELECT COUNT(*) FROM defi_paris WHERE user_id = :u AND course_id = :c
    """), {"u": user.user_id, "c": course_id})).scalar() or 0
    if deja >= MAX_PARIS_PAR_COURSE:
        raise DefiErreur(f"Maximum {MAX_PARIS_PAR_COURSE} paris par course.")

    if type_pari not in {t["type"] for t in types_disponibles(course)}:
        raise DefiErreur(f"Le {type_pari} n'est pas proposé sur cette course.")

    partants = set((await session.execute(
        select(Participation.numero).where(
            Participation.course_id == course_id,
            Participation.non_partant == False,  # noqa: E712
        )
    )).scalars().all())
    if not set(nums) <= partants:
        raise DefiErreur("Cheval inconnu ou non-partant.")

    if len(nums) > len(partants):
        raise DefiErreur("Plus de chevaux choisis que de partants.")

    mois = mois_de(course.date_heure)
    if await solde(session, user.user_id, mois) < points:
        raise DefiErreur("Solde de points insuffisant pour ce mois.")

    type_pari = type_stocke(type_pari, len(nums), course)
    pari = DefiPari(
        user_id=user.user_id, mois=mois, course_id=course_id, type_pari=type_pari,
        chevaux=nums, points=points,
        origine=await detecter_origine(session, user.user_id, course_id, type_pari, nums),
        engage_at=now, statut="en_attente",
    )
    session.add(pari)
    await session.commit()
    invalider_classement()
    await session.refresh(pari)
    return pari


async def regler_course(session, course_id: str) -> int:
    """Règle les paris du défi d'une course arrivée (ou annulée). Idempotent."""
    paris = (await session.execute(
        select(DefiPari).where(DefiPari.course_id == course_id,
                               DefiPari.statut == "en_attente")
    )).scalars().all()
    if not paris:
        return 0
    course = await session.get(Course, course_id)
    if course is None:
        return 0
    now = datetime.now(timezone.utc)

    if course.statut in STATUTS_COURSE_SANS_ARRIVEE:
        for p in paris:
            p.statut, p.rapport, p.points_retour, p.regle_at = "rembourse", 1.0, float(p.points), now
        await session.commit()
        invalider_classement()
        return len(paris)

    if course.statut != "termine":
        return 0
    res = await session.get(Resultat, course_id)
    if res is None or not res.classement:
        return 0
    non_partants = set((await session.execute(
        select(Participation.numero).where(
            Participation.course_id == course_id,
            Participation.non_partant == True,  # noqa: E712
        )
    )).scalars().all())
    nb_part = course.nb_partants or len(res.classement)

    n = 0
    for p in paris:
        r = regler_ticket(p.type_pari, list(p.chevaux), res.classement, res.rapports, nb_part,
                          res.rapports_detail, non_partants)
        if r.get("rembourse"):
            p.statut, p.rapport, p.points_retour = "rembourse", 1.0, float(p.points)
        elif r["gagne"]:
            if r["rapport_reel"] is None:
                continue  # rapport pas encore publié : on attend, on n'invente rien
            p.statut, p.rapport = "gagne", round(float(r["rapport_reel"]), 2)
            p.points_retour = round(p.points * p.rapport * r.get("gain_mult", 1.0), 1)
        else:
            p.statut, p.rapport, p.points_retour = "perd", None, 0.0
        p.regle_at = now
        n += 1
    if _utc(course.date_heure) + DELAI_RAPPORT_MAX < now:
        for p in paris:
            if p.statut == "en_attente":
                p.statut, p.rapport, p.points_retour, p.regle_at = "rembourse", 1.0, float(p.points), now
                n += 1
    if n:
        await session.commit()
        invalider_classement()
    return n


def regler_ticket(type_pari: str, nums: list[int], classement: list[dict],
                  rapports: Optional[dict], nb_partants: int,
                  rapports_detail: Optional[dict], non_partants: set[int]) -> dict:
    """Règle un pari du défi comme le PMU règle le ticket unitaire correspondant.

    Tiercé, Quarté+ et Quinté+ se jouent dans un ordre : l'arrivée exacte paie le
    rapport Ordre, sinon le Désordre, sinon (Quarté+/Quinté+) le Bonus. Les autres
    types sont réglés tels quels par ``settle_pari``.
    """
    from services.bet_settlement import _RAPPORT_KEYS, _rapport_par_libelle

    if type_pari == "Quinté+":
        return settle_pari("Quinté+", nums, classement, rapports, nb_partants,
                           rapports_detail, non_partants, ordre_joue=True)
    if type_pari in ("Tiercé", "Quarté+"):
        n = 3 if type_pari == "Tiercé" else 4
        desordre = "Tiercé Désordre" if n == 3 else "Quarté+ Désordre"
        base = settle_pari(desordre, nums, classement, rapports, nb_partants,
                           rapports_detail, non_partants)
        if base.get("rembourse") or not base["gagne"]:
            return base
        par_pos = {}
        for e in classement or []:
            try:
                par_pos.setdefault(int(e["position"]), int(e["numero"]))
            except (TypeError, ValueError, KeyError):
                continue
        exact = len(nums) == n and all(par_pos.get(i + 1) == nums[i] for i in range(n))
        if exact:
            cles = _RAPPORT_KEYS["Tiercé Ordre" if n == 3 else "Quarté+"]
            ordre = _rapport_par_libelle(rapports_detail, cles, "Ordre", set(nums))
            if ordre is None:
                # Arrivée exacte mais rapport Ordre pas encore publié : on attend,
                # plutôt que de payer le Désordre à un ticket qui vaut l'Ordre.
                return {**base, "rapport_reel": None, "note": "Rapport Ordre pas encore publié."}
            return {**base, "rapport_reel": ordre, "note": "Rang de gain : Ordre."}
        return base
    return settle_pari(type_pari, nums, classement, rapports, nb_partants,
                       rapports_detail, non_partants)


async def regler_en_attente(session) -> int:
    """Rattrapage : règle toutes les courses terminées qui ont encore des paris en attente."""
    course_ids = (await session.execute(text("""
        SELECT DISTINCT d.course_id FROM defi_paris d
        JOIN courses c ON c.course_id = d.course_id
        WHERE d.statut = 'en_attente'
          AND c.statut IN ('termine', 'annule', 'sans_resultat')
    """))).scalars().all()
    total = 0
    for cid in course_ids:
        total += await regler_course(session, cid)
    return total


def _stats(paris: list[DefiPari]) -> dict:
    regles = [p for p in paris if p.statut in ("gagne", "perd")]
    engage = sum(p.points for p in regles)
    net = sum(points_nets(p) for p in regles)
    return {
        "nb_paris": len(paris),
        "nb_gagnes": sum(1 for p in paris if p.statut == "gagne"),
        "nb_en_attente": sum(1 for p in paris if p.statut == "en_attente"),
        "points_nets": round(net, 1),
        "roi": round(net / engage * 100, 1) if engage else None,
    }


async def classement(session, mois: str) -> list[dict]:
    """Tous les joueurs du mois, classés d'abord (≥ MIN paris), puis les autres."""
    paris = (await session.execute(
        select(DefiPari).where(DefiPari.mois == mois).order_by(DefiPari.engage_at)
    )).scalars().all()
    par_user: dict[str, list[DefiPari]] = {}
    for p in paris:
        par_user.setdefault(p.user_id, []).append(p)
    if not par_user:
        return []
    users = {u.user_id: u for u in (await session.execute(
        select(User).where(User.user_id.in_(par_user))
    )).scalars().all()}

    lignes = []
    for uid, ps in par_user.items():
        u = users.get(uid)
        if u is None or not u.is_active:
            continue  # compte exclu (fraude) : retiré du classement
        lignes.append({
            "user_id": uid,
            "nom": nom_public(u),
            "points_mises": sum(p.points for p in ps),
            "dernier_pari_at": ps[-1].engage_at,
            "solde": round(CAPITAL_MENSUEL + sum(points_nets(p) for p in ps), 1),
            "hors_concours": hors_concours(u),
            "classe": len(ps) >= MIN_PARIS_CLASSEMENT and not hors_concours(u),
            "premier_pari_at": ps[0].engage_at,
            **_stats(ps),
        })
    # Départage : solde, puis nombre de paris gagnants, puis le plus ancien engagé.
    lignes.sort(key=lambda l: (not l["classe"], -l["solde"], -l["nb_gagnes"],
                               _utc(l["premier_pari_at"])))
    rang = 0
    for l in lignes:
        if l["classe"]:
            rang += 1
            l["rang"] = rang
        else:
            l["rang"] = None
    return lignes


async def classement_en_cache(session, mois: str) -> list[dict]:
    import time

    vu = _cache_classement.get(mois)
    if vu is not None and time.monotonic() - vu[0] < CACHE_CLASSEMENT:
        return vu[1]
    await regler_en_attente(session)
    lignes = await classement(session, mois)
    _cache_classement[mois] = (time.monotonic(), lignes)
    return lignes


async def resume_joueur(session, user_id: str, mois: str) -> dict:
    paris = (await session.execute(
        select(DefiPari).where(DefiPari.user_id == user_id, DefiPari.mois == mois)
        .order_by(DefiPari.engage_at.desc())
    )).scalars().all()
    return {
        "solde": round(CAPITAL_MENSUEL + sum(points_nets(p) for p in paris), 1),
        **_stats(paris),
        "plan": _stats([p for p in paris if p.origine == "plan"]),
        "perso": _stats([p for p in paris if p.origine == "perso"]),
        "paris": paris,
    }


async def tendance_course(session, course_id: str, depot_ouvert_: bool) -> dict:
    """Ce que les joueurs du défi ont engagé sur la course (sans rien révéler de nominatif).

    Le cheval le plus joué n'est montré qu'une fois le dépôt fermé : avant, il
    trahirait le plan de mise à ceux qui ne l'ont pas (les suiveurs du plan jouent
    tous le même cheval) et inviterait à copier la foule plutôt qu'à pronostiquer.
    """
    paris = (await session.execute(
        select(DefiPari.user_id, DefiPari.chevaux).where(DefiPari.course_id == course_id)
    )).all()
    compte = Counter(n for _, chevaux in paris for n in chevaux)
    top = compte.most_common(1)
    return {
        "nb_joueurs": len({uid for uid, _ in paris}),
        "nb_paris": len(paris),
        "cheval_plus_joue": top[0][0] if top and not depot_ouvert_ else None,
    }


def mois_termine(mois: str, now: Optional[datetime] = None) -> bool:
    return mois < mois_courant(now)


async def _abonnement_vivant(session, user_id: str):
    from api.routes.stripe_routes import STATUTS_VIVANTS
    from db.models import Subscription

    return (await session.execute(
        select(Subscription).where(Subscription.user_id == user_id,
                                   Subscription.statut.in_(STATUTS_VIVANTS))
    )).scalars().first()


def _notifier(session, user_id: str, titre: str, description: str) -> None:
    from db.models import AlerteLog

    session.add(AlerteLog(user_id=user_id, type_alerte="defi_recompense", canal="in-app",
                          envoye=True, payload={"titre": titre, "description": description,
                                                "lien": "/defi"}))


async def attribuer_recompense(session, mois: str, rang: int,
                               now: Optional[datetime] = None) -> DefiRecompense:
    """Remet la récompense du rang ``rang`` pour un mois TERMINÉ, après vérification.

    Refus si le mois n'est pas clos, si des paris du mois attendent encore leur
    règlement (le classement peut encore bouger) ou si le rang est déjà servi.
    """
    now = now or datetime.now(timezone.utc)
    if rang not in RECOMPENSES:
        raise DefiErreur("Aucune récompense pour ce rang.")
    if not mois_termine(mois, now):
        raise DefiErreur("Le mois n'est pas terminé : le classement peut encore bouger.")
    await regler_en_attente(session)
    en_attente = (await session.execute(text("""
        SELECT COUNT(*) FROM defi_paris WHERE mois = :m AND statut = 'en_attente'
    """), {"m": mois})).scalar() or 0
    if en_attente:
        raise DefiErreur(f"{en_attente} pari(s) du mois encore en attente de règlement.")
    deja = (await session.execute(select(DefiRecompense).where(
        DefiRecompense.mois == mois, DefiRecompense.rang == rang))).scalars().first()
    if deja is not None:
        raise DefiErreur("Récompense déjà attribuée pour ce rang.")

    ligne = next((l for l in await classement(session, mois) if l["rang"] == rang), None)
    if ligne is None:
        raise DefiErreur("Personne n'occupe ce rang.")
    user = await session.get(User, ligne["user_id"])
    plan_offert, jours = RECOMPENSES[rang]

    # Un abonné payant ne peut pas recevoir un plan « à la main » : son plan suit
    # Stripe et serait écrasé au prochain webhook (ou le rétrograderait à l'échéance).
    # On l'enregistre en « manuel » : geste commercial à faire dans Stripe.
    abonne = await _abonnement_vivant(session, user.user_id)
    deja_mieux = _NIVEAU_PLAN.get(user.plan or "free", 0) >= _NIVEAU_PLAN[plan_offert]
    statut = "manuel" if abonne is not None or deja_mieux else "applique"
    recompense = DefiRecompense(
        mois=mois, rang=rang, user_id=user.user_id, nom_public=ligne["nom"],
        solde=ligne["solde"], plan_offert=plan_offert, plan_precedent=user.plan,
        statut=statut, attribue_at=now, expire_at=now + timedelta(days=jours),
    )
    session.add(recompense)
    if statut == "applique":
        user.plan = plan_offert
    libelle = plan_offert.capitalize()
    _notifier(session, user.user_id, f"🏆 {rang}{'er' if rang == 1 else 'e'} du Défi du mois !",
              f"Vous gagnez {jours} jours {libelle} offerts."
              if statut == "applique" else
              f"Vous gagnez {jours} jours {libelle} offerts : ils seront déduits de votre abonnement.")
    try:
        await session.commit()
    except IntegrityError:
        # Deux remises simultanées : l'unicité (mois, rang) a tranché pour l'autre.
        await session.rollback()
        raise DefiErreur("Récompense déjà attribuée pour ce rang.")
    await session.refresh(recompense)
    log.info("defi.recompense", mois=mois, rang=rang, user_id=user.user_id, statut=statut)
    return recompense


async def expirer_recompenses(session, now: Optional[datetime] = None) -> int:
    """Rétablit le plan précédent des récompenses échues. Idempotent."""
    now = now or datetime.now(timezone.utc)
    echues = (await session.execute(select(DefiRecompense).where(
        DefiRecompense.statut == "applique", DefiRecompense.expire_at <= now,
    ))).scalars().all()
    for r in echues:
        user = await session.get(User, r.user_id)
        if user is None:
            r.statut = "termine"
            continue
        # Souscrit pendant le mois offert, ou plan changé par ailleurs : on ne
        # touche à rien — rétrograder un client payant serait bien pire qu'oublier.
        if await _abonnement_vivant(session, r.user_id) is not None or user.plan != r.plan_offert:
            r.statut = "conserve"
            continue
        user.plan = r.plan_precedent or "free"
        r.statut = "termine"
    if echues:
        await session.commit()
    return len(echues)


async def palmares(session, limite: int = 24) -> list[dict]:
    rows = (await session.execute(
        select(DefiRecompense).order_by(DefiRecompense.mois.desc(), DefiRecompense.rang)
        .limit(limite * 3)
    )).scalars().all()
    return [{"mois": r.mois, "rang": r.rang, "nom": r.nom_public, "solde": r.solde,
             "plan_offert": r.plan_offert} for r in rows]


async def resume_admin(session, user_ids: list[str], mois: str) -> dict[str, dict]:
    """Défi du mois par compte, pour le back-office : solde, rang, paris, rendement.

    Un compte sans pari dans le mois est absent du dict : l'appelant affiche le
    capital de départ et « aucun pari »."""
    if not user_ids:
        return {}
    voulus = set(user_ids)
    return {
        l["user_id"]: {k: l[k] for k in ("solde", "rang", "nb_paris", "nb_gagnes",
                                          "nb_en_attente", "points_nets", "roi", "classe",
                                          "points_mises", "dernier_pari_at")}
        for l in await classement(session, mois) if l["user_id"] in voulus
    }
