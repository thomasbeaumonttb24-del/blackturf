"""
Bankroll routes — BlackTurf.
CRUD paris + stats ROI + CSV/PDF export + portefeuilles multiples.
"""
import csv
import io
import uuid
import structlog
from datetime import datetime, date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, HTMLResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, desc

from api.routes.auth import get_current_user
from db.database import get_db
from db.models import BankrollEntry, Bankroll, User

log = structlog.get_logger()
router = APIRouter()


# ─────────────────────────────────────────────
# Schemas
# ─────────────────────────────────────────────
class EntryCreate(BaseModel):
    course_id: Optional[str] = None
    reco_id: Optional[str] = None
    bankroll_id: Optional[str] = None
    date: datetime
    type_pari: str
    chevaux: Optional[str] = None
    mise: float
    cote: Optional[float] = None
    resultat: Optional[str] = None  # gagne/perd/annule
    gain_perte: Optional[float] = None
    suivi_reco_ia: bool = False
    notes: Optional[str] = None


class EntryUpdate(BaseModel):
    resultat: Optional[str] = None
    gain_perte: Optional[float] = None
    notes: Optional[str] = None
    cote: Optional[float] = None


class EntryOut(BaseModel):
    entry_id: str
    course_id: Optional[str]
    numero_reunion: Optional[int] = None  # n° réunion public (PMU numExterne) pour le code R
    reco_id: Optional[str]
    bankroll_id: Optional[str]
    date: datetime
    type_pari: str
    chevaux: Optional[str]
    mise: float
    cote: Optional[float]
    resultat: Optional[str]
    gain_perte: Optional[float]
    suivi_reco_ia: bool
    notes: Optional[str]


class BankrollStats(BaseModel):
    bankroll_initiale: Optional[float]
    mise_totale: float
    gains_totaux: float
    pertes_totales: float
    roi_global: float
    roi_ia_only: float
    nb_paris: int
    nb_gagnants: int
    nb_perdants: int
    taux_reussite: float


class BankrollCreate(BaseModel):
    nom: str
    discipline: Optional[str] = None
    montant_initial: float = 0.0
    est_principale: bool = False
    couleur: Optional[str] = None


class BankrollUpdate(BaseModel):
    nom: Optional[str] = None
    discipline: Optional[str] = None
    montant_initial: Optional[float] = None
    couleur: Optional[str] = None


class BankrollOut(BaseModel):
    bankroll_id: str
    nom: str
    discipline: Optional[str]
    montant_initial: float
    est_principale: bool
    couleur: Optional[str]
    solde_actuel: float
    nb_entrees: int
    created_at: datetime


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────
def _entry_to_out(e: BankrollEntry, numero_reunion: Optional[int] = None) -> EntryOut:
    return EntryOut(
        entry_id=e.entry_id,
        course_id=e.course_id,
        numero_reunion=numero_reunion,
        reco_id=e.reco_id,
        bankroll_id=e.bankroll_id,
        date=e.date,
        type_pari=e.type_pari,
        chevaux=e.chevaux,
        mise=e.mise,
        cote=e.cote,
        resultat=e.resultat,
        gain_perte=e.gain_perte,
        suivi_reco_ia=e.suivi_reco_ia,
        notes=e.notes,
    )


async def settle_pending_bets(db: AsyncSession, user_id: Optional[str] = None) -> None:
    """
    Règle automatiquement les paris enregistrés EN ATTENTE (resultat NULL) dont
    la course est terminée, avec les VRAIS rapports PMU (bet_settlement). Met à
    jour gain_perte (net) + resultat. Si un pari a gagné mais que le rapport
    n'est pas encore publié, on le laisse en attente (aucune valeur inventée).

    user_id=None → règle les paris de TOUS les utilisateurs (appelé à la fin de
    chaque course pour que toutes les données — bankroll, back-office admin — soient
    à jour immédiatement, sans attendre que l'utilisateur consulte son compte).
    """
    import re
    from db.models import Resultat as _Res, Course as _Cou
    from services.bet_settlement import settle_pari

    conds = [BankrollEntry.resultat.is_(None), BankrollEntry.course_id.isnot(None)]
    if user_id is not None:
        conds.insert(0, BankrollEntry.user_id == user_id)
    pending = (await db.execute(
        select(BankrollEntry).where(*conds)
    )).scalars().all()
    if not pending:
        return

    by_course: dict[str, list] = {}
    for e in pending:
        by_course.setdefault(e.course_id, []).append(e)

    changed = False
    for cid, entries in by_course.items():
        course = await db.get(_Cou, cid)
        if not course or course.statut != "termine":
            continue
        res = await db.get(_Res, cid)
        if not res or not res.classement:
            continue
        nb_part = course.nb_partants or len(res.classement)
        for e in entries:
            nums = [int(n) for n in re.findall(r"\d+", e.chevaux or "")]
            if not nums:
                continue
            r = settle_pari(e.type_pari, nums, res.classement, res.rapports, nb_part)
            if r["gagne"]:
                if r["rapport_reel"] is not None:
                    gain_brut = round(e.mise * r["rapport_reel"], 2)
                    e.gain_perte = round(gain_brut - e.mise, 2)  # NET
                    e.cote = round(float(r["rapport_reel"]), 2)
                    e.resultat = "gagne"
                    changed = True
                # sinon : rapport pas encore publié → reste en attente
            else:
                e.gain_perte = round(-e.mise, 2)
                e.resultat = "perd"
                changed = True

    if changed:
        await db.commit()


