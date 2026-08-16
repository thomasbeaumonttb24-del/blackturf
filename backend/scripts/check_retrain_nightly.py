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

    if a_oom:
        statut = "oom"
    elif a_deploye:
        statut = "promu"
    elif a_rollback:
        statut = "rejete"
    elif a_demarre:
        statut = "incomplet"   # démarré mais ni promu ni rejeté ni OOM
    else:
        statut = "absent"      # le job n'a même pas démarré
    return {"statut": statut, "detail": "", "lignes": lignes[-12:]}


VERDICTS = {
    "promu": ("✅", "Un nouveau modèle a été promu cette nuit",
              "L'apprentissage est reparti. Surveiller le ROI des prochains jours."),
    "rejete": ("⚠️", "Retrain terminé mais le challenger a été REJETÉ",
               "Le modèle actif reste en place. Normal ponctuellement ; si ça se "
               "répète chaque nuit, le gate de promotion est peut-être encore trop "
               "strict — relancer scripts/check_h2h_champion.py pour comparer."),
    "oom": ("🔴", "Le retrain a été tué par manque de mémoire (OOM)",
            "Le modèle ne peut pas progresser. Action : réduire la fenêtre de "
            "données d'entraînement ou BT_TRAIN_NJOBS, ou augmenter la limite "
            "mémoire du worker dans docker-compose.prod.yml."),
    "incomplet": ("⚠️", "Le retrain a démarré mais ne s'est pas terminé",
                  "Ni promotion, ni rejet, ni OOM détecté. Vérifier les logs du "
                  "worker et la file RQ (FailedJobRegistry)."),
    "absent": ("🔴", "Aucun retrain n'a démarré cette nuit",
               "Le job planifié 02:00 UTC ne s'est pas déclenché. Vérifier que le "
               "conteneur scheduler tourne et que le job est bien enregistré."),
    "inconnu": ("❓", "Impossible de lire les logs du worker",
                "Le script n'a pas pu interroger Docker. Vérifier les droits ou "
                "que le conteneur worker existe."),
}


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
        }


def _html(verdict: tuple, modele: dict, lignes: list[str]) -> str:
    icone, titre, action = verdict
    couleur = {"✅": "#16a34a", "⚠️": "#d97706", "🔴": "#dc2626", "❓": "#6b7280"}[icone]
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
    verdict = VERDICTS[analyse["statut"]]
    lignes = analyse["lignes"] or ([analyse["detail"]] if analyse["detail"] else [])

    icone, titre, _ = verdict
    sujet = f"{icone} BlackTurf retrain — {titre}"
    corps = _html(verdict, modele, lignes)

    if dry_run:
        print(f"SUJET : {sujet}")
        print(f"STATUT : {analyse['statut']}")
        print(f"MODELE : {modele}")
        print(f"LIGNES : {len(lignes)}")
        return

    from services.alerts import send_email
    ok = await send_email(to=DEST, subject=sujet, html=corps)
    print(f"envoi={ok} statut={analyse['statut']} modele=v{modele.get('version')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="affiche sans envoyer")
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
