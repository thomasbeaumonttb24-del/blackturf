"""Mail de l'offre anniversaire (services/offre_anniversaire.py).

Même habillage que les autres mails (services/email_design.py). Le code est
passé en paramètre : il vient du .env au moment de l'envoi, jamais du dépôt.
Rend `(html, texte)`.
"""
from __future__ import annotations

from typing import Optional

from services import email_design as D
from services.email_design import C, CLAIR, POLICE, SITE, e
from services.offre_anniversaire import FIN_TEXTE, POURCENT, PRIX


def _euros(cents: int) -> str:
    return (f"{cents // 100}" if cents % 100 == 0 else f"{cents / 100:.2f}".replace(".", ",")) + " €"


def lien_offre(code: str) -> str:
    return f"{SITE}/tarifs?code={code}#formules"


def _ticket(code: str) -> str:
    """Le bon de réduction : bord pointillé or, code en gros, échéance."""
    return f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#FFFBEB" style="width:100%;border-collapse:separate;background:#FFFBEB;border:2px dashed #C99A3C;border-radius:18px">
  <tr><td align="center" style="padding:22px 18px 20px;text-align:center">
    <div style="font-size:11px;line-height:16px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:#B45309">Votre code personnel</div>
    <div class="gros" style="margin:10px 0 6px;font-size:40px;line-height:46px;font-weight:700;letter-spacing:.06em;color:{C['encre']};font-family:'SFMono-Regular',Menlo,Consolas,'Courier New',monospace">{e(code)}</div>
    <div style="display:inline-block;margin:6px 0 0;padding:6px 14px;border-radius:999px;background:#C2410C;color:#ffffff;font-size:15px;line-height:20px;font-weight:800;font-family:{POLICE}">−{POURCENT} % sur votre 1<sup>er</sup> mois</div>
    <div style="margin:12px 0 0;font-size:12.5px;line-height:19px;color:#78716C">Offre exceptionnelle · valable jusqu’au <b style="color:#1C1917">{FIN_TEXTE}</b></div>
  </td></tr>
</table>"""


def _prix(plan: str, nom: str, accroche: str, mise_en_avant: bool) -> str:
    avant, apres = PRIX[plan]
    fond, bord, encre, sous = (("#1C1917", "#C99A3C", "#FCD34D", "#D6D3D1") if mise_en_avant
                               else ("#FFFFFF", "#ECE7DC", "#0F172A", "#78716C"))
    badge = ('<div style="margin:0 0 8px"><span style="display:inline-block;padding:3px 9px;border-radius:999px;'
             'background:#FCD34D;color:#1C1917;font-size:10px;line-height:14px;font-weight:800;letter-spacing:.08em;'
             'text-transform:uppercase">Recommandé</span></div>') if mise_en_avant else ""
    return f"""
<td class="col2" width="50%" valign="top" style="width:50%;padding:0 6px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{fond}" style="width:100%;border-collapse:separate;background:{fond};border:{'2' if mise_en_avant else '1'}px solid {bord};border-radius:16px">
    <tr><td style="padding:16px 16px 18px">
      {badge}<div style="font-size:17px;line-height:22px;font-weight:700;color:{encre if mise_en_avant else C['encre']};font-family:{POLICE}">{nom}</div>
      <div style="font-size:12px;line-height:17px;color:{sous};margin:2px 0 10px">{accroche}</div>
      <div style="font-size:14px;line-height:18px;color:{sous};text-decoration:line-through">{_euros(avant)}</div>
      <div style="font-size:30px;line-height:34px;font-weight:700;color:{encre};font-family:{POLICE}">{_euros(apres)}<span style="font-size:13px;font-weight:600;color:{sous}"> le 1<sup>er</sup> mois</span></div>
      <div style="font-size:11.5px;line-height:16px;color:{sous};margin-top:6px">puis {_euros(avant)}/mois, résiliable à tout moment</div>
    </td></tr>
  </table>
