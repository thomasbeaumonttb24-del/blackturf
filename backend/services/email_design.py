"""Habillage commun des e-mails BlackTurf.

Un seul gabarit pour tous les mails envoyés aux visiteurs et aux abonnés
(pronostic gratuit, valeurs du jour, bilan hebdomadaire, confirmations,
compte) : fond nuit, bandeau logo, photo fondue, bande de titre, fenêtre du
site, bouton or en relief, bloc Instagram, pied légal. Chaque mail ne décrit
que son contenu propre ; l'enveloppe, elle, ne peut plus diverger d'un mail à
l'autre.

Règles e-mail : tables et styles en ligne uniquement (Outlook), dégradés CSS
toujours posés sur un `bgcolor` plein (un client qui les ignore affiche la
couleur unie), reliefs et pictogrammes cuits en images par
scripts/generer_visuels_email.py et servis depuis blackturf.fr/img/email/.
"""
from __future__ import annotations

from html import escape
from typing import Optional

SITE = "https://blackturf.fr"
IMG = f"{SITE}/img/email"
INSTAGRAM = "https://www.instagram.com/blackturf.fr/"
RESPONSABLE = (
    "Les résultats passés ne garantissent pas les résultats futurs. Jouer comporte des risques : "
    "endettement, isolement, dépendance. Appelez le 09 74 75 13 13 (appel non surtaxé). "
    "Réservé aux personnes majeures."
)

POLICE = "'Space Grotesk',-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"
TEXTE = "-apple-system,'Segoe UI',Roboto,Helvetica,Arial,sans-serif"

# Palette de la fiche course (CX dans plan-mise.tsx + classes Tailwind du site)
# et du fond nuit des mails.
C = {
    "page": "#FFFDF6", "carte": "#FFFFFF", "creme": "#FCFAF5", "bord": "#ECE7DC", "bord2": "#EFE8D8",
    "encre": "#0F172A", "encre2": "#1F2937", "slate7": "#334155", "slate6": "#475569",
    "stone5": "#78716C", "stone6": "#57534E", "stone3": "#D6D3D1", "stone2": "#E7E5E4", "stone1": "#F5F5F4",
    "or": "#B45309", "orFonce": "#92400E", "orClair": "#FEF6E7", "orBord": "#F5DCA8", "ambre": "#F59E0B",
    "vert": "#047857", "vertFond": "#ECFDF5", "vertBord": "#A7F3D0", "vertPlein": "#059669",
    "rouge": "#BE123C", "rougeFond": "#FFF1F2", "rougeBord": "#FECDD3",
    "numero": "#172033", "nuit": "#14110C", "fond": "#0F0D09",
    "orNuit": "#E3C27A", "texteNuit": "#D9D2C3", "douxNuit": "#BDB4A2", "gris": "#8C8272",
}


def e(v) -> str:
    return escape(str(v if v is not None else ""), quote=True)


# ─── Petites briques ────────────────────────────────────────────────────────

def pastille(texte: str, fg: str, bg: str, bd: str, taille: int = 11, gras: int = 700, maj: bool = False) -> str:
    style_maj = "text-transform:uppercase;letter-spacing:.06em;" if maj else ""
    return (
        f'<span style="display:inline-block;padding:3px 9px;border-radius:999px;background:{bg};'
        f'border:1px solid {bd};color:{fg};font-size:{taille}px;line-height:16px;font-weight:{gras};'
        f'{style_maj}white-space:nowrap;font-family:{TEXTE}">{texte}</span>'
    )


def barre(fraction: float, debut: str, fin: str, hauteur: int = 6, fond: str = C["stone1"]) -> str:
    """Barre de progression : cellule pleine (couleur de repli + dégradé) et
    gouttière. Robuste partout, y compris sans CSS."""
    w = max(2, min(100, round(fraction * 100)))
    plein = (
        f'<td width="{w}%" bgcolor="{fin}" style="width:{w}%;height:{hauteur}px;line-height:{hauteur}px;'
        f'font-size:0;background:{fin};background-image:linear-gradient(90deg,{debut},{fin});'
        f'border-radius:{hauteur}px">&nbsp;</td>'
    )
    vide = (
        f'<td bgcolor="{fond}" style="height:{hauteur}px;line-height:{hauteur}px;font-size:0">&nbsp;</td>'
        if w < 100 else ""
    )
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        f'style="width:100%;border-collapse:separate;background:{fond};border-radius:{hauteur}px;'
        f'box-shadow:inset 0 1px 1px rgba(0,0,0,.08)"><tr>{plein}{vide}</tr></table>'
    )


