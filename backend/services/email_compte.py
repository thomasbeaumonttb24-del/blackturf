"""Mails de compte et de confirmation : inscription à la lettre, confirmation
d'adresse, mot de passe oublié, demande de résiliation.

Même habillage que les lettres et le pronostic gratuit (services/email_design.py).
Chaque fonction rend `(html, texte)` : la version texte accompagne toujours le
HTML, pour les clients qui l'affichent et pour la délivrabilité.
"""
from __future__ import annotations

from typing import Optional

from services import email_design as D
from services.email_design import C, INSTAGRAM, POLICE, SITE, e


def _avantages(lignes: list[tuple[str, str, str]]) -> str:
    """Liste « ce qui vous attend » : tuile or en relief, titre, phrase."""
    out = ""
    for icone, titre, texte in lignes:
        out += f"""
<tr><td style="padding:0 0 12px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%"><tr>
    <td width="44" valign="top" style="width:44px"><img src="{D.IMG}/tuile-{icone}.png" width="40" height="40" alt="" style="display:block;width:40px;height:40px;border:0"></td>
    <td valign="top" style="padding-left:12px">
      <div style="font-size:15px;line-height:20px;font-weight:700;color:{C['encre2']};font-family:{POLICE}">{titre}</div>
      <div style="font-size:13px;line-height:19px;color:{C['stone6']}">{texte}</div>
    </td>
  </tr></table>
</td></tr>"""
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">{out}</table>'


def _carte_claire(contenu: str) -> str:
    return D.rangee_nuit(D.carte(contenu, "22px 22px"), padding="0 20px 24px")


def _action(label: str, url: str, note: str) -> str:
    """Bouton or centré et, dessous, le lien en clair (au cas où le bouton ne
    s'afficherait pas) et une note."""
    return D.rangee_nuit(
        D.bouton(label, url)
        + f'<div style="margin-top:16px;font-size:11.5px;line-height:17px;color:{C["gris"]}">Le bouton ne s’affiche pas ? Copiez ce lien :<br>'
        f'<a href="{e(url)}" style="color:{C["orNuit"]};text-decoration:underline;word-break:break-all">{e(url)}</a></div>'
        + (f'<div style="margin-top:12px;font-size:12.5px;line-height:19px;color:{C["douxNuit"]}">{note}</div>' if note else ""),
        padding="0 28px 28px", centre=True,
    )


def _securite(texte: str) -> str:
    return D.encart("Sécurité", texte)


def confirmation_newsletter(lien: str) -> tuple[str, str]:
    avantages = _avantages([
        ("euro", "Le podium de la semaine", "Les meilleurs plans publiés, figés avant le départ puis réglés aux rapports officiels."),
        ("pourcent", "Les chiffres de l’algorithme", "Combien de gagnants figuraient dans notre top 3, comparés au hasard."),
        ("valide", "Le bilan complet", "Tous les profils, plans perdants inclus : rien n’est trié pour faire joli."),
    ])
    rangees = (
        D.barre_logo("La lettre BlackTurf")
        + D.entete("bienvenue", "Bienvenue chez BlackTurf", "Confirmez votre inscription",
                   "Chaque lundi dès 9 h : les meilleurs plans bénéficiaires et le bilan chiffré de la semaine. "
                   "Un clic et c’est parti.")
        + _action("Confirmer mon inscription", lien,
                  "Un seul envoi par semaine. Si les rapports officiels sont incomplets, nous attendons leur validation avant de publier le bilan.")
        + _carte_claire(D.surtitre("Ce que vous recevrez chaque lundi") + avantages)
        + _securite("Vous n’êtes pas à l’origine de cette demande ? Ignorez ce message : sans confirmation, aucune lettre ne sera envoyée.")
        + D.bloc_instagram("En attendant lundi, le bilan du jour passe aussi en story.")
        + D.pied("Vous recevez ce message parce qu’une inscription à la lettre BlackTurf a été demandée avec cette adresse.")
    )
    texte = (
        "Confirmez votre inscription à la lettre hebdomadaire BlackTurf.\n\n"
        "Chaque lundi : le bilan chiffré de la semaine, gains comme pertes.\n\n"
        f"{lien}\n\n"
        f"En attendant lundi, le bilan du jour passe aussi sur Instagram : {INSTAGRAM}\n\n"
        "Vous n'êtes pas à l'origine de cette demande ? Ignorez ce message : sans "
        "confirmation, aucune lettre ne partira."
    )
    return D.document("Confirmez votre inscription", "Un clic pour recevoir le bilan BlackTurf chaque lundi.", rangees), texte


