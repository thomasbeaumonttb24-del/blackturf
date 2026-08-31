"""
Notifications — BlackTurf.
Centre de notifications utilisateur (liste, lecture, préférences).

GET    /notifications           — liste (aussi servie sans slash final)
GET    /notifications/count-unread — compteur badge navbar
PUT    /notifications/{id}/lue  — marquer une notification lue
DELETE /notifications/all       — tout marquer lu
GET    /notifications/prefs     — préférences
PUT    /notifications/prefs     — mettre à jour les préférences

POURQUOI LE CENTRE ÉTAIT VIDE (constaté 2026-08-17, 22 400 alertes in-app non lues
en base pour le compte admin, mais « Aucune notification » à l'écran) — trois bugs
empilés, tous corrigés ici :

1. ROUTE FANTÔME. La liste était déclarée sur `"/"` seulement. Le front appelle
   `/api/v1/notifications` (sans slash) → FastAPI répondait 307 vers
   `http://api.blackturf.fr/api/v1/notifications/` — en **http**, parce qu'uvicorn
   tournait sans `--proxy-headers` et ignorait le `X-Forwarded-Proto` de nginx. Un
   navigateur sur une page https refuse de suivre une redirection vers http
   (contenu mixte) → requête morte, SWR sans données, `total_unread` par défaut à 0
   → « Aucune notification » ET « Tout est lu », alors que le badge navbar (chemin
   `/count-unread`, sans redirection) affichait bien 9+. La route est maintenant
   déclarée sur `""` ET `"/"` : plus aucune redirection, quel que soit l'appelant.
   (Le flag `--proxy-headers` est corrigé en parallèle dans Dockerfile /
   docker-compose.prod.yml, pour toutes les autres redirections de l'app.)

2. CONTENU ILLISIBLE. `_alerte_dict` cherchait `titre`/`description` à la racine du
   payload, que RIEN ne produit : les payloads réels sont soit un value bet unitaire
   (`{nom_cheval, cote, niveau, ev, hippodrome, course_id}`), soit un digest
   (`{nb_value_bets, value_bets: [...], signal_keys}`). Toutes les notifications se
   seraient donc affichées « value_bet_digest » avec une description vide. Le rendu
   est maintenant construit par type, à partir des champs qui existent vraiment.

3. TROIS FOIS LE MÊME ÉVÉNEMENT. Chaque value bet écrit une ligne par CANAL
   (in-app + email + push). Le centre listait les trois → triplons, et le badge
   comptait 67 175 « non lues » pour 22 400 événements réels. Le centre ne montre
   plus que le canal in-app, plus les types e-mail qui n'ont pas de jumeau in-app
   (annonces produit) — cf. `_scope_centre`.
"""
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.auth import get_current_user
from db.database import get_db
from db.models import AlerteLog, User

log = structlog.get_logger()
router = APIRouter()


# ─── Périmètre du centre de notifications ──────────────────────
# `canal` décrit un MOYEN DE LIVRAISON (in-app / email / push), pas un événement :
# un même value bet produit jusqu'à 3 lignes. Le centre affiche l'événement une
# seule fois — la ligne in-app, qui est précisément celle destinée au site.
CANAUX_CENTRE = ("in-app",)

# Exceptions : types envoyés UNIQUEMENT par e-mail mais qui concernent directement
# l'utilisateur (annonces produit, digests). Sans eux, un compte Free — qui ne reçoit
# aucune alerte value bet in-app — aurait un centre désespérément vide.
TYPES_EMAIL_VISIBLES = (
    "free_plan_announcement",
    "weekly_best_vb",
    "digest_matin",
)

# type_alerte → onglet du front (« Paris de valeur » / « Résultats » / « Système »).
# Calculée côté serveur : le front n'a pas à deviner la taxonomie par sous-chaînes.
CATEGORIES: dict[str, str] = {
    "value_bet": "value_bet",
    "value_bet_digest": "value_bet",
    "digest_matin": "value_bet",
    "weekly_best_vb": "value_bet",
    "resultat_pari": "resultat",
    "resultat_value_bet": "resultat",
    "free_plan_announcement": "systeme",
    "systeme": "systeme",
}


def _scope_centre():
    """Condition SQL du périmètre « centre de notifications »."""
    return or_(
        AlerteLog.canal.in_(CANAUX_CENTRE),
        AlerteLog.type_alerte.in_(TYPES_EMAIL_VISIBLES),
    )