</td>"""


def _avantages() -> str:
    lignes = [
        ("ia", "Le classement de l’algorithme", "Probabilités, cote juste et signaux sur chaque course du jour."),
        ("etoile", "Les paris de valeur", "Les cotes que le marché sous-estime, repérées pour vous."),
        ("euro", "Le plan de mise personnalisé", "Combien jouer et sur quoi, selon votre profil de risque."),
    ]
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


def anniversaire(prenom: Optional[str], mois: int, code: str, desinscription: str) -> tuple[str, str]:
    """`mois` : nombre de mois depuis la mise en ligne ; `desinscription` : lien
    de désabonnement aux e-mails (mail commercial, obligatoire)."""
    bonjour = f"Bonjour {e(prenom.strip())}," if prenom and prenom.strip() else "Bonjour,"
    duree = f"{mois} mois" if mois > 1 else "un mois"
    lien = lien_offre(code)
    intro = (
        f"{bonjour}<br><br>Il y a {duree}, BlackTurf ouvrait ses portes. Vous faites partie de nos "
        f"{D.fort('tout premiers inscrits')}, et c’est grâce à vous que le site grandit chaque jour.<br><br>"
        f"Pour vous dire merci, nous vous offrons, à titre {D.fort('exceptionnel')}, "
        f"{D.fort(f'−{POURCENT} % sur votre premier mois')} d’abonnement mensuel."
    )
    carte_offre = (
        _ticket(code)
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:18px"><tr>'
        + _prix("standard", "Standard", "L’essentiel, avec des quotas", False)
        + _prix("expert", "Expert", "Tout BlackTurf, sans limite", True)
        + "</tr></table>"
    )
    etapes = (
        f"1. Cliquez sur le bouton ci-dessus : le code est {D.fort('déjà renseigné')}.<br>"
        "2. Choisissez Standard ou Expert, en mensuel.<br>"
        f"3. La remise s’affiche sur la page de paiement sécurisé : {D.fort('vous ne payez que la moitié')} du premier mois.<br><br>"
        "La remise porte sur le premier paiement uniquement ; l’abonnement se poursuit ensuite au prix habituel "
        "et reste résiliable à tout moment depuis votre profil. Code personnel, réservé aux membres inscrits "
        "avant le 8 octobre, non cumulable avec la remise de parrainage."
    )
    rangees = (
        D.barre_logo(f"{duree} · Merci")
        + D.entete("galop", f"BlackTurf a {duree}", "Joyeux anniversaire… et merci&nbsp;!", intro, lien=lien)
        + D.rangee_nuit(carte_offre, padding="0 20px 24px")
        + D.appel("On fête ça ensemble ?", f"Votre remise vous attend jusqu’au {FIN_TEXTE}.",
                  f"Profiter de −{POURCENT} %", lien,
                  note=f"Le bouton ne s’affiche pas ? Rendez-vous sur blackturf.fr/tarifs et saisissez le code {e(code)}.")
        + D.rangee_nuit(D.carte(D.surtitre("Ce que vous débloquez") + _avantages(), "22px 22px"), padding="0 20px 24px")
        + D.encart("Comment en profiter", etapes)
        + D.bloc_reseaux()
        + D.pied("Vous recevez ce message parce que vous avez un compte sur blackturf.fr. "
                 + D.lien_pied("Ne plus recevoir nos offres", desinscription) + " · "
                 + D.lien_pied("Mes préférences", SITE + "/notifications"))
    )
    texte = (
        f"{bonjour.replace('&#x27;', chr(39))}\n\n"
        f"Il y a {duree}, BlackTurf ouvrait ses portes. Vous faites partie de nos tout premiers inscrits : "
        f"pour vous remercier, nous vous offrons à titre exceptionnel −{POURCENT} % sur votre premier mois "
        "d'abonnement mensuel.\n\n"
        f"VOTRE CODE : {code}\n"
        f"Valable jusqu'au {FIN_TEXTE}.\n\n"
        f"Standard : {_euros(PRIX['standard'][1])} le 1er mois au lieu de {_euros(PRIX['standard'][0])}\n"
        f"Expert : {_euros(PRIX['expert'][1])} le 1er mois au lieu de {_euros(PRIX['expert'][0])}\n\n"
        f"J'en profite : {lien}\n\n"
        "La remise porte sur le premier paiement uniquement ; l'abonnement se poursuit ensuite au prix "
        "habituel, résiliable à tout moment. Réservé aux membres inscrits avant le 8 octobre, non cumulable "
        "avec la remise de parrainage.\n\n"
        f"Ne plus recevoir nos offres : {desinscription}\n\n{D.RESPONSABLE}"
    )
    return D.document(f"BlackTurf a {duree}", f"Merci d’être là depuis le début : −{POURCENT} % sur votre premier mois, jusqu’au {FIN_TEXTE}.",
                      rangees), texte
