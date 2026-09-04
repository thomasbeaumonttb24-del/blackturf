"""Quatre files d'enrichissement ne pouvaient pas avancer.

Le motif, repete quatre fois dans l'orchestrateur :

    stmt = select(Cheval.nom).where(Cheval.running_style.is_(None))
    chevaux_sans_style = [r[0] for r in result.fetchall()[:15]]

Aucun `ORDER BY`, aucune trace d'echec, la table ENTIERE pour population, et le
plafond applique en Python apres avoir tout ramene. Une file pareille ne progresse
que par les SUCCES : les memes lignes de tete sont redemandees a chaque cycle tant
qu'elles echouent. Et elles echouent structurellement — France Galop couvre le plat
et l'obstacle, la requete ne filtrait aucune discipline, et les trotteurs sont la
moitie des partants francais.

Cote Turfoo, le commentaire annonçait « Jockeys du jour » au-dessus d'un
`SELECT DISTINCT` sur TOUS les jockeys jamais enregistres.

Ce que ces files alimentent : `running_style_code`, `taux_en_tete`,
`running_style_terrain_fit`, les `jockey_*` et les `entraineur_*` — soit une bonne
part des features que la supervision compte comme mortes.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from db.models import (
    Cheval, Course, Entraineur, Jockey, Participation, StatsEntraineur, StatsJockey,
)
from scraper.orchestrator import (
    _colonnes_stats_utiles,
    _fiche_letrot,
    _requete_chevaux_sans_pedigree,
    _requete_chevaux_sans_style,
    _requete_entraineurs_a_rafraichir,
    _requete_jockeys_a_rafraichir,
)

async def _course(db, cid, *, discipline="Plat", statut="a_venir", dans_h=6):
    db.add(Course(course_id=cid, reunion_id="R1", numero=1, nom="Prix test",
                  date_heure=datetime.now(timezone.utc) + timedelta(hours=dans_h),
                  hippodrome_nom="Deauville", discipline=discipline,
                  distance=2000, nb_partants=8, statut=statut))


async def _partant(db, cid, suffixe, *, style=None, pere=None, pays="FR",
                   jockey=None, entraineur=None):
    db.add(Cheval(cheval_id=f"H{suffixe}", nom=f"Cheval {suffixe}",
                  running_style=style, pere=pere, pays_naissance=pays))
    if jockey:
        db.add(Jockey(jockey_id=f"J{suffixe}", nom=jockey))
    if entraineur:
        db.add(Entraineur(entraineur_id=f"E{suffixe}", nom=entraineur))
    db.add(Participation(participation_id=f"P{suffixe}", course_id=cid,
                         cheval_id=f"H{suffixe}", numero=int(suffixe) % 20 + 1,
                         non_partant=False,
                         jockey_id=f"J{suffixe}" if jockey else None,
                         entraineur_id=f"E{suffixe}" if entraineur else None))


# ── Style de course : la file ne doit contenir que des chevaux atteignables ───

@pytest.mark.asyncio
async def test_un_trotteur_n_entre_pas_dans_la_file_france_galop(db):
    """LE defaut de fond. France Galop ne connait pas les trotteurs : les demander
    ne peut pas aboutir, et sans ordre ni marqueur d'echec ils occupaient la tete de
    file pour toujours — la file entiere en restait bloquee."""
    await _course(db, "C_TROT", discipline="Attelé")
    await _course(db, "C_PLAT", discipline="Plat")
    await _partant(db, "C_TROT", "01")
    await _partant(db, "C_PLAT", "02")
    await db.commit()

    noms = [r[0] for r in (await db.execute(_requete_chevaux_sans_style(15))).all()]
    assert noms == ["Cheval 02"]


@pytest.mark.asyncio
async def test_seuls_les_chevaux_engages_sont_demandes(db):
    """La requete d'avant balayait la table `chevaux` entiere. On ne calcule des
    features que pour les partants a venir : c'est eux, et eux seuls, qu'il faut."""
    await _course(db, "C1")
    await _partant(db, "C1", "01")
    db.add(Cheval(cheval_id="H99", nom="Retraite", running_style=None,
                  pays_naissance="FR"))
    await db.commit()

    noms = [r[0] for r in (await db.execute(_requete_chevaux_sans_style(15))).all()]
    assert noms == ["Cheval 01"]


@pytest.mark.asyncio
async def test_un_cheval_deja_style_ne_revient_pas(db):
    await _course(db, "C1")
    await _partant(db, "C1", "01", style="mene")
    await _partant(db, "C1", "02")
    await db.commit()

    noms = [r[0] for r in (await db.execute(_requete_chevaux_sans_style(15))).all()]
    assert noms == ["Cheval 02"]


@pytest.mark.asyncio
async def test_la_file_avance_avec_le_calendrier(db):
    """Ce que le correctif garantit vraiment : un cheval qu'on n'arrive JAMAIS a
    lire finit par sortir de la file — quand sa course est courue — au lieu de la
    boucher indefiniment. Le plafond ne se remplit donc plus des memes noms."""
    await _course(db, "C_PASSEE", statut="termine", dans_h=-2)
    await _course(db, "C_A_VENIR")
    await _partant(db, "C_PASSEE", "01")     # jamais lisible, mais deja courue
    await _partant(db, "C_A_VENIR", "02")
    await db.commit()

    noms = [r[0] for r in (await db.execute(_requete_chevaux_sans_style(15))).all()]
    assert "Cheval 01" not in noms and noms == ["Cheval 02"]


@pytest.mark.asyncio
async def test_le_plafond_est_applique_par_la_base(db):
    """Il l'etait en Python, APRES avoir ramene toute la table."""
    await _course(db, "C1")
    for i in range(5):
        await _partant(db, "C1", f"{i:02d}")
    await db.commit()

    lignes = (await db.execute(_requete_chevaux_sans_style(2))).all()
    assert len(lignes) == 2


