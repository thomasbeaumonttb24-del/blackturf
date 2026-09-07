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
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from db.models import Course, ValueBet

# Passé ce délai après le départ, le pari n'a plus d'objet — résultat connu ou
# pas (cf. job_expire_stale_value_bets, qui pose `actif=false` toutes les 15 min ;
# ce filtre rend les lectures correctes entre deux exécutions).
FENETRE_APRES_DEPART = timedelta(hours=6)

# Plan Standard : paris de valeur servis avec 15 min de retard (briefing §4.2).
DELAI_STANDARD = timedelta(minutes=15)
PLANS_DIFFERES = ("standard",)

STATUTS_OUVERTS = ("a_venir", "en_cours")


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


def filtres_sql(plan: Optional[str], now: Optional[datetime] = None) -> list:
    """Conditions SQLAlchemy à appliquer à une requête joignant ValueBet et Course.

    Même liste pour GET /value-bets, le flux WS et le compteur : une divergence
    entre eux serait un bug, pas un réglage.
    """
    t = _maintenant(now)
    conds = [
        ValueBet.actif == True,  # noqa: E712 — SQLAlchemy
        Course.statut.in_(STATUTS_OUVERTS),
        Course.date_heure >= t - FENETRE_APRES_DEPART,
    ]
    cutoff = cutoff_detection(plan, t)
    if cutoff is not None:
        conds.append(ValueBet.detecte_a <= cutoff)
    return conds


def _en_utc(d: datetime) -> datetime:
    # `detecte_a` est écrit en naïf par le cycle (`datetime.now()`, conteneur en
    # UTC) et relu tantôt aware (asyncpg) tantôt naïf (SQLite en test).
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def visible(vb, plan: Optional[str], now: Optional[datetime] = None) -> bool:
    """Même règle que `filtres_sql`, appliquée en Python à UN pari déjà chargé.

    Sert à la fiche course, où les paris d'une course sont lus en bloc puis
    rattachés aux partants : ce qui n'est pas visible n'est pas servi (le
    navigateur ne doit pas recevoir ce qu'il n'a pas le droit d'afficher).
    """
    if not getattr(vb, "actif", False):
        return False
    cutoff = cutoff_detection(plan, now)
    if cutoff is None:
        return True
    detecte = getattr(vb, "detecte_a", None)
    if detecte is None:
        # Pas d'horodatage = impossible de prouver que le délai est écoulé.
        return False
    return _en_utc(detecte) <= _en_utc(cutoff)
