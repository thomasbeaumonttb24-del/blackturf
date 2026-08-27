"""
Le palmarès affiche DEUX rapports par pari gagnant, et c'est délibéré.

La tranche d'un profil (prudent ×1,8-5, modéré ×4-15, risqué ≥×10) est un
engagement pris AVANT la course, sur le rapport ESTIMÉ. Le rapport parimutuel
RÉEL n'est connu qu'après la clôture des paris et dépend, pour un placé ou un
couplé, de QUELS autres chevaux arrivent : il tombe donc régulièrement sous la
tranche annoncée — mesuré sur l'historique des pronostics figés, 22 % des paris
gagnants en France et 34 % à l'étranger. N'afficher que le rapport payé donnait
un palmarès qui semble contredire le profil affiché (un ticket risqué figé à
×14,1 payé ×3,3 le 2026-08-27 à Saratoga).

`_rapports_vises` reconstruit le rapport annoncé depuis le plan FIGÉ. Ces cas
couvrent l'appariement plan ⋈ bilan, qui est l'endroit où ça peut casser en
silence : un mauvais appariement n'affiche simplement rien, sans erreur.
"""
from api.routes.stats import _rapports_vises


def test_appariement_par_type_et_numeros_tries():
    """L'ordre des chevaux n'est pas stable entre le plan et le bilan : sans tri,
    la moitié des combinés ne serait jamais appariée."""
    plan = {"niveaux": [{"paris": [
        {"type": "Couplé Gagnant", "mise": 4,
         "chevaux": [{"numero": 7}, {"numero": 3}], "gain_potentiel": 60},
        {"type": "Simple Placé", "mise": 10,
         "chevaux": [{"numero": 5}], "gain_potentiel": 23},
    ]}]}
    vises = _rapports_vises(plan)
    assert vises[("Couplé Gagnant", (3, 7))] == 15.0
    assert vises[("Simple Placé", (5,))] == 2.3


def test_plan_json_sous_forme_de_chaine():
    """Selon le pilote, la colonne jsonb revient en dict (asyncpg) ou en chaîne
    (SQLite en test) : les deux doivent marcher."""
    assert _rapports_vises(
        '{"niveaux": [{"paris": [{"type": "Trio", "mise": 2,'
        ' "chevaux": [{"numero": 4}, {"numero": 1}, {"numero": 9}],'
        ' "gain_potentiel": 90}]}]}'
    ) == {("Trio", (1, 4, 9)): 45.0}


def test_plan_absent_ou_vide_ne_leve_pas():
    """Un run ancien sans plan exploitable ne doit pas casser le palmarès : on
    renvoie simplement aucun rapport visé (le front affiche alors le payé seul)."""
    for plan in (None, "", "{}", {}, {"niveaux": []}):
        assert _rapports_vises(plan) == {}


def test_ticket_a_mise_nulle_ignore():
    """Mise 0 = aucun ticket réellement joué ; diviser par elle n'aurait pas de sens."""
    plan = {"niveaux": [{"paris": [
        {"type": "Trio", "mise": 0, "chevaux": [{"numero": 1}], "gain_potentiel": 90},
    ]}]}
    assert _rapports_vises(plan) == {}


def test_cheval_sans_numero_ignore_sans_casser():
    """Un partant sans numéro dans un plan ancien ne doit pas faire échouer la
    reconstruction de tout le palmarès."""
    plan = {"niveaux": [{"paris": [
        {"type": "Couplé Placé", "mise": 5,
         "chevaux": [{"numero": 2}, {"nom": "SANS NUMERO"}], "gain_potentiel": 30},
    ]}]}
    assert _rapports_vises(plan) == {("Couplé Placé", (2,)): 6.0}
