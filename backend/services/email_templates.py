"""Lettres BlackTurf : valeurs du jour, bilan hebdomadaire, et l'enveloppe
`layout` utilisée par les mails de confirmation.

Même habillage que le mail « pronostic gratuit » (services/email_design.py) :
fond nuit, photo fondue, fenêtre du site, bouton or en relief, bloc Instagram.
Tables et styles en ligne uniquement ; une seule colonne lisible sur téléphone.
"""
from html import escape
from urllib.parse import urlencode, quote

from services import email_design as D
from services.email_design import C, IMG, POLICE, INSTAGRAM, RESPONSABLE, SITE  # noqa: F401  (réexportés)

# Photos d'en-tête : les anciens noms de fichier restent acceptés (appelants
# existants), convertis vers les bannières fondues générées pour les mails.
PHOTOS = {"galop-lutte.jpg": "valeurs", "galop-foule.jpg": "bilan"}


def e(value):
    return escape(str(value if value is not None else ""), quote=True)


def euro(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " €"


def link(path, campaign):
    return SITE + path + "?" + urlencode({"utm_source": "newsletter", "utm_medium": "email", "utm_campaign": campaign})


def button(label, url):
    return f'<div style="margin:22px 0">{D.bouton(e(label), url)}</div>'


def card(content):
    return f'<div style="margin:0 0 14px">{D.carte(content, "18px 18px")}</div>'


def _mention(unsubscribe, lettre="la lettre BlackTurf"):
    if not unsubscribe:
        return f"Vous recevez {lettre} parce que vous y êtes inscrit sur blackturf.fr."
    texte = f"Vous recevez {lettre} parce que vous y êtes inscrit sur blackturf.fr. " + D.lien_pied("Se désabonner", unsubscribe)
    if "/newsletter/desinscription?" not in unsubscribe:
        texte += " · " + D.lien_pied("Mes préférences", SITE + "/notifications")
    return texte + "."


def layout(title, eyebrow, intro, content, unsubscribe=None, archive=None, photo="galop-lutte.jpg"):
    """Enveloppe générique : en-tête photo, contenu sur carte claire, Instagram, pied."""
    rangees = (
        D.barre_logo("La lettre BlackTurf")
        + D.entete(PHOTOS.get(photo, "bienvenue"), e(eyebrow), e(title), e(intro),
                   legende_photo="Photo d’illustration, sans lien avec les courses présentées.")
        + D.rangee_nuit(D.carte(f'<div style="font-size:15px;line-height:24px;color:{C["slate7"]}">{content}</div>', "22px 22px"),
                        padding="0 20px 28px")
        + D.bloc_instagram()
        + D.pied(_mention(unsubscribe))
    )
    return D.document(title, intro, rangees, lien_web=archive)


# ─── Valeurs du jour ────────────────────────────────────────────────────────

def _carte_valeur(item, url):
    """Une sélection, présentée comme une ligne de la page Value bets : course,
    casaque, cheval, niveau en étoiles, valeur estimée et cote."""
    level = max(0, min(4, int(item["niveau"])))
    ev = item["ev"] * 100
    ev_txt = f"{ev:+.1f} %".replace(".", ",")
    rc = ""
    if item.get("reunion") and item.get("course_num"):
        rc = (f'<span style="display:inline-block;padding:3px 8px;border-radius:7px;background:{C["encre"]};color:#ffffff;'
              f'font-size:12px;line-height:15px;font-weight:700;font-family:{POLICE}">R{e(item["reunion"])}'
              f'<span style="opacity:.45"> · </span>C{e(item["course_num"])}</span> ')
    heure = (f'<span style="display:inline-block;padding:3px 9px;border-radius:999px;background:{C["orClair"]};'
             f'border:1px solid {C["orBord"]};color:{C["or"]};font-size:12px;line-height:15px;font-weight:800">&#9719; {e(item["heure"])}</span> ')
    nom_course = (f'<div style="margin-top:6px;font-size:12px;line-height:16px;color:{C["stone5"]}">{e(item["course_nom"])}</div>'
                  if item.get("course_nom") else "")
    tuiles = (
        D.tuile_chiffre("Valeur estimée", D.chiffre(e(ev_txt), C["vert"]))
        + D.tuile_chiffre("Cote", D.chiffre(e(f'{item["cote"]:.1f}'.replace(".", ",")) if item.get("cote") else "—"))
        + D.tuile_chiffre("Signal", f'<div style="padding-top:2px;line-height:18px">{D.etoiles(level, 15)}</div>')
    )
    contenu = f"""
<div style="line-height:24px">{heure}{rc}<b style="font-size:13px;color:{C['slate7']};vertical-align:middle">{e(item['hippodrome'])}</b></div>
{nom_course}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:12px"><tr>
  <td class="cas" width="58" valign="top" align="center" style="width:58px">{D.casaque(item.get("casaque_url"), item["numero"])}</td>
  <td valign="middle" style="padding-left:12px">
    <div class="nom" style="font-size:18px;line-height:23px;font-weight:800;color:{C['encre2']};letter-spacing:-.01em;font-family:{POLICE}">{e(item['nom_cheval'])}</div>
    <div style="margin-top:4px;font-size:12px;line-height:17px;color:{C['stone6']}" aria-label="Signal {level} étoiles sur 4">{D.etoiles(level, 16)} &nbsp;Niveau {level}/4</div>
  </td>
</tr></table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:12px;table-layout:fixed"><tr>{tuiles}</tr></table>
<div style="margin-top:12px;text-align:right"><a href="{e(url)}" style="display:inline-block;padding:8px 12px;border-radius:10px;background:#ffffff;border:1px solid {C['stone2']};border-bottom:2px solid {C['stone3']};color:{C['or']};font-size:13px;font-weight:700;text-decoration:none">Consulter cette course →</a></div>"""
    return D.rangee_site(D.carte(contenu, "16px 16px", classe="rowin"), "12px 16px 0")


def daily(items, stamp, unsubscribe):
    title = "Les valeurs du jour"
    n = len(items)
    intro = f"{n} {'sélection disponible' if n == 1 else 'sélections disponibles'} au relevé du {stamp}. Les cotes et les signaux peuvent évoluer."
    text = [title, intro]
    top = max(items, key=lambda i: i["ev"]) if items else None
    niveaux = [max(0, min(4, int(i["niveau"]))) for i in items]

    # Récapitulatif chiffré, comme l'en-tête de la page Value bets.
    def stat(titre, valeur, couleur=C["encre"]):
        return ('<td class="pod" width="33%" valign="top" style="width:33%;padding:0 4px">'
                + D.carte(f'<div style="font-size:10px;line-height:14px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:{C["stone5"]}">{titre}</div>'
                          f'<div class="recap" style="margin-top:4px;font-size:26px;line-height:30px;font-weight:700;color:{couleur};font-family:{POLICE};white-space:nowrap">{valeur}</div>',
                          "12px 14px", classe="cellpod") + "</td>")
    recap = (
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed"><tr>'
        + stat("Sélections", str(n))
        + stat("Meilleure valeur", e(f"{top['ev'] * 100:+.1f} %".replace(".", ",")) if top else "—", C["vert"])
        + stat("Signal max", D.etoiles(max(niveaux), 17) if niveaux else "—")
        + "</tr></table>"
    )
    rangees_site = (
        D.rangee_site(D.titre_section("etoile", "Les valeurs du jour",
                                      "Chevaux dont la cote dépasse le prix estimé par le modèle"), "18px 18px 12px")
        + D.rangee_site(recap, "0 12px 4px")
    )
    for item in items[:12]:
        url = link("/courses/" + quote(str(item.get("course_id", "")), safe=""), "quotidien")
        rangees_site += _carte_valeur(item, url)
        level = max(0, min(4, int(item['niveau'])))
        text.extend([f"{item['heure']} · {item['hippodrome']}", f"N° {item['numero']} — {item['nom_cheval']}",
                     f"Niveau {level}/4 · Valeur estimée : {item['ev'] * 100:+.1f} %".replace(".", ","), url])
    if n > 12:
        rangees_site += D.rangee_site(
            f'<div style="padding:4px 4px 0;font-size:13px;color:{C["stone6"]}">{n - 12} autre(s) sélection(s) à retrouver sur le site.</div>',
            "12px 16px 0")

    apercu = f"N° {top['numero']} {top['nom_cheval']} en tête, valeur estimée {top['ev'] * 100:+.1f} %".replace(".", ",") if top else intro
    rangees = (
        D.barre_logo("&#9733; Le rendez-vous quotidien")
        + D.entete("valeurs", "Le rendez-vous quotidien", title, e(intro),
                   lien=link("/value-bets", "quotidien"),
                   legende_photo="Photo d’illustration, sans lien avec les courses présentées.")
        + D.fenetre_site(SITE + "/value-bets", rangees_site)
        + D.appel("Les cotes bougent jusqu’au départ",
                  "Consultez la fiche actualisée avant toute décision : cotes en direct, classement de l’algorithme et plan de mise.",
                  "Voir les valeurs actualisées", link("/value-bets", "quotidien"))
        + D.encart("Le repère du jour",
                   f"La {D.fort('valeur estimée')} compare une probabilité du modèle à une cote. Ce pourcentage "
                   "n’est ni un gain promis ni une probabilité de gagner. Les étoiles traduisent la force du signal, de 1 à 4.")
        + D.bloc_instagram()
        + D.pied(_mention(unsubscribe, "cette sélection quotidienne"))
    )
    text.extend([link("/value-bets", "quotidien"), "La valeur estimée n’est pas une garantie de gain.", INSTAGRAM, RESPONSABLE, "Désabonnement : " + unsubscribe])
    return D.document(title, apercu, rangees), "\n\n".join(text)


# ─── Bilan hebdomadaire ─────────────────────────────────────────────────────

def _signe(v):
    return ("+" if v > 0 else "−" if v < 0 else "") + euro(abs(v))


def _plan(rank, plan, url):
    """Un plan gagnant, avec sa médaille : bénéfice net en grand, mise et retour."""
    medaille = (f'<img src="{IMG}/medaille-{rank}.png" width="40" height="40" alt="{rank}" style="display:block;width:40px;height:40px;border:0">'
                if rank <= 3 else D.numero(rank))
    contenu = f"""
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%"><tr>
  <td width="48" valign="top" style="width:48px">{medaille}</td>
  <td valign="top" style="padding-left:8px">
    <div style="font-size:11px;line-height:16px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;color:{C['or']}">#{rank:02d} · Profil {e(plan['profil'])}</div>
    <div style="margin-top:3px;font-size:17px;line-height:22px;font-weight:800;color:{C['encre2']};font-family:{POLICE}">{e(plan['hippodrome'])} · {e(plan['code'])}</div>
    <div style="font-size:12.5px;line-height:18px;color:{C['stone5']}">&#9719; {e(plan['date'])}</div>
  </td>
</tr></table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="{C['vertFond']}" style="width:100%;margin-top:12px;border-collapse:separate;background:{C['vertFond']};background-image:linear-gradient(135deg,#ECFDF5,#D1FAE5);border:1px solid {C['vertBord']};border-bottom:3px solid #6EE7B7;border-radius:14px">
  <tr><td style="padding:12px 14px">
    <div style="font-size:10px;line-height:14px;font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:{C['vert']}">Bénéfice net du plan</div>
    <div class="gros" style="font-size:34px;line-height:40px;font-weight:700;color:#065F46;font-family:{POLICE};letter-spacing:-.02em">+{e(euro(plan['net']))}</div>
  </td></tr>
</table>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:10px;table-layout:fixed"><tr>
  {D.tuile_chiffre("Mise totale", D.chiffre(e(euro(plan['mise']))))}
  {D.tuile_chiffre("Retour, mise incluse", D.chiffre(e(euro(plan['retour']))))}
</tr></table>
<div style="margin-top:12px;text-align:right"><a href="{e(url)}" style="display:inline-block;padding:8px 12px;border-radius:10px;background:#ffffff;border:1px solid {C['stone2']};border-bottom:2px solid {C['stone3']};color:{C['or']};font-size:13px;font-weight:700;text-decoration:none">Voir la course →</a></div>"""
    return D.rangee_site(D.carte(contenu, "16px 16px"), "12px 16px 0")


def _bilan_profils(profils):
    """Bilan complet par profil, pertes comprises : la preuve que le top 3 ne
    résume pas la semaine."""
    if not profils:
        return ""
    lignes = ""
    for p in profils:
        net = float(p["net"])
        coul = C["vert"] if net > 0 else C["rouge"] if net < 0 else C["stone6"]
        fond = C["vertFond"] if net > 0 else C["rougeFond"] if net < 0 else C["stone1"]
        lignes += f"""
<tr>
  <td class="pf" style="padding:10px 6px;border-top:1px solid #F1EEE6;font-size:14px;font-weight:700;color:{C['encre2']}">{e(p['label'])}<div style="font-size:11px;font-weight:500;color:{C['stone5']}">{int(p['n'])} plan{'s' if int(p['n']) > 1 else ''}</div></td>
  <td align="right" class="pf" style="padding:10px 6px;border-top:1px solid #F1EEE6;font-size:13px;color:{C['slate6']};white-space:nowrap">{e(euro(float(p['mise'])))}</td>
  <td align="right" class="pf" style="padding:10px 6px;border-top:1px solid #F1EEE6;font-size:13px;color:{C['slate6']};white-space:nowrap">{e(euro(float(p['retour'])))}</td>
  <td align="right" class="pf" style="padding:10px 6px;border-top:1px solid #F1EEE6;white-space:nowrap"><span style="display:inline-block;padding:3px 8px;border-radius:8px;background:{fond};color:{coul};font-size:13px;font-weight:800;font-family:{POLICE}">{e(_signe(net))}</span></td>
</tr>"""
    entete = "".join(
        f'<td {"align=right " if i else ""}style="padding:0 6px 8px;font-size:10px;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:{C["stone5"]}">{t}</td>'
        for i, t in enumerate(("Profil", "Misé", "Retour", "Net")))
    contenu = (D.titre_section("euro", "Bilan complet par profil", "Tous les plans publiés, gagnants comme perdants")
               + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:14px"><tr>{entete}</tr>{lignes}</table>')
    return D.rangee_site(D.carte(contenu, "16px 16px"), "16px 16px 0")


def _chiffres_algo(algo):
    """Taux de réussite de l'algorithme, comparés au hasard par une double barre."""
    n = int(algo["courses"])
    top3 = int(algo["gagnant_top3"])
    top1 = int(algo["premier_gagnant"])
    top3_pct = f"{top3 / n * 100:.1f}".replace(".", ",")
    top1_pct = f"{top1 / n * 100:.1f}".replace(".", ",")
    chance = algo.get("hasard_top3")
    chance_n = int(algo.get("hasard_courses") or n)
    chance_scope = f" Sur {chance_n} courses dont le nombre de partants est connu." if chance_n != n else ""

    def tuile(valeur, detail, libelle):
        return ('<td class="col2" width="50%" valign="top" style="width:50%;padding:0 4px">'
                + D.carte(f'<div class="gros" style="font-size:34px;line-height:38px;font-weight:700;color:{C["or"]};font-family:{POLICE};letter-spacing:-.02em">{valeur}&nbsp;%</div>'
                          f'<div style="font-size:12px;color:{C["stone5"]}">{detail}</div>'
                          f'<div style="margin-top:6px;font-size:13.5px;line-height:19px;color:{C["encre2"]};font-weight:600">{libelle}</div>', "14px 16px")
                + "</td>")
    comparaison = ""
    if chance is not None:
        comparaison = f"""
<div style="margin-top:16px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;font-size:12px;color:{C['stone6']}">
    <tr><td style="padding-bottom:4px"><b style="color:{C['encre2']}">Notre top 3</b></td><td align="right" style="padding-bottom:4px"><b style="color:{C['or']}">{top3_pct} %</b></td></tr>
    <tr><td colspan="2" style="padding-bottom:10px">{D.barre(top3 / n, "#FCD34D", "#D97706", 10)}</td></tr>
    <tr><td style="padding-bottom:4px">3 chevaux au hasard</td><td align="right" style="padding-bottom:4px"><b>{e(str(chance).replace(".", ","))} %</b></td></tr>
    <tr><td colspan="2">{D.barre(float(chance) / 100, "#D6D3D1", "#78716C", 10)}</td></tr>
  </table>
  <p style="margin:10px 0 0;font-size:12px;line-height:18px;color:{C['stone5']}">Repère : choisir 3 chevaux au hasard dans chaque course aurait trouvé le gagnant dans <strong>{e(str(chance).replace(".", ","))} %</strong> des cas en moyenne.{e(chance_scope)}</p>
</div>"""
    contenu = (
        D.titre_section("pourcent", "Les chiffres de l’algorithme", f"Sur {n} courses évaluables de cette semaine")
        + '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;margin-top:14px;table-layout:fixed"><tr>'
        + tuile(top3_pct, f"({top3}/{n})", "gagnants figuraient dans notre top 3")
        + tuile(top1_pct, f"({top1}/{n})", "premiers choix de l’IA ont gagné")
        + "</tr></table>" + comparaison
        + f'<p style="margin:12px 0 0;font-size:11.5px;line-height:17px;color:{C["stone5"]}">Classement IA figé avant le départ et comparé à l’arrivée officielle. Les courses sans classement complet vérifiable sont exclues.</p>'
    )
    texte = [
        "Les chiffres de l’algorithme",
        f"{top3_pct} % ({top3}/{n}) : gagnants dans notre top 3",
        f"{top1_pct} % ({top1}/{n}) : premiers choix de l’IA gagnants",
        "Classements IA figés avant le départ ; courses sans classement complet exclues.",
    ]
    if chance is not None:
        texte.append(f"Repère : 3 chevaux choisis au hasard auraient trouvé le gagnant dans {str(chance).replace('.', ',')} % des cas en moyenne.{chance_scope}")
    return D.rangee_site(D.carte(contenu, "16px 16px"), "16px 16px 0"), texte


def weekly(data, unsubscribe=None, archive=None):
    winners = data["top"]
    title = ("Le meilleur plan de la semaine" if len(winners) == 1 else f"Les {len(winners)} meilleurs plans de la semaine") if winners else "Le bilan de la semaine"
    intro = f"Du {data['debut']} au {data['fin']} · Plans du site figés avant le départ, puis réglés aux rapports officiels."
    text = [title, intro]

    rangees_site = D.rangee_site(
        D.titre_section("euro", "Le podium de la semaine", "Classement par bénéfice net du plan complet, toutes mises déduites"),
        "18px 18px 4px",
    )
    rangees_site += D.rangee_site(
        f'<div style="font-size:12.5px;line-height:19px;color:{C["stone6"]}">Il s’agit de résultats des plans de référence, pas de gains encaissés par chaque utilisateur.</div>',
        "6px 20px 0")
    if not winners:
        rangees_site += D.rangee_site(D.carte(
            f'<div style="font-size:14px;line-height:21px;color:{C["slate7"]}">Aucun plan bénéficiaire vérifié sur cette période. Le bilan ci-dessous inclut les pertes.</div>',
            "16px 16px"), "12px 16px 0")
    for rank, plan in enumerate(winners, 1):
        url = link("/courses/" + quote(plan["course_id"], safe=""), "hebdomadaire")
        rangees_site += _plan(rank, plan, url)
        description = f"{plan['date']} · {plan['hippodrome']} · {plan['code']}"
        text.extend([f"N° {rank} — {description} — {plan['profil']}", f"Bénéfice net : +{euro(plan['net'])}",
                     f"Mise totale : {euro(plan['mise'])} · Retour, mise incluse : {euro(plan['retour'])}", url])

    algo = data.get("algo") or {}
    if algo.get("courses", 0) > 0:
        rangee, texte_algo = _chiffres_algo(algo)
        rangees_site += rangee
        text.extend(texte_algo)
    rangees_site += _bilan_profils(data.get("profils") or [])
    for p in data.get("profils") or []:
        text.append(f"{p['label']} : {int(p['n'])} plan(s), misé {euro(float(p['mise']))}, retour {euro(float(p['retour']))}, net {_signe(float(p['net']))}")

    apercu = f"+{euro(winners[0]['net'])} net sur le meilleur plan — {intro}" if winners else intro
    rangees = (
        D.barre_logo("La lettre hebdomadaire")
        + D.entete("bilan", "La lettre hebdomadaire", e(title), e(intro), lien=archive or SITE + "/palmares",
                   legende_photo="Photo d’illustration, sans lien avec les courses présentées.")
        + D.fenetre_site(SITE + "/palmares", rangees_site)
        + D.appel("Tous les résultats, course par course",
                  "Le palmarès détaille chaque plan publié, figé avant le départ puis réglé aux rapports officiels.",
                  "Lire et partager le bilan", archive or SITE + "/palmares")
        + D.encart("À retenir",
                   f"Le {D.fort('retour')} inclut la mise. Le {D.fort('bénéfice net')} est ce qu’il reste une fois toutes "
                   "les mises du plan déduites. Les meilleurs résultats ne représentent pas à eux seuls la performance "
                   "de la semaine : le bilan complet par profil, plans perdants inclus, est juste au-dessus.")
        + D.bloc_instagram()
        + D.pied(_mention(unsubscribe))
    )
    text.extend([archive or SITE + "/palmares", INSTAGRAM, RESPONSABLE])
    if unsubscribe:
        text.append("Désabonnement : " + unsubscribe)
    return D.document(title, apercu, rangees, lien_web=archive), "\n\n".join(text)
