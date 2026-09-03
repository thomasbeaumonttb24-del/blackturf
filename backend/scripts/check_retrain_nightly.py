"""Vérification quotidienne du retrain nocturne — rapport e-mail actionnable.

Contexte (audit 2026-08-16) : le modèle est resté gelé sur v503 pendant 48 jours
sans que personne ne le sache, parce que l'échec du retrain nocturne était
totalement silencieux — soit OOM-killed (7 nuits sur 14 en août), soit rejeté
par un gate de promotion cassé. Ce script existe pour que ce silence ne se
reproduise jamais : chaque matin, un e-mail dit ce qui s'est passé cette nuit.

Lancé par cron sur le VPS (voir scripts/check_retrain_cron.sh), il inspecte
l'état RÉEL et n'invente rien : si une information n'est pas disponible, il le
dit au lieu de supposer.

Le verdict vient de la BASE — `learning_step_runs`, écrit par le retrain
lui-même (ml/learning_steps) — et non des logs du worker. Ceux-ci ne sont qu'un
complément : `docker logs` ne remonte pas au-delà de l'instance courante du
conteneur, disparaît au premier déploiement, et n'existe tout simplement pas
depuis l'intérieur d'un conteneur. Le 03/09/2026, cette dépendance a produit un
rapport « ❓ Impossible de lire les logs du worker » qui ne disait plus rien du
retrain, alors que la base savait qu'il avait tourné et rejeté son challenger :
une panne de plomberie déguisée en panne d'apprentissage. Le silence que ce
script combat revenait par la fenêtre.

Deux canaux le lancent, et l'un rattrape l'autre :
  - le cron de l'HÔTE à 05:00 UTC, seul à pouvoir joindre `docker logs` ;
  - le filet du scheduler à 06:30 UTC (services/jobs.job_filet_rapport_retrain),
    qui n'envoie que si aucun rapport n'est parti depuis 26 h.

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

# Fenêtre de LECTURE DES LOGS, en heures. Même valeur que le `--since` du wrapper
# cron : 12 h couvre largement le retrain de 02:00 UTC vu depuis 05:00 UTC.
FENETRE_HEURES = 12

# Heure UTC du retrain nocturne (services/jobs.job_retrain_trigger). La fenêtre
# de la BASE est ancrée sur ce créneau, pas sur « il y a 12 heures » : un rapport
# lancé à la main en fin de journée annonçait sinon « 🔴 Aucun retrain n'a
# démarré cette nuit » alors que celui de 02:19 s'était parfaitement déroulé —
# la même alerte menteuse que celle qu'on vient de supprimer, par l'autre bout.
RETRAIN_HEURE_UTC = 2
# Tolérance avant le créneau : le job peut partir avec un peu d'avance selon la
# dérive du scheduler. Une heure suffit et ne mord pas sur la nuit précédente.
TOLERANCE_AVANT_H = 1

# Nom de l'étape sous laquelle le rapport journalise SON PROPRE passage. Le
# rapport est le garde-fou du retrain ; sans cette ligne, rien ne garde le
# garde-fou — le cron a déjà été muet plusieurs semaines faute de `chmod +x`
# (2026-08-19), et personne ne l'a vu puisque l'absence d'e-mail ne fait pas
# de bruit.
ETAPE_RAPPORT = "rapport_retrain"

# Au-delà de ce délai, une étape encore « en_cours » est MORTE, pas lente : la
# file RQ tue le job de retrain à 3 600 s (`default_timeout` de la queue `ml`,
# cf. services/jobs.job_retrain_trigger), et le work-horse tué n'écrit jamais son
# issue. 90 min laisse une demi-heure de marge à ce plafond. En deçà, le rapport
# dit « encore en cours » — annoncer une panne à un retrain qui travaille encore
# serait exactement l'alerte menteuse qu'on cherche à supprimer.
EN_COURS_TROP_LONG_MIN = 90

# Motifs cherchés dans les logs du worker sur la fenêtre de la nuit écoulée.
PATTERNS = (
    "nightly_retrain.start", "retrain.deployed", "retrain.rollback",
    "h2h.measured", "signal 9", "MemoryError",
    # Empreinte mémoire par étape : sans elle, un OOM ne dit pas OÙ ça a débordé.
    "pipeline.rss",
)


def _dans_un_conteneur() -> bool:
    """Sommes-nous DANS un conteneur ? `/.dockerenv` est posé par le runtime."""
    return os.path.exists("/.dockerenv")


def _worker_logs(since_hours: int = FENETRE_HEURES) -> str:
    """Logs du worker sur les N dernières heures. CONFORT, jamais preuve.

    Deux modes, parce que les informations nécessaires ne vivent pas au même
    endroit : la base et la clé Resend sont accessibles depuis le CONTENEUR,
    mais `docker logs` ne l'est que depuis l'HÔTE. Le cron résout ça en
    déversant d'abord les logs dans un fichier qu'il monte dans le conteneur
    (`BT_WORKER_LOGS_FILE`). Sans cette variable, on retombe sur un appel
    docker direct — pratique pour un lancement manuel depuis l'hôte.

    Ces logs n'ARBITRENT plus rien : le verdict vient de la base (cf.
    `_verdict`). Le 03/09/2026, un lancement manuel depuis le conteneur avait
    produit « ❓ Impossible de lire les logs du worker » — le rapport ne disait
    plus rien du retrain alors que la base savait parfaitement qu'il avait
    tourné et rejeté son challenger. Une panne de plomberie ne doit pas
    ressembler à une panne d'apprentissage : c'est le silence de l'audit
    2026-08-16 qui revenait par la fenêtre.
    """
    fichier = os.getenv("BT_WORKER_LOGS_FILE")
    if fichier:
        try:
            with open(fichier, encoding="utf-8", errors="replace") as fh:
                return fh.read()
        except Exception as e:
            return f"__LOGS_INDISPONIBLES__ fichier {fichier}: {e}"
    if _dans_un_conteneur():
        # Diagnostic exact plutôt qu'un « [Errno 2] No such file or directory:
        # 'docker' » qui laisse chercher des droits inexistants : le binaire
        # docker n'a jamais été dans l'image, et il n'a pas à y être.
        return ("__LOGS_INDISPONIBLES__ lancé DANS un conteneur sans "
                "BT_WORKER_LOGS_FILE : `docker` n'existe pas dans l'image. "
                "Utiliser scripts/check_retrain_cron.sh depuis l'hôte, qui "
                "déverse les logs et monte le fichier.")
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
    """Extrait ce qui s'est passé cette nuit. Fonction pure → testable.

    Le `statut` renvoyé ici n'est plus le verdict du rapport : c'est l'AVIS des
    logs, que `_verdict` arbitre avec l'état persistant en base. `disponible` dit
    si cet avis vaut quelque chose, `oom` porte le seul fait que la base ne peut
    pas connaître (un SIGKILL n'écrit rien).
    """
    if logs.startswith("__LOGS_INDISPONIBLES__"):
        return {"statut": "inconnu", "detail": logs, "lignes": [],
                "disponible": False, "oom": False, "rss_pic_mb": 0.0}

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
            "disponible": True, "oom": a_oom,
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
    # Le retrain a été VU démarrer par la base (`learning_step_runs` = en_cours)
    # et n'a jamais écrit son issue : le processus a disparu en cours de route.
    # Sans la trace de démarrage, ce cas était indiscernable de « le scheduler
    # n'a pas tiré » — deux pannes, deux actions opposées.
    "interrompu": ("🔴", "Le retrain a démarré puis a disparu sans conclure",
                   "Le processus a été tué en cours d'exécution — OOM-kill "
                   "(`dmesg -T | grep -i oom` sur le VPS le confirme en une "
                   "commande) ou dépassement du plafond RQ d'une heure. Le job "
                   "est dans la FailedJobRegistry de la file `ml`."),
    # Le retrain vient de démarrer et n'a pas encore conclu : ce n'est PAS une
    # panne. Le dire en rouge ferait chercher une cause à un travail en cours,
    # et c'est ainsi qu'on apprend à ignorer les alertes.
    "en_cours": ("⚠️", "Le retrain tournait encore au moment du rapport",
                 "Aucune action immédiate : l'issue n'était simplement pas encore "
                 "écrite. Relancer scripts/check_retrain_cron.sh dans l'heure pour "
                 "obtenir le verdict ; si l'état reste le même, le job a été tué."),
    "insuffisant": ("🔴", "Le retrain s'est arrêté faute de données d'entraînement",
                    "Moins de 300 lignes exploitables : le problème est en amont "
                    "(features non calculées, ou courses non réglées), pas dans le "
                    "modèle. Vérifier le calcul des features et le règlement des "
                    "courses des dernières 24 h."),
    "inconnu": ("❓", "État du retrain indéterminable",
                "Ni la base ni les logs du worker n'ont pu être lus — c'est la "
                "supervision elle-même qui est en panne, pas forcément le "
                "retrain. Vérifier que la base répond et relancer "
                "scripts/check_retrain_cron.sh depuis l'hôte."),
}


def _debut_fenetre(maintenant: datetime) -> datetime:
    """Début de la nuit dont ce rapport parle. Fonction pure → testable.

    Ancrée sur le créneau du retrain (02:00 UTC) et non sur « maintenant moins
    douze heures » : la question posée est « qu'a fait le retrain de cette
    nuit ? », et sa réponse ne doit pas changer selon l'heure à laquelle on
    ouvre le rapport.
    """
    debut = maintenant.replace(hour=RETRAIN_HEURE_UTC, minute=0, second=0,
                               microsecond=0)
    if debut > maintenant:
        debut -= timedelta(days=1)
    return debut - timedelta(hours=TOLERANCE_AVANT_H)


async def _etat_retrain_db() -> dict:
    """Ce que la BASE sait du retrain de la nuit — la source de vérité.

    `learning_step_runs` porte, pour l'étape `retrain` : l'heure de démarrage
    (écrite AVANT le travail, donc survivante à un OOM-kill), le statut de
    sortie, et depuis le 03/09/2026 l'issue elle-même (promu / rejeté /
    données insuffisantes) avec son motif. Aucune de ces informations ne
    dépend de `docker logs`, qui ne remonte pas au-delà de l'instance courante
    du conteneur et disparaît au premier déploiement.

    `lisible=False` signifie que la base n'a pas répondu — et RIEN d'autre : ne
    jamais confondre « la supervision est aveugle » avec « le retrain n'a pas
    tourné ».
    """
    try:
        from ml.learning_steps import dernier_run
        async with AsyncSessionLocal() as s:
            run = await dernier_run(s, "retrain")
    except Exception as e:
        return {"lisible": False, "erreur": str(e)[:200]}

    if run is None:
        return {"lisible": True, "vu": False, "detail": None}

    attempt = run.get("last_attempt_at")
    if attempt is not None and attempt.tzinfo is None:
        # SQLite (tests) rend des datetimes naïfs ; PostgreSQL non. Comparer un
        # naïf à un conscient lève un TypeError, et le rapport ne partirait pas.
        attempt = attempt.replace(tzinfo=timezone.utc)
    maintenant = datetime.now(timezone.utc)
    recent = attempt is not None and attempt >= _debut_fenetre(maintenant)
    trop_long = (attempt is None
                 or attempt < maintenant - timedelta(minutes=EN_COURS_TROP_LONG_MIN))
    detail = run.get("detail") or None
    return {
        "lisible": True,
        "vu": True,
        "recent": recent,
        "demarre_depuis_trop_longtemps": trop_long,
        "statut_etape": run.get("last_status"),
        "erreur": run.get("last_error"),
        "attempt_at": attempt,
        "detail": detail,
        "issue": (detail or {}).get("issue"),
        "raison": (detail or {}).get("raison"),
    }


def _verdict(db: dict, logs: dict, modele: dict) -> str:
    """Statut final. Fonction PURE → testable sans base ni conteneur.

    Ordre des priorités, et pourquoi :

    1. La BASE d'abord. Elle sait ce que les logs oublient (déploiement,
       rotation) et elle survit à ce qui tue le worker.
    2. Les LOGS ensuite, pour ce que la base ne peut pas savoir : un signal 9
       n'écrit rien nulle part, seul le journal du conteneur le montre.
    3. « Indéterminable » en tout dernier recours — et seulement si les DEUX
       sources se taisent. Le 03/09/2026 le rapport tombait sur ce verdict dès
       que les logs manquaient, en ignorant une base parfaitement lisible :
       une panne de plomberie prenait l'apparence d'une panne d'apprentissage.
    """
    oom = logs.get("oom", False)

    if db.get("lisible") and db.get("vu") and db.get("recent"):
        statut_etape = db.get("statut_etape")
        if statut_etape == "en_cours":
            # Démarrage enregistré, aucune issue. Deux lectures possibles, et
            # c'est l'ÂGE du démarrage qui tranche : en deçà du plafond RQ, le
            # retrain travaille peut-être encore ; au-delà, il est mort sans
            # avoir pu écrire quoi que ce soit.
            if oom:
                return "oom"
            return "interrompu" if db.get("demarre_depuis_trop_longtemps", True) \
                else "en_cours"
        if statut_etape == "echec":
            return "incomplet"
        issue = db.get("issue")
        if issue == "promu":
            return "promu_puis_oom" if oom else "promu"
        if issue == "rejete":
            return "rejete"
        if issue == "insuffisant":
            return "insuffisant"
        # Étape terminée sans issue enregistrée : soit un worker antérieur au
        # 03/09/2026, soit une issue perdue. Les logs tranchent s'ils sont là ;
        # sinon la présence d'un modèle promu sur la fenêtre suffit — un retrain
        # qui se termine sans nouveau modèle EST un rejet.
        if logs.get("statut") in ("promu", "rejete", "oom", "promu_puis_oom"):
            return logs["statut"]
        return "promu" if _promu_recemment(modele) else "rejete"

    if db.get("lisible") and (not db.get("vu") or not db.get("recent")):
        # La base est formelle : aucune tentative sur la fenêtre. C'est LE cas
        # que ce rapport existe pour attraper (48 jours de gel en 2026).
        # Exception : un modèle promu ce jour-ci prouve le contraire ; on ne
        # crie pas au loup contre l'état réel du système.
        if _promu_recemment(modele):
            return "promu_logs_absents"
        return "absent"

    # Base illisible : on retombe sur les logs, tels quels.
    statut = logs.get("statut", "inconnu")
    if statut == "absent" and _promu_recemment(modele):
        return "promu_logs_absents"
    return statut


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
        # ── Cliquet anti-derive (migration 0045) ────────────────────────────
        # La dette est la distance cumulee au meilleur niveau atteint. Elle est la
        # seule facon de voir une derive que le gate accepte nuit apres nuit :
        # chaque nuit prise isolement reste sous la tolerance.
        dette, dette_depuis = None, None
        try:
            _r = (await s.execute(text(
                "SELECT dette, depuis_version FROM retrain_ratchet WHERE id = 1"
            ))).first()
            # TABLE PRESENTE MAIS VIDE = dette nulle, et non « on ne sait
            # pas » : c'est l'etat normal tant qu'aucune promotion n'a suivi la
            # migration. Les confondre affichait « cliquet pas encore en place »
            # sur une prod ou il l'etait — le rapport sous-declarait sa propre
            # protection.
            dette = float(_r[0] or 0.0) if _r is not None else 0.0
            dette_depuis = _r[1] if _r is not None else None
        except Exception:
            # Table absente (avant la migration) : on n'invente pas une dette
            # nulle, qui se lirait « aucune derive » alors qu'on n'en sait rien.
            try:
                await s.rollback()
            except Exception:
                pass

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
        # Deux provenances differentes ne se soustraient pas : l'ecart au
        # predecesseur n'a de sens que si les deux valeurs mesurent le meme objet
        # (cf. `rank_source` dans `_record`). Le walk-forward, lui, reste
        # comparable -- sa definition n'a jamais change.
        prec_comparable = prec is not None and prec.rank_source == mv.rank_source

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

            Comparable = trois conditions, chacune pour une raison distincte.

            - Non synthétique : un modèle de secours n'est pas une référence de
              qualité.
            - Volume du même ordre : le walk-forward est d'autant plus optimiste
              que le jeu est petit.
            - Classement intra-course mesuré (`rank_auc`, depuis le 20/08/2026) :
              c'est ce qui borne le record à la génération de mesure courante. Le
              volume seul ne suffit pas — les modèles de juin, à 145 000 lignes,
              passent le plancher mais affichent un walk-forward de 0,816 sur une
              autre fenêtre et un autre jeu de features. C'est exactement cette
              référence-là (0,8104, juin) qui, prise pour comparable, avait rejeté
              quatorze challengers d'affilée et gelé le modèle 48 jours. Un
              walk-forward sans mesure de classement ne dit d'ailleurs pas si ce
              modèle battait la cote : il ne peut pas servir de record.

            `is_not(None)` est explicite : sous PostgreSQL un `ORDER BY … DESC`
            placerait les NULL en tête.
            """
            meme_source = (ModelVersion.rank_source.is_(None)
                           if mv.rank_source is None
                           else ModelVersion.rank_source == mv.rank_source)
            return (
                select(ModelVersion.version_num, colonne)
                .where(
                    colonne.is_not(None),
                    ModelVersion.est_synthetique.is_(False),
                    ModelVersion.nb_courses_train >= volume_min,
                    ModelVersion.rank_auc.is_not(None),
                    # MEME PROVENANCE de mesure (`rank_source`, migration 0045).
                    # Jusqu'au 2026-09-02 `rank_auc` / `rank_delta_market`
                    # recevaient la mesure du WALK-FORWARD et non celle de
                    # l'ensemble deploye : v527 porte +0,0190 la ou le hold-out du
                    # vrai ensemble donne -0,0472 sur la meme nuit. Sans cette
                    # condition, le premier modele mesure correctement se
                    # comparerait a un record de walk-forward et le rapport
                    # annoncerait chaque matin une chute de 0,066 qui n'a pas eu
                    # lieu -- la meme faute que la reference de juin qui avait gele
                    # le modele 48 jours, a une generation de mesure pres.
                    # NULL ne s'egale pas a NULL en SQL : les versions sans
                    # provenance forment leur propre population.
                    meme_source,
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
            "dette": dette,
            "dette_depuis": dette_depuis,
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
                                    prec.rank_delta_market if prec_comparable else None),
            "rank_source": mv.rank_source,
            "wf_record": round(rec_wf[1], 4) if rec_wf else None,
            "wf_record_version": rec_wf[0] if rec_wf else None,
            "wf_vs_record": _ecart(mv.walk_forward_auc, rec_wf[1] if rec_wf else None),
            "delta_record": round(rec_delta[1], 4) if rec_delta else None,
            "delta_record_version": rec_delta[0] if rec_delta else None,
            "delta_vs_record": _ecart(mv.rank_delta_market,
                                      rec_delta[1] if rec_delta else None),
        }


