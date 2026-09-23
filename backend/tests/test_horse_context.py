"""horse_context — audit 2026-09-23, section P0 « Les données de forme et
d'équipement ne parviennent presque pas directement au choix du ticket ».

Vérifie : (1) un signal absent est marqué indisponible, jamais rempli par un
défaut neutre silencieux ; (2) le score de profil ignore les catégories
indisponibles au lieu de les compter comme 0 ; (3) les clés connues mortes ou
race-wide en production (opposition_quality, terrain_code) n'entrent jamais
dans le score numérique ; (4) l'annotation des candidats est additive et ne
modifie aucune clé existante ; (5) le branchement dans `generer_plan` reste un
no-op strict quand `horse_contexts` n'est pas fourni (tout appelant existant).
"""
from datetime import datetime, timedelta, timezone

from ml import horse_context as hc
from services import mise_calculator as mc


def test_feats_vide_tout_indisponible():
    ctx = hc.build_horse_context({})
    assert ctx["profil_score"] is None
    assert ctx["qualite_donnee"] == 0.0
    for cat, data in ctx["signaux"].items():
        assert data["disponible"] is False, cat
        assert data["motif_indisponible"]


def test_signal_absent_jamais_traite_comme_neutre():
    """Une seule catégorie dispo (forme) : la moyenne ne doit PAS être diluée par
    des zéros silencieux pour les 4 autres catégories absentes."""
    feats = {"recent_win_rate": 0.8, "forme_tendance": 1.0}   # forme = +1.0 max
    ctx = hc.build_horse_context(feats)
    assert ctx["signaux"]["forme_recente"]["disponible"] is True
    for cat in ("terrain_distance", "jockey_driver", "cote_enjeux", "presse"):
        assert ctx["signaux"][cat]["disponible"] is False
    # Si les catégories absentes comptaient comme 0, profil_score serait ~0.2
    # (1.0 / 5). Comme elles sont exclues, il doit rester proche de +1.0.
    assert ctx["profil_score"] > 0.9
    assert ctx["qualite_donnee"] == 1 / 5


def test_opposition_quality_et_terrain_code_exclus_du_score():
    """opposition_quality (mort à son repli 0.5 sur 96,8% des vecteurs en prod)
    et terrain_code (race-wide, ne différencie pas deux chevaux de la même
    course) ne doivent influencer aucune catégorie scorée."""
    base = {"recent_win_rate": 0.0, "forme_tendance": 0.0}
    ctx_sans = hc.build_horse_context(base)
    ctx_avec = hc.build_horse_context({**base, "opposition_quality": 0.99, "terrain_code": 2})
    assert ctx_sans["profil_score"] == ctx_avec["profil_score"]


def test_ferrure_rapportee_mais_non_ponderee():
    """Cf. l'audit : le premier déferrage n'a pas de direction causale établie
    (3,45% vs 4,15% de victoires chez les grosses cotes) → signalé, jamais
    utilisé comme + ou - dans le score numérique."""
    base = {"recent_win_rate": 0.5, "forme_tendance": 0.0}
    ctx_sans = hc.build_horse_context(base)
    ctx_avec = hc.build_horse_context({**base, "premier_deferre": 1.0, "deferre_code": 2})
    assert ctx_sans["profil_score"] == ctx_avec["profil_score"]
    assert ctx_avec["ferrure"]["disponible"] is True
    assert ctx_avec["ferrure"]["sous_score"] is None


def test_presse_indisponible_si_zero_expert():
    ctx = hc.build_horse_context({"nb_experts_presse": 0, "presse_score_borda": 0.9})
    assert ctx["signaux"]["presse"]["disponible"] is False


def test_perime_si_features_anciennes():
    now = datetime(2026, 9, 23, tzinfo=timezone.utc)
    vieux = now - timedelta(days=3)
    ctx = hc.build_horse_context({"recent_win_rate": 0.2}, computed_at=vieux, now=now)
    assert ctx["perime"] is True
    assert ctx["age_minutes"] == 3 * 24 * 60


def test_build_horse_contexts_map_numero_sans_features():
    rows = [(1, {"recent_win_rate": 0.5}, None), (2, None, None)]
    m = hc.build_horse_contexts_map(rows)
    assert set(m) == {1, 2}
    assert m[2]["profil_score"] is None


