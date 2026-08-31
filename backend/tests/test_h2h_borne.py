"""La borne hors-échantillon de l'arbitrage champion/challenger.

Régression protégée (2026-08-31) : `_head_to_head_auc` bornait l'échantillon commun à
`created_at`, la date de PROMOTION du champion, alors que `train()` réserve les 20 % de
courses les plus récentes en hold-out — un modèle promu la veille s'est arrêté
d'apprendre ~73 jours plus tôt. La borne jetait donc ces 73 jours et ne laissait qu'une
journée de courses : `n_rows=381` contre `H2H_MIN_ROWS=2000`, toutes les nuits. L'arbitre
décrit dans le code comme « la seule comparaison honnête entre deux modèles » ne s'est
jamais exécuté, et le repli était le walk-forward que le même fichier déclare non
comparable d'une génération de données à l'autre.
"""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from ml.pipeline import _borne_hors_echantillon


PROMOTION = datetime(2026, 8, 31, 2, 19, tzinfo=timezone.utc)
FIN_TRAIN = PROMOTION - timedelta(days=73)


def test_train_fin_fait_foi_quand_elle_existe():
    mv = SimpleNamespace(created_at=PROMOTION, train_fin=FIN_TRAIN)
    borne, source = _borne_hors_echantillon(mv)
    assert borne == FIN_TRAIN
    assert source == "train_fin"


def test_repli_sur_la_promotion_sans_train_fin():
    """Versions antérieures à la migration 0043 : comportement d'avant, inchangé."""
    mv = SimpleNamespace(created_at=PROMOTION, train_fin=None)
    borne, source = _borne_hors_echantillon(mv)
    assert borne == PROMOTION
    assert source == "created_at"


def test_repli_quand_l_attribut_n_existe_pas():
    """Objet sans le champ (ORM d'une session qui n'a pas la colonne) : pas d'AttributeError."""
    mv = SimpleNamespace(created_at=PROMOTION)
    borne, source = _borne_hors_echantillon(mv)
    assert borne == PROMOTION
    assert source == "created_at"


def test_la_borne_train_fin_est_anterieure_donc_plus_permissive():
    """Le sens de la correction : élargir la fenêtre, jamais la rétrécir.

    Une borne PLUS TARDIVE que la promotion sélectionnerait moins de courses que le
    comportement d'origine et pourrait, elle, inclure des courses apprises par le
    champion. Ce test verrouille le sens de l'inégalité.
    """
    mv = SimpleNamespace(created_at=PROMOTION, train_fin=FIN_TRAIN)
    borne, _ = _borne_hors_echantillon(mv)
    assert borne < PROMOTION


def test_train_fin_nulle_n_est_pas_confondue_avec_une_date_valide():
    """`None` doit déclencher le repli, pas produire une borne `None` qui filtrerait tout."""
    mv = SimpleNamespace(created_at=PROMOTION, train_fin=None)
    borne, _ = _borne_hors_echantillon(mv)
    assert borne is not None
