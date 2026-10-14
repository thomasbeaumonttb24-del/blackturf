"""Mail d'anniversaire : −50 % le 1er mois aux comptes sans abonnement payant.

Le code est lu dans CODE_ANNIVERSAIRE (.env du serveur) : jamais dans le dépôt.
Destinataires : comptes actifs, adresse confirmée, sans refus des e-mails
commerciaux, inscrits avant le 8 octobre 2026, et à qui l'offre s'applique
vraiment (mêmes règles que le checkout : services/offre_anniversaire.raison_refus
— pas d'abonnement en cours, pas de remise de parrainage en attente, offre
jamais utilisée).

Par défaut, RIEN n'est envoyé : le script affiche le nombre de destinataires et
le nombre de mois. Trois étapes, dans l'ordre :

    python scripts/envoyer_mail_anniversaire.py                    # simulation
    python scripts/envoyer_mail_anniversaire.py --test moi@exemple.fr
    python scripts/envoyer_mail_anniversaire.py --envoyer

Relance « dernière chance » (la veille ou le jour de la fin) : même chose avec
--derniere-chance. Elle vise tous les comptes éligibles, inscrits depuis le
premier mail compris ; ceux qui ne l'ont pas reçu ont un texte adapté.
Cible (décision de l'exploitant) : comptes gratuits, détenteurs d'un pass,
anciens abonnés. Jamais un abonnement Standard/Expert en cours, un accès
offert à la main ni un admin.

    python scripts/envoyer_mail_anniversaire.py --derniere-chance --test
    python scripts/envoyer_mail_anniversaire.py --derniere-chance --envoyer

L'envoi réel passe par email_campaigns.deliver : un destinataire ne reçoit
jamais le mail deux fois (clé campagne + adresse), relancer le script après une
coupure reprend où il s'était arrêté, les adresses en rebond sont sautées.
"""
import argparse
import asyncio
import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db.models  # noqa: E402,F401
from sqlalchemy import func, select  # noqa: E402

from db.database import AsyncSessionLocal  # noqa: E402
from db.models import EmailLivraison, Subscription, User  # noqa: E402
from services import offre_anniversaire as oa  # noqa: E402
from services.email_offre import anniversaire, derniere_chance  # noqa: E402
from services.email_verification import clause_email_utilisable  # noqa: E402

CAMPAGNE = "promo-anniversaire-2026-10"
CAMPAGNE_RELANCE = "promo-anniversaire-2026-10-derniere-chance"
# Resend : 2 requêtes/s par défaut sur le compte, on reste en dessous.
PAUSE_S = 0.6


def mois_depuis(debut: date, aujourd_hui: date) -> int:
    """Mois pleins écoulés (7 juin → 7 octobre = 4)."""
    n = (aujourd_hui.year - debut.year) * 12 + aujourd_hui.month - debut.month
    return n - (1 if aujourd_hui.day < debut.day else 0)


def sujet(mois: int) -> str:
    return f"🎂 BlackTurf a {mois} mois : −{oa.POURCENT} % pour vous remercier"


def sujet_relance(deja_recu: bool, ce_soir: bool) -> str:
    quand = "ce soir" if ce_soir else "demain soir"
    if deja_recu:
        return f"⏰ Dernière chance : votre −{oa.POURCENT} % expire {quand}"
    return f"🎂 −{oa.POURCENT} % sur votre 1er mois, jusqu'à {quand} seulement"


def jour_relance(maintenant: datetime) -> bool:
    """True le jour même de la fin, False la veille ; sinon le texte serait faux."""
    jour, fin = maintenant.astimezone(oa.PARIS).date(), oa.FIN.date()
    if jour == fin:
        return True
    if (fin - jour).days == 1:
        return False
    sys.exit(f"La relance parle de « demain » ou « ce soir » : elle ne part que le {fin.day - 1} ou le {fin.day}.")


async def profil_relance(session, user: User) -> str | None:
    """« pass », « ancien abonné » ou « gratuit » ; None = hors cible. L'abonnement
    en cours est déjà écarté par oa.raison_refus."""
    from services.passes import pass_actif
    if user.is_admin:
        return None
    if await pass_actif(session, user.user_id):
        return "pass"
    if await session.scalar(select(Subscription.sub_id).where(
            Subscription.user_id == user.user_id, Subscription.statut != "incomplete_expired").limit(1)):
        return "ancien abonné"
    # Plan payant sans pass ni abonnement : accès accordé à la main.
    return "gratuit" if (user.plan or "free") == "free" else None


async def deja_recu_premier_mail(session) -> set[str]:
    return set((await session.execute(select(EmailLivraison.email).where(
        EmailLivraison.campagne == CAMPAGNE, EmailLivraison.statut == "sent"))).scalars())


