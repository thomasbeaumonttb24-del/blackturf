"""
Défi du mois — rappels et alertes de classement (notifications in-app).

Deux familles, chacune soumise à une préférence de l'utilisateur :

  - ``defi_rang`` (préférence « résultats suivis ») : un joueur prend ou perd la
    1re place, entre sur le podium ou en sort. Calculé en comparant le classement
    avant / après chaque événement qui le fait bouger (règlement d'une course,
    10e pari d'un joueur qui entre au classement). On ne signale que ces seuils,
    jamais chaque place gagnée ou perdue, et au plus une alerte par joueur toutes
    les ``ANTI_RAFALE`` pour ne pas inonder deux joueurs qui se doublent en boucle.

  - ``defi_rappel`` (préférence « alertes système ») : passage quotidien qui
    relance au bon moment — nouvelle cagnotte en début de mois, paris manquants
    pour entrer au classement, joueur inactif depuis une semaine, dernière ligne
    droite. Chaque rappel porte une clé (mois + palier) : jamais envoyé deux fois.
"""
from __future__ import annotations

import calendar
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from db.models import AlerteLog, DefiPari, User
from services.defi import (
    CAPITAL_MENSUEL, MIN_PARIS_CLASSEMENT, PARIS_TZ, _utc, classement, formater_points,
    mois_courant, mois_essai,
)

log = structlog.get_logger()

TYPE_RANG = "defi_rang"
TYPE_RAPPEL = "defi_rappel"
ANTI_RAFALE = timedelta(hours=2)
INACTIF_APRES = timedelta(days=7)


def _rang(r: int) -> str:
    return "1er" if r == 1 else f"{r}e"


def _alerte(session, user_id: str, type_alerte: str, titre: str, description: str,
            cle: Optional[str] = None, lien: str = "/defi") -> None:
    payload = {"titre": titre, "description": description, "lien": lien}
    if cle:
        payload["cle"] = cle
    session.add(AlerteLog(user_id=user_id, type_alerte=type_alerte, canal="in-app",
                          envoye=True, payload=payload))


def _prefs(user: User) -> dict:
    from services.alerts import prefs_utilisateur

    return prefs_utilisateur(user)


def message_rang(r0: Optional[int], r1: int, ligne: dict, lignes: list[dict]) -> Optional[tuple[str, str]]:
    """(titre, description) si le passage de r0 à r1 franchit un seuil, sinon None."""
    if r0 == r1:
        return None
    classes = [l for l in lignes if l["rang"]]
    premier = classes[0]
    troisieme = next((l for l in classes if l["rang"] == 3), None)
    solde = f"Solde : {formater_points(ligne['solde'])}."
    if r1 == 1:
        suivant = next((l for l in classes if l["rang"] == 2), None)
        avance = (f" {formater_points(ligne['solde'] - suivant['solde'])} d'avance sur {suivant['nom']}."
                  if suivant else "")
        return "Défi : vous prenez la 1re place !", solde + avance
    if r0 == 1:
        return ("Défi : vous avez perdu la 1re place",
                f"{premier['nom']} passe devant. Vous êtes {_rang(r1)}, à "
                f"{formater_points(premier['solde'] - ligne['solde'])} de la tête.")
    if r1 <= 3 and (r0 is None or r0 > 3):
        return (f"Défi : vous montez sur le podium ({_rang(r1)})",
                f"{solde} Le 1er est à {formater_points(premier['solde'] - ligne['solde'])}.")
    if r0 is not None and r0 <= 3 and r1 > 3 and troisieme is not None:
        return ("Défi : vous sortez du podium",
                f"Vous êtes {_rang(r1)}, à {formater_points(troisieme['solde'] - ligne['solde'])} "
                f"de la 3e place.")
    return None


async def notifier_rangs(session, mois: str, avant: list[dict],
                         now: Optional[datetime] = None) -> int:
    """Compare le classement ``avant`` au classement actuel et prévient les joueurs
    qui ont franchi un seuil (1re place, podium). Ne lève jamais : une alerte
    manquée ne doit pas faire échouer un règlement."""
    now = now or datetime.now(timezone.utc)
    try:
        apres = await classement(session, mois)
        rangs_avant = {l["user_id"]: l["rang"] for l in avant}
        a_prevenir = []
        for l in apres:
            if not l["rang"]:
                continue
            msg = message_rang(rangs_avant.get(l["user_id"]), l["rang"], l, apres)
            if msg:
                a_prevenir.append((l["user_id"], msg))
        if not a_prevenir:
            return 0

        ids = [uid for uid, _ in a_prevenir]
        recents = set((await session.execute(select(AlerteLog.user_id).where(
            AlerteLog.type_alerte == TYPE_RANG, AlerteLog.user_id.in_(ids),
            AlerteLog.created_at >= now - ANTI_RAFALE,
        ))).scalars().all())
        users = {u.user_id: u for u in (await session.execute(
            select(User).where(User.user_id.in_(ids)))).scalars().all()}
        n = 0
        for uid, (titre, description) in a_prevenir:
            u = users.get(uid)
            if uid in recents or u is None or not _prefs(u)["resultats_suivis"]:
                continue
            _alerte(session, uid, TYPE_RANG, titre, description)
            n += 1
        if n:
            await session.commit()
        return n
    except Exception as e:  # noqa: BLE001
        log.warning("defi.rangs.echec", mois=mois, err=str(e)[:160])
        await session.rollback()
        return 0


