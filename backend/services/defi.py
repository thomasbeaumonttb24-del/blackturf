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

# Rang → (plan offert, durée). Remis par l'admin après vérification du compte.
RECOMPENSES: dict[int, tuple[str, int]] = {
    1: ("expert", 30),
    2: ("standard", 30),
    3: ("standard", 30),
}
_NIVEAU_PLAN = {"free": 0, "decouverte": 0, "standard": 1, "starter": 1, "expert": 2, "pro": 2}

# Type de pari → (nombre de chevaux, drapeau de disponibilité du catalogue).
# Quatre paris simples à régler exactement : on élargira s'il y a de la demande.
TYPES_DEFI: dict[str, tuple[int, str]] = {
    "Simple Gagnant": (1, "est_simple_gagnant"),
    "Simple Placé": (1, "est_simple_place"),
    "Couplé Gagnant": (2, "est_couple_gagnant"),
    "Couplé Placé": (2, "est_couple_place"),
}

STATUTS_COURSE_SANS_ARRIVEE = {"annule", "sans_resultat"}


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


async def detecter_origine(session, user_id: str, course_id: str,
                           type_pari: str, chevaux: list[int]) -> str:
    """« plan » si ce pari figure dans un plan de mise montré à ce joueur sur cette course."""
    cible = sorted(chevaux)
    for plan in await _plans_emis(session, user_id, course_id):
        for niveau in plan.get("niveaux") or []:
            for pari in niveau.get("paris") or []:
                nums = sorted(int(c["numero"]) for c in (pari.get("chevaux") or [])
                              if c.get("numero") is not None)
                if pari.get("type") == type_pari and nums == cible:
                    return "plan"
    return "perso"


async def engager_pari(session, user: User, course_id: str, type_pari: str,
                       chevaux: list[int], points: int,
                       now: Optional[datetime] = None) -> DefiPari:
    now = now or datetime.now(timezone.utc)

    if type_pari not in TYPES_DEFI:
        raise DefiErreur("Type de pari non proposé dans le défi.")
    nb_attendu, drapeau = TYPES_DEFI[type_pari]
    if not isinstance(points, int) or not POINTS_MIN <= points <= POINTS_MAX:
        raise DefiErreur(f"Mise entre {POINTS_MIN} et {POINTS_MAX} points.")
    nums = [int(n) for n in chevaux]
    if len(nums) != nb_attendu or len(set(nums)) != nb_attendu:
        raise DefiErreur(f"{type_pari} : choisissez {nb_attendu} cheva{'l' if nb_attendu == 1 else 'ux'}.")

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

    flags = derive_bet_flags(course.paris_disponibles, est_tierce=bool(course.est_tierce),
                             est_quarte=bool(course.est_quarte), est_quinte=bool(course.est_quinte),
                             est_2sur4=bool(course.est_2sur4), nb_partants=course.nb_partants)
    if not flags.get(drapeau):
        raise DefiErreur(f"Le {type_pari} n'est pas proposé sur cette course.")

    partants = set((await session.execute(
        select(Participation.numero).where(
            Participation.course_id == course_id,
            Participation.non_partant == False,  # noqa: E712
        )
    )).scalars().all())
    if not set(nums) <= partants:
        raise DefiErreur("Cheval inconnu ou non-partant.")

    mois = mois_de(course.date_heure)
    if await solde(session, user.user_id, mois) < points:
        raise DefiErreur("Solde de points insuffisant pour ce mois.")

    pari = DefiPari(
        user_id=user.user_id, mois=mois, course_id=course_id, type_pari=type_pari,
        chevaux=nums, points=points,
        origine=await detecter_origine(session, user.user_id, course_id, type_pari, nums),
        engage_at=now, statut="en_attente",
    )
    session.add(pari)
    await session.commit()
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
        r = settle_pari(p.type_pari, list(p.chevaux), res.classement, res.rapports, nb_part,
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
    if n:
        await session.commit()
    return n


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
