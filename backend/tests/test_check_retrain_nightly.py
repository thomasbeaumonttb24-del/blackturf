"""
Tests du rapport quotidien de retrain (audit 2026-08-16).

Ce script existe parce que le modèle est resté gelé 48 jours sans que personne
ne le sache : l'échec du retrain était silencieux. Le point critique est donc
qu'il ne se trompe JAMAIS de verdict — un faux « tout va bien » recréerait
exactement le silence qu'il est censé briser.
"""
import sys
import types

import pytest


@pytest.fixture
def mod(monkeypatch):
    """Importe le script en neutralisant les dépendances lourdes."""
    if "camoufox" not in sys.modules:  # cohérence avec les autres tests scraper
        fake = types.ModuleType("camoufox")
        fake.sync_api = types.ModuleType("camoufox.sync_api")
        monkeypatch.setitem(sys.modules, "camoufox", fake)
    import scripts.check_retrain_nightly as m
    return m


# ── Verdicts ────────────────────────────────────────────────────────────────

def test_oom_detecte(mod):
    logs = ("2026-08-17 02:00:03 pipeline.nightly_retrain.start\n"
            "02:01:46 Moving job to FailedJobRegistry (Work-horse terminated "
            "unexpectedly; waitpid returned 9 (signal 9); )")
    assert mod._analyser_logs(logs)["statut"] == "oom"


def test_promotion_detectee(mod):
    logs = ("pipeline.nightly_retrain.start\n"
            "pipeline.h2h.measured auc_challenger=0.71 auc_champion=0.69 delta=0.02\n"
            "pipeline.retrain.deployed version=504 reason=better_h2h")
    assert mod._analyser_logs(logs)["statut"] == "promu"


def test_rejet_detecte(mod):
    logs = ("pipeline.nightly_retrain.start\n"
            "pipeline.retrain.rollback new_wf_auc=0.794 reason=worse_h2h")
    assert mod._analyser_logs(logs)["statut"] == "rejete"


def test_job_jamais_demarre(mod):
    """Cas le plus insidieux : rien dans les logs = le scheduler n'a pas tiré.
    Ne doit SURTOUT pas être interprété comme « tout va bien »."""
    assert mod._analyser_logs("des logs sans rapport avec le retrain")["statut"] == "absent"


def test_demarre_mais_sans_conclusion(mod):
    """Démarré, ni promu, ni rejeté, ni OOM → anomalie, pas un succès."""
    assert mod._analyser_logs("pipeline.nightly_retrain.start")["statut"] == "incomplet"


def test_logs_indisponibles(mod):
    assert mod._analyser_logs("__LOGS_INDISPONIBLES__ docker absent")["statut"] == "inconnu"


def test_oom_prime_sur_le_reste(mod):
    """Un OOM après un rollback de la veille dans la même fenêtre : l'OOM est le
    problème à signaler, il ne doit pas être masqué."""
    logs = ("pipeline.retrain.rollback reason=worse_h2h\n"
            "pipeline.nightly_retrain.start\n"
            "waitpid returned 9 (signal 9)")
    assert mod._analyser_logs(logs)["statut"] == "oom"


def test_memoryerror_compte_comme_oom(mod):
    logs = "pipeline.nightly_retrain.start\nMemoryError: unable to allocate array"
    assert mod._analyser_logs(logs)["statut"] == "oom"


# ── Couverture des verdicts / rendu ─────────────────────────────────────────

def test_chaque_statut_a_un_verdict_actionnable(mod):
    """Tout statut doit produire une action concrète — un rapport sans action à
    faire ne sert à rien au réveil."""
    for statut in ("promu", "rejete", "oom", "incomplet", "absent", "inconnu"):
        icone, titre, action = mod.VERDICTS[statut]
        assert icone and titre and action
        assert len(action) > 30, f"action trop vague pour {statut}"


def test_statuts_analyses_tous_couverts(mod):
    """Aucun statut renvoyé par l'analyse ne doit manquer dans VERDICTS
    (sinon KeyError au petit matin, et aucun e-mail)."""
    cas = {
        "": "absent",
        "pipeline.nightly_retrain.start": "incomplet",
        "signal 9": "oom",
        "pipeline.retrain.deployed": "promu",
        "pipeline.retrain.rollback": "rejete",
        "__LOGS_INDISPONIBLES__ x": "inconnu",
    }
    for logs, attendu in cas.items():
        statut = mod._analyser_logs(logs)["statut"]
        assert statut == attendu
        assert statut in mod.VERDICTS


