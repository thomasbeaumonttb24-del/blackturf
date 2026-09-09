"""Stérilité silencieuse du daemon Oddschecker (panne du 09/09/2026).

Symptôme : passé un quart d'heure, chaque cycle journalisait `cycle courses=10
cotes=0` en boucle, sans une seule erreur, alors que l'énumération de l'index
continuait de fonctionner. Un `systemctl restart` guérissait instantanément
(`cotes=270` au cycle suivant). Un trou d'une heure entière (13:00→15:00) est
resté invisible dans la distribution horaire de `cotes_bookmakers`.

Cause racine mesurée le 09/09 par sonde sur la production : la page de défi
Cloudflare est servie en **HTTP 403**, titre « Just a moment… » (localisé au
hasard du profil camoufox), 28 ko de HTML sans une seule ligne
`tr.diff-row.evTabRow` — contre ~1 Mo et 9 à 18 lignes pour une vraie page de
course. Le parseur, lui, ne regardait NI le code HTTP NI le titre : il comptait
les lignes du tableau, en trouvait zéro, et rendait « aucune cote » — verdict
rigoureusement identique à celui d'une course sans cote. Le compteur de défis
n'inspectait que l'index : un cycle où l'index passe et où toutes les courses
sont bloquées ne déclenchait donc rien.

Ce que ces tests protègent : une page inexploitable se DISTINGUE d'une page sans
cote, et cette distinction fait recycler le navigateur.
"""
import sys
import types
from datetime import datetime, timedelta, timezone

import pytest


@pytest.fixture
def daemon(monkeypatch):
    """Importe oddschecker_odds_daemon avec `camoufox` stubbé (absent du venv de test)."""
    if "camoufox" not in sys.modules:
        fake_camoufox = types.ModuleType("camoufox")
        fake_sync_api = types.ModuleType("camoufox.sync_api")
        fake_sync_api.Camoufox = object
        fake_camoufox.sync_api = fake_sync_api
        monkeypatch.setitem(sys.modules, "camoufox", fake_camoufox)
        monkeypatch.setitem(sys.modules, "camoufox.sync_api", fake_sync_api)

    import scraper.oddschecker_odds_daemon as mod
    return mod


class FausseReponse:
    def __init__(self, status):
        self.status = status


class FaussePage:
    """Page Playwright minimale : statut HTTP, titre et lignes de partants."""

    def __init__(self, statut=200, titre="Kempton 19:00 Betting Odds", lignes=None,
                 lignes_apres_attente=None):
        self.statut = statut
        self.titre = titre
        self.lignes = lignes if lignes is not None else []
        # Rendu tardif : ce que le sélecteur fait apparaître, comme sur le site.
        self.lignes_apres_attente = lignes_apres_attente
        self.visitees = []
        self.attentes_selecteur = 0

    def wait_for_selector(self, _selecteur, timeout=None):
        self.attentes_selecteur += 1
        if self.lignes_apres_attente is not None:
            self.lignes = self.lignes_apres_attente
            return object()
        if not self.lignes:
            raise TimeoutError("selecteur absent")
        return object()

    def goto(self, url, **_kw):
        self.visitees.append(url)
        return FausseReponse(self.statut)

    def wait_for_timeout(self, _ms):
        return None

    def title(self):
        return self.titre

    def evaluate(self, _js):
        return self.lignes


# ── Reconnaître la page de défi ─────────────────────────────────────────────

def test_le_403_du_defi_est_une_page_bloquee(daemon):
    """Le signal le plus sûr, et le seul indépendant de la langue."""
    page = FaussePage(statut=403, titre="Just a moment...")
    with pytest.raises(daemon.PageBloquee) as capture:
        daemon.ouvrir(page, "https://www.oddschecker.com/horse-racing")
    assert "403" in str(capture.value)


@pytest.mark.parametrize("titre", [
    "Just a moment...",
    "Nur einen Moment…",       # allemand — observé le 09/09 en production
    "Un momento…",             # espagnol — observé le même jour
    "Checking your browser before accessing",
])
def test_un_defi_servi_en_200_est_aussi_une_page_bloquee(daemon, titre):
    """Le titre est le filet : Cloudflare a déjà servi ce défi en HTTP 200
    (mesure du 20/08/2026), et rien ne garantit qu'il ne recommencera pas."""
    page = FaussePage(statut=200, titre=titre)
    with pytest.raises(daemon.PageBloquee):
        daemon.ouvrir(page, "https://www.oddschecker.com/horse-racing")


def test_une_vraie_page_passe(daemon):
    page = FaussePage(statut=200, titre="Kempton 19:00 Betting Odds- Racing")
    daemon.ouvrir(page, "https://www.oddschecker.com/horse-racing/kempton/19:00/winner")
    assert page.visitees == ["https://www.oddschecker.com/horse-racing/kempton/19:00/winner"]


# ── « Aucune cote » n'est pas « page inexploitable » ─────────────────────────