# ── Genealogie : meme file, deux sources qui se partagent le travail ─────────

@pytest.mark.asyncio
async def test_france_galop_prend_les_francais_et_racing_post_les_autres(db):
    await _course(db, "C1")
    await _partant(db, "C1", "01", pays="FR")
    await _partant(db, "C1", "02", pays="IRE")
    await db.commit()

    fr = [r[1] for r in (await db.execute(_requete_chevaux_sans_pedigree(20))).all()]
    etr = [r[1] for r in
           (await db.execute(_requete_chevaux_sans_pedigree(20, etrangers=True))).all()]
    assert fr == ["Cheval 01"] and etr == ["Cheval 02"]


@pytest.mark.asyncio
async def test_un_cheval_avec_pedigree_sort_de_la_file(db):
    await _course(db, "C1")
    await _partant(db, "C1", "01", pere="Un Etalon")
    await db.commit()

    assert (await db.execute(_requete_chevaux_sans_pedigree(20))).all() == []


# ── Acteurs : ceux qui n'ont AUCUNE stat passent devant ──────────────────────

@pytest.mark.asyncio
async def test_les_jockeys_sans_stats_passent_devant(db):
    """Sans ce tri, le plafond de 30 rescrapait eternellement les memes acteurs
    deja connus pendant que les autres restaient vides."""
    saison = datetime.now(timezone.utc).year
    await _course(db, "C1")
    await _partant(db, "C1", "01", jockey="Deja Connu")
    await _partant(db, "C1", "02", jockey="Jamais Vu")
    db.add(StatsJockey(stat_id="S1", jockey_id="J01", saison=saison,
                       taux_victoire_global=0.15))
    await db.commit()

    noms = [r[1] for r in (await db.execute(_requete_jockeys_a_rafraichir(saison, 30))).all()]
    assert noms[0] == "Jamais Vu"


@pytest.mark.asyncio
async def test_seuls_les_jockeys_engages_sont_demandes(db):
    saison = datetime.now(timezone.utc).year
    await _course(db, "C1")
    await _partant(db, "C1", "01", jockey="Monte Demain")
    db.add(Jockey(jockey_id="J_RETRAITE", nom="Retraite"))
    await db.commit()

    noms = [r[1] for r in (await db.execute(_requete_jockeys_a_rafraichir(saison, 30))).all()]
    assert noms == ["Monte Demain"]


@pytest.mark.asyncio
async def test_une_stat_d_une_AUTRE_saison_ne_compte_pas_comme_connue(db):
    """La stat est datee : celle de l'an dernier ne dispense pas de rafraichir."""
    saison = datetime.now(timezone.utc).year
    await _course(db, "C1")
    await _partant(db, "C1", "01", jockey="Stat Perimee")
    db.add(StatsJockey(stat_id="S1", jockey_id="J01", saison=saison - 1,
                       taux_victoire_global=0.15))
    await db.commit()

    noms = [r[1] for r in (await db.execute(_requete_jockeys_a_rafraichir(saison, 30))).all()]
    assert noms == ["Stat Perimee"]