def test_html_signale_un_modele_fige(mod):
    """Le symptôme central de l'incident : un modèle qui ne bouge plus. Le
    rapport doit le rendre visible, pas le noyer."""
    html = mod._html(mod.VERDICTS["rejete"],
                     {"version": 503, "cree_le": "29/06/2026", "age_jours": 48,
                      "wf_auc": 0.8104, "courses_24h": 47},
                     ["pipeline.retrain.rollback reason=worse_h2h"])
    assert "48 jour(s)" in html
    assert "figé depuis longtemps" in html
    assert "v503" in html


def test_html_ne_signale_pas_un_modele_recent(mod):
    html = mod._html(mod.VERDICTS["promu"],
                     {"version": 504, "cree_le": "17/08/2026", "age_jours": 0,
                      "wf_auc": 0.81, "courses_24h": 47},
                     ["pipeline.retrain.deployed version=504"])
    assert "figé depuis longtemps" not in html


def test_html_supporte_absence_de_modele(mod):
    html = mod._html(mod.VERDICTS["absent"], {"version": None}, [])
    assert "Aucun modèle actif" in html


def test_html_echappe_le_contenu_des_logs(mod):
    """Les logs finissent dans du HTML : pas d'injection de balises."""
    html = mod._html(mod.VERDICTS["oom"],
                     {"version": 503, "cree_le": "29/06/2026", "age_jours": 48,
                      "wf_auc": None, "courses_24h": 0},
                     ["<script>alert(1)</script>"])
    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;" in html


# ── Nuit du 19→20/08/2026 : v511 déployé à 02:02:38, worker tué à 02:04:11 ──
# Le mail annonçait « le retrain a été tué par manque de mémoire » et « le modèle
# ne peut pas progresser », alors que le nouveau modèle était en production : le
# verdict OOM primait inconditionnellement sur la promotion.

LOGS_PROMU_PUIS_OOM = """
2026-08-20 02:00:03 [info] pipeline.nightly_retrain.start
2026-08-20 02:00:14 [info] pipeline.rss stage=nightly.dataset_fetched rss_mb=2410.5
2026-08-20 02:02:38 [info] pipeline.retrain.deployed version=511 wf_auc=0.75
02:04:11 Moving job to FailedJobRegistry (Work-horse terminated unexpectedly; waitpid returned 9 (signal 9); )
"""


def test_deploiement_suivi_dun_oom_nest_pas_un_echec_de_retrain(mod):
    """Un OOM APRÈS la promotion ne doit pas être rapporté comme « pas de modèle ».

    Le modèle est en production ; seules les analyses post-retrain ont sauté.
    Confondre les deux envoie le diagnostic dans le mur : on cherche à réduire la
    fenêtre d'entraînement alors que l'entraînement, lui, a parfaitement abouti.
    """
    analyse = mod._analyser_logs(LOGS_PROMU_PUIS_OOM)
    assert analyse["statut"] == "promu_puis_oom"
    assert analyse["statut"] in mod.VERDICTS


def test_oom_sans_deploiement_reste_un_oom(mod):
    logs = LOGS_PROMU_PUIS_OOM.replace(
        "pipeline.retrain.deployed version=511 wf_auc=0.75",
        "pipeline.retrain.dataset_ready n=41893")
    assert mod._analyser_logs(logs)["statut"] == "oom"


def test_pic_rss_extrait_des_logs(mod):
    """Sans pic mémoire tracé, un signal 9 nu ne dit pas si le retrain avait
    débordé ou s'il a été désigné victime d'une pression venue d'ailleurs."""
    assert mod._analyser_logs(LOGS_PROMU_PUIS_OOM)["rss_pic_mb"] == 2410.5


def test_pic_rss_absent_vaut_zero(mod):
    logs = "2026-08-20 02:00:03 [info] pipeline.nightly_retrain.start"
    assert mod._analyser_logs(logs)["rss_pic_mb"] == 0.0


# ── « Aucun retrain » alors qu'un modèle neuf est actif ─────────────────────
# `docker logs` ne remonte pas au-delà de l'instance courante du conteneur : un
# déploiement entre le retrain et le rapport de 05:00 efface les traces. Le
# rapport annonçait alors « aucun retrain n'a démarré cette nuit » avec un
# modèle créé le jour même en base — une alerte qui contredit l'état réel.

def test_promotion_en_base_prime_sur_des_logs_absents(mod):
    assert mod._promu_recemment({"version": 513, "age_jours": 0}) is True


