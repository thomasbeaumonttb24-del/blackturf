"""Email HTML deliberately limited to tables, inline styles and one reading column."""
from html import escape
from urllib.parse import urlencode, quote

SITE = "https://blackturf.fr"
INSTAGRAM = "https://www.instagram.com/blackturf.fr/"
RESPONSABLE = "Les résultats passés ne garantissent pas les résultats futurs. Jouer comporte des risques : endettement, isolement, dépendance. Appelez le 09 74 75 13 13 (appel non surtaxé). Réservé aux personnes majeures."


def e(value):
    return escape(str(value if value is not None else ""), quote=True)


def euro(value):
    return f"{value:,.2f}".replace(",", " ").replace(".", ",") + " €"


def link(path, campaign):
    return SITE + path + "?" + urlencode({"utm_source": "newsletter", "utm_medium": "email", "utm_campaign": campaign})


def button(label, url):
    return f'<table role="presentation" cellpadding="0" cellspacing="0" style="margin:20px 0;width:100%;table-layout:fixed"><tr><td bgcolor="#b89a50" style="padding:16px;text-align:center;border-radius:6px"><a href="{e(url)}" style="color:#141917;font-size:15px;font-weight:bold;text-decoration:none;display:block">{e(label)} →</a></td></tr></table>'


def card(content):
    return f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed;margin:0 0 16px;border:1px solid #e1e3dd;border-radius:8px;background:#ffffff"><tr><td style="padding:20px;overflow-wrap:anywhere;word-wrap:break-word;word-break:break-word">{content}</td></tr></table>'


def layout(title, eyebrow, intro, content, unsubscribe=None, archive=None, photo="galop-lutte.jpg"):
    footer = f'<a href="{e(unsubscribe)}" style="color:#515952">Se désabonner</a>' if unsubscribe else ""
    if unsubscribe and "/newsletter/desinscription?" not in unsubscribe:
        footer += f' · <a href="{SITE}/notifications" style="color:#515952">Mes préférences</a>'
    browser = f'<a href="{e(archive)}" style="color:#68726c">Lire et partager ce bilan sur le web</a>' if archive else "La lettre BlackTurf · Informations horodatées"
    return f'''<!doctype html><html lang="fr"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="color-scheme" content="light"><title>{e(title)} — BlackTurf</title></head>
<body style="margin:0;padding:0;background:#eff0eb;color:#1b2923;font-family:Arial,Helvetica,sans-serif;-webkit-text-size-adjust:100%">
<div style="display:none;max-height:0;overflow:hidden;mso-hide:all">{e(intro)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" bgcolor="#eff0eb" style="width:100%;table-layout:fixed"><tr><td align="center" style="padding:16px 8px">
<!--[if mso]><table role="presentation" width="600"><tr><td><![endif]-->
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;table-layout:fixed">
<tr><td style="text-align:center;font-size:11px;line-height:18px;padding:0 8px 16px;color:#68726c">{browser}</td></tr>
<tr><td align="center" bgcolor="#ffffff" style="padding:8px 24px;border-top:4px solid #b89a50"><a href="{SITE}"><img src="{SITE}/img/logo-blackturf.png" width="200" alt="BlackTurf" style="display:block;width:200px;max-width:100%;height:auto;border:0"></a></td></tr>
<tr><td bgcolor="#142b23"><img src="{SITE}/img/course/{e(photo)}" width="600" alt="Chevaux en course, photo d’illustration" style="display:block;width:100%;max-width:600px;height:auto;border:0;color:#ffffff;font-size:13px"></td></tr>
<tr><td bgcolor="#142b23" style="padding:28px 24px;color:#ffffff;overflow-wrap:anywhere;word-break:break-word"><p style="margin:0 0 12px;font-size:11px;line-height:18px;letter-spacing:2px;color:#dbc58c">{e(eyebrow)}</p><h1 style="margin:0 0 14px;font-size:28px;line-height:34px;font-weight:700">{e(title)}</h1><p style="margin:0;font-size:15px;line-height:24px;color:#e1e9e4">{e(intro)}</p></td></tr>
<tr><td bgcolor="#142b23" style="padding:0 24px 18px;color:#b8c9bd;font-size:11px;line-height:16px">Photo d’illustration, sans lien avec les courses présentées.</td></tr>
<tr><td bgcolor="#f8f9f5" style="padding:24px 16px;font-size:15px;line-height:24px;overflow-wrap:anywhere;word-break:break-word">{content}
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed;margin-top:24px;border-top:1px solid #d6d9cf"><tr><td style="padding:24px 4px 4px"><p style="margin:0 0 8px;font-size:18px;font-weight:bold">La suite se passe aussi sur Instagram.</p><p style="margin:0 0 12px;color:#515952">Les infos du jour et les publications BlackTurf, entre deux lettres.</p><a href="{INSTAGRAM}" style="color:#725519;font-weight:bold;text-decoration:underline">Suivre @blackturf.fr →</a></td></tr></table>
</td></tr><tr><td style="padding:24px 16px;font-size:12px;line-height:19px;color:#616b64;text-align:center">{footer}<p style="margin:16px 0 0">{RESPONSABLE}</p></td></tr></table>
<!--[if mso]></td></tr></table><![endif]--></td></tr></table></body></html>'''