def _bloc_cliquet(modele: dict) -> str:
    """Etat du cliquet anti-derive. Fonction pure, testable sans base.

    La dette dit ce qu'aucune ligne du jour ne peut dire : de combien le modele
    actif est descendu SOUS le meilleur niveau jamais mesure, en cumulant des
    nuits qui, prises une a une, restaient toutes sous la tolerance.

    TROIS etats distincts, et les confondre ferait mentir le rapport :
      - `dette` absente  : table illisible, on ne SAIT pas. Jamais « 0 ».
      - 0 sans record    : cliquet en place, aucune promotion depuis. Rien n'a
                           encore pu deriver.
      - 0 avec record    : le modele actif EST le meilleur niveau mesure.
    """
    if modele.get("version") is None:
        return ""
    _dette = modele.get("dette")
    if _dette is None:
        return ("<p style='color:#666;font-size:13px;'>Cliquet anti-dérive : "
                "état illisible (table <code>retrain_ratchet</code>).</p>")
    _depuis = modele.get("dette_depuis")
    _rec = f"v{_depuis}" if _depuis is not None else "—"
    if _dette >= 0:
        _dtxt = "0,0000"
        _dcoul = "#16a34a"
        _dexp = ("le modèle actif EST le meilleur niveau mesuré"
                 if _depuis is not None else
                 "aucune promotion depuis la mise en place du cliquet : rien "
                 "n’a encore pu dériver")
    else:
        _dtxt = f"{_dette:+.4f}"
        _dcoul = "#dc2626"
        _dexp = (f"le modèle actif est sous le niveau de {_rec} ; la prochaine "
                 f"promotion doit combler cet écart")
    return f"""
    <h3 style="font-size:14px;margin-top:24px;">Cliquet anti-dérive</h3>
    <table style="border-collapse:collapse;font-size:14px;">
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Dette cumulée</td>
          <td style="color:{_dcoul};font-weight:bold;">{_dtxt}</td></tr>
      <tr><td style="padding:4px 12px 4px 0;color:#666;">Niveau record</td><td>{_rec}</td></tr>
    </table>
    <p style="color:#666;font-size:12px;margin-top:6px;">
      {_dexp}. La promotion nocturne tolère une régression de 0,0020 par nuit ;
      le cliquet lui interdit de s’accumuler, en comparant le challenger à la
      distance au RECORD (dette + écart) et non au seul champion de la veille.
    </p>"""


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
        f"Ces deux écarts portent sur des PROMOTIONS PASSÉES : ils disent d’où "
        f"vient le niveau actuel, pas que la dérive continue. Depuis le cliquet "
        f"(03/09), c’est la dette ci-dessus qui borne la suite — une régression "
        f"ne peut plus s’accumuler nuit après nuit.</p>"
    ) if sous_record else ""
    return f"""
    <h3 style="font-size:14px;margin-top:24px;">Tendance</h3>
    <table style="border-collapse:collapse;font-size:14px;">{corps}</table>{avertissement}"""