def test_modele_fige_depuis_plusieurs_jours_reste_une_vraie_alerte(mod):
    """Le cas que ce rapport existe pour attraper : 48 jours sans retrain."""
    assert mod._promu_recemment({"version": 470, "age_jours": 48}) is False


def test_aucun_modele_en_base_nest_pas_une_promotion(mod):
    assert mod._promu_recemment({"version": None}) is False


# ── Cliquet anti-dérive (2026-09-03) ────────────────────────────────────────
# Trois états que le rapport doit distinguer. Les confondre ferait mentir la
# seule ligne qui dit si la protection est active — exactement le silence que ce
# script existe pour briser.

def test_cliquet_etat_illisible_ne_dit_pas_zero(mod):
    """Dette absente = on ne SAIT pas. Jamais « aucune dérive »."""
    html = mod._bloc_cliquet({"version": 527, "dette": None})
    assert "illisible" in html
    assert "0,0000" not in html


def test_cliquet_en_place_sans_promotion(mod):
    """Table vide : le cliquet EST en place, il n'a simplement rien à raconter.

    Premier état après la migration. Le confondre avec « pas encore en place »
    faisait sous-déclarer au rapport sa propre protection.
    """
    html = mod._bloc_cliquet({"version": 527, "dette": 0.0, "dette_depuis": None})
    assert "0,0000" in html
    assert "aucune promotion" in html
    assert "illisible" not in html


def test_cliquet_modele_actif_au_record(mod):
    html = mod._bloc_cliquet({"version": 528, "dette": 0.0, "dette_depuis": 528})
    assert "EST le meilleur niveau" in html
    assert "v528" in html


def test_cliquet_dette_nomme_le_record_a_combler(mod):
    html = mod._bloc_cliquet({"version": 529, "dette": -0.0031, "dette_depuis": 525})
    assert "-0.0031" in html
    assert "v525" in html
    assert "#dc2626" in html, "une dette doit se voir en rouge"


def test_cliquet_muet_sans_modele(mod):
    assert mod._bloc_cliquet({"version": None}) == ""


def test_tendance_ne_promet_plus_la_derive_indefinie(mod):
    """La phrase décrivait le défaut que le cliquet corrige.

    La laisser en l'état ferait mentir le rapport dans l'autre sens : il
    annoncerait chaque matin qu'une régression s'accumule alors que le gate
    l'interdit désormais.
    """
    html = mod._bloc_tendance({
        "wf_auc": 0.7869, "wf_vs_prec": -0.0001, "prec_version": 526,
        "rank_delta_market": 0.0188, "delta_vs_prec": -0.0002,
        "wf_record": 0.7888, "wf_record_version": 521, "wf_vs_record": -0.0019,
        "delta_record": 0.0201, "delta_record_version": 525,
        "delta_vs_record": -0.0013,
    })
    assert "sous son record" in html, "l'écart au record doit rester signalé"
    assert "jamais au meilleur" not in html
    assert "cliquet" in html


# ── Le verdict vient de la BASE, pas des logs (2026-09-03) ──────────────────
# Panne du 03/09/2026 : lancé depuis un conteneur, le script tombait sur
# « [Errno 2] No such file or directory: 'docker' », concluait « ❓ Impossible de
# lire les logs du worker » et ne disait PLUS RIEN du retrain — alors que la base
# savait qu'il avait tourné à 02:19 et rejeté son challenger. Une panne de
# plomberie déguisée en panne d'apprentissage : le silence de l'audit 2026-08-16
# revenait par la fenêtre.

from datetime import datetime, timedelta, timezone


def _db(**kw):
    """État base par défaut : retrain vu, récent, terminé."""
    base = {"lisible": True, "vu": True, "recent": True, "statut_etape": "ok",
            "detail": None, "issue": None, "raison": None, "erreur": None,
            "attempt_at": datetime.now(timezone.utc) - timedelta(hours=3)}
    base.update(kw)
    return base


LOGS_ABSENTS = {"statut": "inconnu", "disponible": False, "oom": False,
                "lignes": [], "detail": "__LOGS_INDISPONIBLES__ docker introuvable"}


def test_sans_logs_le_verdict_vient_de_la_base(mod):
    """LA régression du 03/09 : le rejet était en base, le rapport ne le disait pas."""
    assert mod._verdict(_db(issue="rejete", raison="cliquet"), LOGS_ABSENTS,
                        {"version": 527, "age_jours": 2}) == "rejete"