def test_read_race_rend_le_nombre_de_lignes_de_partants(daemon):
    """Une course où AUCUN des quatre books retenus ne cote reste une page
    exploitable : elle porte ses lignes de partants. C'est ce compte, et non le
    nombre de cotes, qui prouve que la page servie est la bonne."""
    page = FaussePage(lignes=[{"nom": "Gala Marci", "odds": {}},
                              {"nom": "Kalice", "odds": {}}])
    odds, lignes = daemon.read_race(page, "https://www.oddschecker.com/x")
    assert odds == {}
    assert lignes == 2


def test_read_race_laisse_sa_chance_a_un_rendu_tardif(daemon):
    """Le tableau des cotes est posé par du JS. Mesuré le 09/09 : la page Kempton
    19:00 rend zéro ligne à un passage et huit au suivant, sans rien changer
    d'autre. Sans cette attente, une lenteur de rendu se ferait passer pour un
    blocage et ferait recycler un navigateur parfaitement sain."""
    page = FaussePage(lignes=[], lignes_apres_attente=[{"nom": "Kalice", "odds": {"B3": 3.1}}])

    odds, lignes = daemon.read_race(page, "https://www.oddschecker.com/x")

    assert page.attentes_selecteur == 1
    assert lignes == 1
    assert odds == {"kalice": {"B3": 3.1}}


def test_read_race_normalise_les_noms_et_garde_les_cotes(daemon):
    page = FaussePage(lignes=[{"nom": "Gala Marci", "odds": {"B3": 4.5, "BF": 5.2}}])
    odds, lignes = daemon.read_race(page, "https://www.oddschecker.com/x")
    assert lignes == 1
    assert odds == {"galamarci": {"B3": 4.5, "BF": 5.2}}


# ── Verdict de cycle ────────────────────────────────────────────────────────

def _programme(daemon, monkeypatch, *, courses=2):
    """Installe un programme BlackTurf et un index oddschecker cohérents."""
    depart = datetime.now(timezone.utc) + timedelta(hours=1)
    bt = {
        f"C{i}": {"hippo": "kempton", "dt": "", "dt_obj": depart,
                  "chevaux": {"galamarci": ("1", f"P{i}")}}
        for i in range(courses)
    }
    monkeypatch.setattr(daemon, "load_blackturf", lambda: bt)
    monkeypatch.setattr(daemon, "enum_races", lambda _page: [
        {"slug": "kempton", "hhmm": "19:00", "url": f"https://www.oddschecker.com/r{i}",
         "dt_utc": depart}
        for i in range(courses)
    ])
    monkeypatch.setattr(daemon, "match_course",
                        lambda _bt, _slug, _dt, _c=iter(sorted(bt)): next(_c, None))
    return bt


def test_cycle_bloque_arrete_la_visite_des_le_premier_403(daemon, monkeypatch):
    """Le blocage frappe le NAVIGATEUR, pas la page : insister sur les courses
    suivantes ne rapporte rien et retarde le recyclage d'autant."""
    _programme(daemon, monkeypatch, courses=3)
    visitees = []

    def _read_race(_page, url):
        visitees.append(url)
        raise daemon.PageBloquee("http=403")

    monkeypatch.setattr(daemon, "read_race", _read_race)
    verdict, cotes = daemon._cycle(FaussePage())

    assert verdict == daemon.BLOQUE
    assert cotes == 0
    assert len(visitees) == 1, "on doit abandonner le cycle dès la première page bloquée"


def test_cycle_sterile_quand_toutes_les_pages_sont_vides(daemon, monkeypatch):
    """Le cas EXACT du 09/09 : les pages reviennent en 200, sans erreur, et sans
    une seule ligne de partants. Avant ce garde-fou, le daemon journalisait
    `cotes=0` et continuait tranquillement pendant 45 min par heure."""
    _programme(daemon, monkeypatch, courses=2)
    monkeypatch.setattr(daemon, "read_race", lambda _page, _url: ({}, 0))

    verdict, cotes = daemon._cycle(FaussePage())

    assert verdict == daemon.STERILE
    assert cotes == 0


def test_cycle_utile_quand_une_page_porte_ses_partants_sans_cote(daemon, monkeypatch):
    """Une course lue mais non cotée par les quatre books ne doit PAS faire
    recycler le navigateur : la stérilité, c'est l'absence de page servie, pas
    l'absence de cote."""
    _programme(daemon, monkeypatch, courses=2)
    monkeypatch.setattr(daemon, "read_race", lambda _page, _url: ({}, 9))
    monkeypatch.setattr(daemon, "write_odds", lambda *_a: 0)

    verdict, cotes = daemon._cycle(FaussePage())

    assert verdict == daemon.UTILE
    assert cotes == 0


def test_cycle_utile_ecrit_les_cotes(daemon, monkeypatch):
    _programme(daemon, monkeypatch, courses=1)
    monkeypatch.setattr(daemon, "read_race",
                        lambda _page, _url: ({"galamarci": {"B3": 4.5, "LD": 4.2}}, 9))
    ecrits = []
    monkeypatch.setattr(daemon, "write_odds",
                        lambda cid, matches: ecrits.append((cid, matches)) or len(matches))

    verdict, cotes = daemon._cycle(FaussePage())

    assert verdict == daemon.UTILE
    assert cotes == 2
    sources = {m[2] for m in ecrits[0][1]}
    assert sources == {"bet365", "ladbrokes"}