def numero(n) -> str:
    """Pastille du numéro de partant, comme CasaqueNumero côté site."""
    return (
        f'<span style="display:inline-block;min-width:24px;padding:4px 5px;border-radius:6px;'
        f'background:{C["numero"]};color:#ffffff;font-size:13px;line-height:16px;font-weight:800;'
        f'text-align:center;font-family:{POLICE}">{e(n)}</span>'
    )


def url_casaque(url: Optional[str]) -> str:
    """Image PMU de la casaque ; repli sur une casaque neutre, jamais d'image cassée."""
    if url and str(url).startswith(("https://", "http://")):
        return "https://" + str(url).split("://", 1)[1]
    return f"{IMG}/casaque-neutre.png"


def casaque(url: Optional[str], n, taille: int = 40) -> str:
    """Casaque dans un écrin blanc en relief, numéro du partant dessous."""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0" style="border-collapse:separate;margin:0 auto">'
        f'<tr><td align="center" bgcolor="#ffffff" style="background:#ffffff;border:1px solid {C["bord"]};border-bottom:2px solid #DDD5C2;'
        f'border-radius:12px;padding:4px;box-shadow:0 6px 12px -8px rgba(17,24,39,.35)">'
        f'<img src="{e(url_casaque(url))}" width="{taille}" height="{taille}" alt="Casaque du n°{e(n)}" '
        f'style="display:block;width:{taille}px;height:{taille}px;border:0;object-fit:contain"></td></tr>'
        f'<tr><td align="center" style="padding-top:4px">{numero(n)}</td></tr></table>'
    )


def etoiles(niveau: int, taille: int = 18) -> str:
    niveau = max(0, min(4, int(niveau)))
    return (
        f'<span style="color:#D99A1E;font-size:{taille}px;letter-spacing:2px">{"★" * niveau}</span>'
        f'<span style="color:{C["stone3"]};font-size:{taille}px;letter-spacing:2px">{"☆" * (4 - niveau)}</span>'
    )


def tuile_chiffre(titre: str, corps: str, classe: str = "stat") -> str:
    """Case chiffrée crème, comme les tuiles téléphone du classement."""
    return (
        f'<td class="{classe}" valign="top" style="padding:0 3px">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;'
        f'background:{C["creme"]};border:1px solid {C["bord2"]};border-bottom:2px solid #E6DDC8;border-radius:12px">'
        f'<tr><td class="statin" style="padding:7px 9px;height:42px;vertical-align:top">'
        f'<div class="stitre" style="font-size:9.5px;line-height:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;'
        f'color:{C["stone5"]};white-space:nowrap">{titre}</div>{corps}</td></tr></table></td>'
    )


def chiffre(v: str, couleur: str = C["encre"], taille: int = 16) -> str:
    return (
        f'<div style="font-size:{taille}px;line-height:{taille + 5}px;font-weight:700;color:{couleur};'
        f'font-family:{POLICE};letter-spacing:-.01em;white-space:nowrap">{v}</div>'
    )


