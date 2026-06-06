"""
Écrit les données scrapées dans PostgreSQL.
Gère la déduplication et les upserts.
"""
import uuid
import structlog
from typing import Optional
from datetime import datetime, date
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from db.models import (
    Course, Reunion, Participation, Cheval, Jockey, Entraineur,
    Equipement, Resultat, MeteoCourse, ScrapeLog, Hippodrome,
    CoteHistorique, PerformanceCarriere,
    # Nouvelles tables
    CoteBookmaker, PoolPMUHistorique, SuspensionProfessionnel,
    PenetrometreLog, TempsPassage, PronosticPresse,
    AssociationJockeyEntraineur, StatsJockey, StatsEntraineur,
)
from scraper.base import (
    CourseScrape, PartantScrape, ResultatScrape,
    CoteBookmakerScrape, PoolPMUScrape, SuspensionScrape,
    PenetrometreScrape, TempsPassageScrape, PronosticPresseScrape,
    GeneralogieScrape, RunningStyleScrape,
)
from scraper.validation import valid_cote, valid_penetrometre

log = structlog.get_logger()


def _t(v, n: int):
    """Tronque une chaîne à n caractères (sécurité longueur colonne). None inchangé."""
    return v[:n] if isinstance(v, str) and len(v) > n else v


async def save_historique_pmu(session: AsyncSession, cheval_nom: str, courses: list) -> int:
    """
    Sauvegarde l'historique des courses passées d'un cheval (endpoint PMU
    performances-detaillees). Alimente historique_courses → features ML +
    confrontations directes. Dédup sur (cheval_id, date, hippodrome).
    Retourne le nb de lignes ajoutées.
    """
    from db.models import HistoriqueCourse, Cheval
    from datetime import datetime as _dt

    # Trouver le cheval (doit exister depuis la sauvegarde des partants)
    r = await session.execute(select(Cheval.cheval_id).where(Cheval.nom == cheval_nom))
    row = r.first()
    if not row:
        return 0
    cheval_id = row[0]

    added = 0
    for c in courses or []:
        dms = c.get("date_ms")
        if not dms:
            continue
        d_course = _dt.fromtimestamp(dms / 1000.0).date()
        hippo = _t(c.get("hippodrome"), 100) or "?"

        # Dédup
        exist = await session.execute(text("""
            SELECT 1 FROM historique_courses
            WHERE cheval_id = :cid AND date_course = :d AND hippodrome = :h LIMIT 1
        """), {"cid": cheval_id, "d": d_course, "h": hippo})
        if exist.first():
            continue

        ecart = c.get("ecart")
        session.add(HistoriqueCourse(
            historique_id=gen_uuid(),
            cheval_id=cheval_id,
            course_id=None,                       # course externe (passée)
            date_course=d_course,
            hippodrome=hippo,
            discipline=_t(c.get("discipline"), 20) or "?",
            distance=c.get("distance") or 0,
            nb_partants=c.get("nb_partants"),
            position_arrivee=c.get("position"),
            ecart_longueurs=float(ecart) if isinstance(ecart, (int, float)) else None,
            allocation=c.get("allocation"),
            jockey_course=_t(c.get("jockey"), 100),
            reduction_km=c.get("reduction_km"),
        ))
        added += 1
    return added


def gen_uuid() -> str:
    return str(uuid.uuid4())


async def upsert_hippodrome(session: AsyncSession, nom: str) -> str:
    """Upsert hippodrome, retourne hippodrome_id."""
    code = nom.upper().replace(" ", "_")[:20]
    stmt = pg_insert(Hippodrome).values(
        hippodrome_id=gen_uuid(),
        nom=nom,
        code=code,
        pays="FR",
    ).on_conflict_do_update(
        index_elements=["code"],
        set_={"nom": nom},
    ).returning(Hippodrome.hippodrome_id)
    result = await session.execute(stmt)
    return result.scalar_one()


async def upsert_reunion(session: AsyncSession, course: CourseScrape, hippodrome_id: str) -> None:
    """Upsert réunion."""
    date_obj = date.today()
    stmt = pg_insert(Reunion).values(
        reunion_id=course.reunion_id,
        date=date_obj,
        hippodrome_id=hippodrome_id,
        hippodrome_nom=course.hippodrome,
        numero=int(course.reunion_id),
        pays="FR",
    ).on_conflict_do_nothing(index_elements=["reunion_id"])
    await session.execute(stmt)


