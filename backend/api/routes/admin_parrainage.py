"""Suivi du parrainage — console d'administration.

Répond à : qui parraine qui, combien chaque compte a amené de filleuls, où en
est chaque parrainage, ce que le programme coûte (remises + crédits) et ce qu'il
rapporte (paiements encaissés auprès des filleuls), et ce qui ressemble à de la
triche (parrainages refusés, remboursements).

Lecture seule. Les e-mails sont affichés : la console est réservée à l'exploitant.
"""
from collections import defaultdict
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from api.routes.auth import require_admin
from db.database import get_db
from db.models import Parrainage, SubscriptionEvent, User
from services import parrainage as P

router = APIRouter()

# Motif technique → libellé lisible pour l'exploitant.
MOTIFS = {
    "carte_du_parrain": "Le filleul a payé avec la carte du parrain (auto-parrainage)",
    "carte_autre_compte": "Carte déjà utilisée sur un autre compte (ancien client)",
    "parrain_inactif": "Parrain désactivé ou adresse non confirmée",
    "paiement_rembourse": "Premier paiement du filleul remboursé",
    "paiement_conteste": "Premier paiement du filleul contesté (litige bancaire)",
    "plafond_atteint": "Plafond du mois atteint — crédit reporté",
    "credit_en_echec": "Stripe injoignable — crédit reposé automatiquement",
    "cartes_indisponibles": "Cartes illisibles chez Stripe — vérifié au paiement suivant",
}


def _iso(d):
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=timezone.utc)).isoformat()


@router.get("/parrainages")
async def suivi_parrainages(db: AsyncSession = Depends(get_db), _=Depends(require_admin)):
    Parrain = aliased(User)
    Filleul = aliased(User)
    lignes = (await db.execute(
        select(Parrainage, Parrain, Filleul)
        .join(Parrain, Parrain.user_id == Parrainage.parrain_id, isouter=True)
        .join(Filleul, Filleul.user_id == Parrainage.filleul_id, isouter=True)
        .order_by(Parrainage.created_at.desc())
    )).all()

    # Ce que chaque filleul a réellement payé (journal des encaissements).
    ids_filleuls = [l.filleul_id for l, _, _ in lignes if l.filleul_id]
    paye_par_filleul: dict[str, int] = {}
    if ids_filleuls:
        for uid, total in (await db.execute(
            select(SubscriptionEvent.user_id, func.coalesce(func.sum(SubscriptionEvent.montant_cents), 0))
            .where(SubscriptionEvent.type == "paiement_recu", SubscriptionEvent.user_id.in_(ids_filleuls))
            .group_by(SubscriptionEvent.user_id)
        )).all():
            paye_par_filleul[uid] = int(total or 0)

    liens = []
    parrains: dict[str, dict] = {}
    par_mois: dict[str, dict] = defaultdict(lambda: {"inscrits": 0, "valides": 0})
    for lien, parrain, filleul in lignes:
        etape = P._etape(lien, filleul, False)
        paye = paye_par_filleul.get(lien.filleul_id or "", 0)
        liens.append({
            "parrainage_id": lien.parrainage_id,
            "created_at": _iso(lien.created_at),
            "parrain": {"user_id": lien.parrain_id, "email": parrain.email if parrain else None,
                        "prenom": parrain.prenom if parrain else None, "plan": parrain.plan if parrain else None},
            "filleul": {"user_id": lien.filleul_id, "email": filleul.email if filleul else None,
                        "prenom": filleul.prenom if filleul else None, "plan": filleul.plan if filleul else None},
            "statut": lien.statut,
            "etape": etape,
            "etape_libelle": P.ETAPES_ADMIN.get(etape, etape),
            "motif": lien.motif,
            "motif_libelle": MOTIFS.get(lien.motif or "", lien.motif),
            "remise_filleul_at": _iso(lien.remise_filleul_at),
            "valide_at": _iso(lien.valide_at),
            "credit_pose_at": _iso(lien.credit_pose_at),
            "stripe_invoice_id": lien.stripe_invoice_id,
            "paye_filleul_cents": paye,
        })

        mois = (lien.created_at or datetime.now(timezone.utc)).strftime("%Y-%m")
        par_mois[mois]["inscrits"] += 1
        if lien.statut == "valide":
            par_mois[(lien.valide_at or lien.created_at).strftime("%Y-%m")]["valides"] += 1

        if not lien.parrain_id:
            continue
        p = parrains.setdefault(lien.parrain_id, {
            "user_id": lien.parrain_id,
            "email": parrain.email if parrain else None,
            "prenom": parrain.prenom if parrain else None,
            "plan": parrain.plan if parrain else None,
            "code": parrain.code_parrain if parrain else None,
            "filleuls": 0, "en_attente": 0, "valides": 0, "reportes": 0, "refuses": 0, "annules": 0,
            "gagne_cents": 0, "ca_filleuls_cents": 0, "dernier_filleul_at": None,
        })
        p["filleuls"] += 1
        p["ca_filleuls_cents"] += paye
        if lien.statut == "valide":
            p["valides"] += 1
            p["gagne_cents"] += lien.credit_cents or P.REMISE_CENTS
            if lien.credit_pose_at is None:
                p["reportes"] += 1
        elif lien.statut == "en_attente":
            p["en_attente"] += 1
        elif lien.statut == "refuse":
            p["refuses"] += 1
        elif lien.statut == "annule":
            p["annules"] += 1
        d = _iso(lien.created_at)
        if d and (p["dernier_filleul_at"] is None or d > p["dernier_filleul_at"]):
            p["dernier_filleul_at"] = d

    total = len(lignes)
    valides = sum(1 for l, _, _ in lignes if l.statut == "valide")
    remises = sum(1 for l, _, _ in lignes if l.remise_filleul_at is not None)
    reportes = sum(1 for l, _, _ in lignes if l.statut == "valide" and l.credit_pose_at is None)
    refuses = sum(1 for l, _, _ in lignes if l.statut == "refuse")
    annules = sum(1 for l, _, _ in lignes if l.statut == "annule")
    ca = sum(paye_par_filleul.values())
    cout = valides * P.REMISE_CENTS + remises * P.REMISE_CENTS

    # 6 derniers mois, du plus ancien au plus récent (mois vides compris).
    maintenant = datetime.now(timezone.utc)
    mois_liste = []
    for i in range(5, -1, -1):
        a, m = divmod(maintenant.year * 12 + maintenant.month - 1 - i, 12)
        cle = f"{a:04d}-{m + 1:02d}"
        mois_liste.append({"mois": cle, **par_mois.get(cle, {"inscrits": 0, "valides": 0})})

    comptes_codes = (await db.execute(
        select(func.count()).select_from(User).where(User.code_parrain.is_not(None))
    )).scalar_one()

    return {
        "resume": {
            "liens_generes": comptes_codes,
            "parrains_actifs": len(parrains),
            "filleuls": total,
            "en_attente": sum(1 for l, _, _ in lignes if l.statut == "en_attente"),
            "valides": valides,
            "reportes": reportes,
            "refuses": refuses,
            "annules": annules,
            "taux_conversion": round(valides / total * 100, 1) if total else None,
            "credits_parrains_cents": valides * P.REMISE_CENTS,
            "remises_filleuls_cents": remises * P.REMISE_CENTS,
            "cout_total_cents": cout,
            "ca_filleuls_cents": ca,
            "rendement": round(ca / cout, 1) if cout else None,
        },
        "parrains": sorted(parrains.values(), key=lambda p: (-p["valides"], -p["filleuls"], p["email"] or "")),
        "liens": liens,
        "evolution": mois_liste,
    }