def test_cycle_bloque_quand_lindex_est_vide_avec_des_courses_attendues(daemon, monkeypatch):
    """Index servi en 200 mais sans un lien de course : défi silencieux, que le
    code HTTP n'a pas trahi."""
    _programme(daemon, monkeypatch, courses=1)
    monkeypatch.setattr(daemon, "enum_races", lambda _page: [])

    verdict, _cotes = daemon._cycle(FaussePage())

    assert verdict == daemon.BLOQUE


def test_cycle_en_veille_ne_sollicite_pas_le_site(daemon, monkeypatch):
    """La nuit, aucune course à coter : réveiller Cloudflare ne peut que griller
    un navigateur pour rien."""
    monkeypatch.setattr(daemon, "load_blackturf", lambda: {})

    def _interdit(_page):
        raise AssertionError("enum_races ne doit pas être appelé en veille")

    monkeypatch.setattr(daemon, "enum_races", _interdit)

    verdict, cotes = daemon._cycle(FaussePage())

    assert (verdict, cotes) == (daemon.VEILLE, 0)


def test_un_index_bloque_ne_passe_pas_pour_une_erreur_applicative(daemon, monkeypatch):
    """`PageBloquee` remontant de l'énumération doit rester un blocage : la
    ranger dans `cycle.error` la noierait parmi les pannes de base."""
    _programme(daemon, monkeypatch, courses=1)

    def _bloque(_page):
        raise daemon.PageBloquee("http=403")

    monkeypatch.setattr(daemon, "enum_races", _bloque)

    verdict, _cotes = daemon._cycle(FaussePage())

    assert verdict == daemon.BLOQUE


# ── Recyclage du navigateur ─────────────────────────────────────────────────

class FauxNavigateur:
    """Camoufox minimal : compte ses ouvertures, rend toujours la même page."""

    ouvertures = 0

    def __init__(self, **_kw):
        pass

    def __enter__(self):
        FauxNavigateur.ouvertures += 1
        return self

    def __exit__(self, *_a):
        return False

    def new_page(self):
        return FaussePage()


def _main_avec_verdicts(daemon, monkeypatch, verdicts):
    """Fait tourner `main()` sur une suite de verdicts, puis arrête le daemon."""
    FauxNavigateur.ouvertures = 0
    suite = iter(verdicts)
    sorties = []

    def _cycle(_page):
        try:
            return next(suite), 0
        except StopIteration:
            monkeypatch.setattr(daemon, "_run", False)
            return daemon.VEILLE, 0

    monkeypatch.setattr(daemon, "_run", True)
    monkeypatch.setattr(daemon, "Camoufox", FauxNavigateur)
    monkeypatch.setattr(daemon, "_start_watchdog", lambda: None)
    monkeypatch.setattr(daemon, "_cycle", _cycle)
    monkeypatch.setattr(daemon, "_dormir", lambda _t0: None)
    monkeypatch.setattr(daemon, "_attendre", lambda _s: None)
    monkeypatch.setattr(daemon.os, "_exit", lambda code: sorties.append(code))
    daemon.main()
    return sorties


def test_un_cycle_bloque_fait_ouvrir_un_navigateur_neuf(daemon, monkeypatch):
    """Le remède mesuré : un `Camoufox` rouvert = un profil neuf = accès rendu.
    Il ne consomme PAS le budget de redémarrage systemd (10 / 15 min), qui doit
    rester disponible pour une vraie panne."""
    sorties = _main_avec_verdicts(daemon, monkeypatch, [daemon.UTILE, daemon.BLOQUE])

    assert FauxNavigateur.ouvertures == 2
    assert sorties == [], "un blocage ponctuel ne doit pas tuer le process"


def test_une_sterilite_repetee_finit_par_faire_sortir_le_process(daemon, monkeypatch):
    """Si plusieurs navigateurs neufs de suite ne produisent rien, ce n'est plus
    un défi ponctuel : seul un process neuf (profil camoufox sur disque compris)
    peut encore aider."""
    sorties = _main_avec_verdicts(
        daemon, monkeypatch,
        [daemon.STERILE] * daemon.RECYCLAGES_STERILES_AVANT_SORTIE,
    )

    assert sorties == [1]


def test_un_cycle_utile_remet_le_compteur_de_sterilite_a_zero(daemon, monkeypatch):
    """Sinon des blocages espacés sur la journée finiraient par déclencher une
    sortie alors que le daemon produit."""
    verdicts = []
    for _ in range(daemon.RECYCLAGES_STERILES_AVANT_SORTIE + 2):
        verdicts += [daemon.UTILE, daemon.BLOQUE]
    sorties = _main_avec_verdicts(daemon, monkeypatch, verdicts)

    assert sorties == []
