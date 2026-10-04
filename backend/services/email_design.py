"""Habillage commun des e-mails BlackTurf.

Un seul gabarit pour tous les mails envoyés aux visiteurs et aux abonnés
(pronostic gratuit, valeurs du jour, bilan hebdomadaire, confirmations,
compte) : bandeau logo, photo en carte, bande de titre, fenêtre du site,
bouton orange, bloc Instagram, pied légal — en clair ET en sombre (voir
« Clair / sombre » plus bas). Chaque mail ne décrit
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
# Mêmes adresses que AVIS dans frontend/src/lib/social.ts.
AVIS_TRUSTPILOT = "https://fr.trustpilot.com/evaluate/blackturf.fr"
AVIS_GOOGLE = "https://g.page/r/Ca-aIiYY44FdEBM/review"
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


# ─── Clair / sombre ─────────────────────────────────────────────────────────
#
# Les téléphones affichent les mails en clair OU en sombre, et chaque client
# s'y prend à sa façon :
# - Gmail (Android, iOS) et Outlook ignorent nos styles sombres et INVERSENT
#   eux-mêmes : fonds clairs → sombres, textes sombres → clairs. Ils ne touchent
#   ni aux images ni aux `background-image`. Un mail sombre « en dur » en sort
#   cassé (texte inversé posé sur un dégradé resté sombre) ; un mail CLAIR, lui,
#   se convertit proprement.
# - Apple Mail / iOS Mail et Outlook macOS lisent `prefers-color-scheme` :
#   ils reçoivent la palette sombre ci-dessous (classes bt-*).
# - Outlook.com marque ses éléments [data-ogsc] (couleur) / [data-ogsb] (fond).
#
# D'où trois règles pour tout ce qui suit :
# 1. base claire (crème du site), version sombre par classe ;
# 2. jamais de texte sur un `background-image` (dégradé) : couleur pleine ;
# 3. les « îlots » de contenu (carte, fenêtre du site, tuiles, podium) restent
#    clairs dans les deux modes : leurs couleurs en ligne restent lisibles.

SOMBRE = {
    "pg": ("background", "#0B0A07"), "fd": ("background", "#14110C"), "lg": ("background", "#1A160F"),
    "ca": ("background", "#1D1810"),
    "te": ("color", "#F5EFE3"), "tt": ("color", "#D9D2C3"), "td": ("color", "#A8A08F"),
    "to": ("color", "#E9C46A"), "tv": ("color", "#34D399"), "tr": ("color", "#FB7185"),
    "bd": ("border-color", "#2E271B"),
}
CLAIR = {
    "pg": "#F3EDE1", "fd": "#FFFDF8", "lg": "#FFFFFF", "ca": "#FCF8EF", "bord": "#E9E1D0",
    "te": "#1C1917", "tt": "#44403C", "td": "#78716C", "to": "#B45309", "tv": "#047857", "tr": "#BE123C",
    "bouton": "#C2410C", "boutonTranche": "#7C2D12",
}


def _css_sombre() -> str:
    regles = [f".bt-{k}{{{p}:{v}!important}}" for k, (p, v) in SOMBRE.items()]
    regles.append(".bt-pg,.bt-fd,.bt-lg,.bt-ca{background-image:none!important}")
    regles.append(".bt-pi{background:#2A2215!important;border-color:#5B4A2A!important;color:#E9C46A!important}")
    regles.append(".bt-ca,.bt-lg{border-color:#3A2F1C!important}")
    ogsb = [f"[data-ogsb] .bt-{k}{{background:{v}!important}}" for k, (p, v) in SOMBRE.items() if p == "background"]
    ogsc = [f"[data-ogsc] .bt-{k}{{color:{v}!important}}" for k, (p, v) in SOMBRE.items() if p == "color"]
    return ("@media (prefers-color-scheme:dark){" + "".join(regles) + "}\n" + "".join(ogsb) + "\n" + "".join(ogsc))


def _ligne(contenu: str, padding: str, classe: str = "px", centre: bool = False, extra: str = "") -> str:
    align = "text-align:center;" if centre else ""
    return (f'<tr><td bgcolor="{CLAIR["fd"]}" class="bt-fd {classe}" style="background:{CLAIR["fd"]};padding:{padding};'
            f'{align}color:{CLAIR["tt"]};{extra}">{contenu}</td></tr>')


def petite_note(t: str, taille: float = 12.5, marge: str = "12px 0 0") -> str:
    """Petit texte discret sur le fond de page (note sous un bouton, précision)."""
    return (f'<div class="bt-td" style="margin:{marge};font-size:{taille}px;line-height:{round(taille * 1.5)}px;'
            f'color:{CLAIR["td"]}">{t}</div>')


def lien_or(label: str, url: str, souligne: bool = True) -> str:
    deco = "underline" if souligne else "none"
    return (f'<a class="bt-to" href="{e(url)}" style="color:{CLAIR["to"]};text-decoration:{deco};font-weight:700;'
            f'word-break:break-all">{label}</a>')


def vert(t: str) -> str:
    return f'<span class="bt-tv" style="color:{CLAIR["tv"]};font-weight:700">{t}</span>'


def rouge(t: str) -> str:
    return f'<span class="bt-tr" style="color:{CLAIR["tr"]};font-weight:700">{t}</span>'


# ─── Blocs de page (chacun est une rangée <tr> du gabarit) ───────────────────

def rangee_nuit(contenu: str, padding: str = "0 28px 28px", classe: str = "px", centre: bool = False) -> str:
    """Rangée du corps du mail. Le nom date du fond nuit d'origine : c'est
    désormais le fond de page, crème en clair et nuit en sombre."""
    return _ligne(contenu, padding, classe, centre)


def barre_logo(mention: str) -> str:
    return f"""
  <tr><td style="padding:0 0 12px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CLAIR['lg']}" class="bt-lg" style="width:100%;border-collapse:separate;background:{CLAIR['lg']};border:1px solid {CLAIR['bord']};border-radius:18px;border-top:3px solid #C99A3C">
      <tr>
        <td class="logo" style="padding:10px 18px" valign="middle"><a href="{SITE}" style="text-decoration:none"><table role="presentation" cellpadding="0" cellspacing="0"><tr>
          <td valign="middle"><img class="logoimg" src="{IMG}/logo-medaillon.png" width="72" height="72" alt="BlackTurf" style="display:block;width:72px;height:72px;border:0"></td>
          <td valign="middle" class="marque bt-te" style="padding-left:10px;font-size:24px;line-height:28px;font-weight:700;letter-spacing:-.02em;color:{CLAIR['te']};font-family:{POLICE};white-space:nowrap">Black<span class="bt-to" style="color:{CLAIR['to']}">Turf</span></td>
        </tr></table></a></td>
        <td align="right" valign="middle" style="padding:10px 18px">
          <span class="mention bt-pi" style="display:inline-block;padding:6px 12px;border-radius:999px;background:{C['orClair']};border:1px solid {C['orBord']};color:{C['orFonce']};font-size:11px;line-height:14px;font-weight:800;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap">{mention}</span>
        </td>
      </tr>
    </table>
  </td></tr>"""


def entete(photo: Optional[str], surtitre_: str, titre: str, intro: str, lien: str = SITE,
           suite: str = "", legende_photo: str = "", icone: Optional[str] = None) -> str:
    """Photo en carte arrondie (si `photo`), puis surtitre or, grand titre,
    chapeau et contenu libre (`suite`). Ouvre la carte du corps (coins hauts)."""
    haut = ""
    if photo:
        haut = (
            f'<tr><td bgcolor="{CLAIR["fd"]}" class="bt-fd pxi" style="background:{CLAIR["fd"]};padding:16px 16px 0;border-radius:22px 22px 0 0">'
            f'<a href="{e(lien)}"><img src="{IMG}/hero-{photo}.jpg" width="608" alt="Chevaux en course — photo d’illustration" '
            f'style="display:block;width:100%;max-width:608px;height:auto;border:0;border-radius:16px;background:#14110C;'
            f'color:#8C8272;font-size:13px"></a></td></tr>'
        )
    pad = "22px 28px 26px" if photo else "30px 28px 26px"
    arrondi = "" if photo else "border-radius:22px 22px 0 0;"
    legende = petite_note(legende_photo, 10.5, "14px 0 0") if legende_photo else ""
    picto = (
        f'<img src="{IMG}/tuile-{icone}.png" width="56" height="56" alt="" style="display:block;width:56px;height:56px;border:0;margin:0 0 14px">'
        if icone else ""
    )
    return haut + _ligne(
        f'{picto}<div class="bt-to" style="font-size:11px;line-height:16px;font-weight:800;letter-spacing:.2em;text-transform:uppercase;color:{CLAIR["to"]}">{surtitre_}</div>'
        f'<h1 class="h1hero bt-te" style="margin:8px 0 10px;font-size:32px;line-height:37px;font-weight:700;letter-spacing:-.02em;color:{CLAIR["te"]};font-family:{POLICE}">{titre}</h1>'
        f'<div class="bt-tt" style="font-size:15px;line-height:23px;color:{CLAIR["tt"]}">{intro}</div>'
        f'{suite}{legende}',
        pad, extra=arrondi,
    )


def fenetre_site(url: str, contenu_rangees: str) -> str:
    """Fenêtre de navigateur autour d'une réplique du site : la barre d'adresse
    montre l'URL réelle, cliquable. `contenu_rangees` : des <tr>. Îlot clair
    dans les deux modes (barre en couleur pleine, pas de dégradé)."""
    affichee = url.split("?", 1)[0].replace("https://", "")
    return f"""
  <tr><td bgcolor="{CLAIR['fd']}" class="bt-fd" style="background:{CLAIR['fd']};padding:0 0 28px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%"><tr><td class="px" style="padding:0 20px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;border:1px solid {CLAIR['bord']};
    border-radius:16px;overflow:hidden;background:{C['page']};box-shadow:0 18px 40px -24px rgba(17,24,39,.35)">
    <tr><td bgcolor="#EFE8D8" style="background:#EFE8D8;padding:10px 12px;border-radius:15px 15px 0 0;border-bottom:1px solid {CLAIR['bord']}">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed"><tr>
        <td width="52" style="width:52px;font-size:13px;line-height:13px;white-space:nowrap">
          <span style="color:#FF5F57">●</span><span style="color:#FEBC2E">●</span><span style="color:#28C840">●</span>
        </td>
        <td><a href="{e(url)}" style="display:block;padding:5px 10px;border-radius:8px;background:#FFFFFF;border:1px solid {CLAIR['bord']};color:#57534E;
          font-size:11.5px;line-height:15px;text-decoration:none;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">&#128274; {e(affichee)}</a></td>
      </tr></table>
    </td></tr>
    <tr><td bgcolor="{C['page']}" style="background:{C['page']};padding:0 0 16px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">{contenu_rangees}</table>
    </td></tr>
  </table>
  </td></tr></table>
  </td></tr>"""


def rangee_site(contenu: str, padding: str = "16px 16px 0") -> str:
    """Rangée à l'intérieur de la fenêtre du site."""
    return f'<tr><td class="sec" style="padding:{padding}">{contenu}</td></tr>'


