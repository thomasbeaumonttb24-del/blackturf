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
from db.models import User  # noqa: E402
from services import offre_anniversaire as oa  # noqa: E402
from services.email_offre import anniversaire  # noqa: E402
from services.email_verification import clause_email_utilisable  # noqa: E402

CAMPAGNE = "promo-anniversaire-2026-10"
# Resend : 2 requêtes/s par défaut sur le compte, on reste en dessous.
PAUSE_S = 0.6


def mois_depuis(debut: date, aujourd_hui: date) -> int:
    """Mois pleins écoulés (7 juin → 7 octobre = 4)."""
    n = (aujourd_hui.year - debut.year) * 12 + aujourd_hui.month - debut.month
    return n - (1 if aujourd_hui.day < debut.day else 0)


def sujet(mois: int) -> str:
    return f"🎂 BlackTurf a {mois} mois : −{oa.POURCENT} % pour vous remercier"


async def destinataires(session) -> list[User]:
    candidats = (await session.execute(select(User).where(
        User.is_active == True,  # noqa: E712
        User.marketing_opt_out_at.is_(None),
        clause_email_utilisable(),
        User.created_at < oa.COMPTES_AVANT,
    ).order_by(User.created_at))).scalars().all()
    return [u for u in candidats if await oa.raison_refus(u, session) is None]


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--mise-en-ligne", help="AAAA-MM-JJ ; défaut : date du premier compte")
    ap.add_argument("--mois", type=int, help="force le nombre de mois affiché")
    ap.add_argument("--test", metavar="ADRESSE", help="envoie un seul exemplaire à cette adresse")
    ap.add_argument("--envoyer", action="store_true", help="envoi réel à tous les destinataires")
    args = ap.parse_args()

    code = oa.code_actif()
    if not code:
        sys.exit("CODE_ANNIVERSAIRE est vide : posez le code dans le .env avant tout envoi.")

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

        if args.test:
            prenom = await session.scalar(select(User.prenom).where(func.lower(User.email) == args.test.lower()))
            html, texte = anniversaire(prenom, mois, code, SITE + "/notifications")
            ok = await send_email(args.test, "[TEST] " + sujet(mois), html, texte)
            print("Envoi test :", "OK" if ok else f"ÉCHEC ({getattr(ok, 'erreur', '?')})")
            return

        cibles = await destinataires(session)
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


if __name__ == "__main__":
    asyncio.run(main())