def _bloc_apprentissages(etat: dict) -> str:
    """État des ÉTAPES d'apprentissage — celles qui n'existent que derrière le retrain.

    Le rapport savait dire « le retrain a réussi ». Il ne savait pas dire que les
    onze apprentissages qui SUIVENT le retrain dans le même job n'avaient pas
    tourné : le worker OOM-killé le 20/08/2026 l'a été 93 s APRÈS avoir déployé
    v511 avec succès, et le rapport de ce matin-là annonçait donc une nuit
    réussie. C'est cet angle mort que ce bloc ferme.

    On lit l'ÉTAT PERSISTANT (`learning_step_runs`), pas les logs : un journal qui
    ne dit rien ne prouve rien, une date de dernier succès vieille de trois jours
    si — même règle que le verdict de promotion, qui fait déjà primer la base.
    """
    etapes = etat.get("etapes") or []
    if not etapes:
        return ("<h3 style='font-size:14px;margin-top:24px;'>Apprentissages</h3>"
                "<p style='color:#666;font-size:13px;'>Aucune étape journalisée "
                "pour l'instant — le journal se remplit à la première nuit qui suit "
                "le déploiement.</p>")
    perimees = {e["step"] for e in (etat.get("perimees") or [])}
    seuil = etat.get("seuil_heures", 48)
    from html import escape as _esc
    rangs = []
    for e in etapes:
        perimee = e["step"] in perimees
        couleur = "#dc2626" if perimee else ("#16a34a" if e["last_status"] == "ok"
                                             else "#d97706")
        succes = e["last_success_at"]
        succes_txt = succes.strftime("%d/%m %H:%M") if hasattr(succes, "strftime") \
            else (str(succes)[:16] if succes else "jamais")
        detail = ""
        if perimee:
            detail = " ← PÉRIMÉ"
        elif e["last_status"] != "ok" and e.get("last_error"):
            detail = f" — {_esc(str(e['last_error'])[:80])}"
        rangs.append(
            f'<tr><td style="padding:3px 12px 3px 0;color:#666;">{_esc(e["step"])}</td>'
            f'<td style="color:{couleur};">{succes_txt}{detail}</td></tr>')
    entete = ""
    if perimees:
        entete = (f'<div style="background:#fef2f2;border-left:4px solid #dc2626;'
                  f'padding:10px 14px;margin:12px 0;font-size:13px;">'
                  f'<b>{len(perimees)} apprentissage(s) sans succès depuis plus de '
                  f'{seuil} h.</b> Ce qu\'ils produisent (courbes de calibration, '
                  f'poids, gates) décrit un état du monde qui n\'existe plus.</div>')
    return (f"<h3 style='font-size:14px;margin-top:24px;'>Apprentissages "
            f"(dernier succès)</h3>{entete}"
            f"<table style='border-collapse:collapse;font-size:13px;'>"
            f"{''.join(rangs)}</table>")


