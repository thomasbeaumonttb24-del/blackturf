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


def rappel_reconduction(prenom: Optional[str], plan: str, echeance, montant_cents: int) -> tuple[str, str]:
    """Information préalable à la reconduction d'un abonnement annuel (L215-1)."""
    mois = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre")
    date_txt = f"{echeance.day} {mois[echeance.month - 1]} {echeance.year}"
    nom = "Expert" if plan == "expert" else "Standard"
    prix = f"{montant_cents / 100:.2f}".replace(".", ",") + " €"
    detail = (f"Votre abonnement annuel {nom} arrive à échéance le {date_txt}. Sans action de "
              f"votre part, il sera reconduit pour un an et {prix} seront prélevés à cette date.")
    choix = ("Vous pouvez ne pas le reconduire : il suffit de résilier depuis votre profil "
             "(Profil → Abonnement → Résilier) avant le " + date_txt + ". Vous gardez alors "
             "l’accès jusqu’à l’échéance, et aucun prélèvement n’aura lieu.")
    carte = (
        D.surtitre("Ce qui va se passer")
        + f'<div style="font-size:14px;line-height:22px;color:{C["slate7"]}">{detail}</div>'
        + f'<div style="margin-top:14px;font-size:14px;line-height:22px;color:{C["slate7"]}">{choix}</div>'
        + f'<div style="margin-top:14px;font-size:14px;line-height:22px;color:{C["slate7"]}">Une question ? '
          f'<a href="mailto:contact@blackturf.fr" style="color:{C["or"]};font-weight:700">contact@blackturf.fr</a>.</div>'
    )
    rangees = (
        D.barre_logo("Votre abonnement")
        + D.entete(None, "Abonnement annuel", f"Échéance le {date_txt}",
                   "Information préalable à la reconduction de votre abonnement.", icone="valide")
        + _carte_claire(carte)
        + _action("Gérer mon abonnement", SITE + "/profil", "")
        + D.pied("Message lié à votre abonnement blackturf.fr.")
    )
    saut = chr(10)
    texte = saut.join([
        detail, "", choix.replace(chr(8217), chr(39)), "",
        f"Gérer mon abonnement : {SITE}/profil",
        "Une question : contact@blackturf.fr", "", D.RESPONSABLE,
    ])
    return D.document("Échéance de votre abonnement annuel", detail, rangees), texte


# Où tombera le crédit, selon la situation du parrain (cf. services/parrainage.situation_credit).
_OU_VA_LE_CREDIT = {
    "facture": "ils seront déduits automatiquement de votre prochaine facture.",
    "abonne": "ils seront déduits automatiquement de votre prochaine facture.",
    "offert": "votre abonnement vous étant offert, ils restent en réserve et seront déduits "
              "dès que vous aurez une facture à régler.",
    "resilie": "votre abonnement s’arrêtant à l’échéance, ils restent en réserve et seront "
               "déduits de votre prochain abonnement.",
    "sans_abonnement": "ils seront déduits automatiquement de l’abonnement que vous prendrez.",
    "reporte": "vous avez atteint le plafond de ce mois (votre mensualité est déjà entièrement "
               "couverte) : ils sont mis de côté et seront déduits de la facture du mois suivant. "
               "Rien n’est perdu.",
}


def parrainage_credite(prenom: Optional[str], prenom_filleul: Optional[str], lien: str,
                       situation: str = "facture") -> tuple[str, str]:
    ami = (prenom_filleul or "").split(" ")[0] or "Votre filleul"
    detail = (f"{ami} vient de régler son premier abonnement. 5 € de crédit sont posés sur "
              f"votre compte : {_OU_VA_LE_CREDIT.get(situation, _OU_VA_LE_CREDIT['facture'])}")
    carte = (
        D.surtitre("Comment ça marche ?")
        + f'<div style="font-size:14px;line-height:22px;color:{C["slate7"]}">{e(detail)}</div>'
        + f'<div style="margin-top:14px;font-size:14px;line-height:22px;color:{C["slate7"]}">'
          "Vos crédits se cumulent d’un filleul à l’autre. Au plus une mensualité est offerte "
          "par facture : le reste est reporté sur les suivantes.</div>"
    )
    rangees = (
        D.barre_logo("Parrainage")
        + D.entete(None, "Merci !", f"{e(prenom)}, vous avez gagné 5 €" if prenom else "Vous avez gagné 5 €",
                   "Grâce à votre parrainage.", icone="euro")
        + _carte_claire(carte)
        + D.appel("Continuez à parrainer", "Chaque ami qui s’abonne vous offre 5 € de plus.",
                  "Mon lien de parrainage", lien)
        + D.bloc_instagram()
        + D.pied("Message lié à votre compte blackturf.fr.")
    )
    texte = (
        f"Bonjour {prenom or ''},\n\n{detail.replace('’', chr(39))}\n\n"
        f"Votre lien de parrainage : {lien}\n\n{D.RESPONSABLE}"
    )
    return D.document("5 € offerts grâce à votre parrainage",
                      "Votre filleul s'est abonné : 5 € de crédit sur votre compte.", rangees), texte