# ─── schemas ───────────────────────────────────────────────────

class PrefsUpdate(BaseModel):
    vb_niveau_min: int | None = None          # 1/2/3/4
    resultats_suivis: bool | None = None
    alertes_systeme: bool | None = None


class DesabonnementRequest(BaseModel):
    token: str


# ─── rendu d'une alerte ────────────────────────────────────────

def _etoiles(niveau: Any) -> str:
    try:
        n = max(0, min(4, int(niveau)))
    except (TypeError, ValueError):
        return ""
    return "★" * n


def _euro(v: Any) -> str:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return ""
    return f"{f:+.2f} €".replace(".", ",")


def _cote(v: Any) -> str:
    try:
        return f"{float(v):.2f}".replace(".", ",")
    except (TypeError, ValueError):
        return "?"


def _vb_ligne(vb: dict) -> str:
    """« ★★★ LOUBRALTAR (cote 6,40) » — une ligne lisible pour un value bet."""
    etoiles = _etoiles(vb.get("niveau"))
    nom = vb.get("nom_cheval") or vb.get("cheval") or "?"
    cote = vb.get("cote")
    suffixe = f" (cote {_cote(cote)})" if cote else ""
    return f"{etoiles} {nom}{suffixe}".strip()


def _rendu(type_alerte: str, p: dict) -> tuple[str, str]:
    """(titre, description) lisibles pour un type + payload donnés.

    Aucune invention : on n'affiche que ce que le payload contient réellement.
    """
    # ── Value bets ────────────────────────────────────────────
    if type_alerte in ("value_bet", "value_bet_digest"):
        vbs = p.get("value_bets")
        if not isinstance(vbs, list) or not vbs:
            # payload unitaire (ancien format) → le payload EST le value bet
            vbs = [p] if p.get("nom_cheval") else []
        n = int(p.get("nb_value_bets") or len(vbs))

        if n == 1 and vbs:
            vb = vbs[0]
            titre = f"Pari de valeur — {_vb_ligne(vb)}"
            bouts = [b for b in (vb.get("hippodrome"), _heure(vb.get("heure_depart")),
                                 _ev(vb.get("ev"))) if b]
            return titre, " · ".join(bouts)

        titre = f"{n} paris de valeur détectés" if n else "Paris de valeur"
        apercu = ", ".join(_vb_ligne(v) for v in vbs[:3])
        if len(vbs) > 3:
            apercu += f" +{len(vbs) - 3} autre{'s' if len(vbs) - 3 > 1 else ''}"
        return titre, apercu

    if type_alerte == "digest_matin":
        nb = p.get("nb_vb")
        return ("Digest du matin",
                f"{nb} pari{'s' if (nb or 0) > 1 else ''} de valeur pour aujourd'hui"
                if nb else "Les paris de valeur du jour vous attendent")

    if type_alerte == "weekly_best_vb":
        nom = p.get("nom_cheval")
        if nom:
            return ("Meilleur pari de la semaine",
                    f"{nom} gagnant à la cote {_cote(p.get('cote'))} "
                    f"— rapport officiel {_cote(p.get('rapport_simple_gagnant'))}")
        return "Meilleur pari de la semaine", ""

    # ── Résultats (suivi post-course) ─────────────────────────
    if type_alerte == "resultat_pari":
        gagne = int(p.get("nb_gagnes") or 0)
        perdu = int(p.get("nb_perdus") or 0)
        net = p.get("gain_net")
        if gagne and not perdu:
            titre = f"Pari gagné — {_euro(net)}"
        elif perdu and not gagne:
            titre = f"Pari perdu — {_euro(net)}"
        else:
            titre = f"{gagne + perdu} paris réglés — {_euro(net)}"
        bouts = [b for b in (p.get("hippodrome"), p.get("course_nom"),
                             p.get("arrivee")) if b]
        return titre, " · ".join(str(b) for b in bouts)

    if type_alerte == "resultat_value_bet":
        nom = p.get("nom_cheval") or "?"
        pos = p.get("position")
        if pos == 1:
            rap = p.get("rapport_simple_gagnant")
            titre = f"{nom} a GAGNÉ" + (f" — rapport {_cote(rap)}" if rap else "")
        elif isinstance(pos, int) and pos <= 3:
            titre = f"{nom} {pos}ᵉ — placé"
        else:
            titre = f"{nom} non placé"
        bouts = [b for b in (p.get("hippodrome"),
                             f"signalé {_etoiles(p.get('niveau'))}" if p.get("niveau") else None,
                             f"cote {_cote(p.get('cote'))}" if p.get("cote") else None) if b]
        return titre, " · ".join(bouts)

    # ── Système / annonces ────────────────────────────────────
    titre = p.get("titre") or p.get("title") or type_alerte.replace("_", " ").capitalize()
    return titre, str(p.get("description") or p.get("body") or "")