async def upsert_jockey(session: AsyncSession, nom: str, pmu_id: str | None = None) -> str:
    """Upsert jockey, retourne jockey_id."""
    if not nom:
        return ""
    stmt = select(Jockey).where(Jockey.nom == nom)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing.jockey_id
    j = Jockey(jockey_id=gen_uuid(), nom=_t(nom, 100), pmu_id=pmu_id)
    session.add(j)
    return j.jockey_id


async def upsert_entraineur(session: AsyncSession, nom: str, pmu_id: str | None = None) -> str:
    """Upsert entraîneur, retourne entraineur_id."""
    if not nom:
        return ""
    stmt = select(Entraineur).where(Entraineur.nom == nom)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()
    if existing:
        return existing.entraineur_id
    e = Entraineur(entraineur_id=gen_uuid(), nom=_t(nom, 100), pmu_id=pmu_id)
    session.add(e)
    return e.entraineur_id


async def upsert_cheval(session: AsyncSession, partant: PartantScrape) -> str:
    """Upsert cheval, retourne cheval_id."""
    stmt = select(Cheval).where(Cheval.nom == partant.nom)
    result = await session.execute(stmt)
    existing = result.scalar_one_or_none()

    if existing:
        # Mise à jour des champs si nouvelles données
        if partant.age and not existing.age:
            existing.age = partant.age
        sx = (partant.sexe or "")[:1].upper() or None  # code court (évite overflow VARCHAR(5))
        if sx and not existing.sexe:
            existing.sexe = sx
        if partant.entraineur:
            existing.entraineur_actuel = _t(partant.entraineur, 100)
        # Généalogie : remplir si manquante (API PMU)
        if getattr(partant, "pere", None) and not existing.pere:
            existing.pere = _t(partant.pere, 100)
        if getattr(partant, "mere", None) and not existing.mere:
            existing.mere = _t(partant.mere, 100)
        if getattr(partant, "eleveur", None) and not existing.eleveur:
            existing.eleveur = _t(partant.eleveur, 100)
        if getattr(partant, "race", None) and not existing.race:
            existing.race = _t(partant.race, 40)
        if getattr(partant, "robe", None) and not existing.robe:
            existing.robe = _t(partant.robe, 30)
        existing.updated_at = datetime.now()
        # MAJ stats carrière (victoires/places/courses/gains)
        perf = await session.get(PerformanceCarriere, existing.cheval_id)
        if perf:
            if partant.nb_victoires is not None:
                perf.nb_victoires_total = partant.nb_victoires
            if partant.nb_places is not None:
                perf.nb_places_total = partant.nb_places
            if getattr(partant, "nb_courses", None) is not None:
                perf.nb_courses_total = partant.nb_courses
            if partant.gain_carriere:
                perf.gains_carriere_total = partant.gain_carriere
        return existing.cheval_id

    cheval = Cheval(
        cheval_id=gen_uuid(),
        nom=_t(partant.nom, 100),
        age=partant.age,
        # PMU renvoie "FEMELLES"/"MALES"/"HONGRES" → code court (colonne VARCHAR(5)).
        sexe=((partant.sexe or "")[:1].upper() or None),
        entraineur_actuel=_t(partant.entraineur, 100),
        # Généalogie (API PMU participants)
        pere=_t(getattr(partant, "pere", None), 100),
        mere=_t(getattr(partant, "mere", None), 100),
        eleveur=_t(getattr(partant, "eleveur", None), 100),
        race=_t(getattr(partant, "race", None), 40),
        robe=_t(getattr(partant, "robe", None), 30),
    )
    session.add(cheval)

    # Initialiser performances_carriere
    perf = PerformanceCarriere(
        cheval_id=cheval.cheval_id,
        gains_carriere_total=partant.gain_carriere or 0,
        nb_courses_total=getattr(partant, "nb_courses", None) or 0,
        nb_victoires_total=partant.nb_victoires or 0,
        nb_places_total=partant.nb_places or 0,
    )
    session.add(perf)

    return cheval.cheval_id


