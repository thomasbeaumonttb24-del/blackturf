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
