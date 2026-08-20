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
        }


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
