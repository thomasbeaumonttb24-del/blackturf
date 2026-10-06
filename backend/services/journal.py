"""
Données personnelles dans les journaux applicatifs.

Les journaux sont lus en clair (docker logs, sauvegardes, copies sur le PC) et
gardés bien plus longtemps que nécessaire pour une adresse : une seule fuite
de journaux livrait la liste des clients. `user_id` suffit pour enquêter ; l'adresse
n'y figure plus que masquée, juste assez pour repérer un domaine en panne.
"""
from typing import Optional


def masquer_email(adresse: Optional[str]) -> str:
    """« jean.dupont@gmail.com » → « j***@gmail.com ». Jamais d'exception."""
    if not adresse or not isinstance(adresse, str):
        return ""
    local, arobase, domaine = adresse.strip().rpartition("@")
    if not arobase:
        return "***"
    return f"{local[:1]}***@{domaine}"
