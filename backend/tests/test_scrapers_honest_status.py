"""Un scraper qui n'extrait rien ne doit jamais se journaliser « ok ».

C'est le défaut qui a rendu quatre sources muettes invisibles pendant des
semaines : `scrape_log.statut='ok'` signifiait « le cycle s'est terminé sans
exception », jamais « des données sont arrivées ». Les compteurs n'étaient même
pas transmis, donc le back-office lisait 0 partant sur un scrape réussi comme
sur un scrape bloqué — indistinguables.
"""
from __future__ import annotations

import os
import pathlib
import re

import pytest


BACKEND = pathlib.Path(os.environ.get("BLACKTURF_BACKEND_DIR")
                       or pathlib.Path(__file__).resolve().parents[1])
ORCHESTRATEUR = (BACKEND / "scraper/orchestrator.py").read_text(encoding="utf-8")
GENY = (BACKEND / "scraper/sources/geny.py").read_text(encoding="utf-8")


def _appels_log_scrape_result(source: str) -> list[str]:
    """Extrait les appels à log_scrape_result citant cette source."""
    return [bloc for bloc in re.findall(
        r"log_scrape_result\((.*?)\)\s*\n", ORCHESTRATEUR, re.S)
        if f'"{source}"' in bloc]


# ── Statut honnête ───────────────────────────────────────────────────────────

def test_le_cycle_geny_ne_se_declare_pas_ok_sans_donnees():
    appels = _appels_log_scrape_result("geny")
    assert appels, "aucun appel log_scrape_result pour geny"
    for appel in appels:
        assert '"ok" if n_cotes else "erreur"' in " ".join(appel.split()), (
            "le cycle geny doit journaliser 'erreur' quand il n'extrait aucune cote")


def test_le_cycle_geny_transmet_les_compteurs_reels():
    appels = _appels_log_scrape_result("geny")
    for appel in appels:
        assert "nb_partants=n_cotes" in " ".join(appel.split())
        assert "nb_courses=" in " ".join(appel.split())


def test_les_bookmakers_journalisent_leur_compte_reel():
    """Le compteur n'était jamais transmis : 0 partant même sur un scrape réussi."""
    normalise = " ".join(ORCHESTRATEUR.split())
    assert "nb_partants=nb_source" in normalise
    assert '"ok" if nb_source else "erreur"' in normalise


def test_un_bookmaker_desactive_n_est_pas_ouvert():
    """`_should_run` ne filtre que le GROUPE bookmakers : sans ce garde, un
    bookmaker listé dans SCRAPER_DISABLED_SOURCES continuait d'être chargé et
    attendu à chaque cycle, pour rien."""
    normalise = " ".join(ORCHESTRATEUR.split())
    assert "if source_name in self._disabled:" in normalise
    assert "orchestrator.bookmaker_disabled" in normalise


def test_geny_echoue_alimente_le_backoff():
    """Inutile de marteler à pleine cadence une source qui bloque."""
    assert 'self._failed_this_cycle.add("geny")' in ORCHESTRATEUR


# ── Blocage déguisé en succès ────────────────────────────────────────────────

def test_geny_detecte_le_403_deguise_en_200():
    """Geny renvoie HTTP 200 avec un corps de page d'erreur
    (`dataLayer.push({event:'error_page', error_status:'403'})`). Le contrôle sur
    status_code ne voyait rien et le parseur trouvait simplement 0 course."""
    assert "error_page" in GENY
    assert "geny.soft_block" in GENY


@pytest.mark.parametrize("corps,attendu_bloque", [
    ("<html><script>dataLayer.push({ event: 'error_page', error_status: '403' });"
     "</script></html>", True),
    ('<html><script>dataLayer.push({"event":"error_page"});</script></html>', True),
    ("<html><body><a href='/partants-pmu/2026-08-18-vichy-pmu-prix_c123'>x</a>"
     "</body></html>", False),
])
def test_fetch_geny_refuse_la_page_d_erreur(corps, attendu_bloque):
    from scraper.sources import geny as geny_mod

    class _Reponse:
        status_code = 200
        encoding = "latin-1"

        def __init__(self, text):
            self.text = text

    class _Client:
        def __init__(self, text):
            self._text = text

        def get(self, url, timeout=None):
            return _Reponse(self._text)

    resultat = geny_mod._fetch(_Client(corps), "https://www.geny.com/x")
    if attendu_bloque:
        assert resultat is None, "une page d'erreur en HTTP 200 doit être refusée"
    else:
        assert resultat is not None, "une page valide doit être acceptée"


def test_le_parseur_geny_lit_une_vraie_page():
    """Garde-fou : le refus du soft-403 ne doit pas rejeter les pages légitimes."""
    from bs4 import BeautifulSoup
    from scraper.sources.geny import _parse_index

    html = ("<html><body>"
            "<a href='/partants-pmu/2026-08-18-vichy-pmu-prix-des-fleurs_c1677095'>c</a>"
            "</body></html>")
    courses = _parse_index(BeautifulSoup(html, "html.parser"))
    assert len(courses) == 1
    assert courses[0]["course_id"] == 1677095
    assert courses[0]["hippodrome"] == "Vichy"


# ── Session de daemon figée : auto-réparation ────────────────────────────────

ODDSCHECKER = (BACKEND / "scraper/oddschecker_odds_daemon.py").read_text(encoding="utf-8")


