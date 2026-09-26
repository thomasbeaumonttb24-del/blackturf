"""E-mail « pronostic gratuit d'une course » — rendu calqué sur la fiche course.

Le mail reproduit, bloc pour bloc, ce que le visiteur voit sur
blackturf.fr/courses/{id} : l'en-tête de course (R·C, labels de pari, statut,
discipline, hippodrome, distance, partants, départ, allocation), la barre
d'onglets, puis la carte « Le classement de l'algorithme » avec sa « Lecture de
la course » en quatre tuiles et le classement complet (médailles, casaques,
badge valeur, signaux, cote, cote juste, lecture du prix, victoire, top 3).
Le tout est posé dans un cadre de navigateur : c'est le site, pas un résumé.

Sources de vérité côté site, à garder alignées :
  frontend/src/app/(main)/courses/[id]/CourseClient.tsx   (en-tête, onglets)
  frontend/src/components/courses/classement.tsx         (Synthese, ClassementAlgo)

Contraintes e-mail : uniquement des tables et des styles en ligne (Outlook), les
effets de relief que le CSS des clients mail ne sait pas rendre (médailles,
tuile IA, photo fondue, silhouettes de discipline) sont des images générées par
scripts/generer_visuels_email.py et servies depuis blackturf.fr/img/email/.
Les dégradés CSS sont posés en surcouche d'un `bgcolor` plein : un client qui
les ignore affiche la couleur unie, jamais un bloc vide.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Optional
from zoneinfo import ZoneInfo

from services.email_design import (
    C, IMG, POLICE,
    barre as _barre, casaque as _casaque, e,
    pastille as _pastille, url_casaque as _url_casaque,
)
from services import email_design as D

PARIS = ZoneInfo("Europe/Paris")

# Mêmes seuils que classement.tsx.
COTE_JUSTE_MAX = 999.0
ECART_MEILLEUR_PRIX = 0.08

DISCIPLINES = {
    "plat": ("plat", "#B45309"), "attelé": ("attele", "#0E7C66"), "attele": ("attele", "#0E7C66"),
    "monté": ("monte", "#2A5BD7"), "monte": ("monte", "#2A5BD7"),
    "obstacle": ("obstacle", "#86198F"), "haies": ("obstacle", "#86198F"),
    "steeple": ("obstacle", "#A32C3E"), "steeple-chase": ("obstacle", "#A32C3E"),
    "cross": ("obstacle", "#A32C3E"), "cross-country": ("obstacle", "#A32C3E"),
}

SENS = {
    "positif": ("▲", C["vert"], C["vertFond"], C["vertBord"]),
    "negatif": ("▼", C["rouge"], C["rougeFond"], C["rougeBord"]),
    "neutre": ("●", C["orFonce"], "#FFFBEB", "#FDE68A"),
}

# Dégradés des trois premiers segments de la barre de physionomie et des
# liserés de podium (from-amber-300 to-amber-600, slate, orange).
PODIUM = {1: ("#FCD34D", "#D97706"), 2: ("#CBD5E1", "#64748B"), 3: ("#FDBA74", "#EA580C")}


# ─── Formats (identiques à classement.tsx) ──────────────────────────────────

def pct(x: Optional[float]) -> str:
    """Même écriture que `pct` du site. Rendu déjà échappé pour le HTML."""
    if x is None:
        return "—"
    return "&lt;&nbsp;1&nbsp;%" if x < 0.005 else f"{round(x * 100)}&nbsp;%"


def cote(x: float) -> str:
    return f"{x:.1f}".replace(".", ",")


def cote_juste(x: float) -> str:
    if x < 10:
        return f"{x:.2f}".replace(".", ",")
    if x < 100:
        return f"{x:.1f}".replace(".", ",")
    return f"{x:.0f}"


def ecart_prix(marche: Optional[float], juste: Optional[float]) -> Optional[float]:
    if not marche or marche <= 0 or not juste or juste <= 0 or juste >= COTE_JUSTE_MAX:
        return None
    return marche / juste - 1


def _paris(d: Optional[datetime]) -> Optional[datetime]:
    if d is None:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=ZoneInfo("UTC"))).astimezone(PARIS)


def heure_depart(d: Optional[datetime]) -> str:
    p = _paris(d)
    return p.strftime("%Hh%M") if p else ""


def _date_longue(d: Optional[datetime]) -> str:
    p = _paris(d)
    if not p:
        return ""
    jours = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
    mois = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
            "septembre", "octobre", "novembre", "décembre"]
    return f"{jours[p.weekday()]} {p.day} {mois[p.month - 1]}"


# ─── Briques ────────────────────────────────────────────────────────────────

def _musique(musique: Optional[str]) -> str:
    """Musique en pastilles colorées, comme MusiqueDisplay (badges.tsx) :
    victoire en or, places en bleu, reste en gris, incidents en rose."""
    if not musique:
        return ""
    jetons = [t for t in re.findall(r"\(\d{2,4}\)|[0-9A-Za-z][a-z]", musique) if not t.startswith("(")][:8]
    out = []
    for t in jetons:
        h = t[0]
        if h == "1":
            fg, bg, bd = "#B45309", "#FEF3C7", "#FCD34D"
        elif h in "23":
            fg, bg, bd = "#1D4ED8", "#EFF6FF", "#BFDBFE"
        elif h.isdigit() and h != "0":
            fg, bg, bd = "#4B5563", "#F3F4F6", "#E5E7EB"
        else:
            fg, bg, bd = "#BE123C", "#FFF1F2", "#FECDD3"
        out.append(
            f'<span style="display:inline-block;min-width:18px;margin:0 3px 3px 0;padding:1px 3px;border-radius:4px;'
            f'background:{bg};border:1px solid {bd};color:{fg};font-size:10px;line-height:14px;font-weight:700;'
            f'text-align:center;font-family:{POLICE}">{e(t)}</span>'
        )
    return "".join(out)


def _rang(rang: int) -> str:
    if rang in (1, 2, 3):
        return (
            f'<img src="{IMG}/medaille-{rang}.png" width="36" height="36" alt="{rang}" '
            f'style="display:block;width:36px;height:36px;border:0;margin:0 auto">'
        )
    return (
        f'<div style="width:30px;height:30px;line-height:30px;margin:0 auto;border-radius:10px;'
        f'background:#ffffff;border:1px solid {C["stone2"]};color:{C["stone6"]};text-align:center;'
        f'font-size:13px;font-weight:700;font-family:{POLICE};box-shadow:0 1px 0 rgba(17,24,39,.06)">{rang}</div>'
    )


def _lecture_prix(marche: Optional[float], juste: Optional[float]) -> str:
    if not marche or marche <= 0 or not juste or juste <= 0:
        return f'<span style="color:{C["stone3"]};font-size:13px">—</span>'
    if juste >= COTE_JUSTE_MAX:
        return f'<span style="color:{C["stone6"]};font-size:11px">non chiffrable</span>'
    ecart = marche / juste - 1
    if abs(ecart) < ECART_MEILLEUR_PRIX:
        return (
            f'<span style="display:inline-block;padding:2px 6px;border-radius:6px;background:{C["stone1"]};'
            f'color:{C["stone6"]};font-size:11px;font-weight:600">au prix</span>'
        )
    abs_pct = round(abs(ecart) * 100)
    if ecart > 0:
        fg, bg, bd, signe = C["vert"], C["vertFond"], C["vertBord"], "+"
    else:
        fg, bg, bd, signe = C["rouge"], C["rougeFond"], C["rougeBord"], "−"
    return (
        f'<span style="display:inline-block;padding:2px 6px;border-radius:6px;background:{bg};'
        f'border:1px solid {bd};color:{fg};font-size:11px;font-weight:700;white-space:nowrap">{signe}{abs_pct} %</span>'
    )


def _signaux(signaux: list[dict]) -> str:
    if not signaux:
        return ""
    puces = []
    for sg in signaux:
        fleche, fg, bg, bd = SENS.get(sg.get("sens"), SENS["neutre"])
        label = str(sg.get("label") or "").lstrip("•·-–—▲▼● ").strip()
        if not label:
            continue
        puces.append(
            f'<span style="display:inline-block;margin:0 4px 4px 0;padding:2px 8px;border-radius:999px;'
            f'background:{bg};border:1px solid {bd};color:{fg};font-size:11px;line-height:15px;font-weight:600">'
            f'<span style="font-size:8px">{fleche}</span> {e(label)}</span>'
        )
    return f'<div style="margin-top:6px">{"".join(puces)}</div>' if puces else ""


def _tuile(contenu: str) -> str:
    """Tuile de la « Lecture de la course » — carte blanche en relief."""
    return (
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;'
        f'border-collapse:separate;background:#ffffff;border:1px solid {C["bord"]};border-bottom:2px solid #E3DCCB;'
        f'border-radius:16px;box-shadow:inset 0 1px 0 #fff,0 1px 2px rgba(17,24,39,.05),0 10px 22px -18px rgba(17,24,39,.4)">'
        f'<tr><td style="padding:12px 14px;vertical-align:top;height:96px">{contenu}</td></tr></table>'
    )


def _titre_tuile(t: str) -> str:
    return (
        f'<div style="font-size:10px;line-height:14px;font-weight:700;letter-spacing:.1em;'
        f'text-transform:uppercase;color:{C["stone5"]}">{t}</div>'
    )


def _chiffre(v: str, couleur: str) -> str:
    return (
        f'<span style="font-size:24px;line-height:28px;font-weight:700;color:{couleur};'
        f'font-family:{POLICE};letter-spacing:-.02em">{v}</span>'
    )


# ─── Sections ───────────────────────────────────────────────────────────────

def _lecture_de_la_course(chevaux: list[dict], calcule_a: Optional[datetime]) -> str:
    """Les quatre tuiles de `Synthese` (classement.tsx), mêmes calculs."""
    partants = chevaux
    if not partants:
        return ""
    concentration = sum(c["p1"] for c in partants[:3])
    nb_serieux = sum(1 for c in partants if c["p1"] >= 0.1)
    physio = "course fermée" if concentration >= 0.6 else "course disputée" if concentration >= 0.45 else "course ouverte"

    total = sum(max(0.005, c["p1"]) for c in partants) or 1
    segments = ""
    for i, c in enumerate(partants):
        w = max(0.5, max(0.005, c["p1"]) / total * 100)
        if i < 3:
            debut, fin = PODIUM[i + 1]
            fond = f"background:{fin};background-image:linear-gradient(180deg,{debut},{fin});"
            couleur = fin
        else:
            couleur = C["stone3"] if i % 2 else C["stone2"]
            fond = f"background:{couleur};"
        sep = "border-left:1px solid #ffffff;" if i else ""
        segments += (
            f'<td width="{w:.1f}%" bgcolor="{couleur}" style="width:{w:.1f}%;height:10px;line-height:10px;'
            f'font-size:0;{fond}{sep}">&nbsp;</td>'
        )
    t1 = (
        _titre_tuile("Physionomie")
        + f'<div style="margin-top:4px">{_chiffre(pct(concentration), C["encre"])}'
        f' <span style="font-size:12px;color:{C["stone5"]}">{physio}</span></div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:8px;'
        f'border-collapse:collapse;table-layout:fixed;border-radius:10px;overflow:hidden;background:{C["stone1"]}">'
        f'<tr>{segments}</tr></table>'
        f'<div style="margin-top:6px;font-size:11px;line-height:15px;color:{C["stone5"]}">chances des 3 premiers · '
        f'<b style="color:{C["slate7"]}">{nb_serieux}</b> cheva{"ux" if nb_serieux > 1 else "l"} à 10 % ou plus</div>'
    )

    fav_modele = partants[0]
    cotes = [(c, c["cote"]) for c in partants if c.get("cote") and c["cote"] > 0]
    fav_marche = min(cotes, key=lambda x: x[1]) if cotes else None
    meme = bool(fav_marche) and fav_marche[0]["numero"] == fav_modele["numero"]
    ligne_marche = (
        f'<b style="color:{C["encre"]}">N°{e(fav_marche[0]["numero"])}</b> <span style="color:{C["stone5"]}">à</span> '
        f'<b style="color:{C["encre"]}">{cote(fav_marche[1])}</b>'
        if fav_marche else '<span style="color:#a8a29e">cotes indisponibles</span>'
    )
    t2 = (
        _titre_tuile("Favori : marché et modèle")
        + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:6px;font-size:12px;line-height:20px">'
        f'<tr><td style="color:{C["stone5"]}">Marché</td><td align="right">{ligne_marche}</td></tr>'
        f'<tr><td style="color:{C["stone5"]}">Modèle</td><td align="right"><b style="color:{C["encre"]}">N°{e(fav_modele["numero"])}</b> '
        f'<span style="color:{C["stone5"]}">·</span> <b style="color:{C["or"]}">{pct(fav_modele["p1"])}</b></td></tr></table>'
    )
    if fav_marche:
        t2 += '<div style="margin-top:6px">' + (
            _pastille("même favori", C["stone6"], C["stone1"], C["stone2"], 11, 600) if meme
            else _pastille("favoris différents", C["orFonce"], "#FFFBEB", "#FDE68A", 11, 600)
        ) + "</div>"

    ecarts = [(c, ecart_prix(c.get("cote"), c.get("cote_juste"))) for c in partants]
    ecarts = [(c, x) for c, x in ecarts if x is not None]
    positifs = sorted([(c, x) for c, x in ecarts if x >= ECART_MEILLEUR_PRIX], key=lambda t: -t[1])
    if not ecarts:
        legende, valeur = "cotes indisponibles", "—"
    else:
        valeur = str(len(positifs))
        legende = (
            "chevaux payés au-dessus de leur chance" if len(positifs) > 1
            else "cheval payé au-dessus de sa chance" if len(positifs) == 1
            else "aucun écart positif d’au moins 8 %"
        )
    t3 = (
        _titre_tuile("Écarts de prix")
        + f'<div style="margin-top:4px">{_chiffre(valeur, C["vert"] if positifs else C["encre"])}'
        f' <span style="font-size:12px;color:{C["stone5"]}">{legende}</span></div>'
    )
    if positifs:
        t3 += '<div style="margin-top:8px">' + "".join(
            f'<span style="display:inline-block;margin:0 4px 4px 0;padding:2px 6px;border-radius:6px;background:{C["vertFond"]};'
            f'border:1px solid {C["vertBord"]};color:{C["vert"]};font-size:11px;font-weight:700">N°{e(c["numero"])} +{round(x * 100)} %</span>'
            for c, x in positifs[:3]
        ) + "</div>"

    nb_atouts = sum(1 for c in partants for s in c.get("signaux", []) if s.get("sens") == "positif")
    nb_reserves = sum(1 for c in partants for s in c.get("signaux", []) if s.get("sens") == "negatif")
    t4 = (
        _titre_tuile("Partants et signaux")
        + f'<div style="margin-top:4px">{_chiffre(str(len(partants)), C["encre"])}'
        f' <span style="font-size:12px;color:{C["stone5"]}">partant{"s" if len(partants) > 1 else ""} notés</span></div>'
    )
    if nb_atouts or nb_reserves:
        t4 += (
            '<div style="margin-top:8px">'
            + _pastille(f'<span style="font-size:8px">▲</span> {nb_atouts} atout{"s" if nb_atouts > 1 else ""}', C["vert"], C["vertFond"], C["vertBord"], 11, 600)
            + " "
            + _pastille(f'<span style="font-size:8px">▼</span> {nb_reserves} réserve{"s" if nb_reserves > 1 else ""}', C["rouge"], C["rougeFond"], C["rougeBord"], 11, 600)
            + "</div>"
        )
    p = _paris(calcule_a)
    if p:
        t4 += f'<div style="margin-top:8px;font-size:11px;color:{C["stone5"]}">&#9719; calculé le {p.strftime("%d/%m à %Hh%M")}</div>'

    return f"""