async def save_course_to_db(session: AsyncSession, course: CourseScrape) -> None:
    """
    Sauvegarde une course et ses partants en DB.
    Upsert complet : hippodrome → réunion → course → chevaux → participations → équipements.
    """
    log.info("db_writer.save_course", course_id=course.course_id, partants=len(course.partants))

    # Hippodrome
    hippodrome_id = await upsert_hippodrome(session, course.hippodrome)

    # Réunion
    await upsert_reunion(session, course, hippodrome_id)

    # Heure de départ
    date_heure = _parse_datetime(course.date_heure)

    # Course (upsert)
    stmt = pg_insert(Course).values(
        course_id=course.course_id,
        reunion_id=course.reunion_id,
        numero=int(course.course_id.split("C")[-1]) if "C" in course.course_id else 1,
        nom=_t(course.nom, 200),
        date_heure=date_heure,
        hippodrome_nom=_t(course.hippodrome, 100),
        discipline=_t(course.discipline, 20),
        distance=course.distance,
        terrain_officiel=_t(course.terrain, 30),
        terrain_code=course.terrain_code,
        corde=_t(course.corde, 15),
        nb_partants=course.nb_partants,
        allocation=course.dotation,
        niveau_course=_t(course.niveau_course, 30),
        type_depart=_t(course.type_depart, 5),
        est_quinte=course.est_quinte,
        est_quarte=course.est_quarte,
        est_tierce=course.est_tierce,
        # ── Enrichissements PMU course ──
        conditions_texte=course.conditions_texte,
        categorie_particularite=_t(course.categorie_particularite, 30),
        montant_offert_1er=course.montant_offert_1er,
        nombre_declares_partants=course.nombre_declares_partants,
        statut="a_venir",
    ).on_conflict_do_update(
        index_elements=["course_id"],
        set_={
            "terrain_officiel": course.terrain,
            "terrain_code": course.terrain_code,
            "nb_partants": course.nb_partants,
            "allocation": course.dotation,
            "conditions_texte": course.conditions_texte,
            "categorie_particularite": _t(course.categorie_particularite, 30),
            "montant_offert_1er": course.montant_offert_1er,
            "nombre_declares_partants": course.nombre_declares_partants,
            "updated_at": datetime.now(),
        },
    )
    await session.execute(stmt)

    # Partants
    for partant in course.partants:
        cheval_id = await upsert_cheval(session, partant)
        jockey_id = await upsert_jockey(session, partant.jockey or "")
        entraineur_id = await upsert_entraineur(session, partant.entraineur or "")

        participation_id = gen_uuid()
        stmt = pg_insert(Participation).values(
            participation_id=participation_id,
            course_id=course.course_id,
            cheval_id=cheval_id,
            jockey_id=jockey_id or None,
            entraineur_id=entraineur_id or None,
            numero=partant.numero,
            poids_porte=partant.poids,
            decharge=partant.decharge,
            valeur_indice=partant.valeur_indice,
            retard_gains=partant.retard_gains,
            cote_pmu=partant.cote_pmu,
            cote_geny=partant.cote_geny,
            cote_bzh=partant.cote_bzh,
            rang_pronostic_pmu=partant.rang_pronostic_pmu,
            musique=_t(partant.musique, 50),
            # ── Enrichissements PMU ──
            cote_reference=partant.cote_reference,
            mouvement_cote_pct=partant.mouvement_cote_pct,
            tendance_cote=_t(partant.tendance_cote, 2),
            tendance_force=partant.tendance_force,
            est_favori_pmu=partant.est_favori,
            avis_entraineur=_t(partant.avis_entraineur, 20),
            nb_places_second=partant.nb_places_second,
            nb_places_troisieme=partant.nb_places_troisieme,
            handicap_distance=partant.handicap_distance,
            indicateur_inedit=partant.indicateur_inedit,
            jument_pleine=partant.jument_pleine,
            non_partant=False,
        ).on_conflict_do_update(
            constraint="uq_participation_course_numero",
            set_={
                "cote_pmu": partant.cote_pmu,
                "cote_geny": partant.cote_geny,
                "rang_pronostic_pmu": partant.rang_pronostic_pmu,
                # le mouvement de cote évolue → réactualisé à chaque cycle
                "cote_reference": partant.cote_reference,
                "mouvement_cote_pct": partant.mouvement_cote_pct,
                "tendance_cote": _t(partant.tendance_cote, 2),
                "tendance_force": partant.tendance_force,
                "est_favori_pmu": partant.est_favori,
                "avis_entraineur": _t(partant.avis_entraineur, 20),
                "nb_places_second": partant.nb_places_second,
                "nb_places_troisieme": partant.nb_places_troisieme,
                "handicap_distance": partant.handicap_distance,
                "indicateur_inedit": partant.indicateur_inedit,
                "jument_pleine": partant.jument_pleine,
                "updated_at": datetime.now(),
            },
        ).returning(Participation.participation_id)

        result = await session.execute(stmt)
        pid = result.scalar_one_or_none() or participation_id

        # Équipement
        if any([partant.deferre, partant.oeilleres, partant.plaques]):
            # Déterminer si changement vs course précédente
            await _save_equipement(session, pid, cheval_id, course.course_id, partant)

        # Cote en série temporelle
        if partant.cote_pmu:
            cote_entry = CoteHistorique(
                time=datetime.now(),
                participation_id=pid,
                source="pmu",
                cote=partant.cote_pmu,
            )
            session.add(cote_entry)

    await session.flush()
    log.info("db_writer.course_saved", course_id=course.course_id)

    # Invalider le cache Redis pour cette course (cotes ont changé)
    try:
        from db.redis_client import get_redis
        redis = await get_redis()
        await redis.delete(f"course_detail:{course.course_id}")
        await redis.delete(f"programme:{course.date_heure.date().isoformat() if hasattr(course.date_heure, 'date') else str(course.date_heure)[:10]}")
    except Exception:
        pass


