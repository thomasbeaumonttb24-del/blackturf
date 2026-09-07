"""Quels paris de valeur un utilisateur a le droit de VOIR — règle unique.

Quatre surfaces affichent des paris de valeur : la fiche course (carte « pari
de valeur », badges ★ du tableau des partants, analyse), la page /value-bets,
le flux WebSocket qui la rafraîchit et le compteur public du bandeau Free.
Jusqu'au 2026-09-07 chacune portait sa propre copie des filtres, et la fiche
course RECALCULAIT le pari à la cote du moment avec moins d'entrées que le
cycle (ni historique de cotes, ni suspensions, ni signaux appris) : un cheval
pouvait être ★★★ sur sa fiche et absent de /value-bets, ou l'inverse, et le
délai de 15 min du plan Standard ne s'appliquait qu'à la page dédiée.

La source de vérité est la table `value_bets`, écrite par le cycle de
prédiction (toutes les 8 min, cf. orchestrator) qui désactive puis ré-écrit les
paris d'une course à chaque passage. Ce module dit qui voit quoi ; il ne
détecte rien.

Décisions produit du 2026-09-07 (Thomas), après mesure sur 60 jours et 2 115
paris réglés, cotes plafonnées à 20 :
  - ★ (niveau 1) perd plus que le hasard : −18 % ± 12 contre −5 % pour un
    partant pris au hasard → jamais affiché ;
  - à l'étranger, seuls les ★★★★ tiennent (+59 % ± 57, n=31) ; les niveaux
    1-3 y font −22 % ± 14 → masqués.
Le cycle continue d'ÉCRIRE ces paris (mesure, apprentissage) : c'est
l'affichage qui les tait, ici et nulle part ailleurs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import exists, or_, select, text

from db.models import Course, Hippodrome, ValueBet
from services.hippodromes import ZONE_ETRANGER, zone_hippodrome

# Passé ce délai après le départ, le pari n'a plus d'objet — résultat connu ou
# pas (cf. job_expire_stale_value_bets, qui pose `actif=false` toutes les 15 min ;
# ce filtre rend les lectures correctes entre deux exécutions).
FENETRE_APRES_DEPART = timedelta(hours=6)

# Plan Standard : paris de valeur servis avec 15 min de retard (briefing §4.2).
DELAI_STANDARD = timedelta(minutes=15)
PLANS_DIFFERES = ("standard",)

STATUTS_OUVERTS = ("a_venir", "en_cours")

# Niveau minimum affiché partout, et niveau minimum sur une course étrangère.
NIVEAU_MIN_VISIBLE = 2
NIVEAU_MIN_ETRANGER = 4

# Même définition de « France » que `services.hippodromes` : ISO3 écrit par le
# scraper, 'FR' toléré sur les lignes anciennes. Un hippodrome ABSENT de la
# table (1,5 % des courses, Saint-Malo surtout) est traité comme français :
# un pays manquant ne prouve pas l'étranger.
_CODES_FRANCE = ("FRA", "FR")


def _maintenant(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


def cutoff_detection(plan: Optional[str], now: Optional[datetime] = None) -> Optional[datetime]:
    """Instant avant lequel un pari doit avoir été détecté pour être visible.

    None = aucun délai (plans en direct, appels sans utilisateur comme le
    compteur public — qui ne livre qu'un total, jamais un pari).
    """
    if plan in PLANS_DIFFERES:
        return _maintenant(now) - DELAI_STANDARD
    return None


def _condition_zone_sql():
    """Niveau ≥ NIVEAU_MIN_ETRANGER, OU course qui n'est pas à l'étranger.

    « À l'étranger » = un hippodrome de même nom existe dans la table avec un
    pays hors France. La sous-requête corrélée porte sur `Course.hippodrome_nom`
    (jamais `reunions`, dont 15 lignes sont recyclées pour 360 journées).
    """
    a_l_etranger = exists(
        select(Hippodrome.hippodrome_id).where(
            Hippodrome.nom == Course.hippodrome_nom,
            Hippodrome.pays.notin_(_CODES_FRANCE),
        )
    )
    return or_(ValueBet.niveau >= NIVEAU_MIN_ETRANGER, ~a_l_etranger)


def filtres_sql(plan: Optional[str], now: Optional[datetime] = None) -> list:
    """Conditions SQLAlchemy à appliquer à une requête joignant ValueBet et Course.

    Même liste pour GET /value-bets, le flux WS, le compteur, le tableau de
    bord, les notifications et l'assistant : une divergence entre eux serait
    un bug, pas un réglage.
    """
    t = _maintenant(now)
    conds = [
        ValueBet.actif == True,  # noqa: E712 — SQLAlchemy
        Course.statut.in_(STATUTS_OUVERTS),
        Course.date_heure >= t - FENETRE_APRES_DEPART,
        ValueBet.niveau >= NIVEAU_MIN_VISIBLE,
        _condition_zone_sql(),
    ]
    cutoff = cutoff_detection(plan, t)
    if cutoff is not None:
        conds.append(ValueBet.detecte_a <= cutoff)
    return conds


async def course_etrangere(session, hippodrome_nom: Optional[str]) -> bool:
    """True si la course se court hors de France (même règle que `_condition_zone_sql`).

    Sert aux lectures d'UNE course (fiche, analyse) qui filtrent en Python.
    """
    return (await zone_hippodrome(session, hippodrome_nom)) == ZONE_ETRANGER


def _en_utc(d: datetime) -> datetime:
    # `detecte_a` est écrit en naïf par le cycle (`datetime.now()`, conteneur en
    # UTC) et relu tantôt aware (asyncpg) tantôt naïf (SQLite en test).
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def visible(vb, plan: Optional[str], now: Optional[datetime] = None, *, etranger: bool = False) -> bool:
    """Même règle que `filtres_sql`, appliquée en Python à UN pari déjà chargé.

    Sert à la fiche course, où les paris d'une course sont lus en bloc puis
    rattachés aux partants : ce qui n'est pas visible n'est pas servi (le
    navigateur ne doit pas recevoir ce qu'il n'a pas le droit d'afficher).
    `etranger` vient de `course_etrangere(...)`, calculé une fois par course.
    """
    if not getattr(vb, "actif", False):
        return False
    niveau = int(getattr(vb, "niveau", 0) or 0)
    if niveau < NIVEAU_MIN_VISIBLE:
        return False
    if etranger and niveau < NIVEAU_MIN_ETRANGER:
        return False
    cutoff = cutoff_detection(plan, now)
    if cutoff is None:
        return True
    detecte = getattr(vb, "detecte_a", None)
    if detecte is None:
        # Pas d'horodatage = impossible de prouver que le délai est écoulé.
        return False
    return _en_utc(detecte) <= _en_utc(cutoff)