def bouton(label: str, url: str) -> str:
    """Bouton orange PLEIN (pas de dégradé en image : Gmail inverserait le texte
    blanc posé dessus sans toucher au dégradé), tranche sombre en bas."""
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto">
  <tr><td align="center" bgcolor="{CLAIR['bouton']}" style="border-radius:14px;background-color:{CLAIR['bouton']};border-bottom:3px solid {CLAIR['boutonTranche']}">
    <!--[if mso]><a href="{e(url)}" style="font-size:16px;color:#ffffff;font-weight:bold;text-decoration:none;padding:16px 30px;display:block">{label} &rarr;</a><![endif]-->
    <!--[if !mso]><!--><a href="{e(url)}" style="display:inline-block;padding:16px 30px;font-size:16px;line-height:20px;font-weight:800;color:#ffffff;
      text-decoration:none;font-family:{POLICE};letter-spacing:-.01em;border-radius:14px">{label} &rarr;</a><!--<![endif]-->
  </td></tr>
</table>"""


def appel(titre: str, texte: str, label: str, url: str, note: str = "") -> str:
    """Titre, phrase et bouton, centrés."""
    note_html = petite_note(note, 12, "14px 0 0") if note else ""
    return _ligne(
        f'<div class="bt-te" style="font-size:19px;line-height:26px;font-weight:700;color:{CLAIR["te"]};font-family:{POLICE};margin:0 0 6px">{titre}</div>'
        f'<div class="bt-tt" style="font-size:14px;line-height:22px;color:{CLAIR["tt"]};margin:0 0 20px">{texte}</div>'
        f'{bouton(label, url)}{note_html}',
        "0 28px 30px", centre=True,
    )


def encart(titre: str, html: str) -> str:
    """Encadré explicatif (« Comment lire », « À retenir »…)."""
    return _ligne(
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CLAIR["ca"]}" class="bt-ca" '
        f'style="width:100%;border-collapse:separate;background:{CLAIR["ca"]};border:1px solid {CLAIR["bord"]};border-radius:16px">'
        f'<tr><td class="bt-tt" style="padding:16px 18px;font-size:12.5px;line-height:20px;color:{CLAIR["tt"]}">'
        f'<div class="bt-to" style="font-size:11px;font-weight:800;letter-spacing:.14em;text-transform:uppercase;color:{CLAIR["to"]};margin-bottom:6px">{titre}</div>'
        f'{html}</td></tr></table>',
        "0 20px 24px",
    )


def fort(t: str) -> str:
    """Mot en évidence dans le texte courant."""
    return f'<b class="bt-te" style="color:{CLAIR["te"]}">{t}</b>'


def bloc_instagram(accroche: str = "Les infos du jour, les coups de cœur et les arrivées, en story.") -> str:
    """Carte claire : le dégradé de la marque reste dans le pictogramme, jamais
    sous du texte. Ferme la carte du corps (coins bas)."""
    return f"""
  <tr><td bgcolor="{CLAIR['fd']}" class="bt-fd px" style="background:{CLAIR['fd']};padding:0 20px 28px;border-radius:0 0 22px 22px">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CLAIR['ca']}" class="bt-ca" style="width:100%;border-collapse:separate;border-radius:18px;
      background:{CLAIR['ca']};border:1px solid {CLAIR['bord']}">
      <tr>
        <td width="72" valign="middle" style="width:72px;padding:14px 0 14px 16px">
          <a href="{INSTAGRAM}"><img src="{IMG}/instagram-glyph.png" width="50" height="50" alt="Instagram" style="display:block;width:50px;height:50px;border:0;border-radius:14px"></a>
        </td>
        <td valign="middle" style="padding:14px 10px">
          <div class="bt-te" style="font-size:16px;line-height:21px;font-weight:800;color:{CLAIR['te']};font-family:{POLICE}">@blackturf.fr</div>
          <div class="bt-td" style="font-size:13px;line-height:19px;color:{CLAIR['td']}">{accroche}</div>
        </td>
        <td align="right" valign="middle" style="padding:14px 16px 14px 0">
          <a href="{INSTAGRAM}" style="display:inline-block;padding:10px 14px;border-radius:12px;background-color:#C13584;color:#ffffff;font-size:13px;font-weight:800;text-decoration:none;white-space:nowrap">Suivre</a>
        </td>
      </tr>
    </table>
  </td></tr>"""


def fermeture() -> str:
    """Arrondi bas de la carte du corps, pour les mails sans bloc Instagram."""
    return (
        f'<tr><td bgcolor="{CLAIR["fd"]}" class="bt-fd" style="background:{CLAIR["fd"]};height:8px;line-height:8px;font-size:0;'
        f'border-radius:0 0 22px 22px">&nbsp;</td></tr>'
    )


def bloc_avis() -> str:
    """Boutons Trustpilot et Google. Ce sont des images (logos officiels, voir
    scripts/generer_boutons_avis.ps1) : un mail n'exécute pas le widget Trustpilot,
    et une image garde ses couleurs quand le client passe le mail en sombre."""
    boutons = "".join(
        f'<a href="{url}" style="display:inline-block;margin:4px 4px 0;text-decoration:none">'
        f'<img src="{IMG}/{img}" width="{l}" height="48" alt="{alt}" '
        f'style="display:inline-block;width:{l}px;height:48px;border:0;vertical-align:top"></a>'
        for url, img, l, alt in [
            (AVIS_TRUSTPILOT, "avis-trustpilot.png", 272, "Évaluez-nous sur Trustpilot"),
            (AVIS_GOOGLE, "avis-google.png", 252, "Laisser un avis Google"),
        ]
    )
    return (
        f'<div style="margin:0 0 18px">'
        f'<div class="bt-te" style="font-size:14px;line-height:20px;font-weight:700;color:{CLAIR["te"]};font-family:{POLICE}">Un avis sur BlackTurf ?</div>'
        f'<div class="bt-td" style="font-size:12px;line-height:18px;color:{CLAIR["td"]};margin:0 0 6px">30 secondes, et ça aide d’autres turfistes à nous trouver.</div>'
        f'{boutons}</div>'
    )


def pied(mention: str, responsable: str = RESPONSABLE, avis: bool = True) -> str:
    """Pied commun. `avis=False` pour les messages de sécurité (mot de passe,
    vérification d'adresse) : on n'y demande rien d'autre que l'action attendue."""
    liens = '<span class="bt-td" style="color:#A8A08F">&nbsp;·&nbsp;</span>'.join(
        lien_or(t, u, souligne=False) for t, u in [
            ("Courses du jour", f"{SITE}/programme"), ("Value bets", f"{SITE}/value-bets"),
            ("Palmarès", f"{SITE}/track-record"), ("Instagram", INSTAGRAM)])
    return f"""
  <tr><td style="padding:26px 20px 0;text-align:center">
    {bloc_avis() if avis else ""}
    <a href="{SITE}"><img src="{IMG}/logo-medaillon.png" width="60" height="60" alt="BlackTurf" style="display:inline-block;width:60px;height:60px;border:0"></a>
    <div style="margin:10px 0 14px;font-size:12px;line-height:18px">{liens}</div>
    <div class="bt-td" style="font-size:11.5px;line-height:18px;color:{CLAIR['td']};max-width:520px;margin:0 auto">{e(responsable)}</div>
    <div class="bt-td" style="font-size:11.5px;line-height:18px;color:{CLAIR['td']};max-width:520px;margin:12px auto 0">{mention}</div>
  </td></tr>"""


def lien_pied(label: str, url: str) -> str:
    return f'<a class="bt-td" href="{e(url)}" style="color:{CLAIR["td"]};text-decoration:underline">{label}</a>'


def document(titre: str, preheader: str, rangees: str, lien_web: Optional[str] = None) -> str:
    """Page complète : <head>, fond de page, colonne de 640 px, `rangees` (des <tr>)."""
    web = (
        f'<tr><td style="padding:0 0 10px;text-align:center;font-size:11px;line-height:16px">'
        f'<a class="bt-td" href="{e(lien_web)}" style="color:{CLAIR["td"]};text-decoration:underline">Lire et partager sur le web</a></td></tr>'
        if lien_web else ""
    )
    return f"""<!doctype html>
<html lang="fr" xmlns:v="urn:schemas-microsoft-com:vml" xmlns:o="urn:schemas-microsoft-com:office:office">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="x-apple-disable-message-reformatting">
<meta name="color-scheme" content="light dark">
<meta name="supported-color-schemes" content="light dark">
<title>{e(titre)} — BlackTurf</title>
<!--[if mso]><noscript><xml><o:OfficeDocumentSettings><o:PixelsPerInch>96</o:PixelsPerInch></o:OfficeDocumentSettings></xml></noscript><![endif]-->
<style>
  @import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@500;700&display=swap');
  :root{{color-scheme:light dark;supported-color-schemes:light dark}}
  body{{margin:0;padding:0;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}}
  a{{text-decoration:none}}
  @media only screen and (max-width:620px){{
    .wrap{{width:100%!important}}
    .outer{{padding:12px 4px 24px!important}}
    .px{{padding-left:14px!important;padding-right:14px!important}}
    .pxi{{padding-left:10px!important;padding-right:10px!important}}
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
    .marque{{font-size:19px!important;padding-left:6px!important}}
    .logoimg{{width:56px!important;height:56px!important}}
    .recap{{font-size:17px!important;line-height:22px!important}}
    .recap span{{font-size:12px!important;letter-spacing:0!important}}
    .pf{{padding:8px 3px!important;font-size:12px!important}}
    .stitre{{font-size:8.5px!important;letter-spacing:.03em!important}}
  }}
  @media only screen and (max-width:360px){{
    .marque{{font-size:16px!important}}
    .logoimg{{width:48px!important;height:48px!important}}
    .rk{{width:30px!important}}
    .cas{{width:44px!important}}
    .vic{{width:58px!important}}
    .vicpct{{font-size:18px!important;line-height:22px!important}}
    .nom{{font-size:13px!important}}
  }}
  {_css_sombre()}
</style>
</head>
<body class="bt-pg" style="margin:0;padding:0;background:{CLAIR['pg']};font-family:{TEXTE};color:{CLAIR['tt']}">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all;font-size:1px;line-height:1px;color:{CLAIR['pg']}">{e(preheader)}&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;&#8203;&zwnj;&nbsp;</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{CLAIR['pg']}" class="bt-pg" style="width:100%;table-layout:fixed;background:{CLAIR['pg']}">
<tr><td align="center" class="outer" style="padding:20px 8px 32px">
<!--[if mso]><table role="presentation" width="640" align="center"><tr><td><![endif]-->
<table role="presentation" class="wrap" width="640" cellpadding="0" cellspacing="0" style="width:640px;max-width:640px;border-collapse:separate">
{web}{rangees}
</table>
<!--[if mso]></td></tr></table><![endif]-->
</td></tr></table>
</body></html>"""
