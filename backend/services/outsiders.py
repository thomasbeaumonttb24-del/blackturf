"""Outsiders du jour : registre, lecture et bilan (cerveau `ml.outsider_brain`).

- `rafraichir_signaux` (tâche planifiée) : score les partants cotés des courses
  à venir et tient le registre `outsider_signaux`. Un signal se FIGE à T-10 min
  (même gel que le pronostic) : après, plus rien ne le modifie. Le bilan se lit
  donc sur ce qui était réellement affiché, jamais sur un recalcul après coup.
- `lister` : les outsiders d'une journée ou d'une course, avec leur résultat.
- `bilan` : taux de réussite réel et plus beaux rapports sur N jours.

Repartir de zéro (07/10/2026) : seuls les signaux portant une fiche d'analyse
(cerveau génération 2) sont lus. Ceux de la génération 1 restent en base,
hors du site et du bilan.
"""
from __future__ import annotations

import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="outsiders")

PARIS = ZoneInfo("Europe/Paris")
GEL_MIN = 10   # cf. api.routes.predictions.PRONO_LOCK_MIN


def code_course(numero_reunion, numero, course_id: str) -> str:
    if numero_reunion and numero:
        return f"R{numero_reunion}C{numero}"
    return course_id[8:] if len(course_id) > 8 and "R" in course_id[8:] else course_id


# ──────────────────────────────────────────────────────────────────────────────
# Registre
# ──────────────────────────────────────────────────────────────────────────────

async def rafraichir_signaux(session: AsyncSession, maintenant: Optional[datetime] = None) -> dict:
    """Score les courses ouvertes du jour et met le registre à jour (avant le gel)."""
    from ml import outsider_brain as ob

    art = ob.en_service()
    if art is None or art.get("version", 1) < ob.VERSION:
        return {"status": "sans_modele"}
    now = maintenant or datetime.now(timezone.utc)
    debut_jour = datetime.combine(now.astimezone(PARIS).date(), datetime.min.time(), PARIS)
    rows = (await session.execute(text("""
        SELECT course_id FROM courses
        WHERE statut IN ('a_venir', 'en_cours')
          AND date_heure >= :gel AND date_heure < :fin
    """), {"gel": now + timedelta(minutes=GEL_MIN), "fin": debut_jour + timedelta(days=1)})).all()
    cids = [r[0] for r in rows]
    if not cids:
        return {"status": "ok", "courses": 0, "signaux": 0}

    brut = await ob.charger_snapshots(session, course_ids=cids)
    retenus = []
    if not brut.empty:
        brut = brut[brut["partants"] >= 4]
        if not brut.empty:
            d = ob.preparer(brut)
            retenus = ob.selection(ob.scorer(d, art)).to_dict("records")

    # Courses encore ouvertes : on désactive puis on réactive ce qui est retenu.
    await session.execute(text("""
        UPDATE outsider_signaux SET actif = false, maj_at = now()
        WHERE course_id = ANY(:cids) AND actif
    """), {"cids": cids})
    for r in retenus:
        await session.execute(text("""
            INSERT INTO outsider_signaux (participation_id, course_id, numero, chance_place,
                cote_signal, niveau, places_payees, raisons, analyse, modele_entraine_le, actif)
            VALUES (:pid, :cid, :num, :chance, :cote, :niveau, :places, CAST(:raisons AS jsonb),
                    CAST(:analyse AS jsonb), :ent, true)
            ON CONFLICT (participation_id) DO UPDATE SET
                chance_place = EXCLUDED.chance_place, cote_signal = EXCLUDED.cote_signal,
                niveau = EXCLUDED.niveau, places_payees = EXCLUDED.places_payees,
                raisons = EXCLUDED.raisons, analyse = EXCLUDED.analyse, modele_entraine_le = EXCLUDED.modele_entraine_le,
                actif = true, maj_at = now()
        """), {"pid": r["participation_id"], "cid": r["course_id"], "num": int(r["numero"]),
               "chance": round(float(r["chance"]), 4), "cote": float(r["cote_figee"]),
               "niveau": r["niveau"], "places": int(r["places"]),
               "raisons": json.dumps(list(r["raisons"]), ensure_ascii=False),
               "analyse": json.dumps(r.get("analyse") or {}, ensure_ascii=False, default=float),
               "ent": art.get("entraine_le")})
    await session.commit()
    return {"status": "ok", "courses": len(cids), "signaux": len(retenus)}


# ──────────────────────────────────────────────────────────────────────────────
# Lecture
# ──────────────────────────────────────────────────────────────────────────────

def _rapport_place(rapports_detail, numero: int) -> Optional[float]:
    from services.bet_settlement import _RAPPORT_KEYS, _place_rapport_exact
    if isinstance(rapports_detail, str):
        try:
            rapports_detail = json.loads(rapports_detail)
        except ValueError:
            return None
    if not isinstance(rapports_detail, dict):
        return None
    return _place_rapport_exact(rapports_detail, _RAPPORT_KEYS["Simple Placé"], [numero])


def _position(classement, numero: int) -> Optional[int]:
    if isinstance(classement, str):
        try:
            classement = json.loads(classement)
        except ValueError:
            return None
    for e in classement or []:
        try:
            if int(e.get("numero")) == int(numero):
                pos = e.get("position")
                return int(pos) if pos not in (None, "") and str(pos).isdigit() else None
        except (TypeError, ValueError):
            continue
    return None