def _bloc_source(db: dict | None, logs: dict | None) -> str:
    """D'où vient le verdict, et ce qui manquait pour l'établir. Fonction pure.

    Deux choses que le rapport taisait :

    - sur quoi il s'appuie. Un verdict sans provenance ne se vérifie pas.
    - que les logs du worker étaient injoignables. Le 03/09/2026, cette panne de
      plomberie occupait TOUT le rapport (« ❓ Impossible de lire les logs ») et
      effaçait le verdict ; désormais elle se range ici, à sa place : une ligne
      d'entretien, sous un verdict qui, lui, reste établi.
    """
    db = db or {}
    logs = logs or {}
    if not db and not logs:
        return ""

    if db.get("lisible") and db.get("vu") and db.get("recent"):
        issue = db.get("issue")
        raison = db.get("raison")
        quand = db.get("attempt_at")
        quand_txt = quand.strftime("%d/%m %H:%M UTC") if quand else "—"
        detail_txt = {
            "promu": "challenger promu",
            "rejete": "challenger rejeté",
            "insuffisant": "arrêt faute de données",
        }.get(issue, f"issue non enregistrée (statut « {db.get('statut_etape')} »)")
        if raison:
            detail_txt += f" — motif <code>{raison}</code>"
        provenance = (f"base <code>learning_step_runs</code> : démarré {quand_txt}, "
                      f"{detail_txt}")
    elif db.get("lisible"):
        provenance = ("base <code>learning_step_runs</code> : <b>aucune tentative "
                      "de retrain</b> enregistrée sur la fenêtre")
    else:
        provenance = ("base injoignable — verdict établi sur les seuls logs du "
                      "worker")

    bloc = ('<p style="color:#666;font-size:12px;margin:12px 0 0;">'
            f'<b>Source du verdict</b> — {provenance}.</p>')

    if logs.get("disponible") is False:
        raison_logs = (logs.get("detail") or "").replace("__LOGS_INDISPONIBLES__", "").strip()
        from html import escape as _esc
        bloc += (
            '<p style="background:#fff7ed;border-left:4px solid #d97706;'
            'padding:8px 12px;margin:8px 0 0;color:#92400e;font-size:12px;">'
            '<b>Entretien</b> — logs du worker non lus : '
            f'{_esc(raison_logs) or "raison inconnue"}<br>'
            "Le verdict ci-dessus ne dépend pas d'eux ; seuls le détail des "
            "lignes et le pic mémoire manquent.</p>"
        )
    return bloc


