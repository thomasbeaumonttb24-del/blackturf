"""
Tests du dégel de la promotion de modèle (audit 2026-08-16).

Deux bugs cumulés gelaient le modèle actif sur v503 depuis le 29/06 (48 jours,
14 rejets consécutifs) :

  A. `_edge_gate_ok` — le pipeline ne testait que la clé `insufficient`, qui
     n'apparaît qu'en dessous de 500 lignes de dataset. Le vrai signal courant
     est `enough_filt`. En prod : n_filt=25 < min_filt=50 → edge_ok=False PAR
     CONSTRUCTION, lu comme « edge prouvé mauvais » → roi_gate bloquait.

  B. `_should_deploy` — arbitrait sur le walk-forward, qui RÉ-ENTRAÎNE un XGB sur
     des folds du dataset courant : c'est une mesure du DATASET, pas du modèle.
     La référence stockée du champion (0.8104, juin, 151k lignes) n'était jamais
     recalculée et écrasait mécaniquement tout challenger (0.794, août, 168k).
"""
import numpy as np
import pandas as pd
import pytest

from ml.models import temporal_holdout_mask
from ml.pipeline import _edge_gate_ok, _edge_undecidable, _should_deploy


# ── Bug A : edge indécidable ≠ edge mauvais ──────────────────────────────────

def test_edge_indecidable_quand_echantillon_filtre_trop_mince():
    """Le snapshot EXACT de la prod du 2026-08-16."""
    em = {"n_total": 200584, "n_test": 40117, "n_filt": 25, "min_filt": 50,
          "enough_filt": False, "edge_ok": False, "roi_cap": 21.6, "roi_base": -15.1}
    assert _edge_undecidable(em) is True
    assert _edge_gate_ok(em) is True, "un edge indécidable ne doit PAS bloquer"


def test_edge_indecidable_quand_dataset_global_trop_petit():
    em = {"n_total": 120, "insufficient": True}
    assert _edge_undecidable(em) is True
    assert _edge_gate_ok(em) is True


def test_edge_mauvais_avec_echantillon_suffisant_bloque_toujours():
    """Le garde-fou d'origine doit survivre au correctif."""
    em = {"n_filt": 900, "min_filt": 50, "enough_filt": True, "edge_ok": False}
    assert _edge_undecidable(em) is False
    assert _edge_gate_ok(em) is False


def test_edge_bon_avec_echantillon_suffisant():
    em = {"n_filt": 900, "min_filt": 50, "enough_filt": True, "edge_ok": True}
    assert _edge_gate_ok(em) is True


def test_dict_edge_monitor_vide_ne_bloque_pas():
    assert _edge_gate_ok({}) is True


# ── Bug B : le head-to-head arbitre à la place du walk-forward ───────────────

BASE = dict(current_is_synth=False, no_current=False,
            current_unreliable=False, data_jump=False)


def test_h2h_positif_promeut_malgre_un_walk_forward_inferieur():
    """LE cas de la prod : wf 0.794 < 0.8104 (datasets différents = incomparables),
    mais le challenger bat le champion sur le hold-out commun."""
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=+0.012) is True


def test_h2h_negatif_bloque_malgre_un_walk_forward_superieur():
    """Symétrique : un wf flatteur ne doit plus suffire si le modèle perd en réel."""
    assert _should_deploy(0.85, 0.80, **BASE, h2h_delta=-0.03) is False


def test_h2h_egalite_stricte_promeut():
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=0.0) is True


def test_h2h_micro_regression_toleree():
    """±0.002 d'AUC = bruit d'échantillonnage, pas une régression."""
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=-0.001) is True


def test_h2h_regression_franche_bloquee():
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=-0.01) is False


def test_plancher_absolu_prime_sur_un_h2h_positif():
    """Le garde-fou qui a évité un modèle AUC 0.06 en prod reste inconditionnel."""
    assert _should_deploy(0.40, 0.80, **BASE, h2h_delta=+0.20) is False


def test_roi_gate_ne_bloque_pas_un_h2h_positif():
    assert _should_deploy(0.794, 0.8104, **BASE,
                          roi_gate_enabled=True, betting_edge_ok=False,
                          h2h_delta=+0.01) is True