def verification_adresse(prenom: Optional[str], lien: str) -> tuple[str, str]:
    nom = e(prenom or "parieur")
    avantages = _avantages([
        ("ia", "Le classement de l’algorithme", "Chaque course notée, du plus probable au moins probable, avec la cote juste de chaque cheval."),
        ("etoile", "Les valeurs du jour", "Les chevaux dont la cote dépasse le prix estimé par le modèle, en étoiles de 1 à 4."),
        ("euro", "Le plan de mise", "Vos paris répartis selon votre budget et votre profil, prudent à risqué."),
    ])
    rangees = (
        D.barre_logo("Bienvenue")
        + D.entete("bienvenue", "Votre compte BlackTurf", f"Bienvenue, {nom}&nbsp;!",
                   "Plus qu’une étape : confirmez votre adresse e-mail pour activer votre compte.")
        + _action("Confirmer mon adresse", lien, "Lien valable 24 heures. Sans confirmation, le compte reste inactif.")
        + _carte_claire(D.surtitre("Ce qui vous attend sur BlackTurf") + avantages)
        + _securite("Si vous n’êtes pas à l’origine de cette inscription, ignorez ce message : le compte ne s’ouvrira pas.")
        + D.bloc_instagram()
        + D.pied("Message envoyé suite à la création d’un compte sur blackturf.fr.")
    )
    texte = (
        f"Bienvenue sur BlackTurf, {prenom or 'parieur'} !\n\n"
        f"Confirmez votre adresse e-mail pour activer votre compte :\n{lien}\n\n"
        "Lien valable 24 heures. Sans confirmation, le compte reste inactif.\n"
        "Si vous n'êtes pas à l'origine de cette inscription, ignorez ce message.\n\n"
        f"{D.RESPONSABLE}"
    )
    return D.document("Confirmez votre adresse", "Plus qu’une étape pour activer votre compte BlackTurf.", rangees), texte


def reinitialisation_mot_de_passe(prenom: Optional[str], lien: str) -> tuple[str, str]:
    rangees = (
        D.barre_logo("Sécurité du compte")
        + D.entete(None, "Mot de passe oublié", "Choisissez un nouveau mot de passe",
                   f"Bonjour {e(prenom or 'parieur')}, une réinitialisation a été demandée pour votre compte BlackTurf.",
                   icone="cle")
        + _action("Réinitialiser mon mot de passe", lien, "Lien valable 1 heure, utilisable une seule fois.")
        + _securite("Si vous n’avez pas demandé cette réinitialisation, ignorez cet e-mail : votre mot de passe actuel reste inchangé. "
                    "BlackTurf ne vous demandera jamais votre mot de passe par e-mail.")
        + D.fermeture()
        + D.pied("Message de sécurité lié à votre compte blackturf.fr.")
    )
    texte = (
        f"Bonjour {prenom or 'parieur'},\n\n"
        f"Pour réinitialiser votre mot de passe BlackTurf (lien valable 1 heure) :\n{lien}\n\n"
        "Si vous n'avez pas demandé cette réinitialisation, ignorez cet e-mail.\n\n"
        f"{D.RESPONSABLE}"
    )
    return D.document("Réinitialisation du mot de passe", "Lien valable 1 heure pour choisir un nouveau mot de passe.", rangees), texte


def resiliation(via_stripe: bool) -> tuple[str, str]:
    if via_stripe:
        detail = ("Votre abonnement prendra fin à l’échéance de la période en cours ; "
                  "vous gardez l’accès à toutes vos fonctionnalités jusque-là.")
    else:
        detail = ("Elle sera traitée sous 72 h. Vous conservez l’accès jusqu’au traitement. "
                  "Pour toute question : contact@blackturf.fr")
    carte = (
        D.surtitre("Et maintenant ?")
        + f'<div style="font-size:14px;line-height:22px;color:{C["slate7"]}">{detail}</div>'
        + f'<div style="margin-top:14px;font-size:14px;line-height:22px;color:{C["slate7"]}">Une question, un changement d’avis ? '
          f'Écrivez-nous à <a href="mailto:contact@blackturf.fr" style="color:{C["or"]};font-weight:700">contact@blackturf.fr</a>.</div>'
    )
    rangees = (
        D.barre_logo("Votre abonnement")
        + D.entete(None, "Demande enregistrée", "Votre résiliation est bien prise en compte",
                   "Merci d’avoir fait un bout de chemin avec BlackTurf.", icone="valide")
        + _carte_claire(carte)
        + D.appel("Toujours les courses du jour", "Le programme et les arrivées restent consultables librement sur le site.",
                  "Voir les courses du jour", SITE + "/programme")
        + D.bloc_instagram()
        + D.pied("Message lié à votre abonnement blackturf.fr.")
    )
    texte = (
        "Votre demande de résiliation a bien été enregistrée.\n\n"
        f"{detail.replace('’', chr(39))}\n\n"
        f"Une question : contact@blackturf.fr\n\n{D.RESPONSABLE}"
    )
    return D.document("Résiliation enregistrée", "Votre demande de résiliation est bien prise en compte.", rangees), texte
