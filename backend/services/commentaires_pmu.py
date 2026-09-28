"""
Commentaires post-course du PMU : les relire APRÈS la course, avant qu'ils ne
disparaissent.

Le déroulé de chaque partant (« Postée dans le sillage de l'animatrice… ») est
publié par /participants sous `commentaireApresCourse`, mais :
  • PAS au moment de l'arrivée : le résultat est lu dès l'ordre officiel, le
    commentaire vient plus tard. Le 24/09/2026, 25 résultats sur 55 l'avaient, et
    `historique_courses.commentaire_course` en avait 0 sur 48 826 lignes (60 jours) —
    le post-course écrit l'historique une seule fois, à l'arrivée ;
  • pour 30 jours seulement : relevé le 25/09/2026, rien avant le 26/08, tout à
    partir du 26/08 (R1 C1-C6 des deux dates). Un jour non relu est perdu.

Ce module relit donc les courses déjà courues d'une fenêtre, et complète — sans
jamais écraser — l'historique des chevaux (source des features `commentaire_*`)
et le classement stocké dans `resultats`.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger()

# Rétention observée des commentaires côté PMU (cf. docstring).
RETENTION_PMU_JOURS = 30

_COURSE_ID = re.compile(r"^(\d{8})R(\d+)C(\d+)$")


def decouper_course_id(course_id: str) -> Optional[tuple[str, str, int]]:
    """`25092026R1C8` → ("25092026", "1", 8) ; None si le format ne suit pas."""
    m = _COURSE_ID.match(course_id or "")
    if not m:
        return None
    return m.group(1), m.group(2), int(m.group(3))


def commentaires_par_numero(participants) -> dict[int, str]:
    """{numPmu: commentaire} depuis une réponse /participants (liste ou dict)."""
    from scraper.sources.pmu import _extract_commentaire
    ps = participants if isinstance(participants, list) else (participants or {}).get("participants", [])
    out: dict[int, str] = {}
    for p in ps or []:
        num = p.get("numPmu")
        texte = _extract_commentaire({}, p)
        if isinstance(num, int) and texte:
            out[num] = texte[:1000]
    return out


def completer_classement(classement: list, commentaires: dict[int, str]) -> tuple[list, int]:
    """Ajoute le commentaire aux entrées qui n'en ont pas. Ne remplace rien."""
    n = 0
    nouveau = []
    for e in classement or []:
        e = dict(e)
        if not e.get("commentaire") and commentaires.get(e.get("numero")):
            e["commentaire"] = commentaires[e["numero"]]
            n += 1
        nouveau.append(e)
    return nouveau, n


async def courses_a_relire(session, depuis: date, jusqua: date) -> list[str]:
    """Courses courues de la fenêtre dont au moins un historique manque de commentaire."""
    rows = await session.execute(text("""
        SELECT c.course_id FROM courses c
        JOIN resultats r ON r.course_id = c.course_id
        WHERE c.date_heure >= :depuis AND c.date_heure < :jusqua
          AND EXISTS (SELECT 1 FROM historique_courses h
                      WHERE h.course_id = c.course_id AND h.commentaire_course IS NULL)
        ORDER BY c.date_heure
    """), {"depuis": depuis, "jusqua": jusqua + timedelta(days=1)})
    return [r[0] for r in rows.all()]


async def ecrire_commentaires(session, course_id: str, commentaires: dict[int, str]) -> dict:
    """Complète historique_courses et resultats.classement pour une course."""
    n_hist = 0
    for num, texte in commentaires.items():
        res = await session.execute(text("""
            UPDATE historique_courses h SET commentaire_course = :t
            FROM participations p
            WHERE p.course_id = :cid AND p.numero = :num
              AND h.course_id = :cid AND h.cheval_id = p.cheval_id
              AND h.commentaire_course IS NULL
        """), {"t": texte, "cid": course_id, "num": num})
        n_hist += res.rowcount or 0
    n_res = 0
    row = (await session.execute(text(
        "SELECT classement FROM resultats WHERE course_id = :cid"), {"cid": course_id})).first()
    if row and isinstance(row[0], list):
        nouveau, n_res = completer_classement(row[0], commentaires)
        if n_res:
            await session.execute(text(
                "UPDATE resultats SET classement = CAST(:c AS jsonb) WHERE course_id = :cid"),
                {"c": json.dumps(nouveau, ensure_ascii=False), "cid": course_id})
    return {"historique": n_hist, "resultats": n_res}


async def relire_commentaires(depuis: date, jusqua: date, dry_run: bool = False) -> dict:
    """Relit /participants pour chaque course à compléter de [depuis, jusqua]."""
    from db.database import AsyncSessionLocal
    from scraper.sources.pmu import BASE, PmuScraper

    async with AsyncSessionLocal() as s:
        cids = await courses_a_relire(s, depuis, jusqua)
    stats = {"courses": len(cids), "avec_commentaires": 0, "historique": 0,
             "resultats": 0, "sans_reponse": 0}
    scraper = PmuScraper()
    try:
        for cid in cids:
            parts = decouper_course_id(cid)
            if not parts:
                continue
            d, reunion, course = parts
            data = await scraper._fetch_json(
                f"{BASE}/programme/{d}/R{reunion}/C{course}/participants?specialisation=INTERNET")
            if not data:
                stats["sans_reponse"] += 1
                continue
            coms = commentaires_par_numero(data)
            if not coms:
                continue
            stats["avec_commentaires"] += 1
            if dry_run:
                continue
            async with AsyncSessionLocal() as s:
                n = await ecrire_commentaires(s, cid, coms)
                await s.commit()
            stats["historique"] += n["historique"]
            stats["resultats"] += n["resultats"]
    finally:
        await scraper.close()
    log.info("commentaires_pmu.relus", depuis=str(depuis), jusqua=str(jusqua),
             dry_run=dry_run, **stats)
    return stats