async def destinataires(session, inscrits_avant: datetime) -> list[User]:
    candidats = (await session.execute(select(User).where(
        User.is_active == True,  # noqa: E712
        User.marketing_opt_out_at.is_(None),
        clause_email_utilisable(),
        User.created_at < inscrits_avant,
    ).order_by(User.created_at))).scalars().all()
    return [u for u in candidats if await oa.raison_refus(u, session) is None]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mise-en-ligne", help="AAAA-MM-JJ ; défaut : date du premier compte")
    ap.add_argument("--mois", type=int, help="force le nombre de mois affiché")
    ap.add_argument("--test", metavar="ADRESSE", nargs="?", const="",
                    help="envoie un seul exemplaire à cette adresse (défaut : ADMIN_EMAIL)")
    ap.add_argument("--envoyer", action="store_true", help="envoi réel à tous les destinataires")
    ap.add_argument("--derniere-chance", action="store_true",
                    help="relance : fin de l'offre demain (ou ce soir), inscrits récents compris")
    args = ap.parse_args()

    code = oa.code_actif()
    if not code:
        sys.exit("CODE_ANNIVERSAIRE est vide : posez le code dans le .env avant tout envoi.")

    if args.derniere_chance:
        await relance(args, code)
        return

    async with AsyncSessionLocal() as session:
        if args.mois:
            mois = args.mois
        else:
            if args.mise_en_ligne:
                debut = date.fromisoformat(args.mise_en_ligne)
            else:
                premier = await session.scalar(select(func.min(User.created_at)))
                debut = premier.date()
            mois = mois_depuis(debut, datetime.now(oa.PARIS).date())
            print(f"Mise en ligne retenue : {debut:%d/%m/%Y} → {mois} mois")
        if mois < 1:
            sys.exit("Moins d'un mois depuis la mise en ligne : vérifiez --mise-en-ligne.")

        from services.alerts import _unsubscribe_url, make_unsubscribe_token, send_email
        from services.email_campaigns import SITE, deliver

        if args.test is not None:
            if not args.test:
                from services.email_campaigns import CONTROL_ADDRESS
                args.test = CONTROL_ADDRESS
            prenom = await session.scalar(select(User.prenom).where(func.lower(User.email) == args.test.lower()))
            html, texte = anniversaire(prenom, mois, code, SITE + "/notifications")
            ok = await send_email(args.test, "[TEST] " + sujet(mois), html, texte)
            print("Envoi test :", "OK" if ok else f"ÉCHEC ({getattr(ok, 'erreur', '?')})")
            return

        cibles = await destinataires(session, oa.PREMIER_ENVOI_AVANT)
        print(f"Destinataires : {len(cibles)} (offre valable jusqu'au {oa.FIN_TEXTE})")
        if not args.envoyer:
            print("Simulation : rien n'est envoyé. Ajoutez --envoyer pour l'envoi réel.")
            return

        envoyes = 0
        for user in cibles:
            html, texte = anniversaire(user.prenom, mois, code, _unsubscribe_url(user.user_id))
            oneclick = f"{SITE}/api/v1/newsletter/desabonnement-compte?jeton={make_unsubscribe_token(user.user_id)}"
            if await deliver(session, CAMPAGNE, user.email, sujet(mois), html, texte, oneclick,
                             datetime.now(timezone.utc), journal={"offre": oa.COUPON_ID}):
                envoyes += 1
            await asyncio.sleep(PAUSE_S)
        print(f"Envoyés : {envoyes} / {len(cibles)}")


async def relance(args, code: str) -> None:
    ce_soir = jour_relance(datetime.now(timezone.utc))
    from services.alerts import _unsubscribe_url, make_unsubscribe_token, send_email
    from services.email_campaigns import SITE, deliver

    async with AsyncSessionLocal() as session:
        if args.test is not None:
            if not args.test:
                from services.email_campaigns import CONTROL_ADDRESS
                args.test = CONTROL_ADDRESS
            prenom = await session.scalar(select(User.prenom).where(func.lower(User.email) == args.test.lower()))
            for deja_recu in (True, False):  # les deux versions du texte
                html, texte = derniere_chance(prenom, code, SITE + "/notifications", deja_recu, ce_soir)
                ok = await send_email(args.test, "[TEST] " + sujet_relance(deja_recu, ce_soir), html, texte)
                print(f"Envoi test ({'a reçu' if deja_recu else 'inscrit depuis'}) :",
                      "OK" if ok else f"ÉCHEC ({getattr(ok, 'erreur', '?')})")
            return

        cibles, profils = [], {}
        for user in await destinataires(session, oa.COMPTES_AVANT):
            profil = await profil_relance(session, user)
            if profil:
                cibles.append(user)
                profils[profil] = profils.get(profil, 0) + 1
        recus = await deja_recu_premier_mail(session)
        nouveaux = sum(1 for u in cibles if u.email.strip().lower() not in recus)
        print(f"Destinataires : {len(cibles)} dont {nouveaux} sans le premier mail "
              f"(offre valable jusqu'au {oa.FIN_TEXTE})")
        print("  " + " · ".join(f"{n} {p}" for p, n in sorted(profils.items())))
        if not args.envoyer:
            print("Simulation : rien n'est envoyé. Ajoutez --envoyer pour l'envoi réel.")
            return

        envoyes = 0
        for user in cibles:
            deja_recu = user.email.strip().lower() in recus
            html, texte = derniere_chance(user.prenom, code, _unsubscribe_url(user.user_id), deja_recu, ce_soir)
            oneclick = f"{SITE}/api/v1/newsletter/desabonnement-compte?jeton={make_unsubscribe_token(user.user_id)}"
            if await deliver(session, CAMPAGNE_RELANCE, user.email, sujet_relance(deja_recu, ce_soir), html, texte,
                             oneclick, datetime.now(timezone.utc), journal={"offre": oa.COUPON_ID}):
                envoyes += 1
            await asyncio.sleep(PAUSE_S)
        print(f"Envoyés : {envoyes} / {len(cibles)}")


if __name__ == "__main__":
    asyncio.run(main())