def carte(contenu: str, padding: str = "16px", fond: str = "#ffffff", classe: str = "") -> str:
    """Carte blanche en relief (bord, tranche basse plus sombre, ombre douce)."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;'
        f'background:{fond};border:1px solid {C["bord"]};border-bottom:3px solid #E3DCCB;border-radius:20px;'
        f'box-shadow:0 1px 2px rgba(17,24,39,.04),0 18px 40px -28px rgba(17,24,39,.35)">'
        f'<tr><td class="{classe}" style="padding:{padding}">{contenu}</td></tr></table>'
    )


def titre_section(icone: str, titre: str, sous_titre: str = "") -> str:
    """En-tête de carte avec tuile or en relief (IconeTuile côté site)."""
    sous = f'<div style="font-size:12px;line-height:16px;color:{C["stone5"]}">{sous_titre}</div>' if sous_titre else ""
    return (
        f'<table role="presentation" cellpadding="0" cellspacing="0"><tr>'
        f'<td width="44" valign="middle" style="width:44px"><img src="{IMG}/tuile-{icone}.png" width="40" height="40" alt="" '
        f'style="display:block;width:40px;height:40px;border:0"></td>'
        f'<td valign="middle" style="padding-left:8px"><div style="font-size:17px;line-height:22px;font-weight:700;color:#1C1917;'
        f'font-family:{POLICE}">{titre}</div>{sous}</td></tr></table>'
    )


def surtitre(t: str, couleur: str = C["or"]) -> str:
    return (
        f'<div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;'
        f'color:{couleur};margin:0 0 10px">{t}</div>'
    )


# ─── Blocs de page (chacun est une rangée <tr> du gabarit) ───────────────────

def rangee_nuit(contenu: str, padding: str = "0 28px 28px", classe: str = "px", centre: bool = False) -> str:
    align = "text-align:center;" if centre else ""
    return (
        f'<tr><td bgcolor="{C["nuit"]}" class="{classe}" style="background:{C["nuit"]};padding:{padding};{align}'
        f'color:#ffffff">{contenu}</td></tr>'
    )


def barre_logo(mention: str) -> str:
    return f"""
  <tr><td style="padding:0 0 12px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#ffffff" style="width:100%;border-collapse:separate;background:#ffffff;border-radius:18px;border-top:4px solid #C99A3C;box-shadow:0 10px 30px -12px rgba(0,0,0,.6)">
      <tr>
        <td class="logo" style="padding:10px 18px" valign="middle"><a href="{SITE}"><img src="{IMG}/logo-blackturf.png" width="104" alt="BlackTurf" style="display:block;width:104px;height:auto;border:0"></a></td>
        <td align="right" valign="middle" style="padding:10px 18px">
          <span class="mention" style="display:inline-block;padding:6px 12px;border-radius:999px;background:#FEF3C7;border:1px solid #FCD34D;color:{C['orFonce']};font-size:11px;line-height:14px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap">{mention}</span>
        </td>
      </tr>
    </table>
  </td></tr>"""


def entete(photo: Optional[str], surtitre_: str, titre: str, intro: str, lien: str = SITE,
           suite: str = "", legende_photo: str = "", icone: Optional[str] = None) -> str:
    """Photo fondue (ou simple bande sombre si `photo` est None), puis surtitre
    or, grand titre, chapeau et contenu libre (`suite`) sur fond nuit."""
    if photo:
        haut = (
            f'<tr><td style="border-radius:22px 22px 0 0;overflow:hidden;background:{C["nuit"]}">'
            f'<a href="{e(lien)}"><img src="{IMG}/hero-{photo}.jpg" width="640" alt="Chevaux en course — photo d’illustration" '
            f'style="display:block;width:100%;max-width:640px;height:auto;border:0;border-radius:22px 22px 0 0;color:#ffffff;font-size:13px"></a></td></tr>'
        )
        pad = "4px 28px 26px"
    else:
        haut = ""
        pad = "30px 28px 26px"
    legende = (
        f'<div style="margin-top:14px;font-size:10.5px;line-height:15px;color:#6F6656">{legende_photo}</div>' if legende_photo else ""
    )
    arrondi = "" if photo else "border-radius:22px 22px 0 0;"
    picto = (
        f'<img src="{IMG}/tuile-{icone}.png" width="56" height="56" alt="" style="display:block;width:56px;height:56px;border:0;margin:0 0 14px">'
        if icone else ""
    )
    return haut + f"""
  <tr><td bgcolor="{C['nuit']}" class="px" style="background:{C['nuit']};padding:{pad};color:#ffffff;{arrondi}">
    {picto}    <div style="font-size:11px;line-height:16px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:{C['orNuit']}">{surtitre_}</div>
    <h1 class="h1hero" style="margin:8px 0 10px;font-size:32px;line-height:37px;font-weight:700;letter-spacing:-.02em;color:#ffffff;font-family:{POLICE}">{titre}</h1>
    <div style="font-size:15px;line-height:23px;color:{C['texteNuit']}">{intro}</div>
    {suite}{legende}
  </td></tr>"""


def fenetre_site(url: str, contenu_rangees: str) -> str:
    """Fenêtre de navigateur autour d'une réplique du site : la barre d'adresse
    montre l'URL réelle, cliquable. `contenu_rangees` : des <tr>."""
    affichee = url.split("?", 1)[0].replace("https://", "")
    return f"""
  <tr><td bgcolor="{C['nuit']}" style="background:{C['nuit']};padding:0 0 28px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%"><tr><td class="px" style="padding:0 20px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;border:1px solid #2A241A;
    border-radius:16px;overflow:hidden;background:{C['page']};box-shadow:0 30px 60px -20px rgba(0,0,0,.55),0 12px 24px -12px rgba(0,0,0,.35)">
    <tr><td bgcolor="#221D15" style="background:#221D15;background-image:linear-gradient(180deg,#2C261C,#1C1811);padding:10px 12px;border-radius:15px 15px 0 0">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed"><tr>
        <td width="52" style="width:52px;font-size:13px;line-height:13px;white-space:nowrap">
          <span style="color:#FF5F57">●</span><span style="color:#FEBC2E">●</span><span style="color:#28C840">●</span>
        </td>
        <td><a href="{e(url)}" style="display:block;padding:5px 10px;border-radius:8px;background:#0F0C08;color:#D6C7A1;
          font-size:11.5px;line-height:15px;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">&#128274; {e(affichee)}</a></td>
      </tr></table>
    </td></tr>
    <tr><td bgcolor="{C['page']}" style="background:{C['page']};background-image:radial-gradient(ellipse at 18% 0%,rgba(245,158,11,.08) 0%,transparent 46%),linear-gradient(180deg,#FFFDF6 0%,#FAFAF8 60%);padding:0 0 16px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">{contenu_rangees}</table>
    </td></tr>
  </table>
  </td></tr></table>
  </td></tr>"""


