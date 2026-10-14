"""
Tests du relevé rapide des cotes PMU près du départ (scraper/cotes_rapides.py).

Invariants :
  1. une cote PMU plus ANCIENNE que celle en base n'est jamais écrite ;
  2. une cote identique n'est pas comptée comme périmée (seule la date bouge) ;
  3. une cote qui a bougé est écrite et comptée ;
  4. les non-partants du PMU et les cotes aberrantes sont ignorés ;
  5. aucune ligne n'est ajoutée à `cotes_historique` (distribution des features).
"""
import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from scraper import cotes_rapides as cr

T0 = datetime(2026, 10, 15, 13, 0, tzinfo=timezone.utc)


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _Session:
    def __init__(self, lignes):
        self.lignes = lignes
        self.sql: list = []

    async def execute(self, stmt, params=None):
        self.sql.append((str(stmt), params))
        return _Res(self.lignes if "SELECT" in str(stmt) else [])


def _rp(cote, date):
    return {"cote": cote, "cote_ref": 5.0, "mouvement": None, "date": date,
            "tendance": "-", "force": 1.0}


def _updates(s):
    return [p for q, p in s.sql if q.lstrip().startswith("UPDATE")]


def test_cote_plus_ancienne_jamais_ecrite():
    s = _Session([(1, 6.0, T0)])
    suivis, modifies = asyncio.run(cr.ecrire_rapports(
        s, "15102026R1C1", {1: _rp(9.0, T0 - timedelta(minutes=2))}))
    assert (suivis, modifies) == (1, 0)
    assert _updates(s) == []


def test_cote_identique_rafraichit_seulement_la_date():
    s = _Session([(1, 6.0, T0)])
    plus_tard = T0 + timedelta(minutes=1)
    suivis, modifies = asyncio.run(cr.ecrire_rapports(s, "15102026R1C1", {1: _rp(6.0, plus_tard)}))
    assert (suivis, modifies) == (1, 0)
    ups = _updates(s)
    assert len(ups) == 1 and ups[0]["dt"] == plus_tard and "cote" not in ups[0]


def test_cote_qui_bouge_est_ecrite_et_comptee():
    s = _Session([(1, 6.0, T0), (2, 3.1, T0), (3, None, None)])
    plus_tard = T0 + timedelta(minutes=1)
    rapports = {1: _rp(7.4, plus_tard), 2: _rp(3.1, T0), 3: _rp(12.0, plus_tard)}
    suivis, modifies = asyncio.run(cr.ecrire_rapports(s, "15102026R1C1", rapports))
    assert (suivis, modifies) == (3, 2)
    ecrits = {p["num"]: p["cote"] for p in _updates(s) if "cote" in p}
    assert ecrits == {1: 7.4, 3: 12.0}


def test_aucune_ecriture_dans_cotes_historique():
    s = _Session([(1, 6.0, T0)])
    asyncio.run(cr.ecrire_rapports(s, "15102026R1C1", {1: _rp(7.0, T0 + timedelta(minutes=1))}))
    assert not any("cotes_historique" in q for q, _ in s.sql)


def test_fetch_ignore_non_partants_et_cotes_aberrantes():
    ms = int(T0.timestamp() * 1000)
    payload = {"participants": [
        {"numPmu": 1, "dernierRapportDirect": {"rapport": 4.2, "dateRapport": ms,
                                               "indicateurTendance": "+", "nombreIndicateurTendance": 2},
         "dernierRapportReference": {"rapport": 5.0}},
        {"numPmu": 2, "statut": "NON_PARTANT", "dernierRapportDirect": {"rapport": 8.0}},
        {"numPmu": 3, "dernierRapportDirect": {"rapport": 0.5}},
        {"numPmu": 4, "dernierRapportDirect": {}},
    ]}

    def _handler(request):
        assert "/programme/15102026/R1/C1/participants" in str(request.url)
        return httpx.Response(200, json=payload)

    async def _go():
        async with httpx.AsyncClient(transport=httpx.MockTransport(_handler)) as c:
            return await cr.fetch_rapports(c, "15102026R1C1")

    out = asyncio.run(_go())
    assert list(out) == [1]
    assert out[1]["cote"] == 4.2 and out[1]["date"] == T0
    assert out[1]["mouvement"] == round((4.2 - 5.0) / 5.0, 4)
    assert out[1]["tendance"] == "+" and out[1]["force"] == 2.0


def test_fetch_en_echec_ne_rend_rien():
    async def _go():
        transport = httpx.MockTransport(lambda r: httpx.Response(503))
        async with httpx.AsyncClient(transport=transport) as c:
            return await cr.fetch_rapports(c, "15102026R1C1")

    assert asyncio.run(_go()) == {}
