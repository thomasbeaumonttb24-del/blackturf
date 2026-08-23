"""
Dépôt et renouvellement des jetons d'accès des services tiers.

POURQUOI CE MODULE EXISTE — deux contraintes qui se rencontrent :

1. Un jeton d'accès est un SECRET : quiconque le lit publie au nom de la marque. Il ne
   doit donc transiter ni par un chat, ni par un historique de shell.
2. L'exploitant n'a pas à savoir se connecter en SSH pour faire vivre son produit.

D'où le dépôt depuis une page d'administration, sur une connexion chiffrée, plutôt qu'un
fichier `.env` édité à la main.

LE RENOUVELLEMENT N'EST PAS UN LUXE. Un jeton longue durée Instagram expire au bout de
**60 jours**. Sans renouvellement automatique, la publication s'arrêterait sans prévenir
deux mois après la mise en service — et personne ne s'en apercevrait avant des semaines.
Le point d'entrée de renouvellement d'Instagram ne demande QUE le jeton lui-même (pas la
clé secrète de l'application) : tout peut donc se faire côté serveur, sans rien
redemander à personne.
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import JetonIntegration

log = structlog.get_logger()

INSTAGRAM = "instagram"

# Un jeton Instagram longue durée dure 60 jours et ne peut être renouvelé qu'après
# 24 heures d'existence. On renouvelle à 10 jours de l'échéance : assez tôt pour absorber
# plusieurs échecs consécutifs, assez tard pour ne pas renouveler à chaque passage.
MARGE_RENOUVELLEMENT = timedelta(days=10)


def _maintenant() -> datetime:
    return datetime.now(timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    """
    Ramène une date relue en base à une date AVEC fuseau.

    Toutes les colonnes sont déclarées `timezone=True`, mais une valeur relue peut
    revenir sans fuseau selon le moteur — c'est le cas sur SQLite, et cela arrive aussi
    sur PostgreSQL avec certaines colonnes héritées. Soustraire une date naïve d'une date
    aware lève un TypeError : la comparaison d'échéance planterait donc au moment précis
    où on en a besoin, à la relecture du jeton.
    """
    if dt is None:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


async def lire(db: AsyncSession, fournisseur: str = INSTAGRAM) -> Optional[JetonIntegration]:
    res = await db.execute(
        select(JetonIntegration).where(JetonIntegration.fournisseur == fournisseur)
    )
    return res.scalar_one_or_none()


async def deposer(
    db: AsyncSession,
    valeur: str,
    fournisseur: str = INSTAGRAM,
    compte_id: Optional[str] = None,
    duree_secondes: Optional[int] = None,
) -> JetonIntegration:
    """
    Enregistre ou remplace le jeton d'un fournisseur.

    Une seule ligne par fournisseur : deux jetons concurrents pour le même compte, c'est
    la garantie d'utiliser le mauvais. Un dépôt efface donc la dernière erreur connue —
    le nouveau jeton mérite d'être jugé sur ses propres appels.
    """
    jeton = await lire(db, fournisseur)
    expire_at = _maintenant() + timedelta(seconds=duree_secondes) if duree_secondes else None

    if jeton is None:
        jeton = JetonIntegration(fournisseur=fournisseur, valeur=valeur)
        db.add(jeton)

    jeton.valeur = valeur
    jeton.compte_id = compte_id or jeton.compte_id
    jeton.expire_at = expire_at
    jeton.derniere_erreur = None
    await db.commit()
    log.info("jetons.depose", fournisseur=fournisseur, expire_at=str(expire_at))
    return jeton


async def supprimer(db: AsyncSession, fournisseur: str = INSTAGRAM) -> bool:
    jeton = await lire(db, fournisseur)
    if jeton is None:
        return False
    await db.delete(jeton)
    await db.commit()
    log.info("jetons.supprime", fournisseur=fournisseur)
    return True


async def renouveler_instagram(db: AsyncSession) -> tuple[bool, Optional[str]]:
    """
    Prolonge le jeton Instagram de 60 jours. Renvoie (succès, raison d'échec).

    Best-effort : ne lève jamais — l'appelant est un job programmé, et une exception y
    arrêterait les tâches suivantes. En cas d'échec, la raison est ÉCRITE EN BASE :
    sans cela, un renouvellement qui échoue silencieusement se solde par une publication
    morte deux mois plus tard, sans la moindre trace pour comprendre.
    """
    jeton = await lire(db, INSTAGRAM)
    if jeton is None:
        return False, "aucun jeton enregistré"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                "https://graph.instagram.com/refresh_access_token",
                params={"grant_type": "ig_refresh_token", "access_token": jeton.valeur},
            )
        if resp.status_code != 200:
            raison = f"refus du service ({resp.status_code})"
            jeton.derniere_erreur = f"{raison} — {resp.text[:300]}"
            await db.commit()
            log.warning("jetons.renouvellement.refuse", status=resp.status_code)
            return False, raison

        data = resp.json()
        nouveau = data.get("access_token")
        duree = int(data.get("expires_in") or 0)
        if not nouveau:
            jeton.derniere_erreur = "réponse sans access_token"
            await db.commit()
            return False, "réponse sans access_token"

        jeton.valeur = nouveau
        jeton.expire_at = _maintenant() + timedelta(seconds=duree) if duree else None
        jeton.dernier_renouvellement_at = _maintenant()
        jeton.derniere_erreur = None
        await db.commit()
        log.info("jetons.renouvelle", fournisseur=INSTAGRAM, expire_at=str(jeton.expire_at))
        return True, None

    except Exception as e:  # noqa: BLE001
        raison = f"{type(e).__name__}: {e}"[:200]
        try:
            jeton.derniere_erreur = raison
            await db.commit()
        except Exception:  # noqa: BLE001
            pass
        log.warning("jetons.renouvellement.echec", err=raison)
        return False, raison


def renouvellement_necessaire(jeton: Optional[JetonIntegration]) -> bool:
    if jeton is None or jeton.expire_at is None:
        # Sans date d'expiration connue, on renouvelle : Instagram tolère un
        # renouvellement anticipé, alors qu'un jeton expiré ne se rattrape pas.
        return jeton is not None
    return _aware(jeton.expire_at) - _maintenant() <= MARGE_RENOUVELLEMENT


def etat_public(jeton: Optional[JetonIntegration]) -> dict:
    """
    État lisible pour l'administration. **Ne renvoie JAMAIS la valeur du jeton** — une
    interface qui réaffiche un secret finit par le laisser fuiter dans une capture
    d'écran ou un journal de navigateur.
    """
    if jeton is None:
        return {"configure": False}
    return {
        "configure": True,
        "compte_id": jeton.compte_id,
        "expire_at": jeton.expire_at.isoformat() if jeton.expire_at else None,
        "jours_restants": (
            max(0, (_aware(jeton.expire_at) - _maintenant()).days) if jeton.expire_at else None
        ),
        "dernier_renouvellement_at": (
            jeton.dernier_renouvellement_at.isoformat()
            if jeton.dernier_renouvellement_at
            else None
        ),
        "derniere_erreur": jeton.derniere_erreur,
        "depose_le": jeton.created_at.isoformat() if jeton.created_at else None,
    }