def rangee_site(contenu: str, padding: str = "16px 16px 0") -> str:
    """Rangée à l'intérieur de la fenêtre du site."""
    return f'<tr><td class="sec" style="padding:{padding}">{contenu}</td></tr>'


def bouton(label: str, url: str) -> str:
    """Bouton en relief : dégradé or, tranche sombre en bas, ombre portée."""
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto">
  <tr><td align="center" bgcolor="#D97706" style="border-radius:14px;background:#D97706;background-image:linear-gradient(180deg,#FCD34D 0%,#F59E0B 45%,#D97706 100%);
    border-bottom:4px solid #92400E;box-shadow:0 14px 26px -12px rgba(180,83,9,.75),inset 0 1px 0 rgba(255,255,255,.6)">
    <!--[if mso]><a href="{e(url)}" style="font-size:16px;color:#1C1917;font-weight:bold;text-decoration:none;padding:16px 30px;display:block">{label} &rarr;</a><![endif]-->
    <!--[if !mso]><!--><a href="{e(url)}" style="display:inline-block;padding:16px 30px;font-size:16px;line-height:20px;font-weight:800;color:#1C1917;
      text-decoration:none;font-family:{POLICE};letter-spacing:-.01em">{label} &rarr;</a><!--<![endif]-->
  </td></tr>