def test_sans_logs_une_promotion_reste_une_promotion(mod):
    assert mod._verdict(_db(issue="promu"), LOGS_ABSENTS,
                        {"version": 528, "age_jours": 0}) == "promu"


def test_sans_logs_le_gel_du_modele_reste_une_alerte_rouge(mod):
    """Le cas que ce rapport existe pour attraper ne doit JAMAIS être adouci en
    « ❓ » sous prétexte que les logs manquent : la base prouve l'absence."""
    statut = mod._verdict(_db(vu=False), LOGS_ABSENTS,
                          {"version": 470, "age_jours": 48})
    assert statut == "absent"
    assert mod.VERDICTS[statut][0] == "🔴"


def test_une_tentative_hors_fenetre_vaut_absence(mod):
    """Le retrain d'avant-hier ne prouve rien sur cette nuit."""
    assert mod._verdict(_db(recent=False), LOGS_ABSENTS,
                        {"version": 470, "age_jours": 48}) == "absent"


def test_demarrage_sans_issue_est_une_interruption_pas_une_absence(mod):
    """Trace de départ + aucune issue = le processus a disparu en vol.

    Confondre avec « le scheduler n'a pas tiré » envoie chercher un scheduler
    qui va très bien, pendant que la vraie cause est la mémoire.
    """
    statut = mod._verdict(_db(statut_etape="en_cours"), LOGS_ABSENTS, {"version": 527})
    assert statut == "interrompu"
    assert mod.VERDICTS[statut][0] == "🔴"


def test_interruption_confirmee_par_les_logs_est_nommee_oom(mod):
    logs = {"statut": "oom", "disponible": True, "oom": True, "lignes": [], "detail": ""}
    assert mod._verdict(_db(statut_etape="en_cours"), logs, {"version": 527}) == "oom"


def test_promotion_puis_oom_survit_a_la_bascule_sur_la_base(mod):
    """Nuit du 19→20/08 : v511 déployé, worker tué 93 s après. Le modèle EST en
    production ; seules les analyses d'après ont sauté."""
    logs = {"statut": "promu_puis_oom", "disponible": True, "oom": True,
            "lignes": [], "detail": ""}
    assert mod._verdict(_db(issue="promu"), logs,
                        {"version": 511, "age_jours": 0}) == "promu_puis_oom"


def test_donnees_insuffisantes_ne_se_lit_pas_comme_un_rejet(mod):
    """Le problème est alors en AMONT (features, règlement), pas dans le modèle."""
    statut = mod._verdict(_db(issue="insuffisant"), LOGS_ABSENTS, {"version": 527})
    assert statut == "insuffisant"
    assert "amont" in mod.VERDICTS[statut][2]


def test_etape_en_echec_est_signalee(mod):
    assert mod._verdict(_db(statut_etape="echec", erreur="MemoryError"),
                        LOGS_ABSENTS, {"version": 527}) == "incomplet"


def test_worker_ancien_sans_issue_deduit_le_verdict_du_modele(mod):
    """Compatibilité : tant qu'un worker antérieur au 03/09 tourne, l'issue n'est
    pas en base. Un retrain terminé SANS nouveau modèle est un rejet."""
    assert mod._verdict(_db(), LOGS_ABSENTS, {"version": 527, "age_jours": 2}) == "rejete"
    assert mod._verdict(_db(), LOGS_ABSENTS, {"version": 528, "age_jours": 0}) == "promu"


def test_base_illisible_retombe_sur_les_logs(mod):
    logs = {"statut": "promu", "disponible": True, "oom": False, "lignes": [], "detail": ""}
    assert mod._verdict({"lisible": False}, logs, {"version": 528, "age_jours": 0}) == "promu"


def test_les_deux_sources_muettes_donnent_indeterminable(mod):
    """Seul cas légitime du « ❓ » : c'est la SUPERVISION qui est en panne."""
    statut = mod._verdict({"lisible": False}, LOGS_ABSENTS, {"version": 527})
    assert statut == "inconnu"
    assert "supervision" in mod.VERDICTS[statut][2]


def test_base_illisible_et_logs_effaces_ne_crient_pas_au_loup(mod):
    """`docker logs` ne survit pas à un déploiement : un modèle promu du jour
    prime sur des logs vides."""
    logs = {"statut": "absent", "disponible": True, "oom": False, "lignes": [], "detail": ""}
    assert mod._verdict({"lisible": False}, logs,
                        {"version": 528, "age_jours": 0}) == "promu_logs_absents"