def _jours_restants(now: datetime) -> int:
    local = _utc(now).astimezone(PARIS_TZ)
    return calendar.monthrange(local.year, local.month)[1] - local.day + 1


MOIS_FR = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
           "septembre", "octobre", "novembre", "décembre")


def _mois_precedent(mois: str) -> str:
    a, m = map(int, mois.split("-"))
    return f"{a - 1}-12" if m == 1 else f"{a}-{m - 1:02d}"


async def envoyer_rappels(session, now: Optional[datetime] = None) -> int:
    """Passage quotidien des rappels du défi. Idempotent (clé par mois et palier)."""
    now = now or datetime.now(timezone.utc)
    mois = mois_courant(now)
    if mois_essai(mois):
        return 0  # mois d'essai : on laisse découvrir, on ne relance personne
    jr = _jours_restants(now)
    jour = _utc(now).astimezone(PARIS_TZ).day
    lignes = await classement(session, mois)
    par_user = {l["user_id"]: l for l in lignes}

    # Rappels déjà envoyés ce mois-ci : (user_id, clé).
    debut = now - timedelta(days=jour + 1)
    deja = {(uid, (p or {}).get("cle")) for uid, p in (await session.execute(
        select(AlerteLog.user_id, AlerteLog.payload).where(
            AlerteLog.type_alerte == TYPE_RAPPEL, AlerteLog.created_at >= debut)
    )).all()}

    envois: list[tuple[str, str, str, str]] = []  # (user_id, clé, titre, description)

    # 1. Début de mois : ceux qui ont joué le mois dernier et pas encore celui-ci.
    if jour <= 3:
        prec = _mois_precedent(mois)
        anciens = await classement(session, prec)
        lancement = mois_essai(prec)
        for l in anciens:
            if l["user_id"] in par_user or l["hors_concours"]:
                continue
            if lancement:
                # Premier mois officiel : les joueurs de l'essai sont les premiers prévenus.
                envois.append((l["user_id"], f"{mois}:nouveau",
                               "Le Défi du mois est lancé : les récompenses sont en jeu",
                               f"{formater_points(CAPITAL_MENSUEL)} pour tout le monde, le 1er du "
                               f"mois gagne un abonnement Expert offert."))
                continue
            bilan = (f"Vous avez fini {_rang(l['rang'])} en {MOIS_FR[int(prec[5:]) - 1]}. "
                     if l["rang"] else "")
            envois.append((l["user_id"], f"{mois}:nouveau",
                           f"Défi : {formater_points(CAPITAL_MENSUEL)} tout neufs vous attendent",
                           bilan + "Nouveau mois, compteurs à zéro : tout le monde repart à égalité."))

    for l in lignes:
        if l["hors_concours"]:
            continue
        uid = l["user_id"]
        manque = MIN_PARIS_CLASSEMENT - l["nb_paris"]
        # 2. Pas encore classé : relance à 10 jours puis à 3 jours de la fin.
        if manque > 0 and jr <= 10:
            palier = "J3" if jr <= 3 else "J10"
            envois.append((uid, f"{mois}:classement:{palier}",
                           f"Défi : encore {manque} pari{'s' if manque > 1 else ''} pour être classé",
                           f"Plus que {jr} jour{'s' if jr > 1 else ''} : il faut "
                           f"{MIN_PARIS_CLASSEMENT} paris dans le mois pour figurer au classement "
                           f"et viser les récompenses."))
            continue
        # 3. Dernière ligne droite pour le haut du classement.
        if l["rang"] and l["rang"] <= 10 and jr <= 3:
            premier = lignes[0]
            if l["rang"] == 1:
                desc = "Tenez bon : le classement se fige le dernier jour du mois à minuit."
            else:
                cible = next(x for x in lignes if x["rang"] == (1 if l["rang"] <= 3 else 3))
                desc = (f"Vous êtes {_rang(l['rang'])}, à {formater_points(cible['solde'] - l['solde'])} "
                        f"{'de la 1re place' if cible is premier else 'du podium'}.")
            envois.append((uid, f"{mois}:sprint",
                           f"Défi : plus que {jr} jour{'s' if jr > 1 else ''}", desc))
            continue
        # 4. Inactif depuis une semaine, en milieu de mois.
        if jr > 3 and _utc(l["dernier_pari_at"]) < now - INACTIF_APRES:
            envois.append((uid, f"{mois}:relance",
                           f"Défi : il vous reste {formater_points(l['solde'])}",
                           f"Aucun pari depuis une semaine. "
                           + (f"Vous êtes {_rang(l['rang'])} : défendez votre place."
                              if l["rang"] else "Les courses du jour sont ouvertes.")))

    envois = [e for e in envois if (e[0], e[1]) not in deja]
    if not envois:
        return 0
    users = {u.user_id: u for u in (await session.execute(
        select(User).where(User.user_id.in_({e[0] for e in envois})))).scalars().all()}
    n = 0
    for uid, cle, titre, description in envois:
        u = users.get(uid)
        if u is None or not u.is_active or not _prefs(u)["alertes_systeme"]:
            continue
        _alerte(session, uid, TYPE_RAPPEL, titre, description, cle=cle)
        n += 1
    if n:
        await session.commit()
    log.info("defi.rappels", mois=mois, envoyes=n)
    return n
