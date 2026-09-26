"""
Défi du mois — routes.

Ouvert à TOUS les comptes connectés, quel que soit l'abonnement et sans quota :
on peut engager ses propres paris sans avoir vu (ni pouvoir voir) le plan de mise.
"""
import re
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import _access_token, get_current_user, require_admin
from db.database import get_db
from db.models import Course, DefiPari, DefiRecompense, User
from services import defi

router = APIRouter()
admin_router = APIRouter()

_MOIS_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


async def _utilisateur_optionnel(
    token: Optional[str] = Depends(_access_token),
    db: AsyncSession = Depends(get_db),
) -> Optional[User]:
    if not token:
        return None
    try:
        return await get_current_user(token, db)
    except HTTPException:
        return None


def _mois(mois: Optional[str]) -> str:
    if mois is None:
        return defi.mois_courant()
    if not _MOIS_RE.match(mois):
        raise HTTPException(status_code=400, detail="Mois attendu au format AAAA-MM.")
    return mois


class PariIn(BaseModel):
    course_id: str
    type_pari: str
    chevaux: list[int]
    points: int


class PariOut(BaseModel):
    pari_id: str
    course_id: str
    course_label: Optional[str] = None
    date_heure: Optional[datetime] = None
    type_pari: str
    chevaux: list[int]
    points: int
    origine: str
    statut: str
    rapport: Optional[float]
    points_retour: Optional[float]
    engage_at: datetime


async def _pari_out(db: AsyncSession, paris: list[DefiPari]) -> list[PariOut]:
    ids = {p.course_id for p in paris}
    courses = {c.course_id: c for c in (await db.execute(
        select(Course).where(Course.course_id.in_(ids))
    )).scalars().all()} if ids else {}
    out = []
    for p in paris:
        c = courses.get(p.course_id)
        label = None
        if c is not None:
            label = f"R{c.numero_reunion}C{c.numero} · {c.hippodrome_nom}" if c.numero_reunion \
                else c.hippodrome_nom
        out.append(PariOut(
            pari_id=p.pari_id, course_id=p.course_id, course_label=label,
            date_heure=c.date_heure if c else None, type_pari=p.type_pari,
            chevaux=list(p.chevaux), points=p.points, origine=p.origine, statut=p.statut,
            rapport=p.rapport, points_retour=p.points_retour, engage_at=p.engage_at,
        ))
    return out


