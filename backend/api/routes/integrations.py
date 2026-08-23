"""
Intégrations tierces — dépôt des jetons depuis l'administration.

GET    /admin/api/integrations/instagram  — état (JAMAIS la valeur du jeton)
POST   /admin/api/integrations/instagram  — déposer ou remplacer le jeton
POST   /admin/api/integrations/instagram/renouveler — forcer un renouvellement
POST   /admin/api/integrations/instagram/tester     — vérifier que le jeton fonctionne
DELETE /admin/api/integrations/instagram  — retirer le jeton

POURQUOI PASSER PAR L'ADMIN plutôt que par un fichier `.env` :

- un jeton est un secret et ne doit transiter ni par un chat, ni par un historique de
  shell ; ici il part du navigateur vers le serveur sur une connexion chiffrée ;
- l'exploitant n'a pas à savoir se connecter en SSH pour faire vivre son produit ;
- déposé en base, le jeton peut être RENOUVELÉ automatiquement — un jeton Instagram
  expire au bout de 60 jours, et dans un fichier il expirerait sans prévenir.

Aucune route ne renvoie jamais la valeur du jeton : une interface qui réaffiche un secret
finit par le laisser fuiter dans une capture d'écran ou un journal de navigateur.
"""
from typing import Optional

import httpx
import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import require_admin
from db.database import get_db
from db.models import User
from services import jetons as svc_jetons

log = structlog.get_logger()
router = APIRouter()


class DepotJetonIn(BaseModel):
    # Un jeton Instagram longue durée fait bien plus de 50 caractères ; la borne basse
    # écarte un collage tronqué, l'erreur la plus fréquente.
    jeton: str = Field(min_length=50, max_length=1000)
    compte_id: Optional[str] = Field(default=None, max_length=64)


@router.get("/integrations/instagram")
async def etat_instagram(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    jeton = await svc_jetons.lire(db)
    return svc_jetons.etat_public(jeton)


@router.post("/integrations/instagram")
async def deposer_instagram(
    payload: DepotJetonIn,
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Dépose le jeton, puis le VÉRIFIE immédiatement auprès d'Instagram.

    Vérifier tout de suite évite le pire scénario : un jeton mal collé accepté sans
    broncher, et une publication qui échoue en silence des semaines plus tard. La
    vérification renvoie aussi la durée de validité réelle, qui sert à programmer le
    renouvellement.
    """
    valeur = payload.jeton.strip()

    ok, detail = await _verifier(valeur)
    if not ok:
        # On n'enregistre pas un jeton qui ne fonctionne pas : mieux vaut un message
        # clair tout de suite qu'une intégration qui se croit configurée.
        raise HTTPException(status_code=400, detail=f"Jeton refusé par Instagram : {detail}")

    compte_id = payload.compte_id or detail.get("user_id") if isinstance(detail, dict) else None
    duree = detail.get("expire_dans") if isinstance(detail, dict) else None

    jeton = await svc_jetons.deposer(
        db, valeur, compte_id=compte_id, duree_secondes=duree
    )
    return {"ok": True, **svc_jetons.etat_public(jeton)}


@router.post("/integrations/instagram/renouveler")
async def renouveler_instagram(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    ok, raison = await svc_jetons.renouveler_instagram(db)
    jeton = await svc_jetons.lire(db)
    return {"ok": ok, "raison": raison, **svc_jetons.etat_public(jeton)}


@router.post("/integrations/instagram/tester")
async def tester_instagram(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """Interroge Instagram avec le jeton enregistré et renvoie le compte reconnu."""
    jeton = await svc_jetons.lire(db)
    if jeton is None:
        raise HTTPException(status_code=404, detail="Aucun jeton enregistré")

    ok, detail = await _verifier(jeton.valeur)
    if not ok:
        return {"ok": False, "detail": detail}
    return {"ok": True, **(detail if isinstance(detail, dict) else {})}


@router.delete("/integrations/instagram")
async def supprimer_instagram(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    return {"ok": await svc_jetons.supprimer(db)}


async def _verifier(valeur: str):
    """
    Appelle `/me` avec le jeton. Renvoie (True, infos) ou (False, raison lisible).

    On demande explicitement `user_id` et `username` : afficher à l'exploitant le nom du
    compte reconnu est la seule preuve qu'il a collé le jeton du BON compte — il en gère
    plusieurs.
    """
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                "https://graph.instagram.com/v21.0/me",
                params={"fields": "user_id,username", "access_token": valeur},
            )
        if resp.status_code != 200:
            corps = resp.json() if resp.headers.get("content-type", "").startswith("application/json") else {}
            message = (corps.get("error") or {}).get("message") or f"code {resp.status_code}"
            return False, message
        data = resp.json()
        return True, {
            "user_id": str(data.get("user_id") or ""),
            "username": data.get("username"),
            # Un jeton fraîchement généré par l'interface Meta vaut 60 jours.
            "expire_dans": 60 * 24 * 3600,
        }
    except Exception as e:  # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"[:200]


@router.post("/integrations/instagram/publier-mosaique")
async def publier_mosaique_instagram(
    db: AsyncSession = Depends(get_db),
    _: User = Depends(require_admin),
):
    """
    Publie la mosaïque du jour — six publications qui forment une seule image sur la
    grille du profil.

    Les tuiles et leurs légendes viennent du SITE, déjà triées dans l'ordre de
    publication : la grille se remplissant du plus récent en haut à gauche, il faut
    publier à l'envers, et cet ordre est une propriété de la composition, pas de l'API.

    Cette route ne publie QUE si l'interrupteur global est ouvert. Elle ne le force
    jamais : publier au nom d'une marque reste une décision explicite.
    """
    from services.instagram import publier_mosaique, publication_active

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "http://frontend:3000/visuels/mosaique/legendes.json",
                headers={"Host": "blackturf.fr"},
            )
            resp.raise_for_status()
            tuiles = resp.json().get("tuiles", [])
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Mosaïque indisponible : {e}"[:200])

    if len(tuiles) != 6:
        raise HTTPException(status_code=502, detail=f"Mosaïque incomplète ({len(tuiles)} tuiles)")

    resultats = await publier_mosaique(tuiles)
    return {
        "publication_active": publication_active(),
        "tuiles": resultats,
        "publiees": sum(1 for r in resultats if r["publie"]),
    }