@pytest.mark.asyncio
async def test_les_entraineurs_suivent_la_meme_regle(db):
    saison = datetime.now(timezone.utc).year
    await _course(db, "C1")
    await _partant(db, "C1", "01", entraineur="Deja Connu")
    await _partant(db, "C1", "02", entraineur="Jamais Vu")
    db.add(StatsEntraineur(stat_id="S1", entraineur_id="E01", saison=saison,
                           taux_victoire_global=0.20))
    await db.commit()

    noms = [r[1] for r in
            (await db.execute(_requete_entraineurs_a_rafraichir(saison, 20))).all()]
    assert noms[0] == "Jamais Vu"


# ── Un scrape muet n'ecrase pas une donnee juste ─────────────────────────────

def test_un_scrape_muet_n_ecrit_rien():
    """`get_stats_jockey` rend un dict de cles a None quand la page se charge mais
    que les selecteurs ne trouvent rien. Ce dict est NON VIDE : le `if not stats`
    ne l'arretait pas, et l'upsert ecrivait 0,0 par-dessus le taux calcule sur NOS
    arrivees — toutes les trente minutes."""
    muet = {"victoires_saison": None, "taux_victoire_global": None,
            "taux_place_global": None, "roi_global": None, "montes_30j": None,
            "stats_par_distance": {}, "stats_par_hippodrome": {}, "stats_par_terrain": {}}
    assert muet, "le dict d'un scrape muet est bien NON vide — c'est tout le piege"
    assert _colonnes_stats_utiles(muet, StatsJockey) == {}


def test_les_cles_du_scrape_sont_enfin_lues_sous_leur_vrai_nom():
    """LE defaut le plus couteux : le scrape rend `taux_victoire_global`, l'upsert
    lisait `taux_victoire`. Cette cle n'existait dans aucun retour, donc la colonne
    recevait 0,0 MEME QUAND TURFOO REPONDAIT PARFAITEMENT."""
    stats = {"taux_victoire_global": 18.5, "taux_place_global": 42.0,
             "victoires_saison": 37, "stats_par_distance": {"2000m": 22.0}}
    colonnes = _colonnes_stats_utiles(stats, StatsJockey)
    assert colonnes["taux_victoire_global"] == 18.5
    assert colonnes["taux_place_global"] == 42.0
    assert colonnes["victoires_saison"] == 37
    # `stats_par_*` cote scrape, `taux_par_*` en base : la traduction est faite ici.
    assert colonnes["taux_par_distance"] == {"2000m": 22.0}


def test_un_zero_scrape_ne_remplace_pas_une_valeur_calculee():
    """0 veut dire « je n'ai pas su lire », pas « ce jockey n'a jamais gagne »."""
    assert _colonnes_stats_utiles({"taux_victoire_global": 0.0}, StatsJockey) == {}


def test_on_n_ecrit_jamais_une_colonne_absente_du_modele():
    """Un entraineur n'a ni `montes_30j` ni `taux_par_terrain` : les proposer ferait
    lever l'insert au lieu d'ignorer ce qui ne le concerne pas."""
    stats = {"montes_30j": 12, "stats_par_terrain": {"bon": 20.0},
             "taux_victoire_global": 15.0}
    colonnes = _colonnes_stats_utiles(stats, StatsEntraineur)
    assert set(colonnes) == {"taux_victoire_global"}
    assert set(_colonnes_stats_utiles(stats, StatsJockey)) == {
        "montes_30j", "taux_par_terrain", "taux_victoire_global"}


def test_une_absence_de_reponse_ne_leve_pas():
    assert _colonnes_stats_utiles(None, StatsJockey) == {}
    assert _colonnes_stats_utiles({}, StatsJockey) == {}


# ── LeTrot : la fiche est imbriquee, et personne ne la lisait ────────────────

def test_la_fiche_letrot_est_lue_la_ou_elle_est():
    """`get_fiche_cheval` rend {"search_results": [...], "fiche": {...}}. Le cycle
    lisait `meilleur_temps` sur le dictionnaire EXTERIEUR : 25 pages ouvertes toutes
    les dix minutes pour n'ecrire jamais rien."""
    reponse = {"search_results": [{"nom": "X"}],
               "fiche": {"nom": "Kalypso", "meilleur_temps": "1'12\"3"}}
    assert reponse.get("meilleur_temps") is None, "le piege : la cle n'est PAS au dehors"
    assert _fiche_letrot(reponse)["meilleur_temps"] == "1'12\"3"


def test_une_reponse_vide_ne_leve_pas():
    assert _fiche_letrot(None) == {}
    assert _fiche_letrot({}) == {}
    assert _fiche_letrot({"search_results": []}) == {}
