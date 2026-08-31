"""Résolution des courses restées 'a_venir' faute de résultat PMU.

CAUSE RACINE (identifiée le 2026-08-17, 159 courses concernées en prod)
────────────────────────────────────────────────────────────────────────
`Course.statut` ne passe à 'termine' que si `save_resultat_to_db` reçoit un ordre
d'arrivée (db_writer.py). `poll_resultats` (orchestrator.py) ne repolle que sur une
fenêtre glissante de 36h ; passé ce délai la course sort du périmètre POUR TOUJOURS
et son statut reste 'a_venir' à vie.

Le diagnostic prod a levé le doute sur le « pourquoi pas de résultat » : les 159
courses bloquées (Chateaubriant 23/06, Deauville 25/06, Langon-Libourne 28/07,
Palermo ARG 01/06, Casablanca, Wolvega…) renvoient TOUTES, sur l'endpoint course
du PMU, `statut = COURSE_ANNULEE` — 159/159, sans une seule exception. Ce n'était
donc ni une panne de scraper, ni « les pistes étrangères que le PMU ne résulte
jamais » : ce sont des courses ANNULÉES (souvent une réunion entière : Chateaubriant
R3 = 8/8, Langon R2 = 8/8). Le PMU ne publie jamais d'ordreArrivee pour elles, donc
le poll ne pouvait par construction jamais les clôturer.

Le champ `statut` existe pourtant DANS le payload PMU (par course ET par réunion,
valeurs observées : PROGRAMMEE / FIN_COURSE / ARRIVEE_DEFINITIVE_COMPLETE /
COURSE_ANNULEE) : il était simplement ignoré au scrape.

CORRECTIF DURABLE — trois couches
─────────────────────────────────
1. Au scrape (pmu.py + db_writer.py) : le statut PMU est lu et `COURSE_ANNULEE`
   devient `statut='annule'` en base, immédiatement. Couvre les annulations
   décidées avant/pendant la journée de courses.
2. Dans `poll_resultats` (orchestrator.py) : pas d'arrivée → on interroge le statut
   PMU ; annulée → 'annule' tout de suite, sans attendre le balayage nocturne.
3. Ce module, appelé par `job_resolve_courses_sans_resultat` (1x/jour) : balaye la
   traîne au-delà des 36h de `poll_resultats` (défaut 10 jours en arrière). Pour
   chaque course encore ouverte : (a) arrivée publiée tardivement → on l'enregistre
   → 'termine' ; (b) PMU dit annulée → 'annule' ; (c) rien après
   `delai_abandon_jours` (défaut 4) → statut terminal `sans_resultat` + entrée dans
   `system_errors` pour que le trou soit VISIBLE au lieu d'être silencieux.

`sans_resultat` reste re-jouable : le balayage reprend ces courses tant qu'elles
sont dans la fenêtre, donc un résultat publié en retard les fera passer 'termine'.

Le filet de sécurité `job_expire_stale_value_bets` (+ les filtres
`Course.date_heure >= now() - 6h` de predictions.py / ws.py) reste EN PLACE : il
protège les 6 premières heures, bien avant que ce module n'entre en jeu.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text

log = structlog.get_logger()

# Statut PMU d'une course annulée (jamais d'ordreArrivee → jamais de résultat).
PMU_STATUT_ANNULEE = "COURSE_ANNULEE"

# Statut interne posé quand le PMU confirme l'annulation.
STATUT_ANNULE = "annule"
# Statut interne posé quand aucun résultat n'arrive et que le PMU ne dit rien
# d'exploitable : la course est abandonnée pour de bon (mais reste re-jouable).
STATUT_SANS_RESULTAT = "sans_resultat"

# Courses qui n'ont PAS été courues : à masquer partout (programme, stats…).
# Utilisé par api/routes/courses.py et api/routes/stats.py.
STATUTS_NON_COURUES: tuple[str, ...] = (STATUT_ANNULE, STATUT_SANS_RESULTAT)

# Statuts encore « ouverts » : le balayage doit les reprendre.
STATUTS_OUVERTS: tuple[str, ...] = ("a_venir", "en_cours", STATUT_SANS_RESULTAT)

# Défauts surchargeables sans redéploiement du code.
DEFAUT_DEPUIS_HEURES = int(os.getenv("BT_RESOLVE_DEPUIS_HEURES", "36"))
DEFAUT_FENETRE_JOURS = int(os.getenv("BT_RESOLVE_FENETRE_JOURS", "10"))
DEFAUT_ABANDON_JOURS = int(os.getenv("BT_RESOLVE_ABANDON_JOURS", "4"))
DEFAUT_LIMITE = int(os.getenv("BT_RESOLVE_LIMITE", "300"))


def statut_interne_depuis_pmu(statut_pmu: Optional[str]) -> Optional[str]:
    """Mappe un statut PMU vers un statut interne TERMINAL, sinon None.

    Volontairement partiel : on ne dérive PAS 'termine' du statut PMU, car
    'termine' signifie « résultat en base » pour tout l'aval (règlement des paris,
    features ML). Seule l'annulation est déduite du statut.
    """
    if statut_pmu and str(statut_pmu).strip().upper() == PMU_STATUT_ANNULEE:
        return STATUT_ANNULE
    return None


def _as_utc(dt: datetime) -> datetime:
    """Datetime toujours comparable : les naïfs sont réputés UTC.

    La colonne est TIMESTAMPTZ en Postgres (donc aware) mais naïve sous SQLite
    (tests) — sans ça un `now_aware - dt_naif` lèverait TypeError.
    """
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _set_statut(session, course_id: str, statut: str) -> None:
    # updated_at passé en paramètre (pas de `now()` SQL) : portable Postgres/SQLite.
    await session.execute(
        text("UPDATE courses SET statut = :s, updated_at = :u WHERE course_id = :c"),
        {"s": statut, "u": datetime.now(timezone.utc), "c": course_id},
    )


async def resolve_courses_sans_resultat(
    *,
    depuis_heures: int = DEFAUT_DEPUIS_HEURES,
    fenetre_jours: Optional[int] = DEFAUT_FENETRE_JOURS,
    delai_abandon_jours: int = DEFAUT_ABANDON_JOURS,
    limite: int = DEFAUT_LIMITE,
    dry_run: bool = False,
) -> dict:
    """Balaye les courses passées encore ouvertes et leur donne un statut terminal.

    depuis_heures       : ne touche pas aux courses plus récentes (poll_resultats les gère).
    fenetre_jours       : profondeur du balayage ; None = pas de borne (backfill).
    delai_abandon_jours : âge au-delà duquel une course sans verdict PMU passe
                          `sans_resultat`.
    limite              : nb max de courses traitées par appel (borne le nb de
                          requêtes PMU).
    dry_run             : n'écrit rien, ne fait que compter (utilisé par le script
                          de backfill pour un audit à blanc).

    Retourne un compte-rendu {scannees, terminees, annulees, sans_resultat, erreurs}.
    """
    from sqlalchemy import select
    from db.database import AsyncSessionLocal
    from db.models import Course
    from scraper.db_writer import save_resultat_to_db
    from scraper.sources.pmu import PmuScraper
    from services.error_monitor import record_error

    now = datetime.now(timezone.utc)
    # Requête en ORM (et non en SQL brut) : portable Postgres/SQLite, donc testable.
    q = (
        select(Course.course_id, Course.reunion_id, Course.date_heure,
               Course.statut, Course.hippodrome_nom)
        .where(Course.statut.in_(STATUTS_OUVERTS),
               Course.date_heure < now - timedelta(hours=depuis_heures))
        .order_by(Course.date_heure.desc())
        .limit(max(1, int(limite)))
    )
    if fenetre_jours is not None:
        q = q.where(Course.date_heure > now - timedelta(days=fenetre_jours))

    async with AsyncSessionLocal() as session:
        rows = (await session.execute(q)).all()

    cr = {"scannees": len(rows), "terminees": 0, "annulees": 0,
          "sans_resultat": 0, "erreurs": 0}
    if not rows:
        log.info("course_resolution.rien_a_faire")
        return cr

    pmu = PmuScraper()
    try:
        for row in rows:
            course_id = row.course_id
            try:
                c_num = int(str(course_id).split("C")[-1])
                prefixe = str(course_id)[:8]
                d = prefixe if prefixe.isdigit() else row.date_heure

                # 1) Un résultat publié en retard reste prioritaire sur tout le reste.
                resultat = await pmu.get_rapports_definitifs(row.reunion_id, c_num, d)
                if resultat and resultat.ordre_arrivee:
                    if not dry_run:
                        async with AsyncSessionLocal() as s:
                            await save_resultat_to_db(s, resultat)
                            await s.commit()
                    cr["terminees"] += 1
                    log.info("course_resolution.resultat_tardif", course_id=course_id)
                    continue

                # 2) Verdict explicite du PMU : course annulée → statut terminal.
                statut_pmu = await pmu.get_statut_course(row.reunion_id, c_num, d)
                statut_cible = statut_interne_depuis_pmu(statut_pmu)
                if statut_cible == STATUT_ANNULE:
                    if row.statut != STATUT_ANNULE and not dry_run:
                        async with AsyncSessionLocal() as s:
                            await _set_statut(s, course_id, STATUT_ANNULE)
                            await s.commit()
                    cr["annulees"] += 1
                    log.info("course_resolution.annulee", course_id=course_id,
                             hippodrome=row.hippodrome_nom, statut_pmu=statut_pmu)
                    continue

                # 3) Ni résultat ni verdict : on abandonne passé le délai, mais on
                #    laisse le PMU une chance tant qu'on est en dessous.
                age_jours = (now - _as_utc(row.date_heure)).total_seconds() / 86400
                if age_jours >= delai_abandon_jours:
                    if row.statut != STATUT_SANS_RESULTAT and not dry_run:
                        async with AsyncSessionLocal() as s:
                            await _set_statut(s, course_id, STATUT_SANS_RESULTAT)
                            await s.commit()
                        await record_error(
                            "course_resolution",
                            f"Course sans résultat après {age_jours:.1f} j : {course_id}",
                            detail=(f"hippodrome={row.hippodrome_nom} "
                                    f"date_heure={row.date_heure} statut_pmu={statut_pmu}"),
                            level="warning",
                        )
                    cr["sans_resultat"] += 1
                    log.warning("course_resolution.sans_resultat", course_id=course_id,
                                hippodrome=row.hippodrome_nom, age_jours=round(age_jours, 1),
                                statut_pmu=statut_pmu)
            except Exception as e:  # une course fautive n'arrête pas le balayage
                cr["erreurs"] += 1
                log.warning("course_resolution.course_failed",
                            course_id=course_id, err=str(e)[:160])
    finally:
        await pmu.close()

    log.info("course_resolution.done", dry_run=dry_run, **cr)
    return cr