async def _save_equipement(
    session: AsyncSession,
    participation_id: str,
    cheval_id: str,
    course_id: str,
    partant: PartantScrape,
) -> None:
    """Sauvegarde l'équipement et détecte les changements."""
    # Chercher équipement de la course précédente
    from sqlalchemy import text
    prev = await session.execute(text("""
        SELECT e.deferre, e.oeilleres
        FROM equipements e
        JOIN participations p ON e.participation_id = p.participation_id
        JOIN courses c ON p.course_id = c.course_id
        WHERE p.cheval_id = :cheval_id
        ORDER BY c.date_heure DESC
        LIMIT 1
    """), {"cheval_id": cheval_id})
    prev_row = prev.fetchone()

    deferre_change = False
    oeilleres_change = False
    premier_deferre = False
    premieres_oeilleres = False

    if prev_row:
        prev_deferre, prev_oeilleres = prev_row
        if partant.deferre and partant.deferre != prev_deferre:
            deferre_change = True
            if prev_deferre in (None, "Aucun", "") and partant.deferre not in (None, "Aucun", ""):
                premier_deferre = True
        if partant.oeilleres and partant.oeilleres != prev_oeilleres:
            oeilleres_change = True
            if prev_oeilleres in (None, "Sans", "") and partant.oeilleres not in (None, "Sans", ""):
                premieres_oeilleres = True

    # Upsert sur participation_id (unique) — évite la violation au re-scrape.
    vals = dict(
        deferre=_t(partant.deferre, 30),
        oeilleres=_t(partant.oeilleres, 30),
        plaques=_t(partant.plaques, 50),
        muserolle=partant.muserolle,
        langue_attachee=partant.langue_attachee,
        visiere=partant.visiere,
        blinkers=partant.blinkers,
        deferre_change=deferre_change,
        oeilleres_change=oeilleres_change,
        equipement_nouveau=deferre_change or oeilleres_change,
        premier_deferre=premier_deferre,
        premieres_oeilleres=premieres_oeilleres,
    )
    stmt = pg_insert(Equipement).values(
        equipement_id=gen_uuid(),
        participation_id=participation_id,
        cheval_id=cheval_id,
        course_id=course_id,
        **vals,
    ).on_conflict_do_update(index_elements=["participation_id"], set_=vals)
    await session.execute(stmt)


async def save_resultat_to_db(session: AsyncSession, resultat: ResultatScrape) -> None:
    """Sauvegarde le résultat d'une course."""
    stmt = pg_insert(Resultat).values(
        course_id=resultat.course_id,
        classement=resultat.ordre_arrivee,
        rapports=resultat.rapports,
        temps_gagnant=resultat.temps_gagnant,
        incidents=resultat.incidents,
        commentaire=getattr(resultat, "commentaire", None),
        duree_course=getattr(resultat, "duree_course", None),
    ).on_conflict_do_update(
        index_elements=["course_id"],
        set_={
            "classement": resultat.ordre_arrivee,
            "rapports": resultat.rapports,
            "commentaire": getattr(resultat, "commentaire", None),
            "duree_course": getattr(resultat, "duree_course", None),
        },
    )
    await session.execute(stmt)

    # Marquer la course comme terminée
    await session.execute(
        update(Course)
        .where(Course.course_id == resultat.course_id)
        .values(statut="termine", updated_at=datetime.now())
    )


