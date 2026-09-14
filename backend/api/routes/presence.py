"""
Signal de présence — cf. `services/presence.py`.

Route publique : un visiteur anonyme compte aussi. Le compte connecté est lu
dans le jeton SANS exiger qu'il soit valide — un jeton expiré fait simplement
compter la visite comme anonyme, il ne doit jamais produire de 401 (le front
tenterait un refresh toutes les 60 s pour un simple compteur).
"""
import re
from typing import Optional

from fastapi import APIRouter, Depends, Response
from jose import JWTError, jwt
from pydantic import BaseModel, Field

from api.config import get_settings
from api.routes.auth import _access_token
from services import presence

settings = get_settings()
router = APIRouter()

# Identifiant tiré par le navigateur (`crypto.randomUUID`, repli hexadécimal).
VISITEUR_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")


class Signal(BaseModel):
    v: str = Field(min_length=8, max_length=64)
    p: str = Field(default="/", max_length=200)


def _compte_du_jeton(token: Optional[str]) -> Optional[str]:
    if not token:
        return None
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except JWTError:
        return None
    return payload.get("sub") if payload.get("type") == "access" else None


@router.post("/presence", status_code=204)
async def signal_presence(
    body: Signal,
    token: Optional[str] = Depends(_access_token),
) -> Response:
    if VISITEUR_RE.match(body.v):
        # Seul le chemin est gardé : une query string peut porter un jeton de
        # vérification d'e-mail ou de réinitialisation de mot de passe.
        chemin = body.p.split("?", 1)[0].split("#", 1)[0] or "/"
        if chemin.startswith("/"):
            await presence.signaler(body.v, _compte_du_jeton(token), chemin)
    return Response(status_code=204)