<tr><td class="lec" style="padding:0 16px 16px">
  <div style="font-size:11px;line-height:16px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:{C['or']};margin:0 0 10px">Lecture de la course</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">
    <tr>
      <td class="col2" width="50%" valign="top" style="width:50%;padding:0 5px 10px 0">{_tuile(t1)}</td>
      <td class="col2" width="50%" valign="top" style="width:50%;padding:0 0 10px 5px">{_tuile(t2)}</td>
    </tr>
    <tr>
      <td class="col2" width="50%" valign="top" style="width:50%;padding:0 5px 0 0">{_tuile(t3)}</td>
      <td class="col2" width="50%" valign="top" style="width:50%;padding:0 0 0 5px">{_tuile(t4)}</td>
    </tr>
  </table>
</td></tr>"""


def _ligne_cheval(c: dict, meilleur: Optional[int]) -> str:
    rang = c["rang_predit"]
    fav = rang == 1
    podium = rang <= 3
    fond = "#FFFBEB" if fav else "#ffffff"
    fond_css = (
        f"background:{fond};background-image:linear-gradient(90deg,#FEF3C7 0%,#FFFBEB 40%,#ffffff 100%);" if fav
        else f"background:{fond};"
    )
    lisere = PODIUM.get(rang)
    lisere_css = f"border-left:4px solid {lisere[1]};" if lisere else f"border-left:4px solid {fond};"

    badges = []
    if c.get("niveau_value_bet") and c.get("ev_max") is not None:
        ev = round(c["ev_max"] * 100)
        niveau = max(1, min(4, int(c["niveau_value_bet"])))
        badges.append(
            f'<span style="display:inline-block;margin:0 4px 4px 0;padding:3px 7px;border-radius:7px;background:{C["vertPlein"]};'
            f'background-image:linear-gradient(180deg,#10B981,#047857);border-bottom:2px solid #065F46;'
            f'color:#ffffff;font-size:10.5px;line-height:14px;font-weight:800;letter-spacing:.02em">'
            f'VALEUR {"+" if ev > 0 else ""}{ev} % <span style="color:#FDE68A">{"★" * niveau}</span></span>'
        )
    if meilleur == c["numero"]:
        badges.append(_pastille("meilleur écart", C["vert"], C["vertFond"], C["vertBord"], 10, 700, maj=True)
                      .replace("white-space:nowrap;", ""))
    badges_html = f'<div style="margin-top:6px;font-size:0;line-height:0">{"".join(badges)}</div>' if badges else ""

    jockey = c.get("jockey")
    jockey_html = (
        f'<div style="margin-top:3px;font-size:11.5px;line-height:16px;color:{C["stone5"]}">'
        f'&#9873;&nbsp;<b style="color:{C["slate7"]};font-weight:600">{e(jockey)}</b></div>'
        if jockey else ""
    )
    musique = _musique(c.get("musique"))
    musique_html = f'<div style="margin-top:5px;line-height:0">{musique}</div>' if musique else ""

    marche = c.get("cote")
    juste = c.get("cote_juste")
    juste_txt = cote_juste(juste) if juste is not None else "—"
    juste_couleur = C["vert"] if c.get("niveau_value_bet") else C["slate7"]
    ton_victoire = PODIUM[1] if fav else ("#CBD5E1", "#475569") if podium else ("#D6D3D1", "#78716C")

    def tuile_chiffre(titre: str, corps: str) -> str:
        return (
            f'<td class="stat" valign="top" style="padding:0 3px">'
            f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;'
            f'background:{C["creme"]};border:1px solid {C["bord2"]};border-bottom:2px solid #E6DDC8;border-radius:12px">'
            f'<tr><td class="statin" style="padding:7px 9px;height:42px;vertical-align:top">'
            f'<div class="stitre" style="font-size:9.5px;line-height:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{C["stone5"]};white-space:nowrap">{titre}</div>'
            f'{corps}</td></tr></table></td>'
        )

    def chiffre(v: str, coul: str = C["encre"]) -> str:
        return f'<div style="font-size:16px;line-height:21px;font-weight:700;color:{coul};font-family:{POLICE}">{v}</div>'

    tuiles = (
        tuile_chiffre("Cote", chiffre(cote(marche) if marche else "—"))
        + tuile_chiffre("Cote juste", chiffre(juste_txt, juste_couleur))
        + tuile_chiffre("Prix", f'<div style="padding-top:3px">{_lecture_prix(marche, juste)}</div>')
        + tuile_chiffre("Top 3", chiffre(pct(c["p3"])) + _barre(c["p3"], "#7DD3FC", "#0284C7", 4))
    )

    return f"""
