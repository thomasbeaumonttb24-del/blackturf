#!/usr/bin/env python3
"""Envoi d'un mail d'alerte à l'exploitant depuis l'HÔTE (sentinelle, sonde de santé).

Usage :  bt_mail_admin.py "Sujet"  < corps.html
Code de sortie 0 si un fournisseur a ACCEPTÉ le mail, 1 sinon ; une ligne de
compte rendu sur la sortie standard (« resend 200 », « smtp:… ok », ou les erreurs).

POURQUOI CE SCRIPT : la sentinelle et la sonde appelaient Resend seul avec curl.
Le 07/10/2026 le quota Resend (100/j) a été saturé : une alerte d'intrusion
serait alors partie dans le vide. Il suit la même chaîne que l'application
(services/alerts.py) : Resend, puis les relais SMTP gratuits (SMTP_* Brevo,
SMTP2_* Mailjet). On ne passe au suivant que sur un REFUS explicite (code
HTTP/SMTP) : un délai dépassé est ambigu, le mail est peut-être parti.

Hors conteneur, bibliothèque standard seule : il doit fonctionner quand l'app
est à terre. Les secrets sont lus dans le .env, jamais passés en argument.
"""
from __future__ import annotations

import json
import os
import re
import smtplib
import socket
import ssl
import sys
import urllib.error
import urllib.request
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from html import unescape

ENV_FILE = os.environ.get("BT_ENV_FILE", "/opt/blackturf/.env")


def lire_env(chemin: str) -> dict[str, str]:
    env: dict[str, str] = {}
    with open(chemin, encoding="utf-8") as f:
        for ligne in f:
            ligne = ligne.strip()
            if not ligne or ligne.startswith("#") or "=" not in ligne:
                continue
            cle, val = ligne.split("=", 1)
            env[cle.strip()] = val.strip().strip("\"'")
    return env


def texte(html: str) -> str:
    t = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", html, flags=re.S | re.I)
    t = re.sub(r"<br\s*/?>|</p>|</li>|</h\d>|</tr>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    return re.sub(r"\n\s*\n+", "\n\n", unescape(t)).strip()


class Refus(Exception):
    """Refus explicite du fournisseur : on peut essayer le suivant."""


def par_resend(env, dest, sujet, html, expediteur) -> str:
    cle = env.get("RESEND_API_KEY")
    if not cle:
        raise Refus("resend: clé absente")
    corps = json.dumps({"from": expediteur, "to": [dest], "subject": sujet,
                        "html": html, "text": texte(html)}).encode()
    req = urllib.request.Request("https://api.resend.com/emails", data=corps, method="POST",
                                 headers={"Authorization": f"Bearer {cle}",
                                          "Content-Type": "application/json",
                                          "User-Agent": "bt-mail-admin/1"})
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return f"resend {r.status}"
    except urllib.error.HTTPError as e:  # le serveur a RÉPONDU : refus explicite
        raise Refus(f"resend HTTP {e.code} {e.read()[:200]!r}") from None


def par_smtp(env, pre, dest, sujet, html, expediteur_nu, nom_exped) -> str:
    hote, user, mdp = env.get(pre + "HOST"), env.get(pre + "USER"), env.get(pre + "PASSWORD")
    if not (hote and user and mdp):
        raise Refus(f"{pre.lower()}: non configuré")
    port = int(env.get(pre + "PORT") or 587)
    exped = env.get(pre + "FROM") or expediteur_nu
    msg = EmailMessage()
    msg["From"] = formataddr((nom_exped, exped))
    msg["To"] = dest
    msg["Subject"] = sujet
    msg["Message-ID"] = make_msgid(domain=exped.split("@")[-1])
    msg.set_content(texte(html))
    msg.add_alternative(html, subtype="html")
    ctx = ssl.create_default_context()  # certificat VÉRIFIÉ
    transmis = False
    try:
        if port == 465:
            srv = smtplib.SMTP_SSL(hote, port, timeout=20, context=ctx)
        else:
            srv = smtplib.SMTP(hote, port, timeout=20)
            srv.starttls(context=ctx)
        with srv:
            srv.login(user, mdp)
            transmis = True
            srv.send_message(msg)
        return f"{pre.lower()}{hote} ok"
    except (smtplib.SMTPResponseException, smtplib.SMTPRecipientsRefused,
            smtplib.SMTPSenderRefused) as e:
        raise Refus(f"{pre.lower()}{hote} refus {e}"[:300]) from None
    except Exception as e:  # noqa: BLE001
        if not transmis:  # échec AVANT la transmission : rien n'est parti
            raise Refus(f"{pre.lower()}{hote} {type(e).__name__}: {e}"[:300]) from None
        raise RuntimeError(f"{pre.lower()}{hote} ambigu {type(e).__name__}: {e}"[:300]) from None


def envoyer(env, sujet, html) -> tuple[bool, str]:
    dest = env.get("ADMIN_EMAIL")
    if not dest:
        return False, "ADMIN_EMAIL absente du .env"
    nu = env.get("EMAIL_FROM") or "alerte@blackturf.fr"
    nom = env.get("EMAIL_FROM_NAME") or "BlackTurf"
    sujet = f"{sujet} {socket.gethostname()}".strip()
    erreurs = []
    essais = [lambda: par_resend(env, dest, sujet, html, formataddr((nom, nu)))]
    essais += [lambda p=p: par_smtp(env, p, dest, sujet, html, nu, nom) for p in ("SMTP_", "SMTP2_")]
    for essai in essais:
        try:
            return True, essai()
        except Refus as e:
            erreurs.append(str(e))
        except Exception as e:  # noqa: BLE001 — ambigu : ne pas doubler le mail
            erreurs.append(str(e))
            break
    return False, " | ".join(erreurs)[:600]


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: bt_mail_admin.py SUJET < corps.html", file=sys.stderr)
        return 2
    try:
        env = lire_env(ENV_FILE)
    except OSError as e:
        print(f"echec : {ENV_FILE} illisible ({e})")
        return 1
    ok, compte_rendu = envoyer(env, sys.argv[1], sys.stdin.read())
    print(("ok " if ok else "echec ") + compte_rendu)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
