"""Journée de courses — une seule définition pour tout le projet.

Le PMU est un opérateur français : sa « journée du jour » est le jour civil à
Paris. Les conteneurs, eux, tournent en UTC. `date.today()` y bascule donc deux
heures trop tard l'été (une en hiver), et tout ce qui s'appuie dessus se trompe
de jour entre minuit et 2 h du matin, heure française.

Module volontairement sans dépendance : il est importé aussi bien par l'API que
par les scrapers (dont `scraper.base`, qui tire Playwright — l'API ne doit
surtout pas hériter de ça).
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo

PARIS = ZoneInfo("Europe/Paris")


def jour_courses(maintenant: Optional[datetime] = None) -> date:
    """Jour civil à Paris — la seule notion de « aujourd'hui » qui vaille ici.

    Symptôme qui a mené à ce module (constaté le 2026-08-20 à 00 h 11 heure de
    Paris) : la base ne contenait aucune course du jour et le programme affichait
    « Aucune course programmée » à tout visiteur. Le scraper réclamait encore au
    PMU le programme de la VEILLE, parce que son `date.today()` en UTC était
    toujours au 19. Sur les sept jours précédents, la première insertion d'une
    journée tombait systématiquement à 00 h 0x UTC, soit 02 h 0x à Paris : deux
    heures de site vide, chaque nuit.

    `maintenant` (aware) sert aux tests ; par défaut on lit l'horloge UTC.
    """
    reference = maintenant or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return reference.astimezone(PARIS).date()
