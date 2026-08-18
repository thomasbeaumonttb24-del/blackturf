"""
Devises des gains de carrière — BlackTurf.

PROBLÈME RÉSOLU ICI (constaté le 2026-08-17)
--------------------------------------------
`performances_carriere.gains_carriere_total` est écrasé à chaque scrape du cheval
(cf. scraper/db_writer.py) avec la valeur `gainsParticipant.gainsCarriere` renvoyée
par l'API PMU pour la réunion en cours. Or le PMU renvoie ce montant dans la devise
LOCALE de la réunion : un cheval qui court à San Isidro voit ses gains stockés en
pesos argentins, à Sha Tin en dollars de Hong Kong, etc.

Le montant était affiché partout suivi d'un « € », ce qui produisait des aberrations
(médiane 12 077 800 « € » pour les chevaux argentins, maximum 99 899 800 « € »).

Mesure prod du 2026-08-18 sur les 48 837 chevaux à gains > 0, regroupés par pays de
leur DERNIÈRE participation — la médiane suit exactement la force de la devise :

    ARG 12 077 800 · CHL 9 819 900 · TUR 9 282 500 · HKG 1 731 100
    URY   515 340 · USA    78 750 · GBR    24 094 · FRA    32 170

Sur les 4 293 chevaux affichés à plus de 5 M « € », 4 274 (99,5 %) ont leur dernière
course hors zone euro. La division par 100 (centimes → unité) est correcte et n'est
pas touchée : seule l'UNITÉ monétaire était fausse.

RÈGLE RETENUE
-------------
La devise d'un montant de carrière = celle du pays de la DERNIÈRE participation
connue du cheval, puisque c'est ce scrape-là qui a écrit la valeur en base.
Pas de conversion : le projet interdit les chiffres inventés, un taux de change figé
en serait un. On expose la devise réelle, ou rien du tout si on ne sait pas.
"""
from __future__ import annotations

from typing import Iterable, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger()

# ─────────────────────────────────────────────
# Pays (ISO 3166-1 alpha-3, tel que stocké dans hippodromes.pays et
# historique_courses.pays) → devise ISO 4217.
# `historique_courses.pays` contient aussi l'alias historique "FR".
# ─────────────────────────────────────────────
PAYS_DEVISE: dict[str, str] = {
    # Zone euro
    "FRA": "EUR", "FR": "EUR", "BEL": "EUR", "DEU": "EUR", "ESP": "EUR",
    "ITA": "EUR", "NLD": "EUR", "IRL": "EUR", "AUT": "EUR", "FIN": "EUR",
    "PRT": "EUR", "GRC": "EUR", "LUX": "EUR", "SVK": "EUR", "SVN": "EUR",
    "EST": "EUR", "LVA": "EUR", "LTU": "EUR", "CYP": "EUR", "MLT": "EUR",
    "HRV": "EUR",
    # Europe hors euro
    "GBR": "GBP", "CHE": "CHF", "SWE": "SEK", "NOR": "NOK", "DNK": "DKK",
    "POL": "PLN", "CZE": "CZK", "HUN": "HUF", "TUR": "TRY", "RUS": "RUB",
    # Amériques
    "USA": "USD", "CAN": "CAD", "ARG": "ARS", "CHL": "CLP", "URY": "UYU",
    "BRA": "BRL", "PER": "PEN", "MEX": "MXN",
    # Asie / Pacifique
    "JPN": "JPY", "HKG": "HKD", "SGP": "SGD", "KOR": "KRW", "CHN": "CNY",
    "IND": "INR", "AUS": "AUD", "NZL": "NZD",
    # Afrique / Moyen-Orient
    "ARE": "AED", "SAU": "SAR", "QAT": "QAR", "BHR": "BHD", "MAR": "MAD",
    "TUN": "TND", "ZAF": "ZAR",
}