async def save_meteo_to_db(session: AsyncSession, course_id: str, meteo: dict) -> None:
    """Sauvegarde la météo d'une course."""
    stmt = pg_insert(MeteoCourse).values(
        course_id=course_id,
        temperature=meteo.get("temperature"),
        vent_vitesse=meteo.get("vent_vitesse"),
        vent_direction=meteo.get("vent_direction"),
        pluie_24h=meteo.get("pluie_24h"),
        humidite=meteo.get("humidite"),
        pression=meteo.get("pression"),
        visibilite=meteo.get("visibilite"),
    ).on_conflict_do_update(
        index_elements=["course_id"],
        set_={
            "temperature": meteo.get("temperature"),
            "vent_vitesse": meteo.get("vent_vitesse"),
            "pluie_24h": meteo.get("pluie_24h"),
            "updated_at": datetime.now(),
        },
    )
    await session.execute(stmt)


async def log_scrape_result(
    session: AsyncSession,
    source: str,
    statut: str,
    nb_courses: int = 0,
    nb_partants: int = 0,
    erreur: str | None = None,
    duree_ms: int | None = None,
) -> None:
    entry = ScrapeLog(
        log_id=gen_uuid(),
        source=source,
        statut=statut,
        nb_courses=nb_courses,
        nb_partants=nb_partants,
        erreur=erreur,
        duree_ms=duree_ms,
    )
    session.add(entry)
    await session.flush()


async def save_cote_bookmaker(
    session: AsyncSession,
    cote_scrape: CoteBookmakerScrape,
    participation_id: str,
    course_id: str,
) -> None:
    """Sauvegarde une cote bookmaker alternatif + met à jour le champ dénormalisé sur Participation."""
    # Garde-fou intégrité : cote aberrante (parse erroné) → on n'écrit RIEN.
    cote = valid_cote(cote_scrape.cote)
    if cote is None:
        log.warning("db_writer.cote_aberrante_ignoree",
                    source=cote_scrape.source, valeur=cote_scrape.cote,
                    participation_id=participation_id)
        return

    # Timeseries (comme CoteHistorique)
    entry = CoteBookmaker(
        id=gen_uuid(),
        participation_id=participation_id,
        course_id=course_id,
        source=cote_scrape.source,
        cote=cote,
        est_cote_ouverture=cote_scrape.est_cote_ouverture,
    )
    session.add(entry)

    # Mettre à jour le champ dénormalisé sur Participation pour accès rapide
    if not cote_scrape.est_cote_ouverture:
        col_map = {
            "winamax": Participation.cote_winamax,
            "betclic": Participation.cote_betclic,
            "unibet": Participation.cote_unibet,
            "betfair": Participation.cote_betfair_exchange,
        }
        col = col_map.get(cote_scrape.source)
        if col is not None:
            await session.execute(
                update(Participation)
                .where(Participation.participation_id == participation_id)
                .values({col.key: cote, "updated_at": datetime.now()})
            )
    elif cote_scrape.source == "betclic":
        # Cote d'ouverture Betclic uniquement
        await session.execute(
            update(Participation)
            .where(Participation.participation_id == participation_id)
            .values(cote_betclic_ouverture=cote, updated_at=datetime.now())
        )

    # Aussi dans CoteHistorique pour homogénéité timeseries
    cote_hist = CoteHistorique(
        time=datetime.now(),
        participation_id=participation_id,
        source=cote_scrape.source,
        cote=cote,
    )
    session.add(cote_hist)


async def save_pool_pmu(session: AsyncSession, pool: PoolPMUScrape) -> None:
    """Sauvegarde un snapshot du pool PMU + met à jour le champ dénormalisé sur Course."""
    entry = PoolPMUHistorique(
        id=gen_uuid(),
        course_id=pool.course_id,
        pool_total_centimes=pool.pool_total,
        pool_gagnant_centimes=pool.pool_gagnant,
        pool_place_centimes=pool.pool_place,
        nb_parieurs=pool.nb_parieurs,
    )
    session.add(entry)

    # Mettre à jour Course pour accès rapide au dernier pool
    await session.execute(
        update(Course)
        .where(Course.course_id == pool.course_id)
        .values(
            pool_total_centimes=pool.pool_total,
            pool_gagnant_centimes=pool.pool_gagnant,
            pool_gagnant_evolution=pool.gagnant_evolution,
            updated_at=datetime.now(),
        )
    )