def _html(verdict: tuple, modele: dict, lignes: list[str],
          rss_pic_mb: float = 0.0, apprentissages: dict | None = None,
          db: dict | None = None, logs_etat: dict | None = None) -> str:
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
      0,5 = hasard. Mesuré sur l'ensemble RÉELLEMENT déployé, sur son hold-out
      hors-échantillon, chaque course pesant pareil (et non plus sur le XGBoost
      jetable des folds walk-forward). Ne se compare pas à l'AUC poolée ci-dessus.
    </p>"""

    bloc_cliquet = _bloc_cliquet(modele)

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
  {_bloc_source(db, logs_etat)}
  {bloc_modele}
  {bloc_classement}
  {bloc_cliquet}
  {bloc_tendance}
  {_bloc_apprentissages(apprentissages or {})}
  <h3 style="font-size:14px;margin-top:24px;">Extrait des logs</h3>
  {logs}
  <p style="color:#999;font-size:11px;margin-top:24px;">
    Rapport automatique — <code>scripts/check_retrain_nightly.py</code> sur le VPS.
    Existe parce que le modèle est resté gelé 48 jours sans alerte (audit 2026-08-16).
  </p>
</body></html>"""


async def _journaliser_passage(statut: str, envoi_ok: bool, erreur: str | None) -> None:
    """Trace le passage du rapport dans `learning_step_runs`.

    Le rapport surveille le retrain ; cette ligne est ce qui surveille le
    rapport. Elle a un consommateur concret : le filet de sécurité du scheduler
    (`job_filet_rapport_retrain`), qui renvoie le rapport si aucun n'est parti
    depuis plus de 26 h. Sans elle, la panne du cron du 2026-08-19 — un
    `chmod +x` manquant, aucun e-mail pendant des semaines — se reproduirait à
    l'identique, et personne ne remarque l'absence d'un e-mail.

    Ne jamais faire échouer le rapport : il est déjà envoyé quand on écrit ici.
    """
    try:
        from ml.learning_steps import enregistrer_etape
        async with AsyncSessionLocal() as s:
            await enregistrer_etape(
                s, ETAPE_RAPPORT,
                statut="ok" if envoi_ok else "echec",
                erreur=erreur,
                detail={"verdict": statut,
                        "canal": os.getenv("BT_RAPPORT_CANAL", "cron")},
            )
            await s.commit()
    except Exception as e:
        print(f"journalisation du rapport impossible : {e}")


