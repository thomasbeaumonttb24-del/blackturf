"""Le visuel publie le plan CONSEILLÉ, pas le meilleur plan de la journée.

Un plan est ré-émis à chaque mouvement de cote : ~33 snapshots pré-course par
course en production. `/stats/meilleurs-plans-jour` triait ces ré-émissions sur
`net DESC` et remontait donc le MEILLEUR snapshot du jour — y compris un conseil
périmé qui n'était plus affiché au moment du départ.

Constat du 2026-09-04 sur 04092026R5C4, profil agressif :
    snapshots de 07:14 à 13:43 → Couplé Gagnant gagnant, 10 € → 1 286 €
    snapshots de 14:05 à 15:08 → plan perdant,           10 € →     0 €
L'endpoint renvoyait 1 286 € pendant que la fiche course publique affichait
« Risqué −10 € ». La mosaïque Instagram aurait publié un gain jamais conseillé,
sur une publication qu'on ne peut plus corriger.

Ces tests verrouillent les quatre façons dont un chiffre faux pouvait entrer dans
un visuel public : le conseil périmé, le plan d'un utilisateur, le plan émis après
le départ, et le règlement pas encore définitif.
"""
from datetime import datetime, timedelta, timezone

import pytest

from db.models import BetPlanSettlement, BetPlanSnapshot, Course, Hippodrome, Reunion

JOUR = "2026-09-04"
DEPART = datetime(2026, 9, 4, 15, 30, tzinfo=timezone.utc)


def _plan(mise: float) -> dict:
    return {"montant_joue": mise, "niveaux": [{"niveau": "securite", "paris": [{
        "type": "Couplé Gagnant", "chevaux": [{"numero": 1, "nom": "X"}],
        "mise": mise, "gain_potentiel": mise * 3, "probabilite": 0.3,
        "ev_estime": 0.1, "description": "d"}]}]}


def _course(db, course_id: str, *, hippodrome: str = "HIPPODROME DU LION D ANGERS"):
    db.add(Course(course_id=course_id, reunion_id="5", numero=4, nom="Prix T",
                  date_heure=DEPART, hippodrome_nom=hippodrome, discipline="Plat",
                  distance=2000, nb_partants=10, statut="termine"))


def _emission(db, course_id: str, suffixe: str, *, retour: float, emitted_at,
              profil: str = "agressif", mise: float = 10.0,
              origin: str = "profil_run", pre_course: bool = True,
              statut: str = "settled", bilan: dict | None = None):
    """Une émission de plan et son règlement. `retour` = ce que rend le plan."""
    sid = f"bp-{course_id}-{suffixe}"
    db.add(BetPlanSnapshot(
        plan_snapshot_id=sid, course_id=course_id, subject_hash="system",
        profil=profil, montant_demande=mise, plan=_plan(mise),
        plan_hash=f"h-{sid}", cotes_utilisees={"1": 3.0}, algo_config={},
        algo_version="t", nb_paris=1, montant_joue=mise, emitted_at=emitted_at,
        course_start_at=DEPART, is_pre_course=pre_course, origin=origin,
    ))
    db.add(BetPlanSettlement(
        settlement_id=f"st-{sid}", plan_snapshot_id=sid, course_id=course_id,
        bilan=bilan or {"paris": []}, montant_mise=mise, montant_retour=retour,
        net=retour - mise, roi=(retour - mise) / mise * 100, nb_paris=1,
        nb_gagnes=1 if retour > 0 else 0, statut=statut,
        settled_at=DEPART + timedelta(hours=1),
    ))


async def _corps(client) -> dict:
    r = await client.get(f"/api/v1/stats/meilleurs-plans-jour?jour={JOUR}")
    assert r.status_code == 200, r.text
    return r.json()


async def _plans(client) -> list[dict]:
    return (await _corps(client))["plans"]