async def save_suspension(session: AsyncSession, susp: SuspensionScrape) -> None:
    """
    Upsert une suspension officielle.
    Désactive les suspensions expirées automatiquement.
    """
    from datetime import date as date_type
    date_debut = _parse_date(susp.date_debut)
    date_fin = _parse_date(susp.date_fin) if susp.date_fin else None

    stmt = pg_insert(SuspensionProfessionnel).values(
        suspension_id=gen_uuid(),
        nom=susp.nom,
        type_pro=susp.type_pro,
        source=susp.source,
        date_debut=date_debut,
        date_fin=date_fin,
        nb_jours=susp.nb_jours,
        motif=susp.motif,
        est_active=(date_fin is None or date_fin >= date_type.today()),
    ).on_conflict_do_update(
        constraint="uq_suspension_nom_source_date",
        set_={
            "date_fin": date_fin,
            "nb_jours": susp.nb_jours,
            "motif": susp.motif,
            "est_active": (date_fin is None or date_fin >= date_type.today()),
            "updated_at": datetime.now(),
        },
    )
    await session.execute(stmt)


async def save_penetrometre(session: AsyncSession, pen: PenetrometreScrape) -> None:
    """
    Upsert le pénétromètre d'une réunion + met à jour les courses de cette réunion.
    """
    # Garde-fou : coefficient hors échelle 0–9 → NULL (jamais stocker un faux).
    coef = valid_penetrometre(pen.coefficient)
    if coef is None and pen.coefficient is not None:
        log.warning("db_writer.penetrometre_aberrant_ignore",
                    reunion_id=pen.reunion_id, valeur=pen.coefficient)

    # Sauvegarder dans le log
    stmt = pg_insert(PenetrometreLog).values(
        id=gen_uuid(),
        reunion_id=pen.reunion_id,
        hippodrome=pen.hippodrome,
        date_mesure=_parse_date(pen.date),
        coefficient=coef,
        description=pen.description,
        heure_mesure=pen.heure_mesure,
    ).on_conflict_do_update(
        constraint="uq_penetrometre_reunion",
        set_={
            "coefficient": coef,
            "description": pen.description,
        },
    )
    await session.execute(stmt)

    # Propager sur toutes les courses de cette réunion
    if pen.reunion_id:
        await session.execute(
            update(Course)
            .where(Course.reunion_id == pen.reunion_id)
            .values(
                penetrometre_coef=pen.coefficient,
                penetrometre_desc=pen.description,
                updated_at=datetime.now(),
            )
        )


async def save_temps_passage(session: AsyncSession, tp: TempsPassageScrape) -> None:
    """Upsert les temps de passage d'un partant."""
    stmt = pg_insert(TempsPassage).values(
        id=gen_uuid(),
        course_id=tp.course_id,
        numero=tp.numero,
        nom_cheval=tp.nom,
        passage_400m=tp.passage_400m,
        passage_800m=tp.passage_800m,
        passage_1000m=tp.passage_1000m,
        passage_1600m=tp.passage_1600m,
        passage_dernier_400m=tp.passage_dernier_400m,
        vitesse_max_kmh=tp.vitesse_max_kmh,
    ).on_conflict_do_update(
        constraint="uq_temps_passage_course_numero",
        set_={
            "passage_400m": tp.passage_400m,
            "passage_800m": tp.passage_800m,
            "passage_1000m": tp.passage_1000m,
            "passage_1600m": tp.passage_1600m,
            "passage_dernier_400m": tp.passage_dernier_400m,
            "vitesse_max_kmh": tp.vitesse_max_kmh,
        },
    )
    await session.execute(stmt)