def test_le_daemon_oddschecker_garde_un_seul_contexte():
    """`enum=0` était un CHALLENGE CLOUDFLARE, pas une session figée.

    Mesuré sur la production le 20/08/2026 : le premier contexte d'un navigateur
    neuf énumère 156 courses ; tout contexte SUIVANT — donc tout
    `browser.new_page()`, qui en crée un — reçoit « Just a moment… » en HTTP 200,
    que 60 s d'attente ne résolvent jamais. Le MÊME contexte, lui, enchaîne
    index → course → index sans broncher : il porte le cookie `cf_clearance`
    obtenu au premier passage. Ouvrir une page par cycle condamnait donc le
    daemon à être challengé en permanence.
    """
    lignes = ODDSCHECKER.splitlines()
    debut = next(i for i, l in enumerate(lignes) if l.strip() == "while _run:")
    corps = "\n".join(lignes[debut:])

    assert "page = browser.new_page()" in "\n".join(lignes[:debut]), \
        "le contexte doit être ouvert AVANT la boucle et vivre tout le process"
    assert "browser.new_page()" not in corps, \
        "une page par cycle = un contexte sans cf_clearance = challenge garanti"


def test_un_challenge_cloudflare_persistant_fait_redemarrer_le_daemon():
    """Aucune réparation interne n'existe : seul un navigateur NEUF obtient une
    nouvelle clearance. Le process doit donc sortir pour que systemd relance —
    même remède que pour un driver Playwright mort."""
    normalise = " ".join(ODDSCHECKER.split())
    assert "CHALLENGES_AVANT_REDEMARRAGE" in normalise
    assert 'log("cloudflare.exit"' in normalise
    assert "os._exit(1)" in normalise


def test_le_daemon_oddschecker_ne_sollicite_pas_le_site_sans_course_a_coter():
    """La fenêtre se calcule sur NOTRE base avant toute requête sortante : sans
    course à coter, réveiller Cloudflare ne peut que coûter une clearance (et un
    redémarrage) pour rien."""
    normalise = " ".join(ODDSCHECKER.split())
    assert "if not attendues:" in normalise
    assert "veille=True" in normalise


def test_le_daemon_oddschecker_journalise_sa_productivite():
    """« Le daemon tourne » n'est pas « le daemon produit ». Sans le nombre de
    cotes écrites par cycle, un daemon qui tourne à vide reste indétectable."""
    normalise = " ".join(ODDSCHECKER.split())
    assert 'log("cycle", courses=len(visit), cotes=cotes_du_cycle' in normalise


ZETURF = (BACKEND / "scraper/zeturf_live_daemon.py").read_text(encoding="utf-8")


def test_le_daemon_zeturf_a_la_meme_auto_reparation():
    """Correctif PRÉVENTIF : zeturf partage le défaut d'oddschecker (une page
    Camoufox pour toute la vie du process) et alimente `cote_unibet`, la
    meilleure couverture hors PMU (88 %). Sa perte silencieuse coûterait la
    comparaison de marché sans qu'aucun signal ne parte."""
    normalise = " ".join(ZETURF.split())
    assert "ENUM_VIDES_AVANT_RECREATION" in normalise
    assert "session.recreate" in normalise
    assert "if zc: enum_vides = 0" in normalise


def test_genybet_cree_une_session_par_appel_donc_non_concerne():
    """`StealthyFetcher.fetch(url)` ouvre une session neuve à chaque appel : ce
    daemon ne peut pas rester figé sur une session morte, inutile d'y ajouter la
    recréation."""
    genybet = (BACKEND / "scraper/genybet_live_daemon.py").read_text(encoding="utf-8")
    assert "StealthyFetcher.fetch" in genybet
    assert "ENUM_VIDES_AVANT_RECREATION" not in genybet


# ── Driver Playwright mort : sortir pour que systemd relance ─────────────────

@pytest.mark.parametrize("fichier", [
    "scraper/oddschecker_odds_daemon.py",
    "scraper/zeturf_live_daemon.py",
])
def test_un_driver_mort_fait_sortir_le_process(fichier):
    """Constaté le 18/08/2026 : le driver Node de Playwright crashe sur un bug
    interne, puis CHAQUE appel échoue avec « Connection closed while reading from
    the driver ». Le process Python reste vivant, attrape l'exception, dort,
    recommence — indéfiniment. Le watchdog ne se déclenche jamais (les cycles
    échouent VITE, loin de leur timeout) et `Restart=always` ne sert à rien tant
    que le process ne meurt pas : `NRestarts=0` apres des heures de panne."""
    source = (BACKEND / fichier).read_text(encoding="utf-8")
    normalise = " ".join(source.split())
    assert "_exit_si_driver_mort" in normalise
    assert "driver.dead_exit" in normalise
    assert "os._exit(1)" in normalise


@pytest.mark.parametrize("message,doit_sortir", [
    # Message REEL observe en production le 18/08/2026.
    ("Page.goto: Connection closed while reading from the driver", True),
    ("Target closed", True),
    ("Browser has been closed", True),
    # Erreurs applicatives ordinaires : surtout NE PAS tuer le process.
    ("Timeout 45000ms exceeded", False),
    ("net::ERR_NAME_NOT_RESOLVED", False),
    ("no such element", False),
])
def test_seul_un_driver_mort_declenche_la_sortie(message, doit_sortir, monkeypatch):
    """Une erreur de page ordinaire ne doit jamais tuer le daemon : ce serait un
    redémarrage en boucle sur un simple timeout."""
    import re as _re

    source = (BACKEND / "scraper/oddschecker_odds_daemon.py").read_text(encoding="utf-8")
    bloc = _re.search(r"_DRIVER_MORT = \((.*?)\)", source, _re.S)
    assert bloc, "_DRIVER_MORT introuvable"
    signatures = _re.findall(r'"([^"]+)"', bloc.group(1))

    declenche = any(s in message.lower() for s in signatures)
    assert declenche is doit_sortir, (
        f"{message!r} -> sortie={declenche}, attendu {doit_sortir}")
