"""Commentaires post-course du PMU : publiés après l'arrivée, effacés à 30 jours.
On les relit ensuite, sans jamais remplacer un commentaire déjà connu."""
from services import commentaires_pmu as cp

PARTICIPANTS = {"participants": [
    {"numPmu": 1, "commentaireApresCourse": {"texte": "  A bien conclu. ", "source": "DATAHIPPIQUE"}},
    {"numPmu": 2, "commentaireApresCourse": {"texte": "", "source": "DATAHIPPIQUE"}},
    {"numPmu": 3},
    {"numPmu": 4, "commentaireApresCourse": "Jamais en course."},
]}


def test_decoupage_du_course_id():
    assert cp.decouper_course_id("25092026R1C8") == ("25092026", "1", 8)
    assert cp.decouper_course_id("24092026R12C10") == ("24092026", "12", 10)
    assert cp.decouper_course_id("inconnu") is None


def test_commentaires_par_numero_ignore_les_vides():
    assert cp.commentaires_par_numero(PARTICIPANTS) == {1: "A bien conclu.", 4: "Jamais en course."}
    assert cp.commentaires_par_numero(PARTICIPANTS["participants"]) == {
        1: "A bien conclu.", 4: "Jamais en course."}
    assert cp.commentaires_par_numero(None) == {}


def test_le_classement_est_complete_sans_rien_ecraser():
    classement = [{"numero": 1, "position": 1, "commentaire": None},
                  {"numero": 4, "position": 2, "commentaire": "Déjà connu."},
                  {"numero": 9, "position": 3}]
    nouveau, n = cp.completer_classement(classement, {1: "A bien conclu.", 4: "Autre.", 9: None})
    assert n == 1
    assert [e.get("commentaire") for e in nouveau] == ["A bien conclu.", "Déjà connu.", None]
    assert classement[0]["commentaire"] is None, "l'entrée d'origine n'est pas modifiée"
