"""Qualité et fraîcheur des données d'entrée (Point 13 de l'audit).

Le pronostic ne vaut que ce que valent ses entrées, et une panne d'alimentation
est SILENCIEUSE : les conteneurs restent « healthy », le site répond, les
endpoints renvoient 200 — simplement, les cotes ne bougent plus. Constaté en
production : quatre journées entières (12→15/08/2026) sans la moindre course en
base, détectées seulement quatre jours plus tard ; la source `geny` à 0 % de
couverture pendant des semaines alors que son daemon tournait et publiait bien
son heartbeat.

Ce module MESURE (il n'écrit ni ne corrige aucune donnée de course) :

- fraîcheur : à quand remonte la dernière donnée réellement reçue, par source ;
- couverture : part des partants effectivement cotés, par source ;
- cotes figées : cotes dont la SOURCE n'a pas republié de valeur récente
  (`participations.cote_pmu_datetime`, migration 0033) — un scrape récent ne
  prouve pas une cote fraîche, le PMU republiant la même valeur tant que rien ne
  bouge ;
- concordance : partants annoncés vs partants réellement enregistrés, et
  arrivées incohérentes avec les partants connus ;
- courses incomplètes : à venir mais sans cote, donc non pronosticables.

Les seuils sont des choix PRODUIT documentés, pas des valeurs apprises. Un
segment sous son volume minimal est rapporté `insufficient_data` plutôt que
déclaré sain : sur trois partants, 0 % de couverture ne prouve rien.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="data_quality")

# Colonne de cote par source. `zeturf` alimente `cote_unibet` et `oddschecker`
# alimente bet365/ladbrokes/betfair : on nomme ici la DONNÉE observée, pas le
# scraper, car c'est la donnée qui manque quand une source tombe.
SOURCES_COTES: dict[str, str] = {
    "pmu": "cote_pmu",
    "geny": "cote_geny",
    "unibet": "cote_unibet",
    "bet365": "cote_bet365",
    "ladbrokes": "cote_ladbrokes",
    "betfair_exchange": "cote_betfair_exchange",
    "winamax": "cote_winamax",
    "betclic": "cote_betclic",
}

# Sources dont l'absence EMPÊCHE de pronostiquer : sans cote PMU, ni EV ni plan
# de mise ne sont calculables. Les autres enrichissent la comparaison de marché.
SOURCES_CRITIQUES = ("pmu",)

# En dessous, un taux de couverture n'est pas interprétable (une réunion à
# 6 partants ne dit rien de la santé d'une source).
MIN_PARTANTS_POUR_JUGER = 50
# Couverture attendue d'une source critique sur la fenêtre observée.
SEUIL_COUVERTURE_CRITIQUE_PCT = 80.0
# En dessous, une source d'appoint est considérée comme muette (pas « dégradée » :
# à ce niveau elle n'apporte plus rien à la comparaison de marché).
SEUIL_COUVERTURE_MUETTE_PCT = 5.0
# Au-delà, l'absence de toute mise à jour de participation signale un scraper
# mort. Mesuré sur `participations.updated_at`, réécrit à chaque cycle (quelques
# minutes) : 3 h laissent passer une interruption de maintenance sans crier, tout
# en rendant une vraie panne visible le jour même — et non au bout de 4 jours.
SEUIL_FRAICHEUR_SCRAPE_H = 3
# Une cote dont la source n'a rien republié depuis ce délai, sur une course qui
# part bientôt, est figée : le marché bouge toujours à l'approche du départ.
SEUIL_COTE_FIGEE_MIN = 45
# Fenêtre avant le départ où l'on exige des cotes fraîches.
FENETRE_AVANT_DEPART_H = 6
# En dessous, le nombre d'exécutions d'un scraper ne permet pas de conclure
# (un scraper lancé il y a dix minutes n'a pas encore fait ses preuves).
MIN_RUNS_POUR_JUGER_SCRAPER = 20


def _as_dt(valeur) -> datetime | None:
    """Normalise une colonne DateTime lue par ``text()``, en UTC.

    asyncpg (production) renvoie des ``datetime`` ; aiosqlite (tests) renvoie une
    chaîne ISO pour une requête brute non-ORM — même précédent que
    ``ml/bet_plan_performance._as_dt``.
    """
    if valeur is None:
        return None
    if isinstance(valeur, str):
        try:
            valeur = datetime.fromisoformat(valeur)
        except ValueError:
            return None
    if not isinstance(valeur, datetime):
        return None
    return valeur if valeur.tzinfo else valeur.replace(tzinfo=timezone.utc)


async def _scalar(session: AsyncSession, sql: str, params: dict | None = None):
    return (await session.execute(text(sql), params or {})).scalar()


async def couverture_sources(session: AsyncSession, jours: int = 2) -> dict:
    """Part des partants réellement cotés, par source, sur les N derniers jours."""
    colonnes = ", ".join(
        f"count(p.{col}) AS n_{nom}" for nom, col in SOURCES_COTES.items()
    )
    # Bornes calculées en Python plutôt qu'avec make_interval() : SQL portable
    # PostgreSQL/SQLite, donc les tests exercent la requête réellement exécutée
    # en production (même choix que ml/bet_plan_performance.py).
    maintenant = datetime.now(timezone.utc)
    row = (await session.execute(text(f"""
        SELECT count(*) AS n_partants, {colonnes}
        FROM participations p
        JOIN courses c ON c.course_id = p.course_id
        WHERE c.date_heure > :depuis
          AND c.date_heure <= :jusqua
          AND COALESCE(p.non_partant, false) = false
    """), {"depuis": maintenant - timedelta(days=int(jours)),
           "jusqua": maintenant})).first()

    total = int(row[0] or 0) if row else 0
    sources: dict[str, dict] = {}
    for idx, nom in enumerate(SOURCES_COTES, start=1):
        n = int(row[idx] or 0) if row else 0
        pct = round(100.0 * n / total, 1) if total else 0.0
        critique = nom in SOURCES_CRITIQUES
        if total < MIN_PARTANTS_POUR_JUGER:
            statut = "insufficient_data"
        elif critique:
            statut = "ok" if pct >= SEUIL_COUVERTURE_CRITIQUE_PCT else "degraded"
        elif pct < SEUIL_COUVERTURE_MUETTE_PCT:
            statut = "silent"
        else:
            statut = "ok"
        sources[nom] = {"n_cotes": n, "couverture_pct": pct,
                        "critique": critique, "statut": statut}
    return {"fenetre_jours": jours, "n_partants": total, "sources": sources,
            "min_partants_pour_juger": MIN_PARTANTS_POUR_JUGER}


async def fraicheur_alimentation(session: AsyncSession) -> dict:
    """Le scraper alimente-t-il encore la base ?

    Le signal de vivacité est ``participations.updated_at``, réécrit à CHAQUE
    cycle de scrape (quelques minutes). ``courses.created_at`` ne convient pas :
    le programme d'une journée est inséré une seule fois, vers minuit — à 22 h un
    système parfaitement sain affiche donc « dernière course créée il y a 22 h ».
    Ce piège a été constaté en mesurant ce module sur la production.

    On vérifie séparément qu'un PROGRAMME existe pour aujourd'hui : le scraper
    peut continuer à rafraîchir des courses passées tout en ayant cessé de
    récupérer le programme du jour.
    """
    derniere_course = await _scalar(session, "SELECT max(created_at) FROM courses")
    derniere_maj = await _scalar(
        session, "SELECT max(updated_at) FROM participations")
    derniere_cote_source = None
    try:
        derniere_cote_source = await _scalar(
            session, "SELECT max(cote_pmu_datetime) FROM participations")
    except Exception:
        await session.rollback()   # colonne absente (< migration 0033)

    maintenant = datetime.now(timezone.utc)
    debut_journee = maintenant.replace(hour=0, minute=0, second=0, microsecond=0)
    courses_du_jour = await _scalar(session, """
        SELECT count(*) FROM courses
        WHERE date_heure >= :debut AND date_heure < :fin
    """, {"debut": debut_journee, "fin": debut_journee + timedelta(days=1)})

    def _age_h(valeur) -> float | None:
        valeur = _as_dt(valeur)
        if valeur is None:
            return None
        return round((maintenant - valeur).total_seconds() / 3600.0, 2)

    age_maj_h = _age_h(derniere_maj)
    if age_maj_h is None:
        statut = "unknown"
    elif age_maj_h > SEUIL_FRAICHEUR_SCRAPE_H:
        statut = "stale"
    elif not courses_du_jour:
        # Le scraper vit (il rafraîchit des courses) mais n'a pas récupéré le
        # programme du jour : panne partielle, invisible sur le seul âge de maj.
        statut = "programme_manquant"
    else:
        statut = "ok"

    return {
        # Conservé à titre indicatif : utile au diagnostic, mais NE SERT PAS de
        # verdict (le programme n'est inséré qu'une fois par jour).
        "derniere_course_scrapee": _as_dt(derniere_course),
        "age_derniere_course_h": _age_h(derniere_course),
        "n_courses_aujourdhui": int(courses_du_jour or 0),
        # Vrai signal de vivacité : réécrit à chaque cycle de scrape.
        "derniere_participation_maj": _as_dt(derniere_maj),
        "age_derniere_participation_h": age_maj_h,
        # None tant que la migration 0033 n'a pas tourné, ou qu'aucune cote n'a
        # encore été publiée avec sa date source : jamais une valeur fabriquée.
        "derniere_cote_publiee_source": _as_dt(derniere_cote_source),
        "age_derniere_cote_source_h": _age_h(derniere_cote_source),
        "seuil_alerte_h": SEUIL_FRAICHEUR_SCRAPE_H,
        "statut": statut,
    }


async def cotes_figees(session: AsyncSession) -> dict:
    """Cotes non republiées par la source alors que le départ approche.

    Repose sur `cote_pmu_datetime` : `updated_at` ne convient pas, il date le
    scrape et reste récent même quand la source ne publie plus rien.
    """
    maintenant = datetime.now(timezone.utc)
    try:
        row = (await session.execute(text("""
            SELECT
                count(*) AS n_cotees,
                SUM(CASE WHEN p.cote_pmu_datetime < :perimee THEN 1 ELSE 0 END) AS n_figees
            FROM participations p
            JOIN courses c ON c.course_id = p.course_id
            WHERE c.date_heure >= :maintenant
              AND c.date_heure <= :horizon
              AND COALESCE(p.non_partant, false) = false
              AND p.cote_pmu_datetime IS NOT NULL
        """), {"perimee": maintenant - timedelta(minutes=SEUIL_COTE_FIGEE_MIN),
               "maintenant": maintenant,
               "horizon": maintenant + timedelta(hours=FENETRE_AVANT_DEPART_H)})).first()
    except Exception:
        await session.rollback()
        return {"mesurable": False, "raison": "colonne cote_pmu_datetime absente"}

    n_cotees = int(row[0] or 0) if row else 0
    n_figees = int(row[1] or 0) if row else 0
    return {
        "mesurable": True,
        "n_cotes_a_venir": n_cotees,
        "n_figees": n_figees,
        "pct_figees": round(100.0 * n_figees / n_cotees, 1) if n_cotees else 0.0,
        "seuil_min": SEUIL_COTE_FIGEE_MIN,
        "fenetre_h": FENETRE_AVANT_DEPART_H,
    }


async def concordance_partants(session: AsyncSession, jours: int = 2) -> dict:
    """Écarts entre ce que la source annonce et ce qui est réellement en base."""
    maintenant = datetime.now(timezone.utc)
    bornes = {"depuis": maintenant - timedelta(days=int(jours)), "jusqua": maintenant}

    # `courses.nb_partants` est le CHAMP DÉCLARÉ par la source : un cheval déclaré
    # non-partant y reste compté. On le compare donc au nombre TOTAL de lignes
    # enregistrées, non-partants inclus. Mesuré sur la production : comparer au
    # nombre de partants effectifs faisait passer l'écart de 21 à 42 courses sur
    # 85 — un faux signal qui aurait noyé les vraies incohérences de source.
    # Sous-requête corrélée plutôt que JOIN LATERAL : portable PostgreSQL/SQLite.
    ecart = (await session.execute(text("""
        SELECT count(*) AS n_courses,
               SUM(CASE WHEN c.nb_partants IS NOT NULL AND c.nb_partants <> (
                        SELECT count(*) FROM participations p
                        WHERE p.course_id = c.course_id)
                    THEN 1 ELSE 0 END) AS n_discordantes
        FROM courses c
        WHERE c.date_heure > :depuis AND c.date_heure <= :jusqua
    """), bornes)).first()

    # Arrivée citant un numéro absent des partants : incohérence de source qui
    # fausserait le règlement (un pari réglé gagnant sur un cheval inconnu).
    # Le classement est parcouru côté PYTHON : les fonctions jsonb_* sont propres
    # à PostgreSQL, et le volume ici est celui de deux jours de courses.
    lignes = (await session.execute(text("""
        SELECT r.course_id, r.classement
        FROM resultats r
        JOIN courses c ON c.course_id = r.course_id
        WHERE c.date_heure > :depuis AND c.date_heure <= :jusqua
    """), bornes)).all()

    orphelins = 0
    for course_id, classement in lignes:
        if isinstance(classement, str):
            import json as _json
            try:
                classement = _json.loads(classement)
            except (ValueError, TypeError):
                continue
        if not isinstance(classement, list):
            continue
        numeros = set()
        for entree in classement:
            if not isinstance(entree, dict) or entree.get("numero") is None:
                continue
            try:
                numeros.add(int(entree["numero"]))
            except (TypeError, ValueError):
                continue
        if not numeros:
            continue
        connus = {int(r[0]) for r in (await session.execute(text(
            "SELECT numero FROM participations WHERE course_id = :cid"),
            {"cid": course_id})).all() if r[0] is not None}
        orphelins += len(numeros - connus)

    return {
        "n_courses": int(ecart[0] or 0) if ecart else 0,
        "n_nb_partants_discordant": int(ecart[1] or 0) if ecart else 0,
        "n_arrivees_numero_inconnu": orphelins,
    }


async def courses_non_pronosticables(session: AsyncSession) -> dict:
    """Courses à venir dont aucun partant n'a de cote PMU : pas d'EV possible."""
    maintenant = datetime.now(timezone.utc)
    row = (await session.execute(text("""
        SELECT count(*) AS n_a_venir,
               SUM(CASE WHEN (
                        SELECT count(p.cote_pmu) FROM participations p
                        WHERE p.course_id = c.course_id
                          AND COALESCE(p.non_partant, false) = false) = 0
                    THEN 1 ELSE 0 END) AS n_sans_aucune_cote
        FROM courses c
        WHERE c.statut = 'a_venir'
          AND c.date_heure >= :maintenant AND c.date_heure <= :horizon
    """), {"maintenant": maintenant,
           "horizon": maintenant + timedelta(hours=FENETRE_AVANT_DEPART_H)})).first()
    return {
        "n_a_venir": int(row[0] or 0) if row else 0,
        "n_sans_aucune_cote": int(row[1] or 0) if row else 0,
        "fenetre_h": FENETRE_AVANT_DEPART_H,
    }


async def sante_scrapers(session: AsyncSession, jours: int = 2) -> dict:
    """Scrapers qui rapportent un SUCCÈS sans rien extraire.

    `scrape_log.statut='ok'` signifie « le cycle s'est terminé sans exception »,
    pas « des données ont été récupérées ». Mesuré en production : betclic, geny,
    winamax, unibet et paris_turf affichaient chacun ~242 exécutions `ok` avec
    `nb_partants = 0` — un échec total présenté comme un succès, indétectable
    depuis le back-office qui ne regardait que le statut.

    Les sources listées dans `SCRAPER_DISABLED_SOURCES` sont ignorées : leur
    silence est voulu, alerter dessus serait du bruit permanent.
    """
    import os

    desactivees = {s.strip().lower() for s in
                   os.getenv("SCRAPER_DISABLED_SOURCES", "").split(",") if s.strip()}
    maintenant = datetime.now(timezone.utc)
    # « Avec données » = au moins une course OU un partant enregistré. Se limiter
    # aux partants produirait des faux positifs sur les scrapers qui n'en
    # extraient pas par nature : `pool_pmu`, `resultats` et `paris_turf`
    # enregistrent des courses et zéro partant — ils fonctionnent parfaitement.
    lignes = (await session.execute(text("""
        SELECT source,
               count(*) AS n_runs,
               SUM(CASE WHEN statut = 'ok' THEN 1 ELSE 0 END) AS n_ok,
               SUM(CASE WHEN statut = 'ok'
                         AND (COALESCE(nb_partants, 0) > 0 OR COALESCE(nb_courses, 0) > 0)
                        THEN 1 ELSE 0 END) AS n_ok_avec_donnees,
               max(created_at) AS dernier
        FROM scrape_log
        WHERE created_at > :depuis
        GROUP BY source
    """), {"depuis": maintenant - timedelta(days=int(jours))})).all()

    sources: dict[str, dict] = {}
    for source, n_runs, n_ok, n_ok_data, dernier in lignes:
        nom = str(source)
        n_runs = int(n_runs or 0)
        n_ok = int(n_ok or 0)
        n_ok_data = int(n_ok_data or 0)
        if nom.lower() in desactivees:
            statut = "disabled"
        elif n_runs < MIN_RUNS_POUR_JUGER_SCRAPER:
            statut = "insufficient_data"
        elif n_ok == 0:
            statut = "failing"
        elif n_ok_data == 0:
            # Le cas trompeur : que des succès, aucune donnée.
            statut = "ok_but_empty"
        else:
            statut = "ok"
        sources[nom] = {
            "n_runs": n_runs, "n_ok": n_ok, "n_ok_avec_donnees": n_ok_data,
            "dernier_run": _as_dt(dernier), "statut": statut,
        }
    return {"fenetre_jours": jours, "sources": sources,
            "sources_desactivees": sorted(desactivees)}


async def rapport_qualite(session: AsyncSession) -> dict:
    """Rapport complet + liste des anomalies à signaler."""
    couverture = await couverture_sources(session)
    fraicheur = await fraicheur_alimentation(session)
    figees = await cotes_figees(session)
    concordance = await concordance_partants(session)
    incompletes = await courses_non_pronosticables(session)
    scrapers = await sante_scrapers(session)

    anomalies: list[dict] = []

    for nom, info in scrapers["sources"].items():
        if info["statut"] == "ok_but_empty":
            anomalies.append({
                "code": "scraper_succes_sans_donnees",
                "gravite": "warning",
                "message": (f"Scraper '{nom}' : {info['n_ok']} exécutions en succès, "
                            "aucune n'a enregistré la moindre course ni le moindre partant"),
            })
        elif info["statut"] == "failing":
            anomalies.append({
                "code": "scraper_en_echec",
                "gravite": "warning",
                "message": f"Scraper '{nom}' : {info['n_runs']} exécutions, aucune réussie",
            })

    if fraicheur["statut"] == "stale":
        anomalies.append({
            "code": "alimentation_gelee",
            "gravite": "critical",
            "message": (f"Aucune mise à jour de partant depuis "
                        f"{fraicheur['age_derniere_participation_h']} h "
                        f"(seuil {SEUIL_FRAICHEUR_SCRAPE_H} h) — scraper probablement mort"),
        })
    elif fraicheur["statut"] == "programme_manquant":
        anomalies.append({
            "code": "programme_du_jour_absent",
            "gravite": "critical",
            "message": ("Le scraper tourne mais aucune course n'est enregistrée pour "
                        "aujourd'hui : programme du jour non récupéré"),
        })

    for nom, info in couverture["sources"].items():
        if info["statut"] == "degraded":
            anomalies.append({
                "code": "source_critique_degradee",
                "gravite": "critical",
                "message": (f"Source critique '{nom}' à {info['couverture_pct']} % "
                            f"de couverture (seuil {SEUIL_COUVERTURE_CRITIQUE_PCT} %) "
                            f"sur {couverture['n_partants']} partants"),
            })
        elif info["statut"] == "silent":
            anomalies.append({
                "code": "source_muette",
                "gravite": "warning",
                "message": (f"Source '{nom}' quasi muette : "
                            f"{info['couverture_pct']} % de couverture"),
            })

    if figees.get("mesurable") and figees["n_cotes_a_venir"] >= MIN_PARTANTS_POUR_JUGER \
            and figees["pct_figees"] >= 50.0:
        anomalies.append({
            "code": "cotes_figees",
            "gravite": "warning",
            "message": (f"{figees['pct_figees']} % des cotes de courses partant sous "
                        f"{FENETRE_AVANT_DEPART_H} h n'ont pas été republiées depuis "
                        f"{SEUIL_COTE_FIGEE_MIN} min"),
        })

    if concordance["n_arrivees_numero_inconnu"]:
        anomalies.append({
            "code": "arrivee_numero_inconnu",
            "gravite": "critical",
            "message": (f"{concordance['n_arrivees_numero_inconnu']} numéro(s) à "
                        "l'arrivée absents des partants — règlement potentiellement faussé"),
        })

    if incompletes["n_sans_aucune_cote"]:
        anomalies.append({
            "code": "courses_non_pronosticables",
            "gravite": "warning",
            "message": (f"{incompletes['n_sans_aucune_cote']} course(s) partant sous "
                        f"{FENETRE_AVANT_DEPART_H} h sans aucune cote PMU"),
        })

    return {
        "genere_a": datetime.now(timezone.utc).isoformat(),
        "couverture": couverture,
        "fraicheur": fraicheur,
        "cotes_figees": figees,
        "concordance": concordance,
        "courses_incompletes": incompletes,
        "sante_scrapers": scrapers,
        "anomalies": anomalies,
        "statut_global": ("critical" if any(a["gravite"] == "critical" for a in anomalies)
                          else "warning" if anomalies else "ok"),
    }


async def verifier_et_alerter(session: AsyncSession) -> dict:
    """Calcule le rapport et journalise les anomalies dans `system_errors`.

    Une anomalie n'interrompt jamais le scraping : on rend le trou VISIBLE (le
    back-office lit `system_errors`) au lieu de le laisser silencieux.
    """
    rapport = await rapport_qualite(session)
    if rapport["anomalies"]:
        from services.error_monitor import record_error
        for anomalie in rapport["anomalies"]:
            await record_error(
                "data_quality",
                anomalie["message"],
                detail=anomalie["code"],
                level=anomalie["gravite"],
            )
    log.info("data_quality.checked", statut=rapport["statut_global"],
             n_anomalies=len(rapport["anomalies"]),
             codes=[a["code"] for a in rapport["anomalies"]])
    return rapport