<tr><td style="padding:0;border-top:1px solid #F1EEE6">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{fond}" style="width:100%;{fond_css}{lisere_css}">
    <tr><td class="rowin" style="padding:14px 14px 14px 10px">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">
        <tr>
          <td class="rk" width="40" valign="top" style="width:40px;padding-top:10px">{_rang(rang)}</td>
          <td class="cas" width="58" valign="top" align="center" style="width:58px;padding-left:4px">{_casaque(c.get("casaque_url"), c["numero"])}</td>
          <td valign="top" style="padding-left:10px">
            <div class="nom" style="font-size:15px;line-height:20px;font-weight:800;color:{C["encre2"]};letter-spacing:-.01em;font-family:{POLICE}">{e(c["nom"])}</div>
            {jockey_html}
            {musique_html}
            {badges_html}
          </td>
          <td class="vic" width="86" valign="top" align="right" style="width:86px;padding-left:8px">
            <div style="font-size:9.5px;line-height:13px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:{C["stone5"]}">Victoire</div>
            <div class="vicpct" style="font-size:26px;line-height:30px;font-weight:700;color:{C["or"] if fav else C["encre"]};font-family:{POLICE};letter-spacing:-.03em;white-space:nowrap">{pct(c["p1"])}</div>
            {_barre(c["p1"], ton_victoire[0], ton_victoire[1], 6)}
          </td>
        </tr>
      </table>
      {_signaux(c.get("signaux") or [])}
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:10px;table-layout:fixed">
        <tr>{tuiles}</tr>
      </table>
    </td></tr>
  </table>
