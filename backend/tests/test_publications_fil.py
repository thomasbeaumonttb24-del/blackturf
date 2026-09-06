"""Le fil ne reçoit qu'UNE publication par semaine, et jamais une par jour.

Ce qui s'est passé le 2026-09-06 : `INSTAGRAM_PUBLICATION_ACTIVE` est un interrupteur
UNIQUE pour tous les canaux. Ouvert pour la story de bilan, il a du même coup
déverrouillé deux jobs de fil qui dormaient en simulation depuis leur écriture —
`publication_matin` (09:15, « Quinté+ du jour ») et `publication_soir` (20:45).
Le post du matin est parti dans le fil le jour même, sans que personne ne l'ait
demandé, et il a fallu le supprimer à la main.

Retirer les deux jobs du planificateur est la seule mesure qui tienne : tant qu'ils y
sont, n'importe quel futur usage de l'interrupteur les réveille. Un test le vérifie,
parce que la tentation de les remettre « juste pour essayer » est exactement ce qui
a produit l'incident.

Les FONCTIONS restent : elles sont appelables à la main pour un cas ponctuel. Ce qui
est interdit, c'est leur déclenchement automatique.
"""
from __future__ import annotations

import re

from tests._descripteurs_deploiement import RACINE, exiger

JOBS = RACINE / "backend" / "services" / "jobs.py"

# Identifiants de jobs qui publieraient dans le FIL tous les jours.
INTERDITS = ("publication_matin", "publication_soir")


def _enregistrements(source: str) -> set[str]:
    """Les `id=` réellement passés à `scheduler.add_job`."""
    return set(re.findall(r'id="([a-z0-9_]+)"', source))


def test_aucune_publication_quotidienne_dans_le_fil():
    ids = _enregistrements(exiger(JOBS))
    fautifs = sorted(ids & set(INTERDITS))
    assert not fautifs, (
        "ces jobs publient dans le fil tous les jours et ne doivent plus être "
        f"planifiés : {fautifs}. Le fil ne reçoit qu'une publication par semaine, "
        "le dimanche."
    )


def test_la_story_de_bilan_reste_planifiee():
    """Garde symétrique : en retirant les jobs de fil, on ne doit pas emporter la
    story — c'est elle qu'on veut automatique."""
    assert "publication_story" in _enregistrements(exiger(JOBS))


def test_les_fonctions_restent_appelables_a_la_main():
    """Un cas ponctuel doit rester possible sans réécrire le service."""
    from services.jobs import job_publication_matin, job_publication_soir
    assert callable(job_publication_matin) and callable(job_publication_soir)