def devise_pour_pays(pays: Optional[str]) -> Optional[str]:
    """Code ISO 4217 du pays, ou None si le pays est inconnu/non cartographié.

    On ne devine pas : un pays absent de la table renvoie None, ce qui fait
    disparaître le montant côté UI plutôt que de l'afficher dans une devise fausse.
    """
    if not pays:
        return None
    return PAYS_DEVISE.get(pays.strip().upper())


async def devises_gains_carriere(
    db: AsyncSession, cheval_ids: Iterable[str]
) -> dict[str, Optional[str]]:
    """Devise des gains de carrière stockés, pour un lot de chevaux.

    Source primaire : pays de l'hippodrome de la dernière participation connue
    (courses.hippodrome_nom → hippodromes.pays). `reunions` ne conserve que les
    réunions du jour (R1..R15 réutilisés quotidiennement) et ne peut donc PAS
    servir à retrouver le pays d'une course passée — d'où le passage par
    `courses.hippodrome_nom`, dénormalisé et stable.

    Repli : pays de la dernière ligne `historique_courses` du cheval, pour les
    hippodromes dont le nom ne matche aucune ligne de la table `hippodromes`.

    Renvoie {cheval_id: devise ISO 4217 ou None}. Les chevaux sans participation
    ni historique sont absents du dict (donc None à la lecture).
    """
    ids = [c for c in cheval_ids if c]
    if not ids:
        return {}

    from db.models import Course, HistoriqueCourse, Hippodrome, Participation

    devises: dict[str, Optional[str]] = {}

    # ── 1. Pays de la dernière participation (via l'hippodrome de la course) ──
    try:
        rang = (
            func.row_number()
            .over(
                partition_by=Participation.cheval_id,
                order_by=Course.date_heure.desc(),
            )
            .label("rang")
        )
        sub = (
            select(Participation.cheval_id.label("cheval_id"),
                   Hippodrome.pays.label("pays"),
                   rang)
            .join(Course, Course.course_id == Participation.course_id)
            .outerjoin(Hippodrome, Hippodrome.nom == Course.hippodrome_nom)
            .where(Participation.cheval_id.in_(ids))
            .subquery()
        )
        rows = (await db.execute(
            select(sub.c.cheval_id, sub.c.pays).where(sub.c.rang == 1)
        )).all()
        for cheval_id, pays in rows:
            devise = devise_pour_pays(pays)
            if devise:
                devises[cheval_id] = devise
    except Exception as e:  # pragma: no cover - défensif, l'UI dégrade en "—"
        log.warning("devises.participation_lookup_failed", error=str(e)[:200])

    # ── 2. Repli historique_courses pour les chevaux non résolus ──
    manquants = [c for c in ids if c not in devises]
    if manquants:
        try:
            rang_h = (
                func.row_number()
                .over(
                    partition_by=HistoriqueCourse.cheval_id,
                    order_by=HistoriqueCourse.date_course.desc(),
                )
                .label("rang")
            )
            sub_h = (
                select(HistoriqueCourse.cheval_id.label("cheval_id"),
                       HistoriqueCourse.pays.label("pays"),
                       rang_h)
                .where(
                    HistoriqueCourse.cheval_id.in_(manquants),
                    HistoriqueCourse.pays.isnot(None),
                )
                .subquery()
            )
            rows_h = (await db.execute(
                select(sub_h.c.cheval_id, sub_h.c.pays).where(sub_h.c.rang == 1)
            )).all()
            for cheval_id, pays in rows_h:
                devise = devise_pour_pays(pays)
                if devise:
                    devises[cheval_id] = devise
        except Exception as e:  # pragma: no cover
            log.warning("devises.historique_lookup_failed", error=str(e)[:200])

    return devises


async def devise_gains_carriere(db: AsyncSession, cheval_id: str) -> Optional[str]:
    """Variante unitaire de `devises_gains_carriere` (fiche cheval)."""
    return (await devises_gains_carriere(db, [cheval_id])).get(cheval_id)