def test_tous_les_verdicts_produits_existent(mod):
    """Un statut absent de VERDICTS = KeyError au petit matin, et aucun e-mail."""
    cas = [
        (_db(issue="promu"), LOGS_ABSENTS), (_db(issue="rejete"), LOGS_ABSENTS),
        (_db(issue="insuffisant"), LOGS_ABSENTS), (_db(statut_etape="en_cours"), LOGS_ABSENTS),
        (_db(statut_etape="echec"), LOGS_ABSENTS), (_db(vu=False), LOGS_ABSENTS),
        (_db(), LOGS_ABSENTS), ({"lisible": False}, LOGS_ABSENTS),
    ]
    for etat_db, logs in cas:
        assert mod._verdict(etat_db, logs, {"version": 527, "age_jours": 2}) in mod.VERDICTS


def test_chaque_verdict_declare_reste_actionnable(mod):
    """Garde-fou étendu à TOUS les verdicts, pas à une liste écrite à la main :
    un statut ajouté sans action à faire ne sert à rien au réveil."""
    for statut, (icone, titre, action) in mod.VERDICTS.items():
        assert icone and titre, statut
        assert len(action) > 30, f"action trop vague pour {statut}"


# ── La plomberie se dit, elle ne prend plus toute la place ──────────────────

def test_logs_illisibles_dans_un_conteneur_donnent_un_diagnostic_exact(mod, monkeypatch):
    """« [Errno 2] No such file or directory: 'docker' » envoyait chercher des
    droits inexistants : le binaire n'a jamais été dans l'image."""
    monkeypatch.delenv("BT_WORKER_LOGS_FILE", raising=False)
    monkeypatch.setattr(mod, "_dans_un_conteneur", lambda: True)
    msg = mod._worker_logs()
    assert msg.startswith("__LOGS_INDISPONIBLES__")
    assert "check_retrain_cron.sh" in msg


def test_le_bloc_source_nomme_la_base_et_signale_la_plomberie(mod):
    html = mod._bloc_source(_db(issue="rejete", raison="cliquet"), LOGS_ABSENTS)
    assert "learning_step_runs" in html
    assert "rejeté" in html
    assert "cliquet" in html
    assert "Entretien" in html, "l'indisponibilité des logs doit rester visible"
    assert "ne dépend pas d'eux" in html


def test_le_bloc_source_ne_parle_pas_de_plomberie_quand_tout_va_bien(mod):
    logs = {"statut": "rejete", "disponible": True, "oom": False, "lignes": [], "detail": ""}
    html = mod._bloc_source(_db(issue="rejete"), logs)
    assert "Entretien" not in html


def test_le_bloc_source_echappe_le_message_derreur(mod):
    logs = dict(LOGS_ABSENTS, detail="__LOGS_INDISPONIBLES__ <script>alert(1)</script>")
    html = mod._bloc_source(_db(), logs)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html


# ── « En cours » n'est pas « mort » ─────────────────────────────────────────
# Le rapport tourne à 05:00 UTC, le retrain démarre à 02:00 : une étape encore
# `en_cours` trois heures plus tard est morte (la file RQ tue le job à une
# heure). Mais lancé à la main juste après 02:00, le même état signifie
# simplement « ça travaille ». Rouge dans ce cas, c'est une alerte menteuse de
# plus — et on apprend vite à ne plus les lire.

def test_un_retrain_encore_jeune_nest_pas_declare_mort(mod):
    statut = mod._verdict(
        _db(statut_etape="en_cours", demarre_depuis_trop_longtemps=False),
        LOGS_ABSENTS, {"version": 527})
    assert statut == "en_cours"
    assert mod.VERDICTS[statut][0] != "🔴"


def test_un_retrain_en_cours_depuis_trop_longtemps_est_une_panne(mod):
    assert mod._verdict(
        _db(statut_etape="en_cours", demarre_depuis_trop_longtemps=True),
        LOGS_ABSENTS, {"version": 527}) == "interrompu"


def test_le_seuil_reste_sous_le_plafond_rq(mod):
    """La file `ml` tue le job à 3 600 s : au-delà, « en cours » est un mensonge."""
    assert 60 <= mod.EN_COURS_TROP_LONG_MIN <= 120


def test_un_oom_visible_prime_sur_le_delai(mod):
    """Un signal 9 dans les logs n'attend pas 90 minutes pour être un OOM."""
    logs = {"statut": "oom", "disponible": True, "oom": True, "lignes": [], "detail": ""}
    assert mod._verdict(
        _db(statut_etape="en_cours", demarre_depuis_trop_longtemps=False),
        logs, {"version": 527}) == "oom"