_SQL_LISTE = """
SELECT o.participation_id, o.course_id, o.numero, o.chance_place, o.cote_signal, o.niveau,
       o.places_payees, o.raisons, o.analyse, o.premier_signal_at,
       c.date_heure, c.hippodrome_nom, c.discipline, c.numero_reunion, c.numero AS numero_course,
       c.nom AS nom_course, c.statut, c.est_quinte,
       ch.nom AS nom_cheval, p.cote_pmu, p.non_partant, p.casaque_image_url, j.nom AS nom_jockey,
       r.classement, r.rapports_detail
FROM outsider_signaux o
JOIN courses c ON c.course_id = o.course_id
JOIN participations p ON p.participation_id = o.participation_id
JOIN chevaux ch ON ch.cheval_id = p.cheval_id
LEFT JOIN jockeys j ON j.jockey_id = p.jockey_id
LEFT JOIN resultats r ON r.course_id = o.course_id
WHERE o.actif AND o.analyse <> '{{}}'::jsonb AND {filtre}
ORDER BY c.date_heure, o.chance_place DESC
"""


def _ligne(r) -> dict:
    position = _position(r["classement"], r["numero"]) if r["classement"] else None
    termine = bool(r["classement"]) and r["statut"] == "termine"
    place = bool(position and position <= r["places_payees"])
    rap_sp = _rapport_place(r["rapports_detail"], r["numero"]) if place else None
    cote_finale = r["cote_pmu"]
    return {
        "course_id": r["course_id"],
        "code": code_course(r["numero_reunion"], r["numero_course"], r["course_id"]),
        "hippodrome": r["hippodrome_nom"],
        "discipline": r["discipline"],
        "date_heure": r["date_heure"].isoformat() if r["date_heure"] else None,
        "est_quinte": bool(r["est_quinte"]),
        "numero": r["numero"],
        "nom_cheval": r["nom_cheval"],
        "casaque_image_url": r["casaque_image_url"],
        "jockey": r["nom_jockey"],
        "cote_signal": round(float(r["cote_signal"]), 1),
        "cote_actuelle": round(float(cote_finale), 1) if cote_finale else None,
        "chance_place": round(float(r["chance_place"]), 3),
        "niveau": r["niveau"],
        "places_payees": r["places_payees"],
        "raisons": r["raisons"] if isinstance(r["raisons"], list) else json.loads(r["raisons"] or "[]"),
        "analyse": r["analyse"] if isinstance(r["analyse"], dict) else json.loads(r["analyse"] or "{}"),
        "non_partant": bool(r["non_partant"]),
        "termine": termine,
        "position": position,
        "place": place if termine else None,
        "gagne": (position == 1) if termine else None,
        "rapport_place": rap_sp,
        "rapport_gagnant": round(float(cote_finale), 1) if termine and position == 1 and cote_finale else None,
    }


async def lister(session: AsyncSession, *, jour: Optional[date] = None,
                 course_id: Optional[str] = None) -> list[dict]:
    if course_id:
        filtre, params = "o.course_id = :cid", {"cid": course_id}
    else:
        j = jour or datetime.now(PARIS).date()
        debut = datetime.combine(j, datetime.min.time(), PARIS)
        filtre, params = "c.date_heure >= :d AND c.date_heure < :f", {"d": debut, "f": debut + timedelta(days=1)}
    rows = (await session.execute(text(_SQL_LISTE.format(filtre=filtre)), params)).mappings().all()
    return [_ligne(r) for r in rows]


async def bilan(session: AsyncSession, jours: int = 30) -> dict:
    """Réussite réelle des outsiders affichés (figés à T-10) sur les courses terminées."""
    debut = datetime.now(timezone.utc) - timedelta(days=jours)
    rows = (await session.execute(text(_SQL_LISTE.format(
        filtre="c.date_heure >= :d AND c.statut = 'termine' AND r.classement IS NOT NULL")),
        {"d": debut})).mappings().all()
    lignes = [l for l in (_ligne(r) for r in rows) if l["termine"] and not l["non_partant"]]
    n = len(lignes)
    places = [l for l in lignes if l["place"]]
    gagnes = [l for l in lignes if l["gagne"]]
    # Rendement au Simple Placé 1 € (rapport PMU publié ; placé sans rapport publié = 1 €).
    retour_sp = sum((l["rapport_place"] or 1.0) for l in places)
    par_niveau = {}
    for niv in ("fort", "a_suivre"):
        ls = [l for l in lignes if l["niveau"] == niv]
        par_niveau[niv] = {"n": len(ls), "places": sum(1 for l in ls if l["place"]),
                           "taux_place": round(sum(1 for l in ls if l["place"]) / len(ls), 3) if ls else None}
    beaux = sorted(places, key=lambda l: (l["rapport_gagnant"] or 0, l["rapport_place"] or 0), reverse=True)[:8]
    return {
        "jours": jours,
        "n": n,
        "places": len(places),
        "gagnes": len(gagnes),
        "taux_place": round(len(places) / n, 3) if n else None,
        "rendement_simple_place": round(retour_sp / n - 1, 3) if n else None,
        "par_niveau": par_niveau,
        "plus_beaux": beaux,
    }


def validation_modele() -> Optional[dict]:
    """Chiffres de validation du cerveau en service (jours jamais vus)."""
    from ml import outsider_brain as ob
    art = ob.en_service()
    if not art:
        return None
    v = dict(art.get("validation") or {})
    v["entraine_le"] = art.get("entraine_le")
    return v