def test_roi_gate_bloque_une_regression_h2h():
    assert _should_deploy(0.794, 0.8104, **BASE,
                          roi_gate_enabled=True, betting_edge_ok=False,
                          h2h_delta=-0.01) is False


def test_remplacement_structurel_prime_sur_un_h2h_negatif():
    """Un actif synthétique doit partir même s'il « gagne » le head-to-head."""
    assert _should_deploy(0.70, 0.99,
                          current_is_synth=True, no_current=False,
                          current_unreliable=False, data_jump=False,
                          h2h_delta=-0.05) is True


def test_sans_h2h_le_comportement_walk_forward_est_inchange():
    """Repli : pas de champion / échantillon trop mince → logique historique."""
    assert _should_deploy(0.82, 0.80, **BASE, h2h_delta=None) is True
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=None) is False
    # tolérance de régression historique 0.005
    assert _should_deploy(0.7970, 0.8000, **BASE, h2h_delta=None) is True


def test_h2h_zero_n_est_pas_confondu_avec_absent():
    """Piège classique : `if h2h_delta:` traiterait 0.0 comme None et repasserait
    sur le walk-forward, qui rejetterait. Doit être `is not None`."""
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=0.0) is True
    assert _should_deploy(0.794, 0.8104, **BASE, h2h_delta=None) is False


# ── Découpage temporel partagé ───────────────────────────────────────────────

def _df(course_ids):
    return pd.DataFrame({"course_id": course_ids, "f1": np.arange(len(course_ids))})


def _set_group_split(monkeypatch, value: bool):
    """FLAGS est un dataclass GELÉ : on remplace l'instance du module, que
    `temporal_holdout_mask` ré-importe à chaque appel."""
    import dataclasses
    from ml import algo_flags
    monkeypatch.setattr(algo_flags, "FLAGS",
                        dataclasses.replace(algo_flags.FLAGS, group_split=value))


def test_holdout_prend_les_courses_les_plus_recentes(monkeypatch):
    _set_group_split(monkeypatch, True)
    # 10 courses × 2 partants, ordre chronologique.
    X = _df([f"C{i}" for i in range(10) for _ in range(2)])

    mask = temporal_holdout_mask(X, frac_train=0.8)

    assert mask.sum() == 4, "20% de 10 courses = 2 courses = 4 partants"
    assert set(X[mask]["course_id"]) == {"C8", "C9"}


def test_holdout_ne_coupe_jamais_une_course_en_deux(monkeypatch):
    """Un cheval de la même course des deux côtés = fuite (audit edge, -52%)."""
    _set_group_split(monkeypatch, True)
    X = _df([f"C{i}" for i in range(20) for _ in range(7)])

    mask = temporal_holdout_mask(X)

    train_c = set(X[~mask]["course_id"])
    hold_c = set(X[mask]["course_id"])
    assert train_c & hold_c == set()


def test_holdout_positionnel_si_flag_off(monkeypatch):
    _set_group_split(monkeypatch, False)
    X = _df([f"C{i}" for i in range(10)])

    mask = temporal_holdout_mask(X, frac_train=0.8)

    assert mask.sum() == 2
    assert mask[-2:].all() and not mask[:-2].any()


def test_holdout_identique_a_celui_de_train(monkeypatch):
    """train() et le pipeline de promotion DOIVENT découper au participant près,
    sinon le champion serait noté sur des lignes vues par le challenger."""
    _set_group_split(monkeypatch, True)
    X = _df([f"C{i}" for i in range(37) for _ in range(np.random.randint(5, 12))])

    m1 = temporal_holdout_mask(X)
    m2 = temporal_holdout_mask(X)

    assert np.array_equal(m1, m2)
    assert 0 < m1.sum() < len(X)


# ── La mesure head-to-head elle-même ─────────────────────────────────────────