def test_annotate_candidates_additif_et_traceable():
    cands = [{
        "niveau": "securite", "type_pari": "Simple Gagnant",
        "chevaux": [{"numero": 1, "nom": "A", "cote": 3.0}],
        "proba_gain": 0.4, "rapport_estime": 3.0, "ev": 0.1, "edge": 0.05,
        "texte_explication": "x",
    }]
    horse_contexts = {
        1: hc.build_horse_context({"recent_win_rate": 0.8, "forme_tendance": 1.0}),
        2: hc.build_horse_context({"recent_win_rate": 0.8, "forme_tendance": 1.0}),
    }
    preds = [{"numero": 1}, {"numero": 2}]
    avant = dict(cands[0])
    hc.annotate_candidates_with_traceability(cands, horse_contexts, preds)
    # Toutes les clés d'origine restent intactes.
    for k, v in avant.items():
        assert cands[0][k] == v
    ctxt = cands[0]["contexte_traceabilite"]
    assert ctxt["chevaux"][0]["numero"] == 1
    assert ctxt["chevaux"][0]["contributions"]
    # Le n°2 a le même profil que le n°1 (retenu) → pas d'écart notable, donc
    # pas listé comme "écarté à profil supérieur".
    assert ctxt["ecartes_a_profil_superieur"] == []


def test_annotate_signale_cheval_ecarte_a_profil_superieur():
    cands = [{
        "niveau": "securite", "type_pari": "Simple Gagnant",
        "chevaux": [{"numero": 1, "nom": "A", "cote": 3.0}],
        "proba_gain": 0.4, "rapport_estime": 3.0, "ev": 0.1, "edge": 0.05,
        "texte_explication": "x",
    }]
    horse_contexts = {
        1: hc.build_horse_context({"recent_win_rate": 0.0, "forme_tendance": -1.0}),
        2: hc.build_horse_context({"recent_win_rate": 0.8, "forme_tendance": 1.0}),
    }
    preds = [{"numero": 1}, {"numero": 2}]
    hc.annotate_candidates_with_traceability(cands, horse_contexts, preds)
    ecartes = cands[0]["contexte_traceabilite"]["ecartes_a_profil_superieur"]
    assert any(e["numero"] == 2 for e in ecartes)


def test_generer_plan_sans_horse_contexts_est_inchange():
    """Aucun appelant existant ne passe `horse_contexts` : le plan ne doit
    contenir aucun `contexte_traceabilite` (None partout), comportement
    strictement identique à avant ce correctif."""
    preds = [
        {"numero": i + 1, "nom_cheval": f"C{i+1}", "cote_pmu": 2.0 + i * 1.3,
         "proba_top1": max(0.3 - i * 0.02, 0.01), "proba_top3": max(0.6 - i * 0.03, 0.02),
         "non_partant": False}
        for i in range(10)
    ]
    info = {"nb_partants": 10, "est_simple_gagnant": True, "est_simple_place": True,
            "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True}
    plan = mc.generer_plan(10, "equilibre", preds, info, respect_montant=True)
    for niv in plan.niveaux:
        for p in niv.paris:
            assert p.contexte_traceabilite is None


def test_generer_plan_avec_horse_contexts_annote_les_tickets():
    preds = [
        {"numero": i + 1, "nom_cheval": f"C{i+1}", "cote_pmu": 2.0 + i * 1.3,
         "proba_top1": max(0.3 - i * 0.02, 0.01), "proba_top3": max(0.6 - i * 0.03, 0.02),
         "non_partant": False}
        for i in range(10)
    ]
    info = {"nb_partants": 10, "est_simple_gagnant": True, "est_simple_place": True,
            "est_couple_gagnant": True, "est_couple_place": True, "est_trio": True}
    horse_contexts = {
        i + 1: hc.build_horse_context({"recent_win_rate": 0.2, "forme_tendance": 0.0})
        for i in range(10)
    }
    plan = mc.generer_plan(10, "equilibre", preds, info, respect_montant=True,
                           horse_contexts=horse_contexts)
    tickets = [p for niv in plan.niveaux for p in niv.paris]
    assert tickets, "le plan doit toujours proposer au moins un pari"
    assert any(p.contexte_traceabilite is not None for p in tickets)
    out = mc.plan_to_dict(plan)
    assert "contexte_traceabilite" in out["niveaux"][0]["paris"][0]
