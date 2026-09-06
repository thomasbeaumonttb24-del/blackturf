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

import json
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from ml.feature_health import SOURCE_PAR_FEATURE as _SOURCE_PAR_FEATURE

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

# Sources dont on refuse d'AFFICHER la cote, faute de savoir qu'elle porte sur le
# bon cheval. Ce n'est pas une question de disponibilité mais de VÉRACITÉ.
#
# Test décisif, et il est simple : deux carnets honnêtes désignent le même favori
# dans 90 à 95 % des courses. Mesuré en production sur les courses où la source
# couvre au moins 80 % des partants :
#
#     bet365   81,9 %      unibet   81,4 %      ladbrokes  78,8 %
#     betfair  75,5 %      geny     61,8 %  (audit du 2026-08-31, 199 courses)
#
# GenyBet a été corrigé le 2026-08-27 (cotes plafonnées à 9,9, décalage d'un cheval,
# appariement sans le lieu). RE-MESURÉ APRÈS ce correctif, sur les 4 derniers jours
# seuls : 64,5 % d'accord sur 200 courses, corrélation 0,749 sur 2 159 partants.
# Le correctif n'a donc pas suffi : plus d'une course sur trois lui voit un autre
# favori que le PMU. Une cote qui porte sur le mauvais cheval n'est pas une cote
# imprécise, c'est une donnée fausse — et elle entrait dans le « meilleur prix »
# affiché au visiteur (`cote_min`, `LEAST(...)`), où la valeur la PLUS BASSE gagne :
# une erreur y est donc systématiquement retenue plutôt que noyée.
#
# Le modèle ne l'apprend pas (`ml/models.py` META_COLS), donc aucun impact ML. La
# réintégrer suppose de repasser au-dessus de 90 % sur ce même test.
SOURCES_COTES_NON_FIABLES = ("geny",)

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
# Fenêtre avant le départ où l'ABSENCE TOTALE de cote PMU est anormale. Bien plus
# courte que la précédente : le PMU ne price pas une course six heures à l'avance.
# Mesuré en production le 20/08/2026 sur 105 courses (première cote observée dans
# `cotes_historique` vs heure de départ) : médiane 12,6 h d'avance, 10e centile
# 5,9 h, et surtout MINIMUM 3,65 h. Alerter à 6 h revenait donc à crier
# quotidiennement sur des courses parfaitement normales, simplement pas encore
# ouvertes aux paris — aucune course des 3 derniers jours n'a fini sans cote PMU.
# 2 h laisse la marge du pire cas observé tout en gardant l'alerte utile : à ce
# stade, une course sans la moindre cote n'est réellement pas pronosticable.
FENETRE_COURSE_SANS_COTE_H = 2
# En dessous, le nombre d'exécutions d'un scraper ne permet pas de conclure
# (un scraper lancé il y a dix minutes n'a pas encore fait ses preuves).
MIN_RUNS_POUR_JUGER_SCRAPER = 20

# Livraison des alertes : en dessous de 5 envois sur la fenêtre, un échec isolé ne
# prouve rien (un utilisateur au push expiré, une adresse en rebond ponctuel). Au
# delà de 30 % d'échecs, ce n'est plus un destinataire qui pose problème, c'est le
# canal — c'est l'ordre de grandeur observé lors de la panne Resend de juin-août
# 2026, où le taux était de 100 %.
MIN_ENVOIS_POUR_JUGER_CANAL = 5
SEUIL_TAUX_ECHEC_ENVOI = 0.30

# `degraded` se declenchait sur UN SEUL echec, quel que soit le volume : un echec
# in-app isole sur 621 envois (27/08) a produit une alerte critique par heure
# pendant 24 h, toutes identiques. Une anomalie qui se repete a l'identique sans
# rien apprendre de neuf finit par etre ignoree, y compris quand elle est vraie.
# Un canal n'est degrade que si les echecs sont a la fois assez NOMBREUX et assez
# FREQUENTS pour ne plus s'expliquer par un destinataire isole.
MIN_ECHECS_POUR_CANAL_DEGRADE = 3
SEUIL_TAUX_ECHEC_DEGRADE = 0.02

# Tâches de fond : en dessous de 5 échecs sur la fenêtre, c'est le bruit normal
# d'un OOM isolé ou d'une course mal formée. Au-delà, quelque chose est cassé.
SEUIL_ECHECS_TACHES_RECENTS = 5

