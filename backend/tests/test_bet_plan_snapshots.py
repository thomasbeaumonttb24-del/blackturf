"""Le conseil de mise émis est figé, idempotent, et jamais régénéré après coup."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import text

from services import bet_plan_snapshots as bps


DEPART = datetime(2026, 8, 18, 14, 0, tzinfo=timezone.utc)


def _plan(mise: float = 4.0, numero: int = 7, libelle: str = "Placé n°7") -> dict:
    return {
        "montant_total": 10.0,
        "montant_joue": mise,
        "ev_global": 0.12,
        "esperance_gain": 0.48,
        "resume_ia": "texte de présentation",
        "niveaux": [{
            "niveau": "securite",
            "label": "SÉCURITÉ",
            "emoji": "🟢",
            "montant": mise,
            "paris": [{
                "type": "Simple Placé",
                "chevaux": [{"numero": numero, "nom": "Cheval"}],
                "mise": mise,
                "gain_potentiel": 9.2,
                "probabilite": 0.55,
                "description": libelle,
                "ev_estime": 0.12,
                "raisons": ["forme récente"],
            }],
        }],
    }


def _values(**over):
    base = dict(
        course_id="C1",
        plan=_plan(),
        profil="equilibre",
        montant_demande=10.0,
        cotes_utilisees={7: 3.4},
        algo_config={"profil": "equilibre", "heat": 0.0},
        emitted_at=DEPART - timedelta(minutes=20),
        course_start_at=DEPART,
    )
    base.update(over)
    return bps.build_plan_snapshot_values(**base)


# ── Empreinte : stable sur la présentation, sensible sur l'argent ────────────

def test_le_hash_ignore_la_presentation_mais_pas_la_decision():
    ref = bps.plan_hash(_plan(), profil="equilibre", montant=10.0, cotes={7: 3.4})

    # Reformuler la description ne change pas le conseil.
    assert bps.plan_hash(_plan(libelle="Placé sur le 7"), profil="equilibre",
                         montant=10.0, cotes={7: 3.4}) == ref
    # Changer la mise, le cheval, le profil ou la cote SI.
    assert bps.plan_hash(_plan(mise=5.0), profil="equilibre",
                         montant=10.0, cotes={7: 3.4}) != ref
    assert bps.plan_hash(_plan(numero=9), profil="equilibre",
                         montant=10.0, cotes={7: 3.4}) != ref
    assert bps.plan_hash(_plan(), profil="agressif",
                         montant=10.0, cotes={7: 3.4}) != ref
    assert bps.plan_hash(_plan(), profil="equilibre",
                         montant=10.0, cotes={7: 4.1}) != ref


def test_le_hash_ne_depend_pas_de_l_ordre_des_chevaux():
    a = dict(_plan())
    a["niveaux"][0]["paris"][0]["chevaux"] = [{"numero": 3, "nom": "A"},
                                              {"numero": 7, "nom": "B"}]
    b = dict(_plan())
    b["niveaux"][0]["paris"][0]["chevaux"] = [{"numero": 7, "nom": "B"},
                                              {"numero": 3, "nom": "A"}]
    assert (bps.plan_hash(a, profil="equilibre", montant=10.0, cotes={})
            == bps.plan_hash(b, profil="equilibre", montant=10.0, cotes={}))


# ── Contenu figé ─────────────────────────────────────────────────────────────

def test_le_snapshot_conserve_le_plan_sans_les_metadonnees_de_route():
    plan = _plan()
    plan.update({"quota_restant": 3, "roi_observe": -0.12, "prono_fige": True})
    values = _values(plan=plan)

    assert "quota_restant" not in values["plan"]
    assert "roi_observe" not in values["plan"]
    # Le conseil lui-même est intégralement conservé.
    assert values["plan"]["niveaux"][0]["paris"][0]["mise"] == 4.0
    assert values["plan"]["resume_ia"] == "texte de présentation"
    assert values["nb_paris"] == 1
    assert values["montant_joue"] == 4.0
    assert values["ev_estimee"] == 0.12


def test_la_version_algo_derive_de_la_configuration_appliquee():
    v1 = _values(algo_config={"profil": "equilibre", "seuil": 1.1})
    v2 = _values(algo_config={"profil": "equilibre", "seuil": 1.1})
    v3 = _values(algo_config={"profil": "equilibre", "seuil": 1.4})

    assert v1["algo_version"] == v2["algo_version"]
    assert v1["algo_version"] != v3["algo_version"]
    assert v1["algo_version"].startswith("mp-")


def test_un_plan_emis_apres_le_depart_est_marque_non_pre_course():
    avant = _values(emitted_at=DEPART - timedelta(seconds=1))
    apres = _values(emitted_at=DEPART + timedelta(seconds=1))

    assert avant["is_pre_course"] is True
    assert apres["is_pre_course"] is False


def test_un_depart_inconnu_n_est_jamais_suppose_pre_course():
    assert _values(course_start_at=None)["is_pre_course"] is False


# ── Pseudonymisation du destinataire ─────────────────────────────────────────

def test_le_destinataire_est_pseudonymise_de_facon_stable():
    a = bps.subject_hash("user-42", "secret")
    b = bps.subject_hash("user-42", "secret")
    c = bps.subject_hash("user-43", "secret")

    assert a == b            # stable → l'idempotence tient d'une requête à l'autre
    assert a != c
    assert "user-42" not in a
    assert bps.subject_hash(None, "secret") == "system"


# ── Idempotence et écriture ──────────────────────────────────────────────────

class _Recorder:
    def __init__(self, existing_id=None):
        self.inserts: list = []
        self.existing_id = existing_id

    async def execute(self, statement, *args, **kwargs):
        sql = str(statement)
        if "INSERT INTO bet_plan_snapshots" in sql:
            self.inserts.append(sql)
        return _Scalar(self.existing_id)

    def begin_nested(self):
        return _NoopCtx()

    async def commit(self):
        pass

    async def rollback(self):
        pass


class _Scalar:
    def __init__(self, value):
        self._value = value

    def scalar(self):
        return self._value

    def all(self):
        return []

    def first(self):
        return None


class _NoopCtx:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return False


@pytest.mark.asyncio
async def test_l_ecriture_est_idempotente_et_renvoie_l_id_deja_enregistre():
    session = _Recorder(existing_id="PLAN-DEJA-EMIS")
    out = await bps.record_plan_snapshot(
        session,
        course_id="C1", plan=_plan(), profil="equilibre", montant_demande=10.0,
        cotes_utilisees={7: 3.4}, algo_config={}, emitted_at=DEPART - timedelta(minutes=5),
        course_start_at=DEPART,
    )
    # C'est l'identifiant de la PREMIÈRE émission qui fait foi, pas un nouvel uuid.
    assert out == "PLAN-DEJA-EMIS"
    assert len(session.inserts) == 1
    assert "ON CONFLICT" in session.inserts[0]


@pytest.mark.asyncio
async def test_un_echec_d_audit_ne_casse_jamais_la_reponse():
    class _Broken:
        async def execute(self, *_a, **_k):
            raise RuntimeError("db down")

        def begin_nested(self):
            return _NoopCtx()

        async def rollback(self):
            pass

    out = await bps.record_plan_snapshot(
        _Broken(), course_id="C1", plan=_plan(), profil="equilibre",
        montant_demande=10.0, cotes_utilisees={}, algo_config={},
        emitted_at=DEPART, course_start_at=DEPART,
    )
    assert out is None


# ── Règlement : événement ajouté, jamais réécriture ──────────────────────────

def test_le_reglement_ne_relit_que_les_plans_pre_course_non_definitifs():
    source = (bps.settle_course_plans.__doc__ or "") + _module_source()
    assert "s.is_pre_course = true" in source
    assert "AND t.statut = 'settled'" in source
    assert "NOT EXISTS" in source


def test_la_migration_bloque_toute_mutation_des_deux_tables():
    from pathlib import Path
    import os

    backend = Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                   or Path(__file__).resolve().parents[1])
    sql = (backend / "db/migrations/versions/0031_bet_plan_snapshots.py").read_text(
        encoding="utf-8").lower()
    # Le trigger est posé en boucle sur les DEUX tables (le nom est interpolé).
    assert 'for table in ("bet_plan_snapshots", "bet_plan_settlements"):' in sql
    assert "create trigger {table}_append_only" in sql
    assert "before update or delete on {table}" in sql
    assert "raise exception '% is append-only'" in sql
    # Le read-model de ROI n'expose ni les plans post-départ ni les règlements
    # incomplets : un rapport PMU manquant ne doit pas se lire comme une perte.
    assert "s.is_pre_course = true" in sql
    assert "t.statut = 'settled'" in sql


def _module_source() -> str:
    from pathlib import Path
    return Path(bps.__file__).read_text(encoding="utf-8")


# ── Intégration réelle : settle_course_plans lit un plan JSON réel ──────────
# Régression : la version initiale traitait un `plan` JSON renvoyé en chaîne
# (requête texte brute, pas de décodage typé) comme un dict, retombait sur {}
# silencieusement et réglait chaque plan comme s'il n'avait aucun pari.

from db.models import Course, Participation, Resultat  # noqa: E402


@pytest.mark.asyncio
async def test_settle_course_plans_regle_un_plan_reellement_stocke(db):
    depart = DEPART
    db.add(Course(course_id="CS1", reunion_id="R1", numero=1, nom="T",
                  date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    db.add(Participation(participation_id="p-CS1", course_id="CS1",
                         cheval_id="ch-CS1", numero=7, cote_pmu=3.4, non_partant=False))
    db.add(Resultat(course_id="CS1", classement=[
        {"numero": 7, "position": 1}, {"numero": 2, "position": 2},
    ], rapports={"gagnant": {"7": 3.4}},
        rapports_detail={"simple_place": [{"combinaison": "7", "rapport": 1.8}]}))
    values = bps.build_plan_snapshot_values(
        course_id="CS1", plan=_plan(), profil="equilibre", montant_demande=10.0,
        cotes_utilisees={7: 3.4}, algo_config={}, emitted_at=depart - timedelta(minutes=20),
        course_start_at=depart,
    )
    from db.models import BetPlanSnapshot
    db.add(BetPlanSnapshot(**values))
    await db.commit()

    out = await bps.settle_course_plans(db, "CS1")

    assert out == {"n_settled": 1, "n_partial": 0, "n_skipped": 0}
    row = (await db.execute(text(
        "SELECT statut, nb_paris, nb_gagnes FROM bet_plan_settlements "
        "WHERE plan_snapshot_id = :id"
    ), {"id": values["plan_snapshot_id"]})).first()
    assert row is not None
    assert row[0] == "settled"
    assert row[1] == 1
    assert row[2] == 1   # le pari Placé n°7 sur 4€ a bien été réglé gagnant


@pytest.mark.asyncio
async def test_settle_course_plans_ne_recalcule_jamais_un_plan_deja_settled(db):
    """Un plan déjà réglé 'settled' n'est plus jamais relu par settle_course_plans
    (pas de réécriture) — même si la fonction est rappelée (rattrapage nightly)."""
    depart = DEPART
    db.add(Course(course_id="CS2", reunion_id="R1", numero=1, nom="T",
                  date_heure=depart, hippodrome_nom="Pau", discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))
    db.add(Participation(participation_id="p-CS2", course_id="CS2",
                         cheval_id="ch-CS2", numero=7, cote_pmu=3.4, non_partant=False))
    db.add(Resultat(course_id="CS2", classement=[
        {"numero": 7, "position": 1}, {"numero": 2, "position": 2},
    ], rapports={"gagnant": {"7": 3.4}},
        rapports_detail={"simple_place": [{"combinaison": "7", "rapport": 1.8}]}))
    values = bps.build_plan_snapshot_values(
        course_id="CS2", plan=_plan(), profil="equilibre", montant_demande=10.0,
        cotes_utilisees={7: 3.4}, algo_config={}, emitted_at=depart - timedelta(minutes=20),
        course_start_at=depart,
    )
    from db.models import BetPlanSnapshot
    db.add(BetPlanSnapshot(**values))
    await db.commit()

    first = await bps.settle_course_plans(db, "CS2")
    second = await bps.settle_course_plans(db, "CS2")

    assert first == {"n_settled": 1, "n_partial": 0, "n_skipped": 0}
    assert second == {"n_settled": 0, "n_partial": 0, "n_skipped": 0}
    n_rows = (await db.execute(text(
        "SELECT count(*) FROM bet_plan_settlements WHERE plan_snapshot_id = :id"
    ), {"id": values["plan_snapshot_id"]})).scalar()
    assert n_rows == 1   # pas de second règlement ajouté