# ─────────────────────────────────────────────
# Routes — Entries
# ─────────────────────────────────────────────
@router.get("/bankroll/entries", response_model=list[EntryOut])
async def list_entries(
    limit: int = Query(default=50, le=200),
    offset: int = Query(default=0, ge=0),
    resultat: Optional[str] = Query(default=None),
    date_debut: Optional[date] = Query(default=None),
    date_fin: Optional[date] = Query(default=None),
    bankroll_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await settle_pending_bets(db, user.user_id)  # règle les paris en attente
    q = select(BankrollEntry).where(BankrollEntry.user_id == user.user_id)

    if resultat:
        q = q.where(BankrollEntry.resultat == resultat)
    if date_debut:
        q = q.where(BankrollEntry.date >= datetime.combine(date_debut, datetime.min.time()))
    if date_fin:
        q = q.where(BankrollEntry.date <= datetime.combine(date_fin, datetime.max.time()))
    if bankroll_id:
        q = q.where(BankrollEntry.bankroll_id == bankroll_id)

    q = q.order_by(desc(BankrollEntry.date)).limit(limit).offset(offset)
    rows = (await db.execute(q)).scalars().all()

    # Récupère le n° de réunion PUBLIC (numExterne) des courses concernées en un lot,
    # pour afficher le bon code R (cohérent avec pmu.fr) au lieu du numOfficiel parsé.
    from db.models import Course as _Course
    cids = [e.course_id for e in rows if e.course_id]
    num_by_cid: dict[str, int] = {}
    if cids:
        nr = await db.execute(
            select(_Course.course_id, _Course.numero_reunion).where(_Course.course_id.in_(cids))
        )
        num_by_cid = {cid: nrv for cid, nrv in nr.fetchall() if nrv is not None}

    return [_entry_to_out(e, num_by_cid.get(e.course_id)) for e in rows]


@router.post("/bankroll/entries", response_model=EntryOut, status_code=201)
async def create_entry(
    body: EntryCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    bankroll_id = body.bankroll_id
    # If no bankroll_id given, resolve to main bankroll if it exists
    if not bankroll_id:
        res = await db.execute(
            select(Bankroll).where(
                and_(
                    Bankroll.user_id == user.user_id,
                    Bankroll.est_principale == True,
                    Bankroll.est_supprime == False,
                )
            )
        )
        main = res.scalar_one_or_none()
        if main:
            bankroll_id = main.bankroll_id

    data = body.model_dump()
    data["bankroll_id"] = bankroll_id
    entry = BankrollEntry(
        entry_id=str(uuid.uuid4()),
        user_id=user.user_id,
        **data,
    )
    db.add(entry)
    await db.commit()
    await db.refresh(entry)
    return _entry_to_out(entry)


@router.patch("/bankroll/entries/{entry_id}", response_model=EntryOut)
async def update_entry(
    entry_id: str,
    body: EntryUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BankrollEntry).where(
            and_(BankrollEntry.entry_id == entry_id, BankrollEntry.user_id == user.user_id)
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrée introuvable")

    for k, v in body.model_dump(exclude_none=True).items():
        setattr(entry, k, v)
    await db.commit()
    await db.refresh(entry)
    return _entry_to_out(entry)


@router.delete("/bankroll/entries/{entry_id}", status_code=204)
async def delete_entry(
    entry_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await db.execute(
        select(BankrollEntry).where(
            and_(BankrollEntry.entry_id == entry_id, BankrollEntry.user_id == user.user_id)
        )
    )
    entry = result.scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entrée introuvable")
    await db.delete(entry)
    await db.commit()


@router.get("/bankroll/stats", response_model=BankrollStats)
async def get_stats(
    bankroll_id: Optional[str] = Query(default=None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Statistiques ROI complètes."""
    await settle_pending_bets(db, user.user_id)  # règle les paris en attente
    q = select(BankrollEntry).where(BankrollEntry.user_id == user.user_id)
    if bankroll_id:
        q = q.where(BankrollEntry.bankroll_id == bankroll_id)
    entries = (await db.execute(q)).scalars().all()

    mise_totale = sum(e.mise for e in entries)
    gains_totaux = sum(e.gain_perte for e in entries if e.gain_perte and e.gain_perte > 0)
    pertes_totales = sum(abs(e.gain_perte) for e in entries if e.gain_perte and e.gain_perte < 0)
    nb_gagnants = sum(1 for e in entries if e.resultat == "gagne")
    nb_perdants = sum(1 for e in entries if e.resultat == "perd")

    roi_global = (gains_totaux - pertes_totales) / mise_totale if mise_totale > 0 else 0.0

    ia_entries = [e for e in entries if e.suivi_reco_ia]
    mise_ia = sum(e.mise for e in ia_entries)
    gain_ia = sum(e.gain_perte or 0 for e in ia_entries)
    roi_ia = gain_ia / mise_ia if mise_ia > 0 else 0.0

    return BankrollStats(
        bankroll_initiale=user.bankroll_initiale,
        mise_totale=round(mise_totale, 2),
        gains_totaux=round(gains_totaux, 2),
        pertes_totales=round(pertes_totales, 2),
        roi_global=round(roi_global * 100, 2),
        roi_ia_only=round(roi_ia * 100, 2),
        nb_paris=len(entries),
        nb_gagnants=nb_gagnants,
        nb_perdants=nb_perdants,
        taux_reussite=round(nb_gagnants / len(entries) * 100, 2) if entries else 0.0,
    )


# ─────────────────────────────────────────────
# Routes — Export CSV (legacy + enhanced)
# ─────────────────────────────────────────────
@router.get("/bankroll/export")
async def export_csv_legacy(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export CSV de tous les paris (legacy endpoint)."""
    return await _build_csv_response(db, user, None, None)


@router.get("/bankroll/export/csv")
async def export_bankroll_csv(
    date_debut: Optional[date] = Query(None),
    date_fin: Optional[date] = Query(None),
    bankroll_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Export CSV avec filtres date et portefeuille."""
    return await _build_csv_response(db, user, date_debut, date_fin, bankroll_id)


async def _build_csv_response(
    db: AsyncSession,
    user: User,
    date_debut: Optional[date],
    date_fin: Optional[date],
    bankroll_id: Optional[str] = None,
) -> StreamingResponse:
    q = select(BankrollEntry).where(BankrollEntry.user_id == user.user_id)
    if date_debut:
        q = q.where(BankrollEntry.date >= datetime.combine(date_debut, datetime.min.time()))
    if date_fin:
        q = q.where(BankrollEntry.date <= datetime.combine(date_fin, datetime.max.time()))
    if bankroll_id:
        q = q.where(BankrollEntry.bankroll_id == bankroll_id)
    q = q.order_by(BankrollEntry.date)
    entries = (await db.execute(q)).scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "Date", "Type pari", "Chevaux", "Mise", "Cote",
        "Résultat", "Gain/Perte", "Suivi IA", "Notes", "Course",
    ])
    for e in entries:
        writer.writerow([
            e.date.strftime("%Y-%m-%d %H:%M"),
            e.type_pari,
            e.chevaux or "",
            e.mise,
            e.cote or "",
            e.resultat or "",
            e.gain_perte or "",
            "Oui" if e.suivi_reco_ia else "Non",
            e.notes or "",
            e.course_id or "",
        ])

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=blackturf_bankroll.csv"},
    )


# ─────────────────────────────────────────────
# Routes — Export PDF (HTML print-optimized)
# ─────────────────────────────────────────────
@router.get("/bankroll/export/pdf")
async def export_bankroll_pdf(
    date_debut: Optional[date] = Query(None),
    date_fin: Optional[date] = Query(None),
    bankroll_id: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """
    Export PDF bankroll — retourne une page HTML print-optimisée.
    Le navigateur peut l'imprimer en PDF via Ctrl+P / window.print().
    """
    q = select(BankrollEntry).where(BankrollEntry.user_id == user.user_id)
    if date_debut:
        q = q.where(BankrollEntry.date >= datetime.combine(date_debut, datetime.min.time()))
    if date_fin:
        q = q.where(BankrollEntry.date <= datetime.combine(date_fin, datetime.max.time()))
    if bankroll_id:
        q = q.where(BankrollEntry.bankroll_id == bankroll_id)
    q = q.order_by(BankrollEntry.date)
    entries = (await db.execute(q)).scalars().all()

    # Summary stats
    mise_totale = sum(e.mise for e in entries)
    gains = sum(e.gain_perte for e in entries if e.gain_perte and e.gain_perte > 0)
    pertes = sum(abs(e.gain_perte) for e in entries if e.gain_perte and e.gain_perte < 0)
    net = gains - pertes
    roi = net / mise_totale * 100 if mise_totale else 0.0
    nb_gagnants = sum(1 for e in entries if e.resultat == "gagne")
    taux = nb_gagnants / len(entries) * 100 if entries else 0.0

    range_label = ""
    if date_debut or date_fin:
        parts = []
        if date_debut:
            parts.append(f"Du {date_debut.strftime('%d/%m/%Y')}")
        if date_fin:
            parts.append(f"au {date_fin.strftime('%d/%m/%Y')}")
        range_label = " ".join(parts)

    rows_html = ""
    for e in entries:
        gp = e.gain_perte
        color = "#16a34a" if gp and gp > 0 else ("#dc2626" if gp and gp < 0 else "#374151")
        rows_html += f"""
        <tr>
            <td>{e.date.strftime('%d/%m/%Y %H:%M')}</td>
            <td>{e.type_pari}</td>
            <td>{e.chevaux or ''}</td>
            <td class="num">{e.mise:.2f} €</td>
            <td class="num">{e.cote or ''}</td>
            <td>{e.resultat or ''}</td>
            <td class="num" style="color:{color}">{f'{gp:+.2f} €' if gp is not None else ''}</td>
            <td>{'✓' if e.suivi_reco_ia else ''}</td>
            <td>{e.notes or ''}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<title>BlackTurf — Historique bankroll</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: 'Helvetica Neue', Arial, sans-serif; font-size: 11px; color: #111; padding: 20px; }}
  h1 {{ font-size: 18px; font-weight: 700; margin-bottom: 4px; }}
  .subtitle {{ color: #6b7280; font-size: 12px; margin-bottom: 16px; }}
  .stats-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 12px; margin-bottom: 20px; }}
  .stat-box {{ border: 1px solid #e5e7eb; border-radius: 6px; padding: 10px; }}
  .stat-label {{ font-size: 10px; color: #6b7280; margin-bottom: 2px; }}
  .stat-value {{ font-size: 15px; font-weight: 700; }}
  table {{ width: 100%; border-collapse: collapse; }}
  th {{ background: #111827; color: #fff; font-size: 10px; padding: 6px 8px; text-align: left; }}
  td {{ border-bottom: 1px solid #e5e7eb; padding: 5px 8px; vertical-align: middle; }}
  tr:nth-child(even) td {{ background: #f9fafb; }}
  .num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  @media print {{
    body {{ padding: 10px; }}
    @page {{ margin: 15mm; size: A4 landscape; }}
  }}
</style>
</head>
<body>
<h1>BlackTurf — Historique bankroll</h1>
<div class="subtitle">{range_label or 'Toutes les entrées'} · Généré le {datetime.now().strftime('%d/%m/%Y à %H:%M')}</div>
<div class="stats-grid">
  <div class="stat-box"><div class="stat-label">Paris</div><div class="stat-value">{len(entries)}</div></div>
  <div class="stat-box"><div class="stat-label">Mise totale</div><div class="stat-value">{mise_totale:.2f} €</div></div>
  <div class="stat-box"><div class="stat-label">Résultat net</div><div class="stat-value" style="color:{'#16a34a' if net >= 0 else '#dc2626'}">{net:+.2f} €</div></div>
  <div class="stat-box"><div class="stat-label">ROI</div><div class="stat-value" style="color:{'#16a34a' if roi >= 0 else '#dc2626'}">{roi:+.1f}%</div></div>
  <div class="stat-box"><div class="stat-label">Taux réussite</div><div class="stat-value">{taux:.1f}%</div></div>
</div>
<table>
<thead>
  <tr>
    <th>Date</th><th>Type</th><th>Chevaux</th><th>Mise</th><th>Cote</th>
    <th>Résultat</th><th>Gain/Perte</th><th>IA</th><th>Notes</th>
  </tr>
</thead>
<tbody>
{rows_html}
</tbody>
</table>
<script>window.onload = function() {{ window.print(); }}</script>
</body>
</html>"""

    return HTMLResponse(content=html)


# ─────────────────────────────────────────────
# Routes — Portefeuilles (bankrolls multiples)
# ─────────────────────────────────────────────
@router.get("/bankroll/portefeuilles", response_model=list[BankrollOut])
async def list_portefeuilles(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Liste les portefeuilles de l'utilisateur avec solde courant."""
    res = await db.execute(
        select(Bankroll).where(
            and_(Bankroll.user_id == user.user_id, Bankroll.est_supprime == False)
        ).order_by(desc(Bankroll.est_principale), Bankroll.created_at)
    )
    bankrolls = res.scalars().all()

    results = []
    for b in bankrolls:
        # Solde = montant_initial + sum(gain_perte)
        res_agg = await db.execute(
            select(
                func.count(BankrollEntry.entry_id),
                func.coalesce(func.sum(BankrollEntry.gain_perte), 0.0),
            ).where(BankrollEntry.bankroll_id == b.bankroll_id)
        )
        row = res_agg.one()
        nb_entrees = row[0]
        total_gp = float(row[1])

        results.append(BankrollOut(
            bankroll_id=b.bankroll_id,
            nom=b.nom,
            discipline=b.discipline,
            montant_initial=b.montant_initial,
            est_principale=b.est_principale,
            couleur=b.couleur,
            solde_actuel=round(b.montant_initial + total_gp, 2),
            nb_entrees=nb_entrees,
            created_at=b.created_at,
        ))

    return results


@router.post("/bankroll/portefeuilles", response_model=BankrollOut, status_code=201)
async def create_portefeuille(
    body: BankrollCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Crée un nouveau portefeuille. Si est_principale, déplace le flag des autres."""
    if body.est_principale:
        # Unset existing main bankroll
        existing = await db.execute(
            select(Bankroll).where(
                and_(
                    Bankroll.user_id == user.user_id,
                    Bankroll.est_principale == True,
                    Bankroll.est_supprime == False,
                )
            )
        )
        for b in existing.scalars().all():
            b.est_principale = False

    b = Bankroll(
        bankroll_id=str(uuid.uuid4()),
        user_id=user.user_id,
        nom=body.nom,
        discipline=body.discipline,
        montant_initial=body.montant_initial,
        est_principale=body.est_principale,
        couleur=body.couleur,
    )
    db.add(b)
    await db.commit()
    await db.refresh(b)

    return BankrollOut(
        bankroll_id=b.bankroll_id,
        nom=b.nom,
        discipline=b.discipline,
        montant_initial=b.montant_initial,
        est_principale=b.est_principale,
        couleur=b.couleur,
        solde_actuel=b.montant_initial,
        nb_entrees=0,
        created_at=b.created_at,
    )


@router.put("/bankroll/portefeuilles/{bankroll_id}", response_model=BankrollOut)
async def update_portefeuille(
    bankroll_id: str,
    body: BankrollUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    res = await db.execute(
        select(Bankroll).where(
            and_(
                Bankroll.bankroll_id == bankroll_id,
                Bankroll.user_id == user.user_id,
                Bankroll.est_supprime == False,
            )
        )
    )
    b = res.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Portefeuille introuvable")

    for k, v in body.model_dump(exclude_none=True).items():
        setattr(b, k, v)
    await db.commit()
    await db.refresh(b)

    res_agg = await db.execute(
        select(
            func.count(BankrollEntry.entry_id),
            func.coalesce(func.sum(BankrollEntry.gain_perte), 0.0),
        ).where(BankrollEntry.bankroll_id == b.bankroll_id)
    )
    row = res_agg.one()
    return BankrollOut(
        bankroll_id=b.bankroll_id,
        nom=b.nom,
        discipline=b.discipline,
        montant_initial=b.montant_initial,
        est_principale=b.est_principale,
        couleur=b.couleur,
        solde_actuel=round(b.montant_initial + float(row[1]), 2),
        nb_entrees=row[0],
        created_at=b.created_at,
    )


@router.delete("/bankroll/portefeuilles/{bankroll_id}", status_code=204)
async def delete_portefeuille(
    bankroll_id: str,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Soft delete — conserve les entrées."""
    res = await db.execute(
        select(Bankroll).where(
            and_(
                Bankroll.bankroll_id == bankroll_id,
                Bankroll.user_id == user.user_id,
                Bankroll.est_supprime == False,
            )
        )
    )
    b = res.scalar_one_or_none()
    if not b:
        raise HTTPException(status_code=404, detail="Portefeuille introuvable")
    b.est_supprime = True
    if b.est_principale:
        b.est_principale = False
    await db.commit()