@pytest.mark.asyncio
async def test_le_conseil_perime_ne_remonte_pas(db, client):
    """Le cas 04092026R5C4 : gagnant le matin, perdant au départ."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "matin", retour=1286.0,
              emitted_at=DEPART - timedelta(hours=8))
    _emission(db, "04092026R5C4", "depart", retour=0.0,
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert plans == [], (
        "le plan conseillé au départ perdait : rien ne doit être publié. "
        f"Reçu : {plans}"
    )


@pytest.mark.asyncio
async def test_c_est_le_montant_du_dernier_conseil_qui_est_publie(db, client):
    """Un conseil plus modeste au départ ne doit pas être remplacé par un gros
    gain périmé : c'est le montant DU DERNIER conseil qui sort."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "matin", retour=1286.0,
              emitted_at=DEPART - timedelta(hours=8))
    _emission(db, "04092026R5C4", "depart", retour=49.0,
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert len(plans) == 1
    assert plans[0]["retour"] == 49.0
    assert plans[0]["net"] == 39.0
    assert plans[0]["profil"] == "agressif"


@pytest.mark.asyncio
async def test_deux_profils_sur_la_meme_course_ne_font_qu_une_ligne(db, client):
    """Le visuel montre trois COURSES : la même course répétée par profil donnerait
    l'impression d'un doublon. C'est le meilleur profil qui la représente."""
    _course(db, "04092026R5C4")
    for profil, retour in (("agressif", 30.0), ("conservateur", 49.0)):
        _emission(db, "04092026R5C4", f"d-{profil}", retour=retour,
                  profil=profil, emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert len(plans) == 1
    assert plans[0]["profil"] == "conservateur"
    assert plans[0]["retour"] == 49.0


@pytest.mark.asyncio
async def test_le_plan_d_un_utilisateur_n_est_jamais_publie(db, client):
    """`bet_plan_snapshots` contient AUSSI les plans personnels des abonnés (269
    snapshots pré-course de 1 à 50 € en prod). Publier la mise de quelqu'un serait
    publier sa donnée, et à une mise qui n'est pas celle du plan du site."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "user", retour=800.0, mise=50.0,
              origin="mise_plan", emitted_at=DEPART - timedelta(minutes=30))
    await db.commit()

    assert await _plans(client) == []


@pytest.mark.asyncio
async def test_un_plan_emis_apres_le_depart_n_est_jamais_publie(db, client):
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "apres", retour=800.0, pre_course=False,
              emitted_at=DEPART + timedelta(minutes=5))
    await db.commit()

    assert await _plans(client) == []


@pytest.mark.asyncio
async def test_un_reglement_pas_definitif_sort_du_visuel(db, client):
    """Rapport Multi publié en différé → règlement 'partial'. On ne publie pas un
    chiffre qui va changer, et surtout on ne retombe pas sur un snapshot plus
    ancien pour combler le trou — ce serait le bug d'origine."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "matin", retour=1286.0,
              emitted_at=DEPART - timedelta(hours=8))
    _emission(db, "04092026R5C4", "depart", retour=49.0, statut="partial",
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    assert await _plans(client) == []


@pytest.mark.asyncio
async def test_l_hippodrome_vient_de_la_course_pas_de_la_reunion(db, client):
    """`reunions` ne compte que quinze lignes recyclées d'une journée à l'autre :
    son hippodrome est faux pour 36 des 52 courses du 2026-09-04. Le visuel doit
    lire `courses.hippodrome_nom`, jamais la jointure par la réunion.

    La réunion est délibérément renseignée avec un AUTRE hippodrome : c'est le seul
    montage où l'ancienne jointure `reunions → hippodromes` se trahit."""
    db.add(Hippodrome(hippodrome_id="h-nancy", nom="HIPPODROME DE NANCY-BRABOIS",
                      code="NANCY"))
    db.add(Reunion(reunion_id="5", date=DEPART.date(), hippodrome_id="h-nancy",
                   hippodrome_nom="HIPPODROME DE NANCY-BRABOIS", numero=5))
    _course(db, "04092026R5C4", hippodrome="HIPPODROME DE LYON-PARILLY")
    _emission(db, "04092026R5C4", "depart", retour=49.0,
              emitted_at=DEPART - timedelta(minutes=22))
    await db.commit()

    plans = await _plans(client)
    assert len(plans) == 1
    assert plans[0]["hippodrome"] == "Lyon-Parilly"


@pytest.mark.asyncio
async def test_les_totaux_du_jour_portent_sur_les_plans_publies(db, client):
    """Le bilan du soir compte les MÊMES plans que le podium — pas les ré-émissions.

    Deux courses, deux profils chacune, quatre ré-émissions par conseil : la story
    doit voir 4 plans, pas 16, et un total de retour de 49 + 0 + 236 + 0 = 285 €.
    """
    for course_id in ("04092026R5C4", "04092026R5C7"):
        _course(db, course_id)
    attendu = {
        ("04092026R5C4", "conservateur"): 49.0,
        ("04092026R5C4", "agressif"): 0.0,
        ("04092026R5C7", "conservateur"): 0.0,
        ("04092026R5C7", "agressif"): 236.0,
    }
    for (course_id, profil), retour in attendu.items():
        for k in range(4):
            # Les trois premières ré-émissions annoncent un gros gain périmé.
            _emission(db, course_id, f"{profil}-{k}", profil=profil,
                      retour=1286.0 if k < 3 else retour,
                      emitted_at=DEPART - timedelta(hours=6) + timedelta(hours=k))
    await db.commit()

    corps = await _corps(client)
    assert corps["nb_plans"] == 4, "quatre conseils, pas seize ré-émissions"
    assert corps["nb_plans_gagnants"] == 2
    assert corps["total_retour"] == 285.0
    # La mise reste servie par l'API même si le visuel ne l'affiche pas : sans elle,
    # personne ne peut dire si la journée a gagné ou perdu.
    assert corps["total_mise"] == 40.0
    assert corps["total_net"] == 245.0


@pytest.mark.asyncio
async def test_un_jour_sans_plan_reste_publiable(db, client):
    """Aucun plan réglé : totaux à zéro, pas d'erreur. Un visuel qui plante ne se
    publie pas, et c'est le matin qu'on le découvrirait."""
    corps = await _corps(client)
    assert corps["nb_plans"] == 0
    assert corps["total_retour"] == 0
    assert corps["total_mise"] == 0
    assert corps["plans"] == []


# ── Ce que l'ANALYSE de la journée a valu ────────────────────────────────────
# Le chiffre de tête de la story n'est pas un gain, c'est la qualité de classement :
# la part des courses où le gagnant réel figurait dans le Top 3 prédit. Il est publié
# avec son dénominateur ET le repère du hasard, sans quoi « 74,5 % » ne dit pas au
# lecteur ce qu'il bat.

def _analyse(db, course_id: str, *, rang_gagnant: int | None, nb_partants: int,
             prediction_avant_depart: bool = True):
    """Une course analysée : la ligne de journal + la prédiction qui la rend éligible."""
    from db.models import Participation, Prediction, RaceLearningLog

    pid = f"pa-{course_id}"
    db.add(Participation(participation_id=pid, course_id=course_id,
                         cheval_id=f"ch-{course_id}", numero=1, cote_pmu=3.0))
    db.add(Prediction(
        prediction_id=f"pr-{course_id}", participation_id=pid, course_id=course_id,
        proba_top1=0.3, proba_top3=0.6, rang_predit=1,
        # La garde anti-backfill est la SEULE chose qui empêche une prédiction écrite
        # après l'arrivée d'entrer dans le taux de réussite publié.
        created_at=DEPART - timedelta(hours=2) if prediction_avant_depart
        else DEPART + timedelta(hours=2),
    ))
    db.add(RaceLearningLog(log_id=f"rl-{course_id}", course_id=course_id,
                           gagnant_rang_predit=rang_gagnant, nb_partants=nb_partants))


@pytest.mark.asyncio
async def test_le_taux_top3_du_jour_sort_avec_son_denominateur_et_le_hasard(db, client):
    """Quatre courses de 10 partants : gagnant au rang 1, 3, 5 et jamais classé."""
    for i, rang in enumerate((1, 3, 5, None), start=1):
        cid = f"04092026R9C{i}"
        _course(db, cid)
        _analyse(db, cid, rang_gagnant=rang, nb_partants=10)
    await db.commit()

    a = (await _corps(client))["analyse"]
    assert a["nb_courses_analysees"] == 4
    assert a["nb_top3"] == 2 and a["pct_top3"] == 50.0
    assert a["nb_top1"] == 1 and a["pct_top1"] == 25.0
    assert a["nb_partants"] == 40
    # 3 chevaux tirés au hasard sur 10 partants = 30 %. Calculé sur le champ réel,
    # jamais posé à la main : c'est ce que le 50 % doit battre pour valoir quelque chose.
    assert a["hasard_top3"] == 30.0


@pytest.mark.asyncio
async def test_une_prediction_ecrite_apres_le_depart_n_entre_pas_dans_le_taux(db, client):
    """Sans cette garde, un backfill ferait monter le taux publié sans rien prédire."""
    _course(db, "04092026R9C1")
    _analyse(db, "04092026R9C1", rang_gagnant=1, nb_partants=10)
    _course(db, "04092026R9C2")
    _analyse(db, "04092026R9C2", rang_gagnant=1, nb_partants=10,
             prediction_avant_depart=False)
    await db.commit()

    a = (await _corps(client))["analyse"]
    assert a["nb_courses_analysees"] == 1, "la course prédite après le départ est exclue"


@pytest.mark.asyncio
async def test_une_journee_sans_analyse_se_tait_au_lieu_d_afficher_zero(db, client):
    """`null`, pas `0` : un « 0 % » se lit comme un échec, pas comme une absence."""
    a = (await _corps(client))["analyse"]
    assert a["nb_courses_analysees"] == 0
    assert a["pct_top3"] is None and a["pct_top1"] is None


@pytest.mark.asyncio
async def test_le_type_du_pari_gagnant_accompagne_le_montant(db, client):
    """Un montant sans son type de pari n'est pas vérifiable sur la fiche course.
    On prend le pari au plus gros GAIN, pas le premier de la liste : un plan à deux
    tickets peut en avoir un perdant devant."""
    _course(db, "04092026R5C7")
    _emission(db, "04092026R5C7", "d", retour=236.0,
              emitted_at=DEPART - timedelta(minutes=20),
              bilan={"paris": [
                  {"type": "Simple Placé", "gain": 12.0, "statut": "gagne"},
                  {"type": "Couplé Gagnant", "gain": 224.0, "statut": "gagne"},
              ]})
    await db.commit()

    plans = await _plans(client)
    assert plans[0]["type_pari"] == "Couplé Gagnant"


@pytest.mark.asyncio
async def test_les_hippodromes_du_jour_sont_comptes_sur_la_course(db, client):
    """Jamais par la jointure `reunions` : elle recycle quinze lignes d'un jour à
    l'autre et annoncerait un nombre d'hippodromes faux."""
    _course(db, "04092026R1C1", hippodrome="HIPPODROME DE PARIS-VINCENNES")
    _course(db, "04092026R3C1", hippodrome="HIPPODROME DE LYON-PARILLY")
    _course(db, "04092026R3C2", hippodrome="HIPPODROME DE LYON-PARILLY")
    await db.commit()

    assert (await _corps(client))["nb_hippodromes"] == 2


# ── RÈGLE DE PUBLICATION : après le dernier règlement, jamais avant ──────────
# À 11 h du matin, un tiers des courses sont réglées : un total publié là serait
# démenti par la soirée. La journée est « complète » quand la dernière course est
# partie depuis la marge, qu'aucune course courue n'attend son arrivée, et qu'aucun
# plan d'une course arrivée n'attend son règlement définitif.

def _resultat(db, course_id: str):
    from db.models import Resultat
    db.add(Resultat(course_id=course_id, classement=[{"numero": 1, "position": 1}]))


@pytest.mark.asyncio
async def test_la_journee_n_est_pas_complete_tant_qu_une_course_n_est_pas_partie(db, client):
    _course(db, "04092026R5C4")
    # Une course du même jour dont le départ est encore devant nous.
    from db.models import Course
    db.add(Course(course_id="04092026R9C9", reunion_id="9", numero=9, nom="Prix Z",
                  date_heure=datetime.now(timezone.utc) + timedelta(hours=3),
                  hippodrome_nom="H", discipline="Plat", distance=2000,
                  nb_partants=10, statut="a_venir"))
    _emission(db, "04092026R5C4", "d", retour=49.0, emitted_at=DEPART - timedelta(minutes=20))
    _resultat(db, "04092026R5C4")
    await db.commit()

    corps = await _corps(client)
    assert corps["journee_complete"] is False
    assert corps["reste_a_venir"]["courses_a_venir"] == 1


@pytest.mark.asyncio
async def test_une_course_courue_sans_arrivee_bloque_la_publication(db, client):
    _course(db, "04092026R5C4")
    from db.models import Course
    db.add(Course(course_id="04092026R9C9", reunion_id="9", numero=9, nom="Prix Z",
                  date_heure=datetime.now(timezone.utc) - timedelta(hours=2),
                  hippodrome_nom="H", discipline="Plat", distance=2000,
                  nb_partants=10, statut="a_venir"))
    _emission(db, "04092026R5C4", "d", retour=49.0, emitted_at=DEPART - timedelta(minutes=20))
    _resultat(db, "04092026R5C4")
    await db.commit()

    corps = await _corps(client)
    assert corps["journee_complete"] is False
    assert corps["reste_a_venir"]["courses_en_attente"] == 1


@pytest.mark.asyncio
async def test_une_course_annulee_ne_bloque_pas_la_publication_pour_toujours(db, client):
    """Cause racine du 2026-08-17 : une course annulée par le PMU ne passe JAMAIS en
    'termine'. Exiger ce statut aurait empêché toute publication, sans fin."""
    _course(db, "04092026R5C4")
    from db.models import Course
    db.add(Course(course_id="04092026R9C9", reunion_id="9", numero=9, nom="Prix Z",
                  date_heure=DEPART, hippodrome_nom="H", discipline="Plat",
                  distance=2000, nb_partants=10, statut="annule"))
    _emission(db, "04092026R5C4", "d", retour=49.0, emitted_at=DEPART - timedelta(minutes=20))
    _resultat(db, "04092026R5C4")
    await db.commit()

    assert (await _corps(client))["journee_complete"] is True


@pytest.mark.asyncio
async def test_un_plan_pas_encore_regle_bloque_la_publication(db, client):
    """Le rapport Multi est publié en différé : le total bouge encore après l'arrivée."""
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "d", retour=49.0, emitted_at=DEPART - timedelta(minutes=20))
    _emission(db, "04092026R5C4", "attente", retour=0.0, profil="conservateur",
              statut="partial", emitted_at=DEPART - timedelta(minutes=18))
    _resultat(db, "04092026R5C4")
    await db.commit()

    corps = await _corps(client)
    assert corps["journee_complete"] is False
    assert corps["reste_a_venir"]["plans_non_regles"] == 1


@pytest.mark.asyncio
async def test_journee_courue_et_reglee_est_publiable(db, client):
    _course(db, "04092026R5C4")
    _emission(db, "04092026R5C4", "d", retour=49.0, emitted_at=DEPART - timedelta(minutes=20))
    _resultat(db, "04092026R5C4")
    await db.commit()

    corps = await _corps(client)
    assert corps["journee_complete"] is True
    assert corps["reste_a_venir"] == {
        "courses_a_venir": 0, "courses_en_attente": 0, "plans_non_regles": 0,
    }


@pytest.mark.asyncio
async def test_une_journee_vide_n_est_jamais_declaree_complete(db, client):
    """Sans aucune course, les trois compteurs valent 0 : sans garde, la journée
    serait déclarée « complète » et le visuel publiable sur du néant."""
    assert (await _corps(client))["journee_complete"] is False