def _heure(iso: Any) -> str:
    """« 17:13 » depuis un ISO, vide si illisible."""
    if not iso or not isinstance(iso, str):
        return ""
    try:
        from datetime import datetime
        return datetime.fromisoformat(iso).strftime("%H:%M")
    except ValueError:
        return ""


def _ev(ev: Any) -> str:
    try:
        return f"EV {float(ev) * 100:+.0f} %"
    except (TypeError, ValueError):
        return ""


def _alerte_dict(a: AlerteLog) -> dict[str, Any]:
    payload = a.payload if isinstance(a.payload, dict) else {}
    titre, description = _rendu(a.type_alerte, payload)

    # course_id : à la racine (value bet unitaire, résultat) ou dans le 1er élément
    # du digest — pour proposer « Voir la course » quand c'est non ambigu.
    course_id = payload.get("course_id")
    vbs = payload.get("value_bets")
    if not course_id and isinstance(vbs, list) and len(vbs) == 1 and isinstance(vbs[0], dict):
        course_id = vbs[0].get("course_id")

    return {
        "alerte_id": a.alerte_id,
        "type_alerte": a.type_alerte,
        "categorie": CATEGORIES.get(a.type_alerte, "systeme"),
        "canal": a.canal,
        "lue": a.lue,
        "envoye": a.envoye,
        "created_at": a.created_at.isoformat() if a.created_at else None,
        "titre": titre,
        "description": description,
        "course_id": course_id,
        "cheval": payload.get("nom_cheval") or payload.get("cheval"),
        "niveau": payload.get("niveau"),
        "nb": payload.get("nb_value_bets"),
    }


# ─── routes ────────────────────────────────────────────────────

async def _count_unread(db: AsyncSession, user_id: str) -> int:
    """Compteur SQL. Ne JAMAIS charger les lignes pour les compter : un compte
    actif dépasse 20 000 alertes — l'ancien `select(...).scalars().all()` puis
    `len()` ramenait tout en mémoire à chaque affichage de page."""
    return int(await db.scalar(
        select(func.count(AlerteLog.alerte_id)).where(
            AlerteLog.user_id == user_id,
            AlerteLog.lue == False,  # noqa: E712
            _scope_centre(),
        )
    ) or 0)