</td></tr>"""


def _entete_course(course: dict, lien_course: str) -> str:
    """Réplique de l'en-tête de la fiche course (CourseClient.tsx, <header>)."""
    badges = []
    r, n = course.get("numero_reunion"), course.get("numero")
    if r and n:
        badges.append(
            f'<span style="display:inline-block;padding:4px 10px;border-radius:8px;background:{C["encre"]};color:#ffffff;'
            f'font-size:13px;line-height:16px;font-weight:700;font-family:{POLICE}">R{e(r)}<span style="opacity:.45"> · </span>C{e(n)}</span>'
        )
    pari = "Quinté+" if course.get("est_quinte") else "Quarté+" if course.get("est_quarte") else "Tiercé" if course.get("est_tierce") else None
    if pari:
        badges.append(_pastille(pari, C["orFonce"], "#FEF3C7", "#FCD34D", 11, 700, maj=True))
    statut = course.get("statut")
    if statut == "en_cours":
        badges.append(_pastille('<span style="color:#10B981">●</span> En cours', C["vert"], C["vertFond"], C["vertBord"], 11, 700, maj=True))
    elif statut == "termine":
        badges.append(_pastille("Terminée", C["stone6"], C["stone1"], C["stone2"], 11, 700, maj=True))
    else:
        badges.append(_pastille('<span style="color:#F59E0B">●</span> À venir', C["or"], C["orClair"], C["orBord"], 11, 700, maj=True))

    disc = str(course.get("discipline") or "")
    fichier, couleur = DISCIPLINES.get(disc.lower(), ("attele", "#0E7C66"))
    def puce(icone: str, texte: str, fort: bool = False) -> str:
        return (
            f'<span style="display:inline-block;margin:0 5px 6px 0;padding:5px 10px;border-radius:10px;background:#ffffff;'
            f'border:1px solid {C["bord"]};border-bottom:2px solid #E3DCCB;font-size:12.5px;line-height:17px;white-space:nowrap;'
            f'color:{C["slate7"] if fort else C["slate6"]};font-weight:{700 if fort else 500}">'
            f'<span style="color:{C["or"]}">{icone}</span>&nbsp;{texte}</span>'
        )

    infos = [
        f'<span style="display:inline-block;margin:0 5px 6px 0;padding:3px 10px 3px 6px;border-radius:10px;background:#ffffff;'
        f'border:1px solid {C["bord"]};border-bottom:2px solid #E3DCCB;white-space:nowrap">'
        f'<img src="{IMG}/disc-{fichier}.png" height="20" alt="" style="height:20px;width:auto;border:0;vertical-align:middle">'
        f'&nbsp;<b style="color:{couleur};vertical-align:middle;font-size:12.5px">{e(disc)}</b></span>',
        puce("&#9679;", e(course.get("hippodrome_nom")), True),
    ]
    p = _paris(course.get("date_heure"))
    if p:
        infos.append(puce("&#9719;", f'Départ {p.strftime("%Hh%M")}', True))
    if course.get("distance"):
        infos.append(puce("&#8596;", f'{int(course["distance"]):,}&nbsp;m'.replace(",", " ")))
    if course.get("nb_partants"):
        infos.append(puce("&#9823;", f'{e(course["nb_partants"])} partants'))
    if course.get("allocation"):
        euros = f'{round(course["allocation"] / 100):,}'.replace(",", " ")
        infos.append(puce("&#127942;", f'{euros}&nbsp;€'))
    terrain = course.get("terrain")
    if terrain:
        infos.append(puce("&#9788;", f'Terrain {e(terrain).lower()}'))

    nom = course.get("nom") or f'Course R{r}C{n}'
    return f"""
<tr><td class="sec" style="padding:16px 16px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#FFFBF0" style="width:100%;border-collapse:separate;
    background:#FFFBF0;background-image:linear-gradient(180deg,#FFFBF0,#ffffff);border:1px solid #F5E6C4;border-bottom:3px solid #EAD9B0;
    border-radius:22px;box-shadow:0 1px 3px rgba(0,0,0,.04),0 16px 44px -26px rgba(180,83,9,.28)">
    <tr><td style="padding:20px 20px 18px">
      <div style="line-height:30px">{" ".join(badges)}</div>
      <h1 style="margin:8px 0 0;font-size:25px;line-height:30px;font-weight:700;letter-spacing:-.02em;color:#1E293B;font-family:{POLICE}">{e(nom)}</h1>
      <div style="margin-top:12px;font-size:0;line-height:0">{"".join(infos)}</div>
      <div style="margin-top:14px">
        <a href="{e(lien_course)}" style="display:inline-block;padding:9px 14px;border-radius:12px;background:#ffffff;border:1px solid {C["stone2"]};
          border-bottom:2px solid {C["stone3"]};color:{C["slate7"]};font-size:13px;font-weight:600;text-decoration:none">&#9654;&nbsp; Voir la fiche en direct</a>
      </div>
    </td></tr>
  </table>
</td></tr>"""


