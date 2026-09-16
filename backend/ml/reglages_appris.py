"""Les RÉGLAGES APPRIS, rechargés là où l'on prédit — pas seulement au démarrage.

Le défaut
─────────
Plusieurs apprentissages nocturnes ne rejoignent l'inférence que par un cache
MÉMOIRE : l'alpha du mélange marché (`blend_calibration`), la netteté
(`sharpness_calibration`), les exposants d'arrivée (`harville_calibration`), le
mélange appris sur les arrivées (`melange_arrivees`). Ces caches n'étaient remplis
qu'à deux endroits :

  - au démarrage de l'API (`api/main.py`) ;
  - dans le job nocturne, qui tourne dans un processus RQ éphémère et meurt aussitôt.

Or ce n'est pas l'API qui écrit les prédictions : c'est le conteneur `scraper`
(`run_predictions_cycle` toutes les ~8 min, puis le calcul de T-10). Il n'appelait
AUCUN chargeur — vérifié le 2026-09-16 : aucun import de ces modules dans
`scraper/`. Toute valeur apprise et retenue restait donc apprise et jamais servie
sur ~100 % des prédictions, et servie seulement jusqu'au redémarrage suivant par
l'API (conteneurs en service depuis 45 h ce jour-là).

Ce que fait ce module
─────────────────────
Un seul point d'entrée, `rafraichir(session)`, appelé en tête de `predict_course`
et des routes qui génèrent un plan. Il relit les réglages en base au plus une fois
toutes les `TTL_S` secondes par processus : quatre `SELECT` d'une ligne, rien au
regard du calcul d'une course.

Ce qu'il ne fait PAS : recharger l'état adaptatif (`adaptive_learning` :
température du placé, poids de features). Ce chargement changerait la proba placé
servie par le scraper — où ces réglages n'ont jamais agi — sans mesure hors
échantillon de l'effet ; il relève d'une décision séparée, pas d'une réparation de
plomberie.
"""
from __future__ import annotations

import time
from typing import Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

log = structlog.get_logger(module="reglages_appris")

# Le nocturne réécrit ces valeurs une fois par nuit : 5 minutes de latence au pire
# après la fin du recalcul, contre « au prochain redémarrage » avant.
TTL_S = 300.0

_dernier: float = float("-inf")


async def rafraichir(session: Optional[AsyncSession] = None, force: bool = False) -> bool:
    """Recharge les caches si le délai est écoulé. Ne lève jamais.

    Renvoie True si une relecture a eu lieu.

    SESSION DÉDIÉE par défaut, jamais celle de l'appelant : un chargeur qui échoue
    (table absente avant la première nuit) fait `rollback` pour désempoisonner la
    transaction — sur la session d'une route, ce rollback EXPIRE les objets déjà
    chargés (la course, l'utilisateur) et la lecture suivante d'un attribut lève
    `MissingGreenlet`. Vécu en test sur /mise-plan. `session` n'est passé que par
    les tests.
    """
    global _dernier
    maintenant = time.monotonic()
    if not force and maintenant - _dernier < TTL_S:
        return False
    _dernier = maintenant
    try:
        from ml.blend_calibration import charger_alpha
        from ml.harville_calibration import charger_exposants
        from ml.melange_arrivees import charger as charger_melange
        from ml.sharpness_calibration import charger_exposant
    except Exception as e:                                       # noqa: BLE001
        log.warning("reglages_appris.import_impossible", err=str(e)[:140])
        return False

    async def _tout(s: AsyncSession) -> None:
        for nom, chargeur in (("alpha", charger_alpha), ("nettete", charger_exposant),
                              ("harville", charger_exposants), ("melange", charger_melange)):
            try:
                await chargeur(s)
            except Exception as e:                               # noqa: BLE001
                log.warning("reglages_appris.chargement_ignore", reglage=nom,
                            err=str(e)[:140])

    if session is not None:
        await _tout(session)
        return True
    try:
        from db.database import AsyncSessionLocal
        async with AsyncSessionLocal() as propre:
            await _tout(propre)
    except Exception as e:                                       # noqa: BLE001
        log.warning("reglages_appris.session_impossible", err=str(e)[:140])
    return True