# Features mortes. `ml/feature_health` mesure chaque nuit les features à variance
# nulle et persiste le résultat — mais PERSONNE ne le lisait : 54 snapshots en base,
# aucune alerte, et 29 features constantes sur 185 (15,7 % du vecteur) découvertes
# par un audit manuel le 2026-08-31. Une chaîne de scrape peut donc mourir sans que
# rien ne le dise, exactement comme la colonne `ecart_longueurs` restée NULL sur
# 330 145 lignes.
# Le seuil n'est pas zéro : quelques features légitimement constantes existent
# (`saison_code` l'est sur toute fenêtre courte). 12 est au-dessus de ce bruit de
# fond et bien en dessous des 29 constatées.
#
# IL PORTE SUR LES SEULES MORTES INEXPLIQUÉES (cf. `ml.feature_health.SANS_SOURCE`).
# Compter les autres revenait à répéter chaque heure un fait établi et vérifié — ce
# qu'a fait l'alerte 93 fois — en noyant dedans les features dont personne n'a
# cherché la cause. Le total, lui, reste rapporté : il n'est pas caché, il n'alerte
# simplement plus tout seul.
SEUIL_FEATURES_MORTES = 12
# Une hausse BRUSQUE compte autant que le niveau : +5 features mortes d'un snapshot
# à l'autre, c'est une source qui vient de tomber, même si le total reste sous le
# seuil absolu.
SEUIL_HAUSSE_FEATURES_MORTES = 5

# Calibration par bande de probabilité. Une probabilité de X % doit gagner X % du
# temps ; sinon la « cote juste » affichée est fausse, et l'espérance de gain qui en
# découle l'est aussi. Sous 0,40 la calibration est excellente (écart mesuré
# -0,0013 sur 46 500 partants) ; au-dessus elle dérive, mais toute cette queue ne
# pèse que ~1 % de la population. D'où le seuil de PREUVE : on n'alerte pas sur
# 96 observations, on attend d'en avoir assez pour que l'écart signifie quelque
# chose. À 300 observations, l'écart-type binomial autour de 0,5 vaut 2,9 points :
# un écart de 5 points est alors à ~1,7 sigma et mérite d'être regardé.
MIN_OBS_BANDE_CALIBRATION = 300
SEUIL_ECART_CALIBRATION = 0.05
BANDES_CALIBRATION = ((0.0, 0.40), (0.40, 0.50), (0.50, 0.60), (0.60, 0.70), (0.70, 1.01))


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