def _onglets(lien_course: str) -> str:
    """Barre d'onglets de la fiche, « Synthèse » actif, chaque onglet lié."""
    onglets = [("Synthèse", "synthese", True), ("Partants", "partants", False),
               ("Marché", "marche", False), ("Plan de mise", "plan", False)]
    cellules = ""
    for label, cle, actif in onglets:
        style = (
            f"background:#ffffff;color:{C['orFonce']};border:1px solid {C['orBord']};border-bottom:2px solid #E9C98A;"
            f"box-shadow:0 1px 2px rgba(17,24,39,.06)" if actif else f"color:{C['stone6']};border:1px solid transparent"
        )
        cellules += (
            f'<a class="tab" href="{e(lien_course)}#{cle}" style="display:inline-block;margin:0 4px 4px 0;padding:7px 12px;'
            f'border-radius:10px;font-size:12.5px;line-height:16px;font-weight:{700 if actif else 600};text-decoration:none;white-space:nowrap;{style}">{label}</a>'
        )
    # Liens en ligne (et non cellules de table) : sur un petit écran, la barre
    # passe à la ligne au lieu d'élargir tout le mail.
    return f"""
<tr><td class="sec" style="padding:14px 16px 0;line-height:0">{cellules}</td></tr>"""


def _classement(chevaux: list[dict], calcule_a: Optional[datetime]) -> str:
    meilleur = None
    best = None
    for c in chevaux:
        x = ecart_prix(c.get("cote"), c.get("cote_juste"))
        if x is not None and x >= ECART_MEILLEUR_PRIX and (best is None or x > best):
            best, meilleur = x, c["numero"]
    lignes = "".join(_ligne_cheval(c, meilleur) for c in chevaux)
    return f"""
<tr><td class="sec" style="padding:16px 16px 0">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;background:#ffffff;
    border:1px solid {C['bord']};border-bottom:3px solid #E3DCCB;border-radius:20px;overflow:hidden;
    box-shadow:0 1px 2px rgba(17,24,39,.04),0 18px 40px -28px rgba(17,24,39,.35)">
    <tr><td style="padding:16px 16px 14px">
      <table role="presentation" cellpadding="0" cellspacing="0"><tr>
        <td width="44" valign="middle" style="width:44px"><img src="{IMG}/tuile-ia.png" width="40" height="40" alt="IA" style="display:block;width:40px;height:40px;border:0"></td>
        <td valign="middle" style="padding-left:8px">
          <div style="font-size:17px;line-height:22px;font-weight:700;color:#1C1917;font-family:{POLICE}">Le classement de l&rsquo;algorithme</div>
          <div style="font-size:12px;line-height:16px;color:{C['stone5']}">{len(chevaux)} chevaux notés · du plus probable au moins probable</div>
        </td>
      </tr></table>
    </td></tr>
    <tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">{_lecture_de_la_course(chevaux, calcule_a)}</table></td></tr>
    <tr><td bgcolor="{C['creme']}" style="background:{C['creme']};border-top:1px solid #F5F5F4;padding:8px 16px;font-size:10px;line-height:14px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:{C['stone5']}">
      Classement complet · cheval · signaux · chiffres
    </td></tr>
    <tr><td><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%">{lignes}</table></td></tr>
    <tr><td bgcolor="{C['creme']}" style="background:{C['creme']};border-top:1px solid #F5F5F4;padding:10px 16px;font-size:11px;color:{C['stone5']}">
      Aide à la décision — aucune garantie de gain.
    </td></tr>
  </table>
</td></tr>"""