async def save_pronostic_presse(
    session: AsyncSession,
    prono: PronosticPresseScrape,
    course_id: str,  # course_id PMU résolu
) -> None:
    """Upsert un pronostic de presse pour une course."""
    stmt = pg_insert(PronosticPresse).values(
        id=gen_uuid(),
        course_id=course_id,
        source=prono.source,
        journaliste=prono.journaliste,
        selection=prono.selection,
        commentaire=prono.commentaire,
    ).on_conflict_do_update(
        constraint="uq_pronostic_course_source_journaliste",
        set_={
            "selection": prono.selection,
            "commentaire": prono.commentaire,
            "scraped_at": datetime.now(),
        },
    )
    await session.execute(stmt)


async def save_genealogie(session: AsyncSession, gen: GeneralogieScrape) -> None:
    """Met à jour la généalogie d'un cheval existant."""
    await session.execute(
        update(Cheval)
        .where(Cheval.nom == gen.cheval_nom)
        .values(
            **{k: v for k, v in {
                "pere": gen.pere,
                "mere": gen.mere,
                "pere_de_mere": gen.pere_de_mere,
                "mere_de_mere": gen.mere_de_mere,
                "eleveur": gen.eleveur,
                "pays_naissance": gen.pays_naissance,
                "prix_vente_yearling": gen.prix_vente_yearling,
                "updated_at": datetime.now(),
            }.items() if v is not None}
        )
    )
    # Si code_sire fourni, l'enregistrer aussi
    if gen.code_sire:
        await session.execute(
            update(Cheval)
            .where(Cheval.nom == gen.cheval_nom)
            .values(code_sire=gen.code_sire)
        )


async def save_running_style(session: AsyncSession, rs: RunningStyleScrape) -> None:
    """Met à jour le style de course d'un cheval."""
    await session.execute(
        update(Cheval)
        .where(Cheval.nom == rs.cheval_nom)
        .values(
            running_style=rs.running_style,
            taux_en_tete=rs.taux_en_tete,
            updated_at=datetime.now(),
        )
    )


async def compute_and_save_jockey_entraineur_assoc(
    session: AsyncSession, saison: int
) -> None:
    """
    Calcule et sauvegarde les stats d'association jockey × entraîneur depuis les données existantes.
    Lance une requête d'agrégation sur participations + résultats.
    """
    from sqlalchemy import text
    result = await session.execute(text("""
        WITH stats AS (
            SELECT
                p.jockey_id,
                p.entraineur_id,
                COUNT(*) AS nb_courses,
                SUM(CASE WHEN r.position_finale = 1 THEN 1 ELSE 0 END) AS nb_victoires,
                SUM(CASE WHEN r.position_finale <= 3 THEN 1 ELSE 0 END) AS nb_places
            FROM participations p
            JOIN courses c ON p.course_id = c.course_id
            LEFT JOIN (
                -- Vraie position d'arrivée : on cherche l'entrée du cheval (par numéro)
                -- dans le tableau JSON du classement et on lit sa position.
                SELECT p2.participation_id,
                       (SELECT (elem->>'position')::int
                        FROM jsonb_array_elements(r2.classement::jsonb) elem
                        WHERE (elem->>'numero')::int = p2.numero
                        LIMIT 1) AS position_finale
                FROM resultats r2
                JOIN participations p2 ON r2.course_id = p2.course_id
            ) r ON r.participation_id = p.participation_id
            WHERE EXTRACT(YEAR FROM c.date_heure) = :saison
              AND p.jockey_id IS NOT NULL
              AND p.entraineur_id IS NOT NULL
            GROUP BY p.jockey_id, p.entraineur_id
            HAVING COUNT(*) >= 3
        )
        SELECT
            jockey_id, entraineur_id, nb_courses, nb_victoires, nb_places,
            ROUND(nb_victoires::numeric / nb_courses, 3) AS taux_victoire,
            ROUND(nb_places::numeric / nb_courses, 3) AS taux_place
        FROM stats
    """), {"saison": saison})

    rows = result.fetchall()
    for row in rows:
        stmt = pg_insert(AssociationJockeyEntraineur).values(
            id=gen_uuid(),
            jockey_id=row.jockey_id,
            entraineur_id=row.entraineur_id,
            saison=saison,
            nb_courses=row.nb_courses,
            nb_victoires=row.nb_victoires,
            nb_places=row.nb_places,
            taux_victoire=float(row.taux_victoire or 0),
            taux_place=float(row.taux_place or 0),
        ).on_conflict_do_update(
            constraint="uq_asso_jockey_entraineur_saison",
            set_={
                "nb_courses": row.nb_courses,
                "nb_victoires": row.nb_victoires,
                "nb_places": row.nb_places,
                "taux_victoire": float(row.taux_victoire or 0),
                "taux_place": float(row.taux_place or 0),
                "updated_at": datetime.now(),
            },
        )
        await session.execute(stmt)

    log.info("db_writer.asso_jockey_entraineur", nb_paires=len(rows), saison=saison)