@router.get("/count-unread")
async def count_unread(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Nombre de notifications non lues (badge navbar)."""
    return {"count": await _count_unread(db, current_user.user_id)}


# Déclarée sur les DEUX chemins : `/notifications` et `/notifications/`. Sans le
# premier, FastAPI renvoie un 307 dont le Location repart en http derrière le proxy
# → requête bloquée par le navigateur et centre vide (cf. docstring du module).
@router.get("")
@router.get("/")
async def list_notifications(
    page: int = 1,
    limit: int = 50,
    categorie: str | None = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Notifications de l'utilisateur, les plus récentes d'abord.

    `categorie` (value_bet / resultat / systeme) filtre côté SERVEUR : filtrer une
    page de 50 côté client donnait un onglet vide alors que la catégorie avait des
    dizaines d'entrées plus loin dans l'historique.
    """
    limit = max(1, min(int(limit), 100))
    page = max(1, int(page))

    q = (
        select(AlerteLog)
        .where(AlerteLog.user_id == current_user.user_id, _scope_centre())
        .order_by(AlerteLog.created_at.desc())
        .offset((page - 1) * limit)
        .limit(limit)
    )
    if categorie:
        types = [t for t, c in CATEGORIES.items() if c == categorie]
        if not types:
            raise HTTPException(status_code=422, detail="Catégorie inconnue")
        q = q.where(AlerteLog.type_alerte.in_(types))

    rows = (await db.execute(q)).scalars().all()

    return {
        "items": [_alerte_dict(a) for a in rows],
        "total_unread": await _count_unread(db, current_user.user_id),
        "page": page,
        "limit": limit,
        "has_more": len(rows) == limit,
    }


@router.put("/{alerte_id}/lue")
async def mark_read(
    alerte_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marquer une notification comme lue."""
    row = (await db.execute(
        select(AlerteLog).where(
            AlerteLog.alerte_id == alerte_id,
            AlerteLog.user_id == current_user.user_id,
        )
    )).scalar_one_or_none()

    if not row:
        raise HTTPException(status_code=404, detail="Notification introuvable")

    row.lue = True
    await db.commit()
    return {"ok": True, "total_unread": await _count_unread(db, current_user.user_id)}


@router.delete("/all")
async def mark_all_read(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Marquer toutes les notifications comme lues.

    Porte sur TOUS les canaux (pas seulement le périmètre du centre) : sinon les
    lignes email/push resteraient `lue=false` à vie et gonfleraient les statistiques
    admin sans que l'utilisateur puisse jamais y toucher.
    """
    res = await db.execute(
        update(AlerteLog)
        .where(
            AlerteLog.user_id == current_user.user_id,
            AlerteLog.lue == False,  # noqa: E712
        )
        .values(lue=True)
    )
    await db.commit()
    return {"ok": True, "n": res.rowcount or 0, "total_unread": 0}


@router.post("/desabonnement")
async def desabonnement_marketing(
    body: DesabonnementRequest,
    db: AsyncSession = Depends(get_db),
):
    """
    Désabonnement des e-mails MARKETING via le jeton signé du lien de l'e-mail.

    PUBLIC et sans login : exiger une connexion pour exercer son droit
    d'opposition (RGPD) reviendrait à ne pas offrir de désinscription réelle.
    Le jeton porte une audience dédiée (`unsub`) — il ne peut PAS servir de
    jeton d'accès, et ne permet rien d'autre que de poser cet opt-out.

    Idempotent : re-cliquer le lien renvoie le même succès. Réponse volontairement
    identique (200 {"ok": true}) que le jeton corresponde ou non à un compte
    existant — ne pas transformer ce endpoint public en oracle d'existence de
    comptes (énumération).
    """
    from datetime import datetime, timezone
    from services.alerts import read_unsubscribe_token

    user_id = read_unsubscribe_token(body.token)
    if not user_id:
        raise HTTPException(status_code=400, detail="Lien de désabonnement invalide ou expiré")

    user = (await db.execute(select(User).where(User.user_id == user_id))).scalar_one_or_none()
    if user and user.marketing_opt_out_at is None:
        user.marketing_opt_out_at = datetime.now(timezone.utc)
        db.add(user)
        await db.commit()
        log.info("notifications.desabonnement_marketing", user_id=user_id)

    return {"ok": True, "message": "Vous ne recevrez plus d'e-mails de ce type."}


@router.get("/prefs")
async def get_prefs(
    current_user: User = Depends(get_current_user),
):
    """Préférences de notifications (lues par services/alerts.py à chaque envoi)."""
    from services.alerts import prefs_utilisateur
    return prefs_utilisateur(current_user)


@router.put("/prefs")
async def update_prefs(
    body: PrefsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mettre à jour les préférences de notifications."""
    from services.alerts import PREFS_DEFAUT, prefs_utilisateur

    push_sub = dict(current_user.push_subscription or {})
    prefs = dict(prefs_utilisateur(current_user))

    if body.vb_niveau_min is not None:
        if body.vb_niveau_min not in (1, 2, 3, 4):
            raise HTTPException(status_code=422, detail="vb_niveau_min doit être entre 1 et 4")
        prefs["vb_niveau_min"] = body.vb_niveau_min
    if body.resultats_suivis is not None:
        prefs["resultats_suivis"] = bool(body.resultats_suivis)
    if body.alertes_systeme is not None:
        prefs["alertes_systeme"] = bool(body.alertes_systeme)

    push_sub["prefs"] = {k: prefs[k] for k in PREFS_DEFAUT}
    # Réaffectation d'un NOUVEAU dict : muter en place un JSON SQLAlchemy ne marque
    # pas la colonne comme sale → la préférence n'était pas persistée de façon fiable.
    current_user.push_subscription = push_sub
    db.add(current_user)
    await db.commit()
    return push_sub["prefs"]