def rendu_html(course: dict, chevaux: list[dict], lien_course: str, lien_desinscription: str,
               calcule_a: Optional[datetime] = None, responsable: str = "") -> str:
    """HTML complet du mail. `course` : champs de la table `courses` utiles à
    l'en-tête ; `chevaux` : lignes de `_classement_complet`, triées par rang."""
    disc = str(course.get("discipline") or "").lower()
    hero = "trot" if disc in ("attelé", "attele", "monté", "monte") else "galop"
    heure = heure_depart(course.get("date_heure"))
    jour = _date_longue(course.get("date_heure"))
    nom = course.get("nom") or "la course"
    hippodrome = course.get("hippodrome_nom") or ""
    top = chevaux[0] if chevaux else None
    preheader = (
        f"{hippodrome} · départ {heure} — le n°1 de l’algorithme : N°{top['numero']} {top['nom']} ({round(top['p1'] * 100)} % de victoire)."
        if top else f"{hippodrome} · départ {heure}"
    )

    contenu = (
        _entete_course(course, lien_course)
        + _onglets(lien_course)
        + _classement(chevaux, calcule_a)
    )

    lecture = (
        f"{D.fort('Victoire / Top 3')} : probabilités estimées par le modèle. "
        f"{D.fort('Cote juste')} = 1 / probabilité de victoire, sans marge — le prix à partir duquel le pari "
        "devient rentable si la probabilité est exacte. "
        f"{D.fort('Lecture du prix')} = écart entre la cote payée par le marché et cette cote juste : "
        '<span style="color:#34D399">vert</span> quand le marché paie au-dessus, '
        '<span style="color:#FB7185">rouge</span> en dessous. '
        "Chiffres figés à l’envoi : les cotes continuent d’évoluer jusqu’au départ."
    )
    mention = (
        "Vous recevez cet e-mail unique parce que vous l’avez demandé sur blackturf.fr. "
        "Ce n’est pas un abonnement : rien d’autre ne partira. "
        + D.lien_pied("Ne plus recevoir ce type d’e-mail", lien_desinscription) + "."
    )
    rangees = (
        D.barre_logo("&#9733; Pronostic IA offert")
        + D.entete(
            hero, f"Votre pronostic · {e(jour)}", e(nom),
            f"{e(hippodrome)} · départ <b style=\"color:#ffffff\">{e(heure)}</b>. Voici la fiche de la course telle "
            "qu’elle apparaît sur BlackTurf, avec le classement complet de l’algorithme.",
            lien=lien_course, suite=_podium_express(chevaux),
        )
        + D.fenetre_site(lien_course, contenu)
        + D.appel(
            "La fiche complète vous attend",
            "Fiche détaillée de chaque partant, cotes en direct, argent engagé et plan de mise selon votre budget.",
            "Ouvrir la fiche sur BlackTurf", lien_course,
        )
        + D.encart("Comment lire", lecture)
        + D.bloc_instagram()
        + D.pied(mention, responsable or D.RESPONSABLE)
    )
    return D.document(f"Le pronostic de {nom}", preheader, rangees)