</table>"""


def appel(titre: str, texte: str, label: str, url: str, note: str = "") -> str:
    """Titre, phrase et bouton or, centrés sur fond nuit."""
    note_html = f'<div style="margin-top:14px;font-size:12px;line-height:18px;color:{C["gris"]}">{note}</div>' if note else ""
    return rangee_nuit(
        f'<div style="font-size:19px;line-height:26px;font-weight:700;color:#ffffff;font-family:{POLICE};margin:0 0 6px">{titre}</div>'
        f'<div style="font-size:14px;line-height:22px;color:{C["douxNuit"]};margin:0 0 20px">{texte}</div>'
        f'{bouton(label, url)}{note_html}',
        padding="0 28px 30px", centre=True,
    )


def encart(titre: str, html: str) -> str:
    """Encadré explicatif sombre (« Comment lire », « À retenir »…)."""
    return rangee_nuit(
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;background:#1D1810;border:1px solid #33291A;border-radius:16px">'
        f'<tr><td style="padding:16px 18px;font-size:12.5px;line-height:20px;color:{C["douxNuit"]}">'
        f'<div style="font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:{C["orNuit"]};margin-bottom:6px">{titre}</div>'
        f'{html}</td></tr></table>',
        padding="0 20px 24px",
    )


def fort(t: str) -> str:
    """Mot en évidence dans un encart sombre."""
    return f'<b style="color:#F3EBDA">{t}</b>'


def bloc_instagram(accroche: str = "Les infos du jour, les coups de cœur et les arrivées, en story.") -> str:
    return f"""
  <tr><td bgcolor="{C['nuit']}" class="px" style="background:{C['nuit']};padding:0 20px 28px;border-radius:0 0 22px 22px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#2A1B3D" style="width:100%;border-collapse:separate;border-radius:18px;
      background:#2A1B3D;background-image:linear-gradient(120deg,#F58529 0%,#DD2A7B 45%,#8134AF 75%,#515BD4 100%);border-bottom:3px solid #3B1E5A;box-shadow:0 18px 34px -18px rgba(221,42,123,.7)">
      <tr>
        <td width="76" valign="middle" style="width:76px;padding:16px 0 16px 18px">
          <a href="{INSTAGRAM}"><img src="{IMG}/instagram-glyph.png" width="52" height="52" alt="Instagram" style="display:block;width:52px;height:52px;border:0;border-radius:14px;background:#ffffff"></a>
        </td>
        <td valign="middle" style="padding:16px 12px">
          <div style="font-size:17px;line-height:22px;font-weight:800;color:#ffffff;font-family:{POLICE}">@blackturf.fr</div>
          <div style="font-size:13px;line-height:19px;color:#FDE7F3">{accroche}</div>
        </td>
        <td align="right" valign="middle" style="padding:16px 18px 16px 0">
          <a href="{INSTAGRAM}" style="display:inline-block;padding:10px 14px;border-radius:12px;background:#ffffff;color:#9B1B6B;font-size:13px;font-weight:800;text-decoration:none;white-space:nowrap;box-shadow:0 6px 14px -6px rgba(0,0,0,.45)">Suivre</a>
        </td>
      </tr>
    </table>
  </td></tr>"""


def fermeture() -> str:
    """Arrondi bas de la carte nuit, pour les mails sans bloc Instagram."""
    return (
        f'<tr><td bgcolor="{C["nuit"]}" style="background:{C["nuit"]};height:8px;line-height:8px;font-size:0;'
        f'border-radius:0 0 22px 22px">&nbsp;</td></tr>'
    )


def pied(mention: str, responsable: str = RESPONSABLE) -> str:
    return f"""
  <tr><td style="padding:26px 20px 0;text-align:center">
    <a href="{SITE}"><img src="{IMG}/cheval-or.png" width="64" alt="BlackTurf" style="display:inline-block;width:64px;height:auto;border:0"></a>
    <div style="margin:10px 0 14px;font-size:12px;line-height:18px">
      <a href="{SITE}/programme" style="color:{C['orNuit']};text-decoration:none;font-weight:700">Courses du jour</a>
      <span style="color:#5B5140">&nbsp;·&nbsp;</span>
      <a href="{SITE}/value-bets" style="color:{C['orNuit']};text-decoration:none;font-weight:700">Value bets</a>
      <span style="color:#5B5140">&nbsp;·&nbsp;</span>
      <a href="{SITE}/palmares" style="color:{C['orNuit']};text-decoration:none;font-weight:700">Palmarès</a>
      <span style="color:#5B5140">&nbsp;·&nbsp;</span>
      <a href="{INSTAGRAM}" style="color:{C['orNuit']};text-decoration:none;font-weight:700">Instagram</a>
    </div>
    <div style="font-size:11.5px;line-height:18px;color:{C['gris']};max-width:520px;margin:0 auto">{e(responsable)}</div>
    <div style="font-size:11.5px;line-height:18px;color:{C['gris']};max-width:520px;margin:12px auto 0">{mention}</div>
  </td></tr>"""


def lien_pied(label: str, url: str) -> str:
    return f'<a href="{e(url)}" style="color:{C["douxNuit"]};text-decoration:underline">{label}</a>'


def document(titre: str, preheader: str, rangees: str, lien_web: Optional[str] = None) -> str:
    """Page complète : <head>, fond nuit, colonne de 640 px, `rangees` (des <tr>)."""
    web = (
        f'<tr><td style="padding:0 0 10px;text-align:center;font-size:11px;line-height:16px">'
        f'<a href="{e(lien_web)}" style="color:{C["gris"]};text-decoration:underline">Lire et partager sur le web</a></td></tr>'
        if lien_web else ""
    )
    return f"""<!doctype html>
