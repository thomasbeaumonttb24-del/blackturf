"""ROI jockey/entraîneur : trois features constantes redeviennent du signal.

Mesuré en production le 2026-08-19 : sur 206 features, 32 étaient MORTES — même
valeur pour les 22 939 lignes analysées. Parmi elles `jockey_roi`,
`entraineur_roi` et `jockey_montes_30j`, non pas faute de données mais parce que
rien ne les calculait : `stats_jockeys.roi_global` comptait 0 valeur non nulle
sur 3 804 lignes.
"""
import inspect

import pytest

from scraper.db_writer import (
    MIN_COURSES_ROI,
    compute_and_save_acteur_stats,
    roi_acteur,
)


# ── Le calcul lui-même ───────────────────────────────────────────────────────
def test_roi_nul_quand_les_gains_couvrent_exactement_les_mises():
    """40 montes à 1 €, 40 € de rapports encaissés → on rentre dans ses frais."""
    assert roi_acteur(gains=40.0, rides=40) == 0.0


def test_roi_negatif_est_le_cas_NORMAL():
    """Le prélèvement PMU (~25 %) rend le ROI d'un joueur moyen négatif : un ROI
    positif partout signalerait un bug, pas un don pour la sélection."""
    assert roi_acteur(gains=30.0, rides=40) == -0.25


def test_roi_positif_pour_un_acteur_reellement_rentable():
    assert roi_acteur(gains=60.0, rides=40) == 0.5


def test_pas_de_roi_sous_le_seuil_de_fiabilite():
    """Une victoire à 30/1 sur 10 montes donne un ROI de +200 % qui ne mesure que
    la chance. On préfère l'absence de valeur à un faux signal."""
    assert roi_acteur(gains=39.0, rides=MIN_COURSES_ROI - 1) is None
    assert roi_acteur(gains=0.0, rides=0) is None


def test_gains_absents_ne_plantent_pas():
    """Aucune victoire → SUM() renvoie 0 ou NULL selon le moteur."""
    assert roi_acteur(gains=None, rides=50) == -1.0


# ── Ce que la requête doit contenir ──────────────────────────────────────────
def test_le_calcul_lit_les_rapports_pmu_officiels():
    """Le ROI doit venir des rapports RÉELS (base 1 €), pas d'une cote estimée ni
    d'une reconstruction. La requête est du SQL PostgreSQL (LATERAL, FILTER,
    regex) que le SQLite des tests ne sait pas exécuter : on vérifie la source.
    """
    sql = inspect.getsource(compute_and_save_acteur_stats)
    assert "simple_gagnant" in sql and "e_simple_gagnant" in sql, (
        "les deux clés de rapport doivent être tentées, comme dans bet_settlement")
    assert "roi_global" in sql and "montes_30j" in sql, (
        "les colonnes mortes doivent être écrites, pas seulement calculées")
    assert "interval '30 days'" in sql, "l'activité récente se mesure sur 30 jours"


def test_une_seule_source_pour_le_calcul():
    """Deux copies du même SQL avaient divergé (le script ignorait ROI et activité
    récente) sans que rien ne le signale."""
    from scripts import compute_acteur_stats

    source = inspect.getsource(compute_acteur_stats)
    assert "compute_and_save_acteur_stats" in source
    assert "INSERT INTO" not in source, (
        "le script doit déléguer, pas réimplémenter la requête")


def test_on_n_ecrit_que_des_colonnes_qui_existent():
    """Les deux tables ne sont PAS symétriques : un entraîneur n'a pas de montes,
    et `stats_entraineurs` ne porte pas la colonne. Une requête unique pour les
    deux échoue en `UndefinedColumnError` — vécu au premier déploiement, la
    transaction entière étant perdue, jockeys compris."""
    from db.models import StatsEntraineur, StatsJockey

    assert hasattr(StatsJockey, "montes_30j")
    assert not hasattr(StatsEntraineur, "montes_30j"), (
        "si la colonne est ajoutée côté entraîneurs, activer le drapeau dans "
        "compute_and_save_acteur_stats")

    sql = inspect.getsource(compute_and_save_acteur_stats)
    assert '("stats_entraineurs", "entraineur_id", False)' in sql
    assert '("stats_jockeys", "jockey_id", True)' in sql


def test_un_scraper_muet_n_ecrase_pas_le_roi_calcule():
    """Turfoo ne publie pas de ROI (et renvoie 403 depuis le VPS) : le code posait
    quand même `roi_global = stats.get("roi", 0.0)`, donc 0.0 par-dessus le ROI
    calculé sur nos propres règlements. La feature serait retombée à plat au
    prochain passage du scraper, sans le moindre signal.

    La garde vit désormais dans `_colonnes_stats_utiles`, et elle vaut pour TOUTES
    les colonnes — pas seulement le ROI, qui n'était que le premier cas repéré.
    """
    from db.models import StatsJockey
    from scraper.orchestrator import _colonnes_stats_utiles

    source = inspect.getsource(
        __import__("scraper.orchestrator", fromlist=["x"])
    )
    assert 'roi_global=stats.get("roi", 0.0)' not in source, (
        "un ROI absent ne doit jamais devenir un ROI de 0")
    assert '"roi_global": stats.get("roi", 0.0)' not in source

    # Le scrape muet : des clés présentes, toutes vides. Rien ne doit être écrit.
    muet = {"roi_global": None, "taux_victoire_global": None, "victoires_saison": 0}
    assert _colonnes_stats_utiles(muet, StatsJockey) == {}
    # Un ROI réellement publié, lui, passe.
    assert _colonnes_stats_utiles({"roi_global": -0.18}, StatsJockey) == {
        "roi_global": -0.18}


def test_la_garde_lisait_une_cle_qui_n_existait_pas():
    """Le garde-fou de juin 2026 lisait `stats.get("roi")` là où `TurfooScraper`
    rend `roi_global` : il n'a donc jamais pu se déclencher. Le ROI calculé sur nos
    règlements n'a survécu que PAR ACCIDENT — et les autres colonnes, elles,
    lisaient `taux_victoire` pour une donnée nommée `taux_victoire_global`, donc
    écrivaient 0,0 même quand Turfoo répondait parfaitement."""
    from scraper.sources.turfoo import TurfooScraper

    js = inspect.getsource(TurfooScraper.get_stats_jockey)
    assert "roi_global:" in js and "taux_victoire_global:" in js, (
        "noms rendus par le scrape — ce sont EUX que l'écriture doit lire")

    orch = inspect.getsource(__import__("scraper.orchestrator", fromlist=["x"]))
    assert 'stats.get("taux_victoire")' not in orch
    assert 'stats.get("taux_place")' not in orch
