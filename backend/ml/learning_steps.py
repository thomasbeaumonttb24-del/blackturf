"""Journal des ÉTAPES d'apprentissage — pour qu'une panne cesse d'être muette.

Le problème
───────────
Onze apprentissages s'enchaînent SÉQUENTIELLEMENT dans un seul job RQ, derrière le
retrain nocturne : calibration longshots, isotone top1, isotone top3, température,
calibration par tranche de cote, rattrapages de règlement, gates de segments,
performance par signal, par bande d'EV, poids de profils, calibration des rapports,
edge monitor, santé des features, CLV. Aucun n'a d'entrée propre dans
``services/jobs.py`` : ils n'existent QUE derrière le retrain.

Deux conséquences, toutes deux vécues :

1. Le worker s'est fait OOM-killer le 20/08/2026 à 02:04, quatre-vingt-treize
   secondes APRÈS avoir déployé v511 avec succès. Cette nuit-là — et à chaque
   récidive — les onze apprentissages suivants n'ont simplement pas eu lieu,
   pendant que le journal annonçait un déploiement réussi.

2. Chaque étape est enveloppée dans un ``try/except`` qui journalise un
   ``warning``. Une étape peut donc échouer TOUTES LES NUITS pendant des semaines
   sans que rien ne le signale : la calibration reste figée sur une courbe périmée,
   et c'est indétectable depuis le produit.

Ce que ce module apporte
────────────────────────
Un état PERSISTANT par étape. La règle est celle que le système applique déjà
ailleurs : *l'état persistant fait foi contre les logs*. Un journal qui ne dit rien
ne prouve rien ; une ligne ``last_success_at`` vieille de trois jours, si.

``CREATE TABLE IF NOT EXISTS`` plutôt qu'une migration : même convention que
``edge_monitor``, ``cote_cloture_log`` et ``profil_learning.ensure_tables``.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="learning_steps")

# Au-delà de ce délai sans succès, une étape est PÉRIMÉE : ce qu'elle produit
# (courbe de calibration, poids, gates) décrit un monde qui n'existe plus. 48 h
# laisse passer une nuit ratée — deux, c'est une panne.
PERIME_APRES_HEURES = 48

# TIMESTAMPTZ et non TIMESTAMP : les horodatages écrits ici portent leur fuseau
# (`datetime.now(timezone.utc)`), et asyncpg REFUSE de lier un datetime conscient
# du fuseau à une colonne qui ne l'est pas — « invalid input for query argument ».
# SQLite l'accepte sans broncher : le défaut ne se voyait qu'en production, où il
# aurait rendu le journal des apprentissages muet, c'est-à-dire exactement la
# panne silencieuse que ce module existe pour rendre visible. Même convention que
# `cote_cloture_log` et le reste du schéma.
_DDL = """
CREATE TABLE IF NOT EXISTS learning_step_runs (
    step             VARCHAR(64) PRIMARY KEY,
    last_attempt_at  TIMESTAMPTZ,
    last_success_at  TIMESTAMPTZ,
    last_status      VARCHAR(20),
    last_error       VARCHAR(300),
    n_obs            INTEGER,
    detail           TEXT
)
"""


async def ensure_table(session: AsyncSession) -> None:
    await session.execute(text(_DDL))


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


async def enregistrer_etape(session: AsyncSession, step: str, *, statut: str,
                            n_obs: Optional[int] = None,
                            erreur: Optional[str] = None,
                            detail: Optional[dict] = None) -> None:
    """Écrit le résultat d'une étape. ``last_success_at`` n'avance QUE sur succès.

    Une étape qui échoue met à jour son statut et son erreur, mais LAISSE la date
    du dernier succès en place : c'est cet écart qui rend la panne visible.
    """
    await ensure_table(session)
    now = _maintenant()
    params = {
        "step": step, "now": now, "statut": statut,
        "erreur": (erreur or "")[:300] or None,
        "n_obs": int(n_obs) if n_obs is not None else None,
        "detail": json.dumps(detail, default=str) if detail else None,
        "succes": now if statut == "ok" else None,
    }
    await session.execute(text("""
        INSERT INTO learning_step_runs
            (step, last_attempt_at, last_success_at, last_status, last_error,
             n_obs, detail)
        VALUES (:step, :now, :succes, :statut, :erreur, :n_obs, :detail)
        ON CONFLICT (step) DO UPDATE SET
            last_attempt_at = EXCLUDED.last_attempt_at,
            last_success_at = COALESCE(EXCLUDED.last_success_at,
                                       learning_step_runs.last_success_at),
            last_status     = EXCLUDED.last_status,
            last_error      = EXCLUDED.last_error,
            n_obs           = COALESCE(EXCLUDED.n_obs, learning_step_runs.n_obs),
            detail          = COALESCE(EXCLUDED.detail, learning_step_runs.detail)
    """), params)


async def demarrer_etape(session: AsyncSession, step: str) -> None:
    """Marque une étape COMME DÉMARRÉE, avant d'en connaître l'issue.

    Sans cette écriture, le journal ne contient que ce qui a eu le temps de se
    terminer : un ``SIGKILL`` en plein retrain (7 nuits sur 14 en août 2026)
    n'écrit rien du tout, et la table est alors indiscernable d'une nuit où le
    scheduler n'a jamais tiré. Or ces deux pannes n'appellent pas la même
    action — la première demande de la mémoire, la seconde un scheduler.

    ``last_success_at`` est préservé (c'est l'écart qui rend la panne visible),
    mais l'erreur, le volume et le détail de la run PRÉCÉDENTE sont effacés :
    les laisser en place ferait lire au rapport du matin le verdict de la
    veille comme s'il était celui de la nuit.
    """
    await ensure_table(session)
    await session.execute(text("""
        INSERT INTO learning_step_runs
            (step, last_attempt_at, last_success_at, last_status, last_error,
             n_obs, detail)
        VALUES (:step, :now, NULL, 'en_cours', NULL, NULL, NULL)
        ON CONFLICT (step) DO UPDATE SET
            last_attempt_at = EXCLUDED.last_attempt_at,
            last_status     = 'en_cours',
            last_error      = NULL,
            n_obs           = NULL,
            detail          = NULL
    """), {"step": step, "now": _maintenant()})


def _vers_datetime(valeur) -> Optional[datetime]:
    """Normalise un horodatage lu en SQL brut en `datetime` CONSCIENT du fuseau.

    Le même `SELECT` ne rend pas le même type partout : asyncpg décode
    `TIMESTAMPTZ` en `datetime` conscient, aiosqlite renvoie la chaîne telle
    quelle. Un appelant qui compare directement à `datetime.now(timezone.utc)`
    marche donc en production et casse en test — ou l'inverse le jour où le
    driver change. C'est la même embûche que le JSON brut de `detail`, et elle
    se traite au même endroit : à la lecture, une fois pour tous les appelants.

    Un horodatage naïf est lu en UTC : c'est ce que `_maintenant()` écrit.
    """
    if valeur is None or isinstance(valeur, datetime):
        return (valeur.replace(tzinfo=timezone.utc)
                if valeur is not None and valeur.tzinfo is None else valeur)
    try:
        dt = datetime.fromisoformat(str(valeur).replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


async def dernier_run(session: AsyncSession, step: str) -> Optional[dict]:
    """État persistant d'UNE étape, décodé. ``None`` si elle n'a jamais tourné.

    C'est la source de vérité du rapport du matin : `docker logs` ne couvre que
    l'instance courante du conteneur et disparaît au moindre déploiement, la
    table non.
    """
    try:
        await ensure_table(session)
        row = (await session.execute(text("""
            SELECT step, last_attempt_at, last_success_at, last_status,
                   last_error, n_obs, detail
            FROM learning_step_runs WHERE step = :step
        """), {"step": step})).first()
    except Exception as e:
        log.warning("learning_steps.lecture_impossible", step=step, err=str(e)[:160])
        return None
    if row is None:
        return None
    detail = row[6]
    # asyncpg rend le TEXT tel quel (str) ; certains dialectes le décodent déjà.
    # Un détail illisible ne doit jamais empêcher de lire le statut.
    if isinstance(detail, str):
        try:
            detail = json.loads(detail)
        except Exception:
            detail = None
    if not isinstance(detail, dict):
        detail = None
    return {"step": row[0],
            "last_attempt_at": _vers_datetime(row[1]),
            "last_success_at": _vers_datetime(row[2]),
            "last_status": row[3], "last_error": row[4], "n_obs": row[5],
            "detail": detail}


class etape:
    """Gestionnaire de contexte : journalise une étape et n'interrompt jamais la nuit.

    ``async with etape(session_factory, "isotone_top3") as e:`` — le corps s'exécute,
    ``e.n_obs`` peut être renseigné, et l'issue est persistée dans TOUS les cas. Une
    exception est avalée (comme les ``try/except`` d'origine) mais laisse désormais
    une trace durable au lieu d'un simple ``warning`` que personne ne lit.

    La session d'écriture est PROPRE et distincte de celle de l'étape : si l'étape a
    empoisonné sa transaction (asyncpg la marque avortée), l'écriture du journal
    échouerait avec elle — et la panne redeviendrait muette au pire moment.
    """

    def __init__(self, session_factory, step: str):
        self._factory = session_factory
        self.step = step
        self.n_obs: Optional[int] = None
        self.detail: Optional[dict] = None

    async def __aenter__(self) -> "etape":
        # Marquer le DÉPART, pas seulement l'arrivée : une étape tuée par l'OOM
        # ne repasse jamais par `__aexit__`, et sans cette trace elle est
        # indiscernable d'une étape jamais lancée. Comme l'écriture de sortie,
        # elle ne doit jamais casser la nuit si le journal est indisponible.
        try:
            async with self._factory() as s:
                await demarrer_etape(s, self.step)
                await s.commit()
        except Exception as e:
            log.warning("learning_steps.journal_indisponible",
                        step=self.step, phase="demarrage", err=str(e)[:160])
        return self

    async def __aexit__(self, exc_type, exc, _tb) -> bool:
        statut = "ok" if exc is None else "echec"
        erreur = f"{exc_type.__name__}: {exc}" if exc is not None else None
        try:
            async with self._factory() as s:
                await enregistrer_etape(s, self.step, statut=statut, n_obs=self.n_obs,
                                        erreur=erreur, detail=self.detail)
                await s.commit()
        except Exception as e:      # journaliser ne doit JAMAIS casser la nuit
            log.warning("learning_steps.journal_indisponible",
                        step=self.step, err=str(e)[:160])
        if exc is not None:
            log.warning("learning_steps.etape_en_echec", step=self.step,
                        err=str(exc)[:160])
        # On avale les `Exception`, comme le faisaient les try/except d'origine :
        # une étape qui tombe ne doit pas emporter les dix suivantes. Mais JAMAIS
        # une BaseException — annulation de tâche ou interruption doivent traverser,
        # sinon un arrêt propre du worker se transformerait en nuit fantôme qui
        # continue de tourner.
        return exc is None or isinstance(exc, Exception)


async def etapes_perimees(session: AsyncSession,
                          seuil_heures: int = PERIME_APRES_HEURES) -> list[dict]:
    """Étapes dont le dernier SUCCÈS remonte à plus de `seuil_heures`.

    Inclut celles qui n'ont jamais réussi (``last_success_at`` nul) dès lors
    qu'elles ont été tentées : une étape qui échoue depuis son installation est
    exactement le cas qu'on veut voir.
    """
    try:
        await ensure_table(session)
        limite = _maintenant() - timedelta(hours=seuil_heures)
        rows = (await session.execute(text("""
            SELECT step, last_attempt_at, last_success_at, last_status, last_error
            FROM learning_step_runs
            WHERE last_success_at IS NULL OR last_success_at < :limite
        """), {"limite": limite})).all()
    except Exception as e:
        log.warning("learning_steps.lecture_impossible", err=str(e)[:160])
        return []
    return [{"step": r[0], "last_attempt_at": r[1], "last_success_at": r[2],
             "last_status": r[3], "last_error": r[4]} for r in rows]


async def etat_apprentissages(session: AsyncSession) -> dict:
    """Vue complète pour l'admin et le rapport du matin."""
    try:
        await ensure_table(session)
        rows = (await session.execute(text("""
            SELECT step, last_attempt_at, last_success_at, last_status, last_error,
                   n_obs
            FROM learning_step_runs ORDER BY step
        """))).all()
    except Exception as e:
        log.warning("learning_steps.lecture_impossible", err=str(e)[:160])
        return {"etapes": [], "perimees": [], "seuil_heures": PERIME_APRES_HEURES}
    etapes = [{"step": r[0], "last_attempt_at": r[1], "last_success_at": r[2],
               "last_status": r[3], "last_error": r[4], "n_obs": r[5]} for r in rows]
    perimees = await etapes_perimees(session)
    return {"etapes": etapes, "perimees": perimees,
            "seuil_heures": PERIME_APRES_HEURES}