<html lang="fr" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<title>{e(titre)} — BlackTurf</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap');
  body{{margin:0;padding:0;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}}
  a{{text-decoration:none}}
  @media only screen and (max-width:620px){{
    .wrap{{width:100%!important}}
    .outer{{padding:12px 4px 24px!important}}
    .px{{padding-left:10px!important;padding-right:10px!important}}
    .col2{{display:block!important;width:100%!important;padding:0 0 10px 0!important}}
    .stat{{padding:0 2px!important}}
    .h1hero{{font-size:28px!important;line-height:33px!important}}
    .pod{{padding:0 3px!important}}
    .podpct{{font-size:17px!important;padding-left:5px!important}}
    .podnom{{font-size:11.5px!important;line-height:15px!important}}
    .tab{{padding:6px 8px!important;font-size:12px!important}}
    .cellpod{{padding:10px 8px!important}}
    .sec{{padding-left:8px!important;padding-right:8px!important}}
    .lec{{padding-left:10px!important;padding-right:10px!important}}
    .rowin{{padding:12px 8px 12px 6px!important}}
    .rk{{width:34px!important}}
    .vic{{width:74px!important}}
    .statin{{padding:6px 6px!important}}
    .cas{{width:50px!important;padding-left:2px!important}}
    .nom{{font-size:14px!important;line-height:18px!important}}
    .vicpct{{font-size:22px!important;line-height:26px!important}}
    .gros{{font-size:30px!important;line-height:34px!important}}
    .mention{{font-size:9.5px!important;letter-spacing:.04em!important;padding:5px 8px!important;white-space:normal!important}}
    .logo{{padding:8px 10px!important}}
    .recap{{font-size:17px!important;line-height:22px!important}}
    .recap span{{font-size:12px!important;letter-spacing:0!important}}
    .pf{{padding:8px 3px!important;font-size:12px!important}}
    .stitre{{font-size:8.5px!important;letter-spacing:.03em!important}}
  }}
  @media only screen and (max-width:360px){{
    .rk{{width:30px!important}}
    .cas{{width:44px!important}}
    .vic{{width:58px!important}}
    .vicpct{{font-size:18px!important;line-height:22px!important}}
    .nom{{font-size:13px!important}}
  }}
</style>
</head>
<body style="margin:0;padding:0;background:{C['fond']};font-family:{TEXTE};color:{C['encre2']}">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:{C['fond']}">{e(preheader)}&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{C['fond']}" style="width:100%;table-layout:fixed;background:{C['fond']};background-image:radial-gradient(ellipse at 50% 0%,#3A2E17 0%,#15110B 45%,#0F0D09 100%)">
<tr><td align="center" class="outer" style="padding:20px 8px 32px">
<!--[if mso]><table role="presentation" width="640" align="center"><tr><td><![endif]-->
<table role="presentation" class="wrap" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px">
{web}{rangees}
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body></html>"""