def _podium_express(chevaux: list[dict]) -> str:
    """Les trois premiers du modèle en un coup d'œil, sur le fond sombre de
    l'en-tête — médaille, casaque, numéro, nom, chance de victoire et cote."""
    if not chevaux:
        return ""
    cellules = ""
    for c in chevaux[:3]:
        rang = c["rang_predit"]
        teinte = {1: "#F5C451", 2: "#CBD5E1", 3: "#F59E6B"}.get(rang, "#E3C27A")
        cote_txt = f'cote {cote(c["cote"])}' if c.get("cote") else "cote —"
        cellules += f"""
      <td class="pod" width="33%" valign="top" style="width:33%;padding:0 4px">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;border-collapse:separate;background:#221C12;
          background-image:linear-gradient(180deg,#30271A,#1A150D);border:1px solid #3A2F1D;border-top:2px solid {teinte};border-bottom:3px solid #0A0805;
          border-radius:16px;box-shadow:0 16px 28px -16px rgba(0,0,0,.9)">
          <tr><td class="cellpod" align="center" style="padding:14px 10px 12px;text-align:center">
            <table role="presentation" cellpadding="0" cellspacing="0" align="center" style="margin:0 auto"><tr>
              <td valign="middle"><img src="{IMG}/medaille-{rang}.png" width="30" height="30" alt="{rang}" style="display:block;width:30px;height:30px;border:0"></td>
              <td valign="middle" style="padding-left:6px">
                <img src="{e(_url_casaque(c.get('casaque_url')))}" width="40" height="40" alt="Casaque du n°{e(c['numero'])}" style="display:block;width:40px;height:40px;border:0;border-radius:10px;background:#ffffff;padding:3px">
              </td>
            </tr></table>
            <div class="podpct" style="margin-top:8px;font-size:26px;line-height:30px;font-weight:700;color:#ffffff;font-family:{POLICE};letter-spacing:-.03em">{pct(c['p1'])}</div>
            <div style="font-size:9.5px;line-height:12px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:#8C8272">de victoire</div>
            <div style="margin-top:8px"><span style="display:inline-block;padding:2px 7px;border-radius:6px;background:#F3EBDA;color:#14110C;font-size:12px;line-height:16px;font-weight:800;font-family:{POLICE}">{e(c['numero'])}</span></div>
            <div class="podnom" style="margin-top:5px;font-size:12.5px;line-height:16px;color:#F3EBDA;font-weight:700;word-break:break-word">{e(c['nom'])}</div>
            <div style="margin-top:3px;font-size:11px;line-height:15px;color:{teinte}">{cote_txt}</div>
          </td></tr>
        </table>
      </td>"""
    return f"""
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:22px">
      <tr><td style="padding:0 4px 10px;font-size:11px;font-weight:800;letter-spacing:.16em;text-transform:uppercase;color:#8C8272">Le podium de l’algorithme</td></tr>
    </table>
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed"><tr>{cellules}</tr></table>"""