def _sources_en_sommeil() -> set[str]:
    """Sources listées dans SCRAPER_DISABLED_SOURCES (silence assumé)."""
    import os
    return {s.strip().lower() for s in
            os.getenv("SCRAPER_DISABLED_SOURCES", "").split(",") if s.strip()}


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
    en_sommeil = _sources_en_sommeil()
    sources: dict[str, dict] = {}
    for idx, nom in enumerate(SOURCES_COTES, start=1):
        n = int(row[idx] or 0) if row else 0
        pct = round(100.0 * n / total, 1) if total else 0.0
        critique = nom in SOURCES_CRITIQUES
        if total < MIN_PARTANTS_POUR_JUGER:
            statut = "insufficient_data"
        elif critique:
            statut = "ok" if pct >= SEUIL_COUVERTURE_CRITIQUE_PCT else "degraded"
        elif pct >= SEUIL_COUVERTURE_MUETTE_PCT:
            # Une source peut être alimentée par un AUTRE producteur que son
            # scraper : `cote_unibet` vient du daemon zeturf, donc `unibet` reste
            # « ok » même si le scraper du même nom est en sommeil.
            statut = "ok"
        elif nom in en_sommeil:
            # Silence ASSUMÉ : la source est explicitement désactivée. On le
            # rapporte sans alerter, sinon la surveillance crie en permanence
            # sur une décision déjà prise.
            statut = "silent_disabled"
        else:
            statut = "silent"
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
    """Courses à venir dont aucun partant n'a de cote PMU : pas d'EV possible.

    Fenêtre `FENETRE_COURSE_SANS_COTE_H` et non `FENETRE_AVANT_DEPART_H` : une
    course sans cote six heures avant son départ n'est pas une panne, c'est le
    fonctionnement normal du PMU (cf. la mesure documentée sur la constante).
    """
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
           "horizon": maintenant + timedelta(hours=FENETRE_COURSE_SANS_COTE_H)})).first()
    return {
        "n_a_venir": int(row[0] or 0) if row else 0,
        "n_sans_aucune_cote": int(row[1] or 0) if row else 0,
        "fenetre_h": FENETRE_COURSE_SANS_COTE_H,
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


async def livraison_alertes(session: AsyncSession, heures: int = 24) -> dict:
    """Les alertes envoyées arrivent-elles VRAIMENT ?

    `alertes_log.envoye` dit si le fournisseur a accepté le message. Personne ne
    le lisait : entre le 07/06 et le 01/08/2026, le digest du matin a échoué
    **253 fois d'affilée** (clé Resend invalide) sans qu'aucun signal ne remonte —
    le job tournait proprement, les logs disaient « done », et aucun abonné ne
    recevait rien. Un canal peut être mort pendant deux mois sans que rien ne
    l'indique : on le mesure ici.

    Statuts par canal : `ok`, `ok_avec_echecs` (echecs residuels, sous le seuil de
    signalement), `insufficient_data` (trop peu d'envois pour juger), `degraded`
    (des echecs, mais minoritaires), `failing` (canal casse).
    """
    maintenant = datetime.now(timezone.utc)
    lignes = (await session.execute(text("""
        SELECT canal,
               count(*) AS n_total,
               SUM(CASE WHEN envoye THEN 0 ELSE 1 END) AS n_echecs
        FROM alertes_log
        WHERE created_at > :depuis
        GROUP BY canal
    """), {"depuis": maintenant - timedelta(hours=int(heures))})).all()

    canaux: dict[str, dict] = {}
    for canal, n_total, n_echecs in lignes:
        n_total = int(n_total or 0)
        n_echecs = int(n_echecs or 0)
        taux = (n_echecs / n_total) if n_total else 0.0
        if n_total < MIN_ENVOIS_POUR_JUGER_CANAL:
            statut = "insufficient_data"
        elif taux >= SEUIL_TAUX_ECHEC_ENVOI:
            statut = "failing"
        elif (n_echecs >= MIN_ECHECS_POUR_CANAL_DEGRADE
              and taux >= SEUIL_TAUX_ECHEC_DEGRADE):
            statut = "degraded"
        elif n_echecs:
            # Echecs residuels : comptes et visibles dans le rapport, mais pas
            # remontes en anomalie (voir MIN_ECHECS_POUR_CANAL_DEGRADE).
            statut = "ok_avec_echecs"
        else:
            statut = "ok"
        canaux[str(canal)] = {
            "n_total": n_total, "n_echecs": n_echecs,
            "taux_echec": round(taux, 3), "statut": statut,
        }
    return {"fenetre_heures": heures, "canaux": canaux}


def sante_files_taches(heures: int = 24) -> dict:
    """Tâches de fond mortes en silence.

    Un job RQ qui échoue atterrit dans la `FailedJobRegistry` et n'en sort jamais :
    ni log applicatif, ni trace au back-office. En production, 517 échecs de
    `post_course_sync` (apprentissage post-course) et 33 de `retrain_if_needed`
    s'y étaient accumulés depuis juin sans que personne le sache — l'essentiel
    tué par le OOM killer.

    On ne remonte que les échecs RÉCENTS : le passif historique n'est pas une
    alerte, ce serait du bruit permanent.
    """
    from datetime import datetime as _dt

    resultat: dict = {"fenetre_heures": heures, "files": {}, "disponible": False}
    try:
        from redis import Redis
        from rq.job import Job
        from rq.registry import FailedJobRegistry
    except Exception:
        return resultat  # rq absent (tests, conteneur allégé) : on ne juge pas

    try:
        from api.config import get_settings
        connexion = Redis.from_url(get_settings().redis_url)
        limite = _dt.utcnow() - timedelta(hours=int(heures))
        for nom in ("default", "ml"):
            registre = FailedJobRegistry(nom, connection=connexion)
            identifiants = registre.get_job_ids()
            recents = 0
            for jid in identifiants:
                try:
                    job = Job.fetch(jid, connection=connexion)
                except Exception:
                    continue
                fin = job.ended_at
                if fin is not None and fin.replace(tzinfo=None) > limite:
                    recents += 1
            resultat["files"][nom] = {
                "echecs_total": len(identifiants),
                "echecs_recents": recents,
            }
        resultat["disponible"] = True
    except Exception as e:  # noqa: BLE001
        log.warning("data_quality.files_taches_indisponible", err=str(e)[:120])
    return resultat


async def sante_features(session: AsyncSession) -> dict:
    """Les features apprises portent-elles encore de l'information ?

    `ml/feature_health` calcule cette mesure chaque nuit depuis des mois et la
    persiste dans `feature_health`. Rien ne la LISAIT : 54 snapshots en base, zéro
    alerte, et 29 features à variance strictement nulle — toute la chaîne « presse »
    et toute la chaîne « dynamique de course » — découvertes par un audit manuel.
    Une mesure que personne ne consulte n'est pas une supervision.

    On compare aussi au snapshot précédent : une source qui tombe fait bondir le
    compte d'un coup, et ce saut doit alerter même sous le seuil absolu.

    UN COMPTE GLOBAL NE SUFFIT PAS, et c'est ce que l'alerte a démontré en tournant :
    93 répétitions du même message, listant chaque heure les huit premiers noms par
    ordre alphabétique — dont la moitié documentée depuis l'audit du 2026-08-31 comme
    dépendant d'une donnée qui n'existe pas à la source. Une alerte qui répète un fait
    connu ne fait pas remonter celui qui ne l'est pas. On sépare donc les deux
    (`ml.feature_health.SANS_SOURCE`) : ce qui alerte, c'est l'INEXPLIQUÉ.

    Et le registre lui-même est vérifié en retour : une entrée dont la feature a
    retrouvé de la variance est signalée (`registre_perime`), sinon une liste
    d'exceptions se transforme en angle mort permanent.
    """
    # `feature_health` est créée à la volée par `persist_feature_health` : elle
    # n'existe pas tant que le calcul nocturne n'a jamais tourné (base neuve, tests).
    # On ne juge pas, mais on DÉSEMPOISONNE : sous PostgreSQL, une requête échouée
    # avorte la transaction entière et toutes les suivantes lèvent, avec un message
    # sans rapport avec la cause (panne du 20/08/2026, cf. db.database.desempoisonner).
    try:
        lignes = (await session.execute(text("""
            SELECT data, created_at FROM feature_health
            ORDER BY created_at DESC LIMIT 2
        """))).all()
    except Exception as e:                                        # noqa: BLE001
        from db.database import desempoisonner
        await desempoisonner(session)
        log.info("data_quality.feature_health_absente", err=str(e)[:160])
        return {"disponible": False, "raison": "table feature_health absente"}
    if not lignes:
        return {"disponible": False, "raison": "aucun instantané feature_health"}

    actuel = lignes[0][0] or {}
    if isinstance(actuel, str):
        actuel = json.loads(actuel)
    if actuel.get("insufficient"):
        return {"disponible": False, "raison": "échantillon trop court"}

    mortes = list(actuel.get("dead") or [])
    precedent = None
    if len(lignes) > 1:
        p = lignes[1][0] or {}
        if isinstance(p, str):
            p = json.loads(p)
        if not p.get("insufficient"):
            precedent = list(p.get("dead") or [])

    nouvelles = sorted(set(mortes) - set(precedent)) if precedent is not None else []
    n_features = int(actuel.get("n_features") or 0)

    from ml.feature_health import classer_mortes, registre_perime
    # Une source coupée exprès (`SCRAPER_DISABLED_SOURCES`) n'est pas une panne : la
    # couverture des cotes le savait déjà (`silent_disabled`), la santé des features
    # l'ignorait et criait chaque heure sur huit features dont on a décidé de ne plus
    # collecter la donnée. Même source de vérité pour les deux mesures.
    _eteintes = _sources_en_sommeil()
    classees = classer_mortes(mortes, sources_desactivees=_eteintes)
    # Une feature documentée qui « meurt » à nouveau n'apprend rien : elle était déjà
    # morte, et sa cause est connue. Le saut brutal ne doit désigner que l'inattendu.
    nouvelles_inexpliquees = [f for f in nouvelles if f in set(classees["inexpliquees"])]
    _sources_mortes = sorted({
        src for f in classees["documentees"]
        if (src := _SOURCE_PAR_FEATURE.get(f)) and src in _eteintes
    })
    return {
        "disponible": True,
        # `_as_dt` : aiosqlite (tests) rend un TEXTE là où asyncpg rend un datetime.
        "mesure_a": (lambda d: d.isoformat() if d else None)(_as_dt(lignes[0][1])),
        "n_features": n_features,
        "n_mortes": len(mortes),
        "part_mortes": round(len(mortes) / n_features, 3) if n_features else None,
        # Les noms sont bornés : une anomalie doit rester lisible dans une alerte.
        "mortes": sorted(mortes)[:40],
        # Ce que l'audit a établi (cause connue) vs ce que personne n'a expliqué.
        "mortes_documentees": classees["documentees"],
        "n_mortes_documentees": len(classees["documentees"]),
        "mortes_inexpliquees": classees["inexpliquees"][:40],
        "n_mortes_inexpliquees": len(classees["inexpliquees"]),
        "raisons_connues": classees["raisons"],
        # Sources en sommeil qui expliquent une partie du compte : elles doivent
        # rester LISIBLES, sinon « rallumer france_galop » ne se relie jamais à
        # « six features reviennent ».
        "sources_desactivees_en_cause": _sources_mortes,
        # Entrées du registre dont la feature revit : la cause inscrite n'est plus vraie.
        "registre_perime": registre_perime(mortes),
        # Features NÉES récemment : absentes du passé parce qu'elles n'existaient pas.
        # Elles étaient comptées mortes — et même « devenues mortes », l'anomalie
        # critical réservée à la chute d'une source (cf. ml.feature_health).
        "nouvelles_features": list(actuel.get("nouvelles") or [])[:20],
        "n_nouvelles_features": len(actuel.get("nouvelles") or []),
        "nouvelles_mortes": nouvelles_inexpliquees[:20],
        "n_nouvelles_mortes": len(nouvelles_inexpliquees),
    }


async def calibration_par_bande(session: AsyncSession, jours: int = 90) -> dict:
    """Une probabilité de X % gagne-t-elle X % du temps ?

    Ce que la mesure a établi le 2026-08-31, et qui motive une SURVEILLANCE plutôt
    qu'un correctif :

      bande      n servi   réel    écart
      0,00-0,40  46 497  0,0880  0,0893  -0,0013   <- excellent
      0,40-0,50     338  0,4427  0,3639  +0,0788
      0,50-0,60     138  0,5429  0,4855  +0,0574
      0,70+          29  0,7936  0,4138  +0,3798

    MÉCANISME IDENTIFIÉ : ce n'est pas la courbe isotone qui échoue, c'est la
    RENORMALISATION Σ=1 appliquée APRÈS elle. Mesuré dans la bande 0,70+ : la courbe
    rend 0,6122, c'est 0,7973 qui est servi, et le réel vaut 0,4074. La division par
    la somme redonne au favori la confiance que la calibration venait de lui retirer.

    CE QUI A ÉTÉ TESTÉ ET REJETÉ, en 5 plis GROUPÉS PAR COURSE (protocole du
    calibrage de `_PRIOR`), 4 375 courses / 47 045 partants, hors échantillon :

      A. renorm(courbe(brut))  — l'actuel     logloss 0,27463  ECE 0,00265  Σ=1,000
      B. deuxième passe sur le servi          logloss 0,27455  ECE 0,00358  Σ=1,000
      C. deuxième passe sans renorm finale    logloss 0,27485  ECE 0,00706  Σ=1,073
      D. aucune renormalisation               logloss 0,27522  ECE 0,00616  Σ=1,066
      E. plafond au sommet de la courbe       logloss 0,27459  ECE 0,00258  (36 lignes)

    Aucune ne domine. B redresse la bande 0,50-0,60 (+0,127 -> +0,013) mais sur
    96 observations contre 71 : l'écart tient dans 2 sigma de bruit binomial, et
    l'ECE global se dégrade. C et D cassent Σ=1 pour un résultat pire. E ne touche
    que 0,08 % des lignes. Toute la queue >= 0,40 pèse ~490 partants sur 47 045 :
    à ce volume, aucune méthode de calibration ne peut être départagée.

    CE QUI A CHANGÉ DEPUIS (2026-09-04). Les cinq variantes se battaient toutes sur
    la même queue de ~490 partants, c'est-à-dire au mauvais endroit. Le défaut se lit
    aussi de l'autre bout : la masse qui manque sous 0,40 (−0,0013 sur 46 497
    partants, ≈ 60 victoires) est celle qui déborde au-dessus (≈ 45 victoires). C'est
    UNE seule grandeur — la netteté de la distribution — et elle s'ajuste sur les
    47 045 partants, pas sur 96. `ml.sharpness_calibration` le fait, sous la même
    règle que le reste : identité tant que rien ne tient hors échantillon.

    Cette mesure-ci ne change pas de rôle pour autant : elle reste le juge, pas le
    correcteur. Elle rapporte en plus ce qui a été servi APRÈS la mise en service de
    l'exposant (`bandes_depuis_correction`) — sans quoi une fenêtre de 90 jours
    continuerait de crier des semaines durant sur un défaut déjà corrigé.
    """
    # SQL volontairement PORTABLE : ni `LATERAL`, ni `jsonb_array_elements`, ni
    # `make_interval` — la suite tourne sur SQLite, et une supervision dont
    # l'invariant n'est pas testable ne vaut rien (même parti pris que
    # `/seo/analyse-du-jour`). Le vainqueur est extrait en Python : ~3 500 classements
    # sur la fenêtre, contre une jointure latérale par partant.
    depuis = datetime.now(timezone.utc) - timedelta(days=int(jours))
    partants = (await session.execute(text("""
        SELECT p.course_id, pa.numero, p.proba_top1, p.created_at
        FROM prediction_evaluation p
        JOIN participations pa ON pa.participation_id = p.participation_id
        JOIN courses c ON c.course_id = p.course_id
        WHERE c.statut = 'termine'
          AND c.date_heure IS NOT NULL AND p.created_at IS NOT NULL
          AND p.created_at < c.date_heure
          AND c.date_heure >= :depuis
          AND pa.non_partant = false
          AND p.proba_top1 IS NOT NULL
    """), {"depuis": depuis})).all()
    if not partants:
        return {"disponible": False, "raison": "cohorte trop courte", "n": 0}

    resultats = (await session.execute(text("""
        SELECT r.course_id, r.classement
        FROM resultats r
        JOIN courses c ON c.course_id = r.course_id
        WHERE c.date_heure IS NOT NULL AND c.date_heure >= :depuis
    """), {"depuis": depuis})).all()

    vainqueur: dict[str, int] = {}
    for course_id, classement in resultats:
        if isinstance(classement, str):
            try:
                classement = json.loads(classement)
            except (TypeError, ValueError):
                continue
        if not isinstance(classement, list):
            continue
        for entree in classement:
            # `position == 1` et JAMAIS l'index 0 : le classement n'est pas garanti
            # trié (même convention que `_naive_favorite_roi`).
            if isinstance(entree, dict):
                try:
                    if int(entree.get("position")) == 1:
                        vainqueur[course_id] = int(entree.get("numero"))
                        break
                except (TypeError, ValueError):
                    continue

    lignes: list[tuple[float, int, datetime | None]] = []
    for course_id, numero, proba, produit_le in partants:
        gagnant = vainqueur.get(course_id)
        if gagnant is None:
            continue                      # course sans arrivée exploitable
        try:
            lignes.append((float(proba), 1 if int(numero) == gagnant else 0,
                           _as_dt(produit_le)))
        except (TypeError, ValueError):
            continue

    if len(lignes) < MIN_OBS_BANDE_CALIBRATION:
        return {"disponible": False, "raison": "cohorte trop courte", "n": len(lignes)}

    # Date de mise en service de la correction de netteté, s'il y en a une. Une
    # fenêtre de 90 jours regarde très majoritairement des pronostics produits AVANT
    # elle : sans cette date, l'alerte continuerait de crier des semaines durant sur
    # un défaut déjà corrigé — et personne ne saurait dire si la correction a pris.
    corrige_depuis = await _correction_nettete_depuis(session)

    # Dernier EXAMEN de l'exposant, retenu ou non. Une dérive qu'un correcteur
    # examine chaque nuit et écarte faute de preuve n'est pas la même chose qu'une
    # dérive que personne ne regarde — et l'alerte disait la même phrase dans les
    # deux cas, 145 fois de suite.
    examen = None
    try:
        from ml.sharpness_calibration import charger_dernier_examen
        examen = await charger_dernier_examen(session)
    except Exception as e:                                       # noqa: BLE001
        log.info("data_quality.examen_nettete_indisponible", err=str(e)[:140])

    resultat = {
        "disponible": True, "fenetre_jours": jours, "n": len(lignes),
        "bandes": _bandes(lignes),
        "correction_nettete_depuis": (corrige_depuis.isoformat() if corrige_depuis else None),
        "dernier_examen_nettete": examen,
    }
    if corrige_depuis:
        depuis_correction = [l for l in lignes if l[2] and l[2] >= corrige_depuis]
        resultat["n_depuis_correction"] = len(depuis_correction)
        resultat["bandes_depuis_correction"] = _bandes(depuis_correction)
    return resultat


def _bandes(lignes) -> list[dict]:
    """Découpe (proba servie, gagné) en bandes de probabilité. Fonction PURE."""
    bandes = []
    for bas, haut in BANDES_CALIBRATION:
        pris = [(p, g) for p, g, *_ in lignes if bas <= p < haut]
        if not pris:
            continue
        n = len(pris)
        servi = sum(p for p, _ in pris) / n
        reel = sum(g for _, g in pris) / n
        bandes.append({
            "bande": f"{bas:.2f}-{min(haut, 1.0):.2f}",
            "n": n,
            "proba_moyenne": round(servi, 4),
            "taux_reel": round(reel, 4),
            "ecart": round(servi - reel, 4),
            # `concluant` : au-dessus, l'écart n'est plus explicable par le seul bruit
            # d'échantillonnage. En dessous, le chiffre est PUBLIÉ mais n'autorise
            # aucune conclusion — c'est la différence entre mesurer et conclure.
            "concluant": n >= MIN_OBS_BANDE_CALIBRATION,
        })
    return bandes


async def _correction_nettete_depuis(session: AsyncSession) -> datetime | None:
    """Quand l'exposant de netteté en vigueur a-t-il été mis en service ?

    Lecture DÉFENSIVE : la table n'existe pas tant que le premier calcul nocturne
    n'a pas tourné, et une requête échouée avorte la transaction entière sous
    PostgreSQL (cf. `desempoisonner`).
    """
    try:
        r = (await session.execute(text(
            "SELECT data FROM sharpness_calibration WHERE id = 1"))).first()
    except Exception:                                            # noqa: BLE001
        from db.database import desempoisonner
        await desempoisonner(session)
        return None
    if not r or not r[0]:
        return None
    data = r[0] if isinstance(r[0], dict) else json.loads(r[0])
    return _as_dt(data.get("applique_depuis"))


def _suffixe_examen_nettete(examen) -> str:
    """Ce que le correcteur de netteté a décidé la dernière fois qu'il a regardé.

    Sans cette phrase, l'anomalie de calibration se lit comme un défaut abandonné.
    Elle est en réalité mesurée chaque nuit par `ml.sharpness_calibration`, qui
    refuse de corriger tant qu'un exposant ne tient pas hors échantillon — un refus
    est une décision, pas une absence de supervision.
    """
    if not isinstance(examen, dict) or not examen.get("examine_le"):
        return ""
    _jour = str(examen["examine_le"])[:10]
    if examen.get("retenu"):
        return (f" ; correcteur de netteté : exposant {examen.get('exposant')} "
                f"mis en service le {_jour}")
    _cand = examen.get("exposant_candidat")
    _cand_txt = f"candidat {_cand} écarté" if _cand is not None else "aucun candidat"
    return (f" ; correcteur de netteté examiné le {_jour} : {_cand_txt} "
            f"({examen.get('raison') or 'sans conclusion'}) — l'exposant en service "
            f"reste {examen.get('exposant_en_place', 1.0)}")


async def rapport_qualite(session: AsyncSession) -> dict:
    """Rapport complet + liste des anomalies à signaler."""
    couverture = await couverture_sources(session)
    fraicheur = await fraicheur_alimentation(session)
    figees = await cotes_figees(session)
    concordance = await concordance_partants(session)
    incompletes = await courses_non_pronosticables(session)
    scrapers = await sante_scrapers(session)
    livraison = await livraison_alertes(session)
    features = await sante_features(session)
    calibration = await calibration_par_bande(session)
    files = sante_files_taches()

    anomalies: list[dict] = []

    for file, info in files.get("files", {}).items():
        if info["echecs_recents"] >= SEUIL_ECHECS_TACHES_RECENTS:
            anomalies.append({
                "code": "taches_de_fond_en_echec",
                "gravite": "warning",
                "message": (f"File '{file}' : {info['echecs_recents']} tâches en échec "
                            f"en {files['fenetre_heures']} h "
                            f"({info['echecs_total']} au total dans le registre)"),
            })

    for canal, info in livraison["canaux"].items():
        if info["statut"] == "failing":
            anomalies.append({
                "code": "canal_envoi_casse",
                "gravite": "critical",
                "message": (f"Canal '{canal}' : {info['n_echecs']} envois en échec sur "
                            f"{info['n_total']} en {livraison['fenetre_heures']} h "
                            f"({info['taux_echec']:.0%}) — les destinataires ne "
                            "reçoivent rien"),
            })
        elif info["statut"] == "degraded":
            anomalies.append({
                "code": "canal_envoi_degrade",
                "gravite": "warning",
                "message": (f"Canal '{canal}' : {info['n_echecs']} envois en échec sur "
                            f"{info['n_total']} en {livraison['fenetre_heures']} h"),
            })

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

    if features.get("disponible"):
        if features["n_nouvelles_mortes"] >= SEUIL_HAUSSE_FEATURES_MORTES:
            anomalies.append({
                "code": "features_devenues_mortes",
                "gravite": "critical",
                "message": (f"{features['n_nouvelles_mortes']} features sont devenues "
                            f"constantes depuis la dernière mesure "
                            f"({', '.join(features['nouvelles_mortes'][:8])}) — une source "
                            "de données vient probablement de tomber"),
            })
        elif features["n_mortes_inexpliquees"] >= SEUIL_FEATURES_MORTES:
            # Le message ne dit plus « le modèle les apprend comme du bruit » : depuis
            # `ml.models.train`, une colonne constante sur la part d'apprentissage n'entre
            # plus dans le modèle. Ce qui reste vrai, et seul en jeu, c'est qu'elles ne
            # servent à rien tant que leur cause n'est pas trouvée.
            anomalies.append({
                "code": "features_mortes",
                "gravite": "warning",
                "message": (f"{features['n_mortes_inexpliquees']} features sur "
                            f"{features['n_features']} sont à variance nulle sans cause "
                            f"établie ({', '.join(features['mortes_inexpliquees'][:8])}"
                            f"{'…' if features['n_mortes_inexpliquees'] > 8 else ''}) — "
                            "elles n'apportent rien au modèle, qui ne les apprend plus, "
                            f"et {features['n_mortes_documentees']} autres ont une cause "
                            "établie" + (
                                f" (dont les sources en sommeil "
                                f"{', '.join(features['sources_desactivees_en_cause'])})"
                                if features.get("sources_desactivees_en_cause") else "")),
            })
        if features.get("registre_perime"):
            # Le registre des causes établies affirme « cette donnée n'existe pas ». Si
            # la feature revit, l'affirmation est fausse et masque désormais un signal.
            anomalies.append({
                "code": "registre_features_perime",
                "gravite": "warning",
                "message": (f"{len(features['registre_perime'])} feature(s) inscrites "
                            "comme sans source ont retrouvé de la variance "
                            f"({', '.join(features['registre_perime'][:8])}) — le registre "
                            "ml.feature_health.SANS_SOURCE doit être mis à jour"),
            })

    # Ce que la fenêtre observe est le PASSÉ : 90 jours de pronostics, presque tous
    # produits avant la correction en vigueur. Sans le dire, l'alerte se répète des
    # semaines après le correctif et laisse croire qu'il n'a rien donné.
    _depuis_corr = {b["bande"]: b for b in (calibration.get("bandes_depuis_correction") or [])}
    for bande in (calibration.get("bandes") or []):
        if bande["concluant"] and abs(bande["ecart"]) >= SEUIL_ECART_CALIBRATION:
            _suite = _suffixe_examen_nettete(calibration.get("dernier_examen_nettete"))
            _recent = _depuis_corr.get(bande["bande"])
            if _recent:
                _suite += (f" ; depuis la correction de netteté, l'écart est de "
                          f"{_recent['ecart']:+.1%} sur {_recent['n']} partants"
                          f"{'' if _recent['concluant'] else ' (pas encore concluant)'}")
            anomalies.append({
                "code": "calibration_derive",
                "gravite": "warning",
                "message": (f"Probabilités de la bande {bande['bande']} sur "
                            f"{calibration.get('fenetre_jours')} j : annoncées "
                            f"{bande['proba_moyenne']:.1%}, réalisées {bande['taux_reel']:.1%} "
                            f"({bande['ecart']:+.1%} sur {bande['n']} partants) — la cote "
                            "juste affichée et l'espérance qui en découle sont faussées "
                            f"d'autant{_suite}"),
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
                        f"{incompletes['fenetre_h']} h sans aucune cote PMU"),
        })

    return {
        "genere_a": datetime.now(timezone.utc).isoformat(),
        "couverture": couverture,
        "fraicheur": fraicheur,
        "cotes_figees": figees,
        "concordance": concordance,
        "courses_incompletes": incompletes,
        "sante_scrapers": scrapers,
        "livraison_alertes": livraison,
        "sante_features": features,
        "calibration_par_bande": calibration,
        "files_taches": files,
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
                # Ce job tourne TOUTES LES HEURES. Sans clé, une anomalie qui
                # dure produit une ligne par heure : deux faits persistants ont
                # rempli 40 des 42 « erreurs ouvertes » du 01/09, chassant de
                # l'affichage tout ce qui était réellement nouveau. Le code de
                # l'anomalie est son identité — le message, lui, bouge (il porte
                # des compteurs qui varient d'un passage à l'autre).
                cle=anomalie["code"],
            )
    log.info("data_quality.checked", statut=rapport["statut_global"],
             n_anomalies=len(rapport["anomalies"]),
             codes=[a["code"] for a in rapport["anomalies"]])
    return rapport
