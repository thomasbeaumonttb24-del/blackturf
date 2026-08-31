"""Vérification quotidienne du retrain nocturne — rapport e-mail actionnable.

Contexte (audit 2026-08-16) : le modèle est resté gelé sur v503 pendant 48 jours
sans que personne ne le sache, parce que l'échec du retrain nocturne était
totalement silencieux — soit OOM-killed (7 nuits sur 14 en août), soit rejeté
par un gate de promotion cassé. Ce script existe pour que ce silence ne se
reproduise jamais : chaque matin, un e-mail dit ce qui s'est passé cette nuit.

Lancé par cron sur le VPS (voir scripts/install_check_retrain_cron.sh), il
inspecte l'état RÉEL (base + logs du worker) et n'invente rien : si une
information n'est pas disponible, il le dit au lieu de supposer.

Usage :
    python -m scripts.check_retrain_nightly            # envoie l'e-mail
    python -m scripts.check_retrain_nightly --dry-run  # affiche, n'envoie pas
"""
import argparse
import asyncio
import os
import subprocess
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, text

from db.database import AsyncSessionLocal
from db.models import ModelVersion

DEST = os.getenv("RETRAIN_REPORT_TO", "thomas.beaumont.tb24@gmail.com")
WORKER_CONTAINER = os.getenv("BT_WORKER_CONTAINER", "blackturf_worker")

# Motifs cherchés dans les logs du worker sur la fenêtre de la nuit écoulée.
PATTERNS = (
    "nightly_retrain.start", "retrain.deployed", "retrain.rollback",
    "h2h.measured", "signal 9", "MemoryError",
    # Empreinte mémoire par étape : sans elle, un OOM ne dit pas OÙ ça a débordé.
    "pipeline.rss",
)