def daily(items, stamp, unsubscribe):
    title = "Les valeurs du jour"
    intro = f"{len(items)} {"sélection disponible" if len(items) == 1 else "sélections disponibles"} au relevé du {stamp}. Les cotes et les signaux peuvent évoluer."
    body = '<p style="margin:0 0 20px;color:#515952">Votre sélection, course par course. Consultez la fiche actualisée avant toute décision.</p>'
    text = [title, intro]
    for item in items[:12]:
        url = link("/courses/" + quote(str(item.get("course_id", "")), safe=""), "quotidien")
        heading = f"{item['heure']} · {item['hippodrome']}"
        name = f"N° {item['numero']} — {item['nom_cheval']}"
        level = max(0, min(4, int(item['niveau'])))
        signal = f"Niveau {level}/4 · Valeur estimée : {item['ev'] * 100:+.1f} %".replace(".", ",")
        stars = f'<span style="color:#b18a32;font-size:21px;letter-spacing:2px">{"★" * level}</span><span style="color:#c8ccc5;font-size:21px;letter-spacing:2px">{"☆" * (4 - level)}</span>'
        body += card(f'<p style="margin:0 0 9px;color:#80612b;font-size:12px;font-weight:bold;letter-spacing:1px">{e(heading)}</p><h2 style="margin:0 0 12px;font-size:22px;line-height:29px;color:#142b23">{e(name)}</h2><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed;margin:0 0 14px;background:#f5f3eb;border-left:3px solid #b89a50"><tr><td style="padding:10px 12px"><div aria-label="Signal {level} étoiles sur 4">{stars}</div><div style="font-size:13px;line-height:20px;color:#515952">{e(signal)}</div></td></tr></table><a href="{e(url)}" style="color:#244e3d;font-weight:bold">Consulter cette course →</a>')
        text.extend([heading, name, signal, url])
    if len(items) > 12:
        body += f'<p>{len(items) - 12} autre(s) sélection(s) à retrouver sur le site.</p>'
    body += button("Voir les valeurs actualisées", link("/value-bets", "quotidien"))
    body += '<p style="font-size:13px;color:#515952"><strong>Le repère du jour</strong><br>La valeur estimée compare une probabilité du modèle à une cote. Ce pourcentage n’est ni un gain promis ni une probabilité de gagner.</p>'
    text.extend([link("/value-bets", "quotidien"), "La valeur estimée n’est pas une garantie de gain.", INSTAGRAM, RESPONSABLE, "Désabonnement : " + unsubscribe])
    return layout(title, "LE RENDEZ-VOUS QUOTIDIEN", intro, body, unsubscribe), "\n\n".join(text)


