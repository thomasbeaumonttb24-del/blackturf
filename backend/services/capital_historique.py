"""
Historique de l'ancien « suivi du capital » (retiré au profit du Défi du mois).

Plus aucun pari n'y est enregistré, mais des lignes `bankroll_entries` étaient
encore en attente au moment du changement : on continue de les régler aux vrais
rapports PMU pour que l'historique (back-office, apprentissage par type de pari)
reste juste. Une fois ces lignes réglées, la fonction ne fait plus rien.
"""
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BankrollEntry


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
    from services.bet_settlement import TYPES_QUINTE, regler_ligne_quinte, settle_pari

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
        # Non-partants déclarés → paris remboursés (net 0, pas comptés perdants).
        np_rows = (await db.execute(text("""
            SELECT numero FROM participations
            WHERE course_id = :cid AND non_partant = true
        """), {"cid": cid})).all()
        non_partants = {int(x[0]) for x in np_rows if x[0] is not None}
        for e in entries:
            nums = [int(n) for n in re.findall(r"\d+", e.chevaux or "")]
            if not nums:
                continue
            if e.type_pari in TYPES_QUINTE and len(set(nums)) >= 5:
                # Ticket Quinté+ (tendu OU champ, dont celui enregistré avec le plan) :
                # réglé combinaison par combinaison aux vrais rapports, Bonus compris.
                q = regler_ligne_quinte(e.type_pari, nums, e.mise, res.classement,
                                        res.rapports, nb_part,
                                        getattr(res, "rapports_detail", None), non_partants)
                if q is not None:          # None = rapport gagnant pas encore publié
                    e.resultat = q["resultat"]
                    e.gain_perte = q["gain_perte"]
                    if q["cote"] is not None:
                        e.cote = q["cote"]
                    changed = True
                continue
            r = settle_pari(e.type_pari, nums, res.classement, res.rapports, nb_part,
                            getattr(res, "rapports_detail", None), non_partants)
            if r.get("rembourse"):
                # Cheval non-partant : mise rendue → net nul, jamais compté perdant.
                e.gain_perte = 0.0
                e.cote = 1.0
                e.resultat = "rembourse"
                changed = True
            elif r["gagne"]:
                if r["rapport_reel"] is not None:
                    # gain_mult < 1 sur formules combinées (ex. 2sur4 4 chevaux =
                    # 6 combinaisons, seules les gagnantes paient).
                    gain_brut = round(e.mise * r["rapport_reel"] * r.get("gain_mult", 1.0), 2)
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