# ── Lecture réelle de l'état persistant ─────────────────────────────────────
# `_verdict` est pur, mais il ne vaut que ce que vaut ce qu'on lui donne. Ces
# tests-ci exercent la lecture elle-même, sur une vraie base.

def _branche_session(mod, monkeypatch, db):
    class _Ctx:
        async def __aenter__(self):
            return db

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(mod, "AsyncSessionLocal", lambda: _Ctx())


@pytest.mark.asyncio
async def test_etat_retrain_lit_lissue_ecrite_par_le_pipeline(mod, monkeypatch, db):
    from ml import learning_steps as ls

    _branche_session(mod, monkeypatch, db)
    await ls.enregistrer_etape(db, "retrain", statut="ok",
                               detail={"issue": "rejete", "raison": "cliquet"})
    await db.commit()

    etat = await mod._etat_retrain_db()
    assert etat["lisible"] and etat["vu"] and etat["recent"]
    assert etat["issue"] == "rejete"
    assert etat["raison"] == "cliquet"


@pytest.mark.asyncio
async def test_un_horodatage_naif_ne_fait_pas_planter_le_rapport(mod, monkeypatch, db):
    """SQLite rend des datetimes SANS fuseau, PostgreSQL avec.

    Comparer les deux lève un `TypeError` — et le rapport ne partirait pas du
    tout, ce qui est la pire des pannes pour un outil dont le seul rôle est de
    rompre le silence.
    """
    from sqlalchemy import text

    from ml import learning_steps as ls

    _branche_session(mod, monkeypatch, db)
    await ls.enregistrer_etape(db, "retrain", statut="ok")
    await db.execute(text("UPDATE learning_step_runs "
                          "SET last_attempt_at = '2026-09-03 02:00:00' "
                          "WHERE step = 'retrain'"))
    await db.commit()

    etat = await mod._etat_retrain_db()
    assert etat["lisible"] is True
    assert etat["attempt_at"].tzinfo is not None


@pytest.mark.asyncio
async def test_aucune_ligne_de_retrain_se_lit_comme_une_absence(mod, monkeypatch, db):
    from ml import learning_steps as ls

    _branche_session(mod, monkeypatch, db)
    await ls.ensure_table(db)
    await db.commit()

    etat = await mod._etat_retrain_db()
    assert etat == {"lisible": True, "vu": False, "detail": None}
    assert mod._verdict(etat, LOGS_ABSENTS, {"version": 470, "age_jours": 48}) == "absent"


@pytest.mark.asyncio
async def test_une_base_injoignable_se_dit_illisible_pas_absente(mod, monkeypatch):
    """Confondre « je ne sais pas » avec « rien n'a tourné » ferait crier au loup
    chaque fois que la base tousse."""
    class _Casse:
        async def __aenter__(self):
            raise RuntimeError("connection refused")

        async def __aexit__(self, *_a):
            return False

    monkeypatch.setattr(mod, "AsyncSessionLocal", lambda: _Casse())
    etat = await mod._etat_retrain_db()
    assert etat["lisible"] is False


@pytest.mark.asyncio
async def test_le_rapport_journalise_son_propre_passage(mod, monkeypatch, db):
    """Sans cette ligne, rien ne surveille le surveillant : le filet du scheduler
    n'a aucun moyen de savoir que le cron s'est tu."""
    from ml import learning_steps as ls

    _branche_session(mod, monkeypatch, db)
    await mod._journaliser_passage("rejete", envoi_ok=True, erreur=None)

    run = await ls.dernier_run(db, mod.ETAPE_RAPPORT)
    assert run["last_status"] == "ok"
    assert run["last_success_at"] is not None
    assert run["detail"]["verdict"] == "rejete"


@pytest.mark.asyncio
async def test_un_envoi_rate_ne_compte_pas_comme_un_rapport_envoye(mod, monkeypatch, db):
    """Sinon le filet resterait muet alors que personne n'a rien reçu."""
    from ml import learning_steps as ls

    _branche_session(mod, monkeypatch, db)
    await mod._journaliser_passage("rejete", envoi_ok=False, erreur="Resend 401")

    run = await ls.dernier_run(db, mod.ETAPE_RAPPORT)
    assert run["last_status"] == "echec"
    assert run["last_success_at"] is None