class _FakeModel:
    """Prédit une proba d'autant plus juste que `skill` est grand.

    Le bruit est DISPERSÉ à l'intérieur de chaque course, et non croissant sur
    tout le tableau. Avec un bruit monotone, le gagnant — toujours en tête de son
    groupe — restait premier de sa course même à skill=0.30 : les deux modèles
    obtenaient un classement intra-course parfait et ne se départageaient que sur
    l'AUC poolée. C'est précisément le faux ami que le head-to-head a cessé de
    mesurer le 20/08/2026 ; la fixture doit donc discriminer sur l'ORDRE.
    """

    def __init__(self, skill: float):
        self.skill = skill

    def predict_proba(self, X):
        y = X["truth"].to_numpy().astype(float)
        # Bruit déterministe pseudo-dispersé : reproductible sans RNG partagé.
        bruit = ((np.arange(len(X)) * 7919) % 1000) / 1000.0
        return self.skill * y + (1 - self.skill) * bruit


class _FakeSession:
    def __init__(self, course_ids):
        self._rows = [(c,) for c in course_ids]
        self.dernier_cutoff = None

    async def execute(self, _stmt, params=None):
        if params:
            self.dernier_cutoff = params.get("cutoff")
        return self._rows


class _FakeMV:
    def __init__(self, created_at):
        self.created_at = created_at


def _holdout(n_courses=400, first=0):
    """n_courses × 6 partants, 1 gagnant par course."""
    cid, truth = [], []
    for i in range(first, first + n_courses):
        for j in range(6):
            cid.append(f"C{i}")
            truth.append(1 if j == 0 else 0)
    X = pd.DataFrame({"course_id": cid, "truth": truth})
    return X, pd.Series(truth)


@pytest.mark.asyncio
async def test_h2h_mesure_le_delta_sur_le_meme_echantillon(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout(400)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.30)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.95), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res is not None
    assert res["delta"] > 0, "un challenger plus fort doit ressortir positif"
    assert res["auc_challenger"] > res["auc_champion"]
    assert res["n_rows"] == len(X)
    assert res["n_courses"] == 400


@pytest.mark.asyncio
async def test_h2h_delta_negatif_si_le_champion_est_meilleur(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout(400)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.95)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.30), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res["delta"] < 0


@pytest.mark.asyncio
async def test_h2h_restreint_aux_courses_posterieures_au_champion(monkeypatch):
    """Le cœur de l'honnêteté : les courses que le CHAMPION a vues à
    l'entraînement doivent sortir de l'échantillon, sinon il part avantagé."""
    from ml import pipeline as pl
    X, y = _holdout(500)
    # Seules les 400 dernières courses sont postérieures au champion.
    recentes = [f"C{i}" for i in range(100, 500)]
    session = _FakeSession(recentes)
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.5)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.5), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res["n_courses"] == 400, "les 100 courses vues par le champion sont exclues"
    assert res["n_rows"] == 2400
    assert session.dernier_cutoff == pd.Timestamp("2026-06-29")


@pytest.mark.asyncio
async def test_h2h_indecidable_si_echantillon_trop_mince(monkeypatch):
    """Sous H2H_MIN_ROWS l'AUC est du bruit → None, repli walk-forward."""
    from ml import pipeline as pl
    X, y = _holdout(10)  # 60 lignes
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.5)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.9), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res is None


@pytest.mark.asyncio
async def test_h2h_indecidable_si_aucune_course_posterieure(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout(400)
    session = _FakeSession([])  # champion entraîné APRÈS tout le hold-out
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.5)))

    assert await pl._head_to_head_auc(session, _FakeModel(0.9), X, y,
                                      _FakeMV(pd.Timestamp("2026-06-29"))) is None


@pytest.mark.asyncio
async def test_h2h_indecidable_sans_champion():
    from ml import pipeline as pl
    X, y = _holdout(400)
    assert await pl._head_to_head_auc(_FakeSession([]), _FakeModel(0.9), X, y, None) is None


@pytest.mark.asyncio
async def test_h2h_indecidable_si_le_pkl_champion_est_illisible(monkeypatch):
    """Un .pkl corrompu / incompatible ne doit pas faire échouer le retrain."""
    from ml import pipeline as pl
    X, y = _holdout(400)
    session = _FakeSession(X["course_id"].unique())

    def _boom(cls):
        raise EOFError("pickle tronqué")

    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current", classmethod(_boom))

    assert await pl._head_to_head_auc(session, _FakeModel(0.9), X, y,
                                      _FakeMV(pd.Timestamp("2026-06-29"))) is None