async def detect_jockey_change(
    session: AsyncSession,
    course_id: str,
    cheval_id: str,
    jockey_id: str,
    participation_id: str,
) -> bool:
    """
    Détecte si le jockey a changé par rapport à la dernière course du cheval.
    Retourne True si changement détecté.
    """
    from sqlalchemy import text
    result = await session.execute(text("""
        SELECT p.jockey_id
        FROM participations p
        JOIN courses c ON p.course_id = c.course_id
        WHERE p.cheval_id = :cheval_id
          AND c.date_heure < (SELECT date_heure FROM courses WHERE course_id = :course_id)
          AND p.jockey_id IS NOT NULL
        ORDER BY c.date_heure DESC
        LIMIT 1
    """), {"cheval_id": cheval_id, "course_id": course_id})

    row = result.fetchone()
    if not row:
        return False

    prev_jockey_id = row[0]
    changed = (prev_jockey_id != jockey_id)

    if changed:
        await session.execute(
            update(Participation)
            .where(Participation.participation_id == participation_id)
            .values(changement_jockey=True)
        )
    return changed


async def compute_jours_depuis_derniere(
    session: AsyncSession,
    course_id: str,
    cheval_id: str,
    participation_id: str,
) -> Optional[int]:
    """
    Calcule le nombre de jours depuis la dernière course et le sauvegarde.
    """
    from sqlalchemy import text
    result = await session.execute(text("""
        SELECT MAX(c.date_heure) AS derniere_course
        FROM participations p
        JOIN courses c ON p.course_id = c.course_id
        WHERE p.cheval_id = :cheval_id
          AND c.date_heure < (SELECT date_heure FROM courses WHERE course_id = :course_id)
          AND c.statut = 'termine'
    """), {"cheval_id": cheval_id, "course_id": course_id})

    row = result.fetchone()
    if not row or not row[0]:
        return None

    from datetime import date as date_type
    course_result = await session.execute(
        select(Course.date_heure).where(Course.course_id == course_id)
    )
    course_row = course_result.fetchone()
    if not course_row:
        return None

    jours = (course_row[0].date() - row[0].date()).days

    await session.execute(
        update(Participation)
        .where(Participation.participation_id == participation_id)
        .values(jours_depuis_derniere=jours)
    )
    return jours


async def resolve_bookmaker_course_id(
    session: AsyncSession,
    hippodrome_hint: str,
    time_hint: str,
) -> Optional[str]:
    """
    Résout un pseudo course_id bookmaker (hippodrome + heure)
    en course_id PMU réel depuis la DB.
    """
    from sqlalchemy import text
    from datetime import date as date_type
    today = date_type.today()

    result = await session.execute(text("""
        SELECT course_id
        FROM courses
        WHERE DATE(date_heure) = :today
          AND UPPER(hippodrome_nom) LIKE :hippodrome
          AND TO_CHAR(date_heure AT TIME ZONE 'Europe/Paris', 'HH24MI') = :time
        LIMIT 1
    """), {
        "today": today,
        "hippodrome": f"%{hippodrome_hint[:6].upper()}%",
        "time": time_hint[:4] if time_hint else "0000",
    })

    row = result.fetchone()
    return row[0] if row else None


def _parse_date(date_str: Optional[str]):
    """Parse string date en date Python."""
    if not date_str:
        return None
    from datetime import date as date_type
    import re
    # Formats : "01/06/2026", "2026-06-01", "1er juin 2026"
    for fmt in ("%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            pass
    return None


def _parse_datetime(dt_str: str) -> datetime:
    """Parse l'heure PMU en datetime complet."""
    if not dt_str:
        return datetime.now()
    try:
        # PMU retourne parfois un timestamp MS
        if str(dt_str).isdigit() and len(str(dt_str)) > 10:
            return datetime.fromtimestamp(int(dt_str) / 1000)
        return datetime.fromisoformat(dt_str)
    except Exception:
        return datetime.now()
