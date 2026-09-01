"""Une anomalie qui dure doit rester UNE ligne.

Défaut du 2026-09-01 : le back-office annonçait « 42 ouvertes » sur 72 h alors
qu'il n'y avait que trois faits distincts. `job_data_quality_check` tourne toutes
les heures et réinsérait ses anomalies sans regarder si elles étaient déjà
ouvertes — 40 lignes pour deux problèmes persistants, qui chassaient de
l'affichage (huit lignes visibles) tout ce qui était réellement nouveau et
rendaient « marquer résolu » inopérant.

Ce que ces tests verrouillent, et pourquoi ils ne peuvent pas être des tests
d'intégration : la déduplication elle-même repose sur `ON CONFLICT ... WHERE`
et un index unique PARTIEL, deux constructions PostgreSQL que la base SQLite des
tests ne connaît pas. On vérifie donc les deux moitiés vérifiables sans serveur :
que la requête PORTE bien la clause de fusion, et que les appelants périodiques
FOURNISSENT une clé. Le reste — le comportement du moteur — est garanti par
PostgreSQL, pas par nous.
"""
from __future__ import annotations

import pytest

import services.error_monitor as em


class _SessionFactice:
    """Capture les requêtes au lieu de les exécuter (aucune base requise)."""

    def __init__(self, journal: list[tuple[str, dict]]):
        self._journal = journal

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False

    async def execute(self, clause, params=None):
        self._journal.append((str(clause), params or {}))
        return None

    async def commit(self):
        return None


@pytest.fixture
def journal(monkeypatch) -> list[tuple[str, dict]]:
    requetes: list[tuple[str, dict]] = []
    monkeypatch.setattr(em, "AsyncSessionLocal", lambda: _SessionFactice(requetes))
    return requetes


@pytest.mark.asyncio
async def test_l_insertion_fusionne_les_occurrences_ouvertes(journal):
    """La requête doit fusionner sur `(source, cle)` tant que la ligne est OUVERTE.

    Le prédicat `WHERE resolved = false` n'est pas décoratif : sans lui, une
    anomalie close se ferait rouvrir en silence par la ligne d'origine, et le
    geste « marquer résolu » de l'admin n'aurait aucun effet observable.

    `created_at` doit rester à la PREMIÈRE apparition : c'est la durée du
    problème qui informe, pas son dernier écho. Le test le vérifie en creux —
    la clause de mise à jour ne doit pas y toucher.
    """
    await em.record_error("data_quality", "40 features mortes", cle="features_mortes")

    inserts = [(sql, p) for sql, p in journal if "INSERT INTO system_errors" in sql]
    assert len(inserts) == 1, "l'écriture d'une erreur ne doit produire qu'une requête"
    sql, params = inserts[0]

    assert "ON CONFLICT (source, cle) WHERE resolved = false" in sql, (
        "la fusion sur clé a disparu : chaque passage horaire du contrôle qualité "
        "réécrira une ligne, et le compteur d'erreurs ouvertes mesurera la DURÉE "
        "du problème au lieu de leur NOMBRE.")
    assert "occurrences = system_errors.occurrences + 1" in sql, (
        "les occurrences ne s'accumulent plus : une anomalie vue 40 fois "
        "s'afficherait comme vue une seule fois.")
    assert "derniere_occurrence = now()" in sql
    assert "created_at" not in sql.split("DO UPDATE")[1], (
        "`created_at` est réécrit à la fusion : la ligne perdrait la date de "
        "DÉBUT du problème, seule information qui dise depuis quand il dure.")
    assert params["k"] == "features_mortes"


@pytest.mark.asyncio
async def test_sans_cle_le_comportement_reste_une_ligne_par_appel(journal):
    """`NULL` n'entre pas en conflit avec `NULL` : un événement ponctuel n'est
    pas dédupliqué, et c'est le bon défaut. Un appelant qui ne sait pas nommer
    son anomalie ne doit pas voir son comportement changer sous ses pieds."""
    await em.record_error("api", "boum")
    _, params = next((s, p) for s, p in journal if "INSERT INTO system_errors" in s)
    assert params["k"] is None


@pytest.mark.asyncio
async def test_la_cle_est_bornee_comme_la_colonne(journal):
    """`cle` est un VARCHAR(160). Une clé plus longue ferait échouer l'INSERT, et
    `record_error` étant best-effort, l'échec serait AVALÉ : l'anomalie
    disparaîtrait purement et simplement du back-office."""
    await em.record_error("api", "boum", cle="x" * 500)
    _, params = next((s, p) for s, p in journal if "INSERT INTO system_errors" in s)
    assert len(params["k"]) == 160


@pytest.mark.asyncio
async def test_toute_anomalie_horaire_porte_une_cle(monkeypatch):
    """`verifier_et_alerter` tourne TOUTES LES HEURES : une anomalie sans clé y
    est une fuite garantie (24 lignes par jour et par anomalie persistante).

    Le test vaut aussi pour les anomalies FUTURES : il n'énumère pas les codes
    connus, il exige que chacun de ceux que le rapport produit arrive avec sa
    clé. Ajouter une anomalie sans clé casse ici, pas en production trois
    semaines plus tard.
    """
    import services.data_quality as dq

    anomalies = [
        {"code": "features_mortes", "gravite": "warning", "message": "24 features mortes"},
        {"code": "calibration_bande", "gravite": "warning", "message": "bande 0.40-0.50"},
        {"code": "source_muette", "gravite": "critical", "message": "pmu muet"},
    ]

    async def _rapport(_session):
        return {"anomalies": anomalies, "statut_global": "critical"}

    monkeypatch.setattr(dq, "rapport_qualite", _rapport)

    appels: list[dict] = []

    async def _record(source, message, *, detail=None, endpoint=None,
                      level="error", cle=None):
        appels.append({"source": source, "message": message, "cle": cle})

    monkeypatch.setattr(em, "record_error", _record)

    await dq.verifier_et_alerter(session=None)

    assert len(appels) == len(anomalies)
    for appel, anomalie in zip(appels, anomalies):
        assert appel["cle"] == anomalie["code"], (
            f"l'anomalie « {anomalie['code']} » est journalisée sans clé stable : "
            "elle réapparaîtra en une ligne neuve à chaque passage horaire.")