@pytest.mark.asyncio
async def test_h2h_indecidable_si_pas_de_champion_sur_disque(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout(400)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: None))

    assert await pl._head_to_head_auc(session, _FakeModel(0.9), X, y,
                                      _FakeMV(pd.Timestamp("2026-06-29"))) is None


@pytest.mark.asyncio
async def test_h2h_indecidable_si_une_seule_classe(monkeypatch):
    """roc_auc_score lèverait sur un échantillon sans gagnant."""
    from ml import pipeline as pl
    X, _ = _holdout(400)
    y = pd.Series(np.zeros(len(X), dtype=int))
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.5)))

    assert await pl._head_to_head_auc(session, _FakeModel(0.9), X, y,
                                      _FakeMV(pd.Timestamp("2026-06-29"))) is None


# ── Référence marché dans le head-to-head (diagnostic 2026-08-20) ────────
# Le head-to-head confrontait le challenger au champion et à rien d'autre. Deux
# modèles sous le niveau d'un `ORDER BY cote_pmu` pouvaient donc se succéder
# indéfiniment sans qu'aucun chiffre ne le révèle.

def _holdout_avec_cotes(n_courses=400, marche_juste=True):
    """Comme `_holdout`, plus une colonne de cotes.

    `marche_juste` : la cote la plus courte est celle du gagnant.
    Sinon le marché est inversé et son classement vaut 0.
    """
    cid, truth, cotes = [], [], []
    for i in range(n_courses):
        for j in range(6):
            cid.append(f"C{i}")
            gagnant = (j == 0)
            truth.append(1 if gagnant else 0)
            cotes.append((2.0 + j) if marche_juste else (20.0 - j * 3))
    X = pd.DataFrame({"course_id": cid, "truth": truth, "cote_pmu": cotes})
    return X, pd.Series(truth)


@pytest.mark.asyncio
async def test_h2h_expose_le_classement_du_marche(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout_avec_cotes(400, marche_juste=True)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.30)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.30), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    # Marché parfait : le favori gagne toujours.
    assert res["rank_marche"] == 1.0
    # Un modèle médiocre doit ressortir SOUS le marché, et c'est le chiffre
    # qui manquait depuis 513 versions.
    assert res["delta_marche"] < 0
    assert res["delta_marche"] == pytest.approx(res["rank_challenger"] - 1.0)


@pytest.mark.asyncio
async def test_h2h_delta_marche_positif_quand_le_marche_se_trompe(monkeypatch):
    from ml import pipeline as pl
    X, y = _holdout_avec_cotes(400, marche_juste=False)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.30)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.99), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res["rank_marche"] == 0.0
    assert res["delta_marche"] > 0


@pytest.mark.asyncio
async def test_h2h_sans_cotes_le_delta_marche_est_None(monkeypatch):
    """Pas de cote sur le hold-out → pas de verdict marché. Surtout pas 0.0,
    qui se lirait « à égalité avec le marché »."""
    from ml import pipeline as pl
    X, y = _holdout(400)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.30)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.95), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res["rank_marche"] is None
    assert res["delta_marche"] is None


@pytest.mark.asyncio
async def test_h2h_delta_porte_sur_le_classement_pas_sur_l_AUC_poolee(monkeypatch):
    """`delta` arbitre champion/challenger : il doit refléter le CLASSEMENT.

    Les deux AUC poolées restent exposées pour le diagnostic, mais ne décident
    plus rien.
    """
    from ml import pipeline as pl
    X, y = _holdout_avec_cotes(400)
    session = _FakeSession(X["course_id"].unique())
    monkeypatch.setattr(pl.BlackTurfEnsemble, "load_current",
                        classmethod(lambda cls: _FakeModel(0.30)))

    res = await pl._head_to_head_auc(session, _FakeModel(0.95), X, y,
                                     _FakeMV(pd.Timestamp("2026-06-29")))

    assert res["delta"] == pytest.approx(res["rank_challenger"] - res["rank_champion"])
    assert "auc_challenger" in res and "auc_champion" in res