@router.get("/defi/regles")
async def regles():
    return {
        "capital_mensuel": defi.CAPITAL_MENSUEL,
        "points_min": defi.POINTS_MIN,
        "points_max": defi.POINTS_MAX,
        "min_paris_classement": defi.MIN_PARIS_CLASSEMENT,
        "max_paris_par_course": defi.MAX_PARIS_PAR_COURSE,
        "verrou_minutes": int(defi.VERROU_AVANT_DEPART.total_seconds() // 60),
        "recompenses": [{"rang": r, "plan": p, "jours": j}
                        for r, (p, j) in sorted(defi.RECOMPENSES.items())],
        "types": [{k: v for k, v in t.items() if k != "drapeau"} for t in defi.CATALOGUE_DEFI],
        "mois": defi.mois_courant(),
    }


def _ligne_publique(l: dict, moi: Optional[str]) -> dict:
    return {k: v for k, v in l.items()
            if k not in ("user_id", "premier_pari_at", "dernier_pari_at", "points_mises")} \
        | {"moi": l["user_id"] == moi}


@router.get("/defi/classement")
async def get_classement(
    mois: Optional[str] = Query(None),
    top: Optional[int] = Query(None, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(_utilisateur_optionnel),
):
    """Classement public. ``top`` : les N premiers classés seulement, plus la
    ligne du joueur connecté dans ``ma_ligne`` (widgets de l'accueil, des courses…)."""
    m = _mois(mois)
    lignes = await defi.classement_en_cache(db, m)
    moi = user.user_id if user else None
    ma = next((l for l in lignes if l["user_id"] == moi), None)
    affichees = [l for l in lignes if l["classe"]][:top] if top else lignes
    return {
        "mois": m,
        "nb_joueurs": len(lignes),
        "nb_classes": sum(1 for l in lignes if l["classe"]),
        "lignes": [_ligne_publique(l, moi) for l in affichees],
        "ma_ligne": _ligne_publique(ma, moi) if ma else None,
    }


@router.get("/defi/palmares")
async def get_palmares(db: AsyncSession = Depends(get_db)):
    return await defi.palmares(db)


@router.get("/defi/moi")
async def get_moi(
    mois: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    m = _mois(mois)
    await defi.regler_en_attente(db)
    resume = await defi.resume_joueur(db, user.user_id, m)
    lignes = await defi.classement(db, m)
    ma_ligne = next((l for l in lignes if l["user_id"] == user.user_id), None)
    paris = resume.pop("paris")
    return {
        "mois": m,
        "nom": defi.nom_public(user),
        "rang": ma_ligne["rang"] if ma_ligne else None,
        "nb_classes": sum(1 for l in lignes if l["classe"]),
        **resume,
        "paris": await _pari_out(db, paris),
    }


@router.get("/defi/course/{course_id}")
async def get_course(
    course_id: str,
    db: AsyncSession = Depends(get_db),
    user: Optional[User] = Depends(_utilisateur_optionnel),
):
    course = await db.get(Course, course_id)
    if course is None:
        raise HTTPException(status_code=404, detail="Course introuvable")
    await defi.regler_course(db, course_id)
    mes_paris: list[DefiPari] = []
    solde = None
    if user is not None:
        mes_paris = list((await db.execute(
            select(DefiPari).where(DefiPari.course_id == course_id,
                                   DefiPari.user_id == user.user_id)
            .order_by(DefiPari.engage_at)
        )).scalars().all())
        solde = await defi.solde(db, user.user_id, defi.mois_de(course.date_heure))
    return {
        "mois": defi.mois_de(course.date_heure),
        # Les paris que le PMU ouvre sur CETTE course, dans l'ordre du catalogue.
        "types": defi.types_disponibles(course),
        "ouvert": defi.depot_ouvert(course),
        "limite": defi.limite_depot(course),
        "solde": solde,
        "tendance": await defi.tendance_course(db, course_id, defi.depot_ouvert(course)),
        "mes_paris": await _pari_out(db, mes_paris),
        # Le plan que CE joueur a déjà consulté sur la course (vide sinon).
        "plan": await defi.paris_du_plan(db, user.user_id, course, mes_paris) if user else [],
    }


@router.post("/defi/paris", response_model=PariOut, status_code=201)
async def post_pari(
    body: PariIn,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    try:
        pari = await defi.engager_pari(db, user, body.course_id, body.type_pari,
                                       body.chevaux, body.points)
    except defi.DefiErreur as e:
        raise HTTPException(status_code=400, detail=str(e))
    return (await _pari_out(db, [pari]))[0]


# ─────────────────────────────────────────────
# Admin — clôture du mois
# ─────────────────────────────────────────────
class RecompenseIn(BaseModel):
    mois: str
    rang: int


@admin_router.get("/defi/cloture")
async def admin_cloture(
    mois: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    """Top du mois avec ce qu'il faut pour vérifier un compte AVANT de le récompenser."""
    m = _mois(mois)
    await defi.regler_en_attente(db)
    lignes = [l for l in await defi.classement(db, m) if l["classe"]][:10]
    users = {u.user_id: u for u in (await db.execute(
        select(User).where(User.user_id.in_([l["user_id"] for l in lignes]))
    )).scalars().all()} if lignes else {}
    deja = {r.rang: r for r in (await db.execute(
        select(DefiRecompense).where(DefiRecompense.mois == m))).scalars().all()}
    debut_mois = datetime.strptime(m + "-01", "%Y-%m-%d").replace(tzinfo=defi.PARIS_TZ)
    out = []
    for l in lignes:
        u = users[l["user_id"]]
        cree = defi._utc(u.created_at) if u.created_at else None
        alertes = []
        if cree and cree >= debut_mois:
            alertes.append("Compte créé pendant le mois du défi")
        if not u.email_verified:
            alertes.append("Adresse e-mail non confirmée")
        r = deja.get(l["rang"])
        out.append({
            **{k: v for k, v in l.items() if k != "premier_pari_at"},
            "email": u.email, "plan": u.plan, "created_at": u.created_at,
            "last_login_at": u.last_login_at, "alertes": alertes,
            "recompense": {"statut": r.statut, "plan_offert": r.plan_offert,
                           "expire_at": r.expire_at} if r and r.user_id == u.user_id else None,
        })
    en_attente = sum(l["nb_en_attente"] for l in await defi.classement(db, m))
    return {
        "mois": m,
        "mois_termine": defi.mois_termine(m),
        "paris_en_attente": en_attente,
        "recompenses": [{"rang": r, "plan": p, "jours": j}
                        for r, (p, j) in sorted(defi.RECOMPENSES.items())],
        "lignes": out,
    }


@admin_router.post("/defi/recompenses")
async def admin_recompense(
    body: RecompenseIn,
    db: AsyncSession = Depends(get_db),
    _=Depends(require_admin),
):
    try:
        r = await defi.attribuer_recompense(db, _mois(body.mois), body.rang)
    except defi.DefiErreur as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"rang": r.rang, "nom": r.nom_public, "statut": r.statut,
            "plan_offert": r.plan_offert, "expire_at": r.expire_at}