async def main(dry_run: bool = False) -> None:
    logs = _worker_logs()
    analyse = _analyser_logs(logs)
    # L'ÉTAT PERSISTANT d'abord : il survit aux déploiements et aux OOM, les logs
    # du conteneur non. Lu avant tout le reste pour que le verdict ne dépende
    # jamais de la disponibilité de `docker logs`.
    db = await _etat_retrain_db()
    modele = await _etat_modele()
    try:
        from ml.learning_steps import etat_apprentissages
        async with AsyncSessionLocal() as s:
            apprentissages = await etat_apprentissages(s)
    except Exception as e:
        # Le rapport doit partir même si le journal est illisible : mieux vaut un
        # rapport amputé qu'aucun rapport — c'est le silence qu'on combat ici.
        print(f"apprentissages indisponibles : {e}")
        apprentissages = {}

    statut = _verdict(db, analyse, modele)
    verdict = VERDICTS[statut]
    lignes = analyse["lignes"] or ([analyse["detail"]] if analyse["detail"] else [])

    icone, titre, _ = verdict
    sujet = f"{icone} BlackTurf retrain — {titre}"
    corps = _html(verdict, modele, lignes, analyse.get("rss_pic_mb", 0.0),
                  apprentissages=apprentissages, db=db, logs_etat=analyse)

    if dry_run:
        print(f"SUJET : {sujet}")
        print(f"STATUT : {statut}")
        print(f"AVIS LOGS : {analyse['statut']} (disponibles={analyse.get('disponible')})")
        print(f"BASE : {db}")
        print(f"MODELE : {modele}")
        print(f"LIGNES : {len(lignes)}")
        print(f"PIC RSS : {analyse.get('rss_pic_mb', 0.0)} Mo")
        _perimees = [e["step"] for e in (apprentissages.get("perimees") or [])]
        print(f"APPRENTISSAGES : {len(apprentissages.get('etapes') or [])} journalisés, "
              f"périmés={_perimees}")
        return

    from services.alerts import send_email
    ok = await send_email(to=DEST, subject=sujet, html=corps)
    await _journaliser_passage(statut, envoi_ok=bool(getattr(ok, "ok", False)),
                               erreur=getattr(ok, "erreur", None))
    print(f"envoi={ok} statut={statut} modele=v{modele.get('version')}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="affiche sans envoyer")
    args = ap.parse_args()
    asyncio.run(main(dry_run=args.dry_run))