def weekly(data, unsubscribe=None, archive=None):
    winners = data["top"]
    title = ("Le meilleur plan de la semaine" if len(winners) == 1 else f"Les {len(winners)} meilleurs plans de la semaine") if winners else "Le bilan de la semaine"
    intro = f"Du {data['debut']} au {data['fin']} · Plans du site figés avant le départ, puis réglés aux rapports officiels."
    body = '<p style="margin:0 0 20px;color:#515952">Classement par bénéfice net du plan complet, après déduction de toutes ses mises. Il s’agit de résultats des plans de référence, pas de gains encaissés par chaque utilisateur.</p>'
    text = [title, intro]
    if not winners:
        body += card("Aucun plan bénéficiaire vérifié sur cette période. Le bilan ci-dessous inclut les pertes.")
    for rank, plan in enumerate(winners, 1):
        url = link("/courses/" + quote(plan["course_id"], safe=""), "hebdomadaire")
        description = f"{plan['date']} · {plan['hippodrome']} · {plan['code']}"
        amounts = f"Mise totale : {euro(plan['mise'])} · Retour, mise incluse : {euro(plan['retour'])}"
        body += card(f'<p style="margin:0 0 10px;font-size:12px;color:#80612b;font-weight:bold;letter-spacing:1px">#{rank:02d} &nbsp;·&nbsp; PROFIL {e(plan["profil"]).upper()}</p><h2 style="margin:0 0 12px;font-size:20px;line-height:27px;color:#142b23">{e(description)}</h2><table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="width:100%;table-layout:fixed;margin:0 0 14px;background:#eff5ed;border-left:3px solid #3d7658"><tr><td style="padding:12px"><div style="color:#515952;font-size:13px">Bénéfice net du plan</div><div style="font-size:32px;line-height:40px;color:#24513d;font-weight:bold">+{e(euro(plan["net"]))}</div></td></tr></table><p style="margin:0 0 16px;color:#515952;font-size:14px">Mise totale : <strong>{e(euro(plan["mise"]))}</strong><br>Retour, mise incluse : <strong>{e(euro(plan["retour"]))}</strong></p><a href="{e(url)}" style="color:#244e3d;font-weight:bold">Voir la course →</a>')
        text.extend([f"N° {rank} — {description} — {plan['profil']}", f"Bénéfice net : +{euro(plan['net'])}", amounts, url])
    algo = data.get("algo") or {}
    if algo.get("courses", 0) > 0:
        n = int(algo["courses"])
        top3 = int(algo["gagnant_top3"])
        top1 = int(algo["premier_gagnant"])
        body += '<h2 style="font-size:21px;line-height:27px;margin:28px 0 12px;color:#142b23">Les chiffres de l’algorithme</h2>'
        body += card(f'<p style="margin:0 0 16px;color:#515952;font-size:13px">Sur <strong>{n} courses évaluables</strong> de cette semaine :</p><p style="margin:0 0 8px;font-size:19px;line-height:27px;color:#142b23"><strong style="color:#80612b">{top3}/{n}</strong> gagnants figuraient dans notre top 3</p><p style="margin:0 0 16px;font-size:19px;line-height:27px;color:#142b23"><strong style="color:#80612b">{top1}/{n}</strong> premiers choix de l’IA ont gagné</p><p style="margin:0;color:#5c665e;font-size:12px;line-height:19px">Classement IA figé avant le départ et comparé à l’arrivée officielle. Les courses sans classement complet vérifiable sont exclues.</p>')
        text.extend(["Les chiffres de l’algorithme", f"{top3}/{n} gagnants figuraient dans notre top 3", f"{top1}/{n} premiers choix de l’IA ont gagné", "Classements IA figés avant le départ ; courses sans classement complet exclues."])
    body += button("Lire et partager le bilan", archive or SITE + "/palmares")
    body += '<p style="font-size:13px;color:#515952"><strong>À retenir</strong><br>Le retour inclut la mise. Le bénéfice net est ce qu’il reste une fois toutes les mises du plan déduites. Les meilleurs résultats ne représentent pas à eux seuls la performance de la semaine.</p>'
    text.extend([archive or SITE + "/palmares", INSTAGRAM, RESPONSABLE])
    if unsubscribe:
        text.append("Désabonnement : " + unsubscribe)
    return layout(title, "LA LETTRE HEBDOMADAIRE", intro, body, unsubscribe, archive, photo="galop-foule.jpg"), "\n\n".join(text)
