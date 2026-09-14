"""
Présence en ligne — combien de personnes ont le site ouvert en ce moment.

Aucune mesure n'existait : `users.last_login_at` date une CONNEXION (la session
vit 7 jours), pas une visite, et un visiteur anonyme n'y apparaît jamais.

Principe : chaque onglet ouvert envoie un signal toutes les 60 s tant qu'il est
visible (`POST /api/v1/presence`). Redis garde le dernier signal de chaque
visiteur dans un ensemble trié (score = horodatage) ; est « en ligne » tout
visiteur vu dans les `FENETRE_S` dernières secondes.

Ce qui est stocké, et rien d'autre : un identifiant aléatoire tiré par le
navigateur (ou l'identifiant du compte connecté), la page courante et l'heure.
Pas d'IP, pas d'agent utilisateur. Tout expire seul après la fenêtre.

Fail-open partout : une panne Redis ne doit ni casser la navigation d'un
visiteur, ni faire planter la console — elle renvoie simplement « inconnu ».
"""
from __future__ import annotations

import json
import time
from typing import Optional

import structlog

from db.redis_client import get_redis

log = structlog.get_logger()

# Au-delà de 5 minutes sans signal, l'onglet est fermé ou oublié en arrière-plan.
FENETRE_S = 300
CLE_ENSEMBLE = "presence:vus"
PREFIXE_INFO = "presence:info:"


def membre(visiteur: str, user_id: Optional[str]) -> str:
    """Un compte connecté compte UNE fois, quel que soit le nombre d'onglets ou
    d'appareils ; un anonyme est identifié par son tirage aléatoire."""
    return f"u:{user_id}" if user_id else f"a:{visiteur}"


async def signaler(visiteur: str, user_id: Optional[str], chemin: str) -> None:
    maintenant = time.time()
    m = membre(visiteur, user_id)
    try:
        redis = await get_redis()
        pipe = redis.pipeline()
        pipe.zadd(CLE_ENSEMBLE, {m: maintenant})
        pipe.zremrangebyscore(CLE_ENSEMBLE, 0, maintenant - FENETRE_S)
        pipe.set(PREFIXE_INFO + m, json.dumps({"chemin": chemin, "vu": maintenant}),
                 ex=FENETRE_S)
        await pipe.execute()
    except Exception as e:  # noqa: BLE001
        log.warning("presence.signal_ignore", err=str(e)[:120])


async def en_ligne() -> Optional[dict]:
    """Photo de l'instant. `None` si Redis ne répond pas — jamais un faux zéro."""
    maintenant = time.time()
    try:
        redis = await get_redis()
        await redis.zremrangebyscore(CLE_ENSEMBLE, 0, maintenant - FENETRE_S)
        membres = await redis.zrangebyscore(CLE_ENSEMBLE, maintenant - FENETRE_S, "+inf")
        membres = [m.decode() if isinstance(m, bytes) else m for m in membres]
        infos = await redis.mget([PREFIXE_INFO + m for m in membres]) if membres else []
    except Exception as e:  # noqa: BLE001
        log.warning("presence.lecture_impossible", err=str(e)[:120])
        return None

    visiteurs = []
    for m, brut in zip(membres, infos):
        info = {}
        if brut:
            try:
                info = json.loads(brut)
            except (ValueError, TypeError):
                info = {}
        visiteurs.append({
            "user_id": m[2:] if m.startswith("u:") else None,
            "chemin": info.get("chemin"),
            "vu_il_y_a_s": round(maintenant - info["vu"]) if info.get("vu") else None,
        })
    return {"fenetre_s": FENETRE_S, "visiteurs": visiteurs}
