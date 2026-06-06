"""
Tests du socle scraper (base.py) : parc User-Agent + circuit breaker.
"""
import re

from scraper.base import USER_AGENTS, random_user_agent, CircuitBreaker


# ── User-Agents ──────────────────────────────────────────────────────────────
def test_user_agents_recents_et_diversifies():
    assert len(USER_AGENTS) >= 6
    # Plus aucune UA Chrome obsolète (≤ 124) dans le parc.
    for ua in USER_AGENTS:
        m = re.search(r"Chrome/(\d+)", ua)
        if m:
            assert int(m.group(1)) >= 130, f"UA Chrome obsolète: {ua}"
    # Diversité : au moins Chrome + Firefox représentés.
    assert any("Firefox/" in ua for ua in USER_AGENTS)
    assert any("Chrome/" in ua for ua in USER_AGENTS)


def test_random_user_agent_du_parc():
    for _ in range(20):
        assert random_user_agent() in USER_AGENTS


# ── Circuit breaker ──────────────────────────────────────────────────────────
def test_circuit_breaker_ouvre_apres_seuil():
    cb = CircuitBreaker(failures_threshold=3, cooldown_s=999)
    assert cb.is_open() is False
    for _ in range(3):
        cb.record_failure("test")
    assert cb.is_open() is True


def test_circuit_breaker_reset_sur_succes():
    cb = CircuitBreaker(failures_threshold=2, cooldown_s=999)
    cb.record_failure("test")
    cb.record_success()
    cb.record_failure("test")
    # Le succès a remis le compteur à zéro → un seul échec ne rouvre pas.
    assert cb.is_open() is False
