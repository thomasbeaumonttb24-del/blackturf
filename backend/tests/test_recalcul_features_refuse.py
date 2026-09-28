"""Les recalculs complets de features_ml refusent de tourner sans option explicite :
lancés le 24/09/2026, ils ont fait fuir le résultat dans tout l'historique."""
import pytest

from scripts import force_recompute_features, recompute_features_prerace


@pytest.mark.parametrize("module", [recompute_features_prerace, force_recompute_features])
def test_refus_sans_option(module, monkeypatch):
    monkeypatch.setattr("sys.argv", ["script", "--depuis-jours", "400"])
    with pytest.raises(SystemExit) as e:
        module.refuser_sans_option()
    assert e.value.code == 2


@pytest.mark.parametrize("module", [recompute_features_prerace, force_recompute_features])
def test_option_explicite_laisse_passer(module, monkeypatch):
    monkeypatch.setattr("sys.argv", ["script", "--malgre-la-fuite"])
    module.refuser_sans_option()


def test_la_maintenance_ci_ne_propose_plus_le_recalcul():
    from pathlib import Path
    wf = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "maintenance-elo.yml"
    texte = wf.read_text(encoding="utf-8")
    ligne = next(l for l in texte.splitlines() if l.strip().startswith("options:"))
    assert "features_12_mois" not in ligne
    assert "recompute_features_prerace" not in texte