def parrainage_inscrit(prenom: Optional[str], prenom_filleul: Optional[str], lien: str) -> tuple[str, str]:
    ami = (prenom_filleul or "").split(" ")[0] or "Un ami"
    detail = (f"{ami} vient de créer son compte avec votre lien. Dès qu’il réglera son premier "
              "abonnement (avec 5 € de remise), 5 € seront déduits automatiquement de votre "
              "prochaine mensualité. Vous serez prévenu par e-mail.")
    carte = (
        D.surtitre("Où en est-il ?")
        + f'<div style="font-size:14px;line-height:22px;color:{C["slate7"]}">{e(detail)}</div>'
        + f'<div style="margin-top:14px;font-size:14px;line-height:22px;color:{C["slate7"]}">'
          "Suivez chacun de vos filleuls, étape par étape, depuis l’onglet Parrainage de votre profil.</div>"
    )
    rangees = (
        D.barre_logo("Parrainage")
        + D.entete(None, "Bonne nouvelle", f"{e(ami)} a rejoint BlackTurf",
                   "Grâce à votre lien de parrainage.", icone="valide")
        + _carte_claire(carte)
        + D.appel("Suivre mes parrainages", "Inscrits, abonnés, crédits gagnés : tout est au même endroit.",
                  "Voir mon suivi", lien)
        + D.bloc_instagram()
        + D.pied("Message lié à votre compte blackturf.fr.")
    )
    texte = (
        f"Bonjour {prenom or ''},\n\n{detail.replace('’', chr(39))}\n\n"
        f"Votre suivi : {lien}\n\n{D.RESPONSABLE}"
    )
    return D.document(f"{ami} a rejoint BlackTurf", "Un ami s'est inscrit avec votre lien de parrainage.", rangees), texte


_MOIS = ("janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
         "septembre", "octobre", "novembre", "décembre")


def _date_heure_paris(d) -> str:
    from zoneinfo import ZoneInfo
    p = d.astimezone(ZoneInfo("Europe/Paris"))
    return f"{p.day} {_MOIS[p.month - 1]} {p.year} à {p.hour:02d} h {p.minute:02d}"


def confirmation_pass(prenom: Optional[str], libelle: str, montant_cents: int, debut, fin,
                      renonciation_texte: str, renonciation_at) -> tuple[str, str]:
    """Confirmation d'achat d'un pass, sur support durable (art. L221-13) : elle
    reprend la renonciation expresse au droit de rétractation."""
    prix = f"{montant_cents / 100:.2f}".replace(".", ",") + " €"
    detail = (f"Votre {libelle} est confirmé ({prix}, paiement unique). Accès Expert du "
              f"{_date_heure_paris(debut)} au {_date_heure_paris(fin)} (heure de Paris). "
              "Aucun renouvellement : l’accès s’arrête seul à cette date, rien ne sera prélevé.")
    renonciation = (f"Lors du paiement, le {_date_heure_paris(renonciation_at)}, vous avez coché : "
                    f"« {renonciation_texte} »")
    carte = (
        D.surtitre("Votre pass")
        + f'<div style="font-size:14px;line-height:22px;color:{C["slate7"]}">{e(detail)}</div>'
        + f'<div style="margin-top:14px;font-size:13px;line-height:20px;color:{C["slate7"]}">{e(renonciation)}</div>'
        + f'<div style="margin-top:14px;font-size:14px;line-height:22px;color:{C["slate7"]}">Une question ? '
          f'<a href="mailto:contact@blackturf.fr" style="color:{C["or"]};font-weight:700">contact@blackturf.fr</a>.</div>'
    )
    rangees = (
        D.barre_logo("Votre pass")
        + D.entete(None, "Paiement confirmé", libelle, "Votre accès Expert est ouvert.", icone="valide")
        + _carte_claire(carte)
        + _action("Voir les courses du jour", SITE + "/programme", "")
        + D.pied("Message lié à votre achat sur blackturf.fr.")
    )
    saut = chr(10)
    texte = saut.join([
        f"Bonjour {prenom or ''},", "", detail.replace(chr(8217), chr(39)), "",
        renonciation, "", f"Les courses du jour : {SITE}/programme",
        "Une question : contact@blackturf.fr", "", D.RESPONSABLE,
    ])
    return D.document("Votre pass BlackTurf", detail, rangees), texte


async def envoyer_confirmation_pass(user, p) -> None:
    from services.alerts import send_email
    from services.passes import PASSES, RENONCIATION_TEXTE

    libelle = PASSES[p.duree][2].split(" — ")[0]
    html, texte = confirmation_pass(user.prenom, libelle, p.montant_cents, p.debut, p.fin,
                                    RENONCIATION_TEXTE, p.renonciation_at)
    await send_email(to=user.email, subject=f"BlackTurf — {libelle} confirmé",
                     html=html, text=texte)