def _worker_logs(since_hours: int = 12) -> str:
    """Logs du worker sur les N dernières heures.

    Deux modes, parce que les informations nécessaires ne vivent pas au même
    endroit : la base et la clé Resend sont accessibles depuis le CONTENEUR,
    mais `docker logs` ne l'est que depuis l'HÔTE. Le cron résout ça en
    déversant d'abord les logs dans un fichier qu'il monte dans le conteneur
    (`BT_WORKER_LOGS_FILE`). Sans cette variable, on retombe sur un appel
    docker direct — pratique pour un lancement manuel depuis l'hôte.
    """
    fichier = os.getenv("BT_WORKER_LOGS_FILE")
    if fichier:
        try:
            with open(fichier, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except Exception as e:
            return f"__LOGS_INDISPONIBLES__ fichier {fichier}: {e}"
    try:
        out = subprocess.run(
            ["docker", "logs", WORKER_CONTAINER, "--since", f"{since_hours}h"],
            capture_output=True, text=True, timeout=60,
        )
        return (out.stdout or "") + (out.stderr or "")
    except Exception as e:
        return f"__LOGS_INDISPONIBLES__ {e}"


def _pic_rss(logs: str) -> float:
    """Plus haut `rss_mb=` tracé par le pipeline sur la fenêtre. 0.0 si absent.

    Le signal 9 d'un OOM-kill n'écrit rien : sans cette mesure, il est impossible
    de dire après coup si le retrain avait débordé ou s'il a été désigné victime
    d'une pression venue d'ailleurs (le 20/08/2026, c'était le second cas).
    """
    pic = 0.0
    for ligne in logs.splitlines():
        if "rss_mb=" not in ligne:
            continue
        for mot in ligne.split():
            if mot.startswith("rss_mb="):
                try:
                    pic = max(pic, float(mot.split("=", 1)[1]))
                except ValueError:
                    pass
    return pic


def _analyser_logs(logs: str) -> dict:
    """Extrait ce qui s'est passé cette nuit. Fonction pure → testable."""
    if logs.startswith("__LOGS_INDISPONIBLES__"):
        return {"statut": "inconnu", "detail": logs, "lignes": []}

    lignes = [l.strip() for l in logs.splitlines()
              if any(p in l for p in PATTERNS)]

    a_demarre = any("nightly_retrain.start" in l for l in lignes)
    a_oom = any(("signal 9" in l) or ("MemoryError" in l) for l in lignes)
    a_deploye = any("retrain.deployed" in l for l in lignes)
    a_rollback = any("retrain.rollback" in l for l in lignes)

    # L'OOM ne l'emporte PLUS inconditionnellement sur la promotion. La nuit du
    # 19→20/08/2026, v511 a été déployé à 02:02:38 et le worker tué à 02:04:11 :
    # le modèle était bel et bien en production, mais le mail annonçait « le
    # retrain a été tué par manque de mémoire / le modèle ne peut pas
    # progresser ». Verdict faux, et diagnostic envoyé dans le mur.
    if a_oom and a_deploye:
        statut = "promu_puis_oom"
    elif a_oom:
        statut = "oom"
    elif a_deploye:
        statut = "promu"
    elif a_rollback:
        statut = "rejete"
    elif a_demarre:
        statut = "incomplet"   # démarré mais ni promu ni rejeté ni OOM
    else:
        statut = "absent"      # le job n'a même pas démarré
    return {"statut": statut, "detail": "", "lignes": lignes[-12:],
            "rss_pic_mb": _pic_rss(logs)}


VERDICTS = {
    "promu": ("✅", "Un nouveau modèle a été promu cette nuit",
              "L'apprentissage est reparti. Surveiller le ROI des prochains jours."),
    "rejete": ("⚠️", "Retrain terminé mais le challenger a été REJETÉ",
               "Le modèle actif reste en place. Normal ponctuellement ; si ça se "
               "répète chaque nuit, le gate de promotion est peut-être encore trop "
               "strict — relancer scripts/check_h2h_champion.py pour comparer."),
    "promu_puis_oom": (
        "⚠️", "Modèle promu, mais le worker a été tué avant la fin des analyses",
        "Le nouveau modèle EST en production — l'apprentissage du modèle a "
        "abouti. Ce qui a sauté, ce sont les étapes d'après (calibrations, ROI "
        "par signal, poids appris), qui repartiront demain. Vérifier `rss_mb` "
        "ci-dessous : si le pic reste bas, la pression mémoire venait d'ailleurs "
        "que du retrain (typiquement les daemons de cotes hors Docker)."),
    "oom": ("🔴", "Le retrain a été tué par manque de mémoire (OOM)",
            "Le modèle ne peut pas progresser. Action : réduire la fenêtre de "
            "données d'entraînement ou BT_TRAIN_NJOBS, ou augmenter la limite "
            "mémoire du worker dans docker-compose.prod.yml."),
    "incomplet": ("⚠️", "Le retrain a démarré mais ne s'est pas terminé",
                  "Ni promotion, ni rejet, ni OOM détecté. Vérifier les logs du "
                  "worker et la file RQ (FailedJobRegistry)."),
    "promu_logs_absents": (
        "✅", "Un modèle a été promu cette nuit (logs du worker introuvables)",
        "La base fait foi : un nouveau modèle y a été enregistré sur la fenêtre. "
        "Les logs manquent simplement parce que le conteneur worker a été "
        "recréé depuis (déploiement) — `docker logs` ne remonte pas au-delà de "
        "l'instance courante. Rien à faire."),
    "absent": ("🔴", "Aucun retrain n'a démarré cette nuit",
               "Le job planifié 02:00 UTC ne s'est pas déclenché. Vérifier que le "
               "conteneur scheduler tourne et que le job est bien enregistré."),
    "inconnu": ("❓", "Impossible de lire les logs du worker",
                "Le script n'a pas pu interroger Docker. Vérifier les droits ou "
                "que le conteneur worker existe."),
}


def _promu_recemment(modele: dict, fenetre_jours: int = 1) -> bool:
    """Un modèle a-t-il été promu sur la fenêtre couverte par le rapport ?"""
    age = modele.get("age_jours")
    return modele.get("version") is not None and age is not None and age <= fenetre_jours


async def _etat_modele() -> dict:
    """Modèle actif + ancienneté. Ce qui compte vraiment : depuis combien de
    jours le modèle n'a pas bougé."""
    async with AsyncSessionLocal() as s:
        mv = (await s.execute(
            select(ModelVersion).where(ModelVersion.est_actif == True)
            .order_by(ModelVersion.version_num.desc())
        )).scalars().first()
        if mv is None:
            return {"version": None}
        age = (datetime.now(timezone.utc) - mv.created_at).days
        # Volume de données réglées depuis 24 h : un retrain sans données
        # nouvelles n'a rien à apprendre, c'est un contexte utile au diagnostic.
        nb = (await s.execute(text("""
            SELECT count(*) FROM courses
            WHERE statut = 'termine' AND date_heure > now() - interval '24 hours'
        """))).scalar() or 0
        # ── Tendance ────────────────────────────────────────────────────────
        # Le rapport ne montrait que les chiffres du jour. Or le gate de promotion
        # tolère une régression par rapport au champion de la VEILLE, sans jamais
        # se comparer au meilleur modèle jamais atteint : une dérive de quelques
        # dix-millièmes par nuit passe donc indéfiniment, et un chiffre isolé la
        # rend invisible. Constaté le 2026-08-31 : walk-forward 0,7888 → 0,7869 et
        # avantage sur la cote 0,0201 → 0,0188 en cinq nuits, chaque nuit annoncée
        # comme une amélioration. Ces deux écarts sont le seul moyen de le voir.
        #
        # Le prédécesseur est la version de numéro immédiatement inférieur, pas
        # « celle d'hier » : plusieurs promotions peuvent tomber le même jour
        # (v511/512/513 le 20/08), et une date ne les départage pas.
        prec = (await s.execute(
            select(ModelVersion)
            .where(ModelVersion.version_num < mv.version_num)
            .order_by(ModelVersion.version_num.desc())
        )).scalars().first()

        # Volume plancher d'un modèle COMPARABLE. Le walk-forward ré-entraîne un
        # modèle rapide sur des folds du dataset courant : c'est une mesure du
        # DATASET autant que du modèle, et elle est d'autant plus optimiste que le
        # jeu est petit. Sans ce plancher, le record remontait la v2 à 0,9949 —
        # entraînée sur une poignée de courses aux tout débuts — et le rapport
        # aurait annoncé −0,2079 chaque matin, une alerte permanente et vide.
        # 80 % du volume courant garde la génération de dataset en cours (depuis la
        # fenêtre 12 mois : ~176 000 lignes) et écarte la précédente (~41 000).
        volume_courant = mv.nb_courses_train or 0
        volume_min = int(volume_courant * 0.8)

        def _record(colonne):
            """Meilleure valeur atteinte par un modèle COMPARABLE, et sa version.

            Comparable = non synthétique (un modèle de secours n'est pas une
            référence de qualité) ET entraîné sur un volume du même ordre. Le
            plancher de volume est indispensable au walk-forward ; il est appliqué
            aussi à l'avantage sur la cote, dont la variance sur un petit jeu ne se
            compare pas davantage.

            `is_not(None)` est explicite : sous PostgreSQL un `ORDER BY … DESC`
            placerait les NULL en tête.
            """
            return (
                select(ModelVersion.version_num, colonne)
                .where(
                    colonne.is_not(None),
                    ModelVersion.est_synthetique.is_(False),
                    ModelVersion.nb_courses_train >= volume_min,
                )
                .order_by(colonne.desc())
                .limit(1)
            )

        rec_wf = (await s.execute(_record(ModelVersion.walk_forward_auc))).first()
        rec_delta = (await s.execute(_record(ModelVersion.rank_delta_market))).first()

        def _ecart(actuel, reference):
            if actuel is None or reference is None:
                return None
            return round(actuel - reference, 4)

        return {
            "version": mv.version_num,
            "cree_le": mv.created_at.strftime("%d/%m/%Y"),
            "age_jours": age,
            "wf_auc": round(mv.walk_forward_auc, 4) if mv.walk_forward_auc else None,
            "courses_24h": int(nb),
            # Le couple qui dit si le modèle mérite d'exister (migration 0035).
            # None sur les versions antérieures au 20/08/2026, jamais 0.0.
            "rank_auc": round(mv.rank_auc, 4) if mv.rank_auc is not None else None,
            "market_rank_auc": (round(mv.market_rank_auc, 4)
                                if mv.market_rank_auc is not None else None),
            "rank_delta_market": (round(mv.rank_delta_market, 4)
                                  if mv.rank_delta_market is not None else None),
            # Tendance : écart au prédécesseur immédiat et au record historique.
            "prec_version": prec.version_num if prec else None,
            "wf_vs_prec": _ecart(mv.walk_forward_auc,
                                 prec.walk_forward_auc if prec else None),
            "delta_vs_prec": _ecart(mv.rank_delta_market,
                                    prec.rank_delta_market if prec else None),
            "wf_record": round(rec_wf[1], 4) if rec_wf else None,
            "wf_record_version": rec_wf[0] if rec_wf else None,
            "wf_vs_record": _ecart(mv.walk_forward_auc, rec_wf[1] if rec_wf else None),
            "delta_record": round(rec_delta[1], 4) if rec_delta else None,
            "delta_record_version": rec_delta[0] if rec_delta else None,
            "delta_vs_record": _ecart(mv.rank_delta_market,
                                      rec_delta[1] if rec_delta else None),
        }


def _ligne_tendance(libelle: str, valeur, ecart, reference: str) -> str:
    """Une ligne « métrique — écart — référence ».

    Le signe porte la couleur, pas la valeur absolue : un walk-forward de 0,7869
    n'est ni bon ni mauvais dans l'absolu, ce qui compte est qu'il ait baissé.
    Un écart nul est neutre (gris) et non vert : ne pas avoir régressé n'est pas
    une amélioration.
    """
    if valeur is None:
        return ""
    if ecart is None:
        etxt, coul = "—", "#666"
    elif ecart > 0:
        etxt, coul = f"{ecart:+.4f}", "#16a34a"
    elif ecart < 0:
        etxt, coul = f"{ecart:+.4f}", "#dc2626"
    else:
        etxt, coul = "=", "#666"
    return (
        f'<tr><td style="padding:4px 12px 4px 0;color:#666;">{libelle}</td>'
        f'<td><b>{valeur:.4f}</b></td>'
        f'<td style="padding-left:12px;color:{coul};font-weight:bold;">{etxt}</td>'
        f'<td style="padding-left:8px;color:#666;font-size:12px;">{reference}</td></tr>'
    )


def _bloc_tendance(modele: dict) -> str:
    """Écart au modèle précédent ET au meilleur jamais atteint.

    Pourquoi le record et pas seulement la veille : le gate de promotion tolère une
    régression par rapport au champion de la veille, sans plancher absolu. Une baisse
    de quelques dix-millièmes par nuit est donc acceptée indéfiniment, et chaque nuit
    prise isolément paraît normale. L'écart au record est la seule ligne qui rende
    cette dérive cumulée visible.
    """
    if modele.get("wf_auc") is None and modele.get("rank_delta_market") is None:
        return ""
    prec = modele.get("prec_version")
    ref_prec = f"vs v{prec}" if prec else "pas de prédécesseur"
    lignes = [
        _ligne_tendance("Walk-forward AUC", modele.get("wf_auc"),
                        modele.get("wf_vs_prec"), ref_prec),
        _ligne_tendance("Walk-forward AUC", modele.get("wf_auc"),
                        modele.get("wf_vs_record"),
                        f"vs record v{modele.get('wf_record_version')}"
                        f" ({modele['wf_record']:.4f})" if modele.get("wf_record") else "—"),
        _ligne_tendance("Avantage sur la cote", modele.get("rank_delta_market"),
                        modele.get("delta_vs_prec"), ref_prec),
        _ligne_tendance("Avantage sur la cote", modele.get("rank_delta_market"),
                        modele.get("delta_vs_record"),
                        f"vs record v{modele.get('delta_record_version')}"
                        f" ({modele['delta_record']:+.4f})" if modele.get("delta_record") else "—"),
    ]
    corps = "".join(l for l in lignes if l)
    if not corps:
        return ""
    # Une dérive ne se lit qu'au cumul : on la nomme quand l'écart au record est
    # négatif, sinon le lecteur voit deux nombres sans savoir lequel doit l'inquiéter.
    _wr, _dr = modele.get("wf_vs_record"), modele.get("delta_vs_record")
    sous_record = [
        nom for nom, ec in (("le walk-forward", _wr), ("l'avantage sur la cote", _dr))
        if ec is not None and ec < 0
    ]
    avertissement = (
        f'<p style="color:#d97706;font-size:13px;margin-top:6px;">'
        f'Le modèle actif est sous son record historique sur {" et ".join(sous_record)}. '
        f'La promotion nocturne se compare au modèle de la veille, jamais au meilleur '
        f'jamais atteint : une baisse répétée sous le seuil de tolérance est acceptée '
        f'nuit après nuit.</p>'
    ) if sous_record else ""
    return f"""
    <h3 style="font-size:14px;margin-top:24px;">Tendance</h3>
    <table style="border-collapse:collapse;font-size:14px;">{corps}</table>{avertissement}"""


def _html(verdict: tuple, modele: dict, lignes: list[str],
          rss_pic_mb: float = 0.0) -> str:
    icone, titre, action = verdict
    couleur = {"✅": "#16a34a", "⚠️": "#d97706", "🔴": "#dc2626", "❓": "#6b7280"}[icone]
    # Pic mémoire du retrain. Le VPS a 7,6 Gio partagés : au-delà d'environ
    # 3,5 Gio le retrain devient le plus gros RSS de la machine et donc la cible
    # naturelle de l'OOM killer, même quand la pression vient d'ailleurs.
    if rss_pic_mb <= 0:
        ligne_rss = ""
    else:
        _seuil = "#dc2626" if rss_pic_mb > 3500 else "#666"
        ligne_rss = (
            f'<tr><td style="padding:4px 12px 4px 0;color:#666;">Pic mémoire retrain</td>'
            f'<td style="color:{_seuil};">{rss_pic_mb:.0f} Mo</td></tr>'
        )

    # ── Verdict de CLASSEMENT ────────────────────────────────────────────────
    # L'AUC affichée jusqu'ici est POOLÉE : elle mélange la variance inter-course
    # et le classement intra-course, et flatte un modèle qui se contente de relire
    # la cote. Ce bloc affiche la seule comparaison qui dit si le modèle mérite
    # d'exister — son classement contre un simple `ORDER BY cote_pmu`.
    _delta = modele.get("rank_delta_market")
    if modele.get("rank_auc") is None:
        bloc_classement = (
            "<p style='color:#666;font-size:13px;'>Classement intra-course pas "
            "encore mesuré sur ce modèle (antérieur au 20/08/2026).</p>")
    else:
        _bat = _delta is not None and _delta > 0
        _coul = "#16a34a" if _bat else "#dc2626"
        _verdict = ("bat la cote" if _bat
                    else "SOUS la cote — le classement affiché ferait mieux sans modèle"
                    if _delta is not None else "référence marché non mesurable")
        _dtxt = f"{_delta:+.4f}" if _delta is not None else "—"
        _mtxt = (f"{modele['market_rank_auc']:.4f}"
                 if modele.get("market_rank_auc") is not None else "—")
        bloc_classement = f"""
    <h3 style="font-size:14px;margin-top:24px;">Classement intra-course</h3>
    <table style="border-collapse:collapse;font-size:14px;">
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Modèle</td><td><b>{modele['rank_auc']:.4f}</b></td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Cote seule (ORDER BY cote_pmu)</td><td>{_mtxt}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Écart</td>
          <td style="color:{_coul};font-weight:bold;">{_dtxt} — {_verdict}</td></tr>
    </table>
    <p style="color:#666;font-size:12px;margin-top:6px;">
      0,5 = hasard. Mesuré sur les folds walk-forward, chaque course pesant pareil.
      Ne se compare pas à l'AUC poolée ci-dessus.
    </p>"""

    # ── Tendance ─────────────────────────────────────────────────────────────
    # Une valeur isolée ne dit pas si le modèle monte ou descend, et le gate de
    # promotion ne se compare jamais au meilleur modèle jamais atteint : sans ces
    # deux écarts, une dérive lente reste invisible nuit après nuit.
    bloc_tendance = _bloc_tendance(modele)

    if modele.get("version") is None:
        bloc_modele = "<p>Aucun modèle actif en base.</p>"
    else:
        alerte_age = ("  <span style='color:#dc2626;font-weight:bold;'>← figé depuis longtemps</span>"
                      if modele["age_jours"] >= 7 else "")
        bloc_modele = f"""
    <table style="border-collapse:collapse;font-size:14px;">
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Modèle actif</td><td><b>v{modele['version']}</b> (créé le {modele['cree_le']})</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Ancienneté</td><td>{modele['age_jours']} jour(s){alerte_age}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Walk-forward AUC</td><td>{modele['wf_auc'] if modele['wf_auc'] is not None else '—'}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Courses réglées (24 h)</td><td>{modele['courses_24h']}</td></tr>
      {ligne_rss}
    </table>"""

    # Les lignes de log sont du contenu non maîtrisé qui atterrit dans du HTML :
    # échappement standard (pas un simple remplacement de "<", qui laissait
    # passer ">" et produisait du HTML mal formé).
    from html import escape as _esc
    logs = ("<pre style='background:#f5f5f5;padding:12px;border-radius:6px;"
            "font-size:11px;overflow-x:auto;white-space:pre-wrap;'>"
            + "\n".join(_esc(l) for l in lignes) + "</pre>") if lignes else \
           "<p style='color:#666;font-size:13px;'>Aucune ligne de log pertinente trouvée.</p>"

    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"></head>
<body style="font-family:Arial,sans-serif;max-width:640px;margin:0 auto;padding:20px;">
  <h2 style="color:{couleur};margin-bottom:4px;">{icone} {titre}</h2>
  <p style="color:#666;font-size:13px;margin-top:0;">Retrain nocturne BlackTurf — nuit du {(datetime.now(timezone.utc) - timedelta(days=1)).strftime('%d/%m')} au {datetime.now(timezone.utc).strftime('%d/%m/%Y')}</p>
  <div style="background:#fff7ed;border-left:4px solid {couleur};padding:12px 16px;margin:16px 0;">
    <b>À faire :</b> {action}
  </div>
  {bloc_modele}
  {bloc_classement}
  {bloc_tendance}
  <h3 style="font-size:14px;margin-top:24px;">Extrait des logs</h3>
  {logs}
  <p style="color:#999;font-size:11px;margin-top:24px;">
    Rapport automatique — <code>scripts/check_retrain_nightly.py</code> sur le VPS.
    Existe parce que le modèle est resté gelé 48 jours sans alerte (audit 2026-08-16).
  </p>
</body></html>"""


async def main(dry_run: bool = False) -> None:
    logs = _worker_logs()
    analyse = _analyser_logs(logs)
    modele = await _etat_modele()
    # La BASE prime sur les logs quand les deux se contredisent. `docker logs`
    # ne couvre que l'instance courante du conteneur : un déploiement entre le
    # retrain et le rapport efface les traces et faisait annoncer « aucun
    # retrain n'a démarré » alors qu'un modèle tout neuf était actif. C'est le
    # même travers que le verdict OOM qui primait sur la promotion : une alerte
    # qui contredit l'état réel du système fait perdre plus de temps qu'elle
    # n'en fait gagner.
    if analyse["statut"] == "absent" and _promu_recemment(modele):
        analyse["statut"] = "promu_logs_absents"
    verdict = VERDICTS[analyse["statut"]]
    lignes = analyse["lignes"] or ([analyse["detail"]] if analyse["detail"] else [])

    icone, titre, _ = verdict
    sujet = f"{icone} BlackTurf retrain — {titre}"
    corps = _html(verdict, modele, lignes, analyse.get("rss_pic_mb", 0.0))

    if dry_run:
        print(f"SUJET : {sujet}")
        print(f"STATUT : {analyse['statut']}")
        print(f"MODELE : {modele}")
        print(f"LIGNES : {len(lignes)}")
        print(f"PIC RSS : {analyse.get('rss_pic_mb', 0.0)} Mo")
        return

    from services.alerts import send_email
    ok = await send_email(to=DEST, subject=sujet, html=corps)
    print(f"envoi={ok} statut={analyse['statut']} modele=v{modele.get('version')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="affiche sans envoyer")
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
