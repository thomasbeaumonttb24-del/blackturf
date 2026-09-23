import pandas as pd

from ml.models import BlackTurfEnsemble


def test_old_terrain_schema_receives_current_terrain_value():
    model = BlackTurfEnsemble.__new__(BlackTurfEnsemble)
    model.feature_names = ["pref_terrain_bon", "pref_terrain_souple",
                           "pref_terrain_lourd", "terrain_code"]
    current = pd.DataFrame({"pref_terrain_actuel": [0.7, 0.4, 0.9],
                            "terrain_code": [0, 1, 2]})
    aligned = model._aligned_features(current)
    assert aligned["pref_terrain_bon"].tolist() == [0.7, 0.0, 0.0]
    assert aligned["pref_terrain_souple"].tolist() == [0.0, 0.4, 0.0]
    assert aligned["pref_terrain_lourd"].tolist() == [0.0, 0.0, 0.9]
    assert list(current.columns) == ["pref_terrain_actuel", "terrain_code"]


def test_new_terrain_schema_keeps_current_feature():
    model = BlackTurfEnsemble.__new__(BlackTurfEnsemble)
    model.feature_names = ["pref_terrain_actuel", "terrain_code"]
    current = pd.DataFrame({"pref_terrain_actuel": [0.7], "terrain_code": [2]})
    aligned = model._aligned_features(current)
    assert aligned.iloc[0].to_dict() == {"pref_terrain_actuel": 0.7, "terrain_code": 2.0}
