#!/usr/bin/env python3
"""
betfair_fetch.py — Récupère les cotes Betfair Exchange (marché le plus efficient)
et les POST vers l'API BlackTurf (endpoint /admin/api/ingest-betfair).

CONÇU POUR TOURNER DANS GITHUB ACTIONS (gratuit), PAS sur le VPS allemand :
Betfair géo-bloque le hippique depuis une IP DE. Les runners GitHub (Azure US)
ne le sont pas → on contourne le blocage gratuitement.

Variables d'environnement requises (secrets GitHub) :
  BETFAIR_USER       identifiant Betfair
  BETFAIR_PASS       mot de passe Betfair
  BETFAIR_APPKEY     clé Application "delayed" (gratuite)
  BLACKTURF_INGEST_URL    ex: https://api.blackturf.fr/api/v1/admin/ingest-betfair
  BLACKTURF_INGEST_TOKEN  secret partagé (auth de l'endpoint)

Optionnel :
  BETFAIR_COUNTRIES  CSV pays (défaut: FR,GB,IE)
"""
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import httpx

LOGIN_URL = "https://identitysso.betfair.com/api/login"
BETTING_URL = "https://api.betfair.com/exchange/betting/rest/v1.0"
HORSE_RACING_EVENT_TYPE = "7"


def log(msg: str) -> None:
    print(f"[betfair] {msg}", flush=True)


def login(user: str, password: str, appkey: str) -> str:
    """Login interactif → token de session."""
    r = httpx.post(
        LOGIN_URL,
        data={"username": user, "password": password},
        headers={"X-Application": appkey, "Accept": "application/json"},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("status") != "SUCCESS":
        raise RuntimeError(f"Betfair login échoué: {data.get('status')} / {data.get('error')}")
    return data["token"]


def _rpc(endpoint: str, payload: dict, appkey: str, token: str) -> list:
    r = httpx.post(
        f"{BETTING_URL}/{endpoint}/",
        json=payload,
        headers={
            "X-Application": appkey,
            "X-Authentication": token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def fetch_markets(appkey: str, token: str, countries: list[str]) -> list[dict]:
    """Marchés WIN hippiques du jour (FR/GB/IE) + prix back/lay + dernier échangé."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(hours=24)

    catalogue = _rpc("listMarketCatalogue", {
        "filter": {
            "eventTypeIds": [HORSE_RACING_EVENT_TYPE],
            "marketCountries": countries,
            "marketTypeCodes": ["WIN"],
            "marketStartTime": {
                "from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "to": end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            },
        },
        "maxResults": 200,
        "marketProjection": ["RUNNER_DESCRIPTION", "EVENT", "MARKET_START_TIME"],
        "sort": "FIRST_TO_START",
    }, appkey, token)

    if not catalogue:
        log("aucun marché hippique retourné (géo-bloqué ? pays sans course ?)")
        return []

    market_ids = [m["marketId"] for m in catalogue]
    # Prix (best back/lay + last traded). Par lots de 40 (limite API).
    price_by_market: dict[str, dict] = {}
    for i in range(0, len(market_ids), 40):
        batch = market_ids[i:i + 40]
        books = _rpc("listMarketBook", {
            "marketIds": batch,
            "priceProjection": {"priceData": ["EX_BEST_OFFERS", "EX_TRADED"]},
        }, appkey, token)
        for b in books:
            price_by_market[b["marketId"]] = b

    out = []
    for m in catalogue:
        book = price_by_market.get(m["marketId"], {})
        runners_price = {r["selectionId"]: r for r in book.get("runners", [])}
        horses = []
        for r in m.get("runners", []):
            sid = r["selectionId"]
            rp = runners_price.get(sid, {})
            ex = rp.get("ex", {})
            back = ex.get("availableToBack") or []
            lay = ex.get("availableToLay") or []
            horses.append({
                "name": r.get("runnerName"),
                "back_price": back[0]["price"] if back else None,
                "lay_price": lay[0]["price"] if lay else None,
                "last_traded": rp.get("lastPriceTraded"),
            })
        ev = m.get("event", {})
        out.append({
            "market_id": m["marketId"],
            "hippodrome": ev.get("venue") or ev.get("name"),
            "country": ev.get("countryCode"),
            "market_start_time": m.get("marketStartTime"),
            "horses": horses,
        })
    return out


def main() -> int:
    user = os.environ.get("BETFAIR_USER")
    password = os.environ.get("BETFAIR_PASS")
    appkey = os.environ.get("BETFAIR_APPKEY")
    ingest_url = os.environ.get("BLACKTURF_INGEST_URL")
    ingest_token = os.environ.get("BLACKTURF_INGEST_TOKEN")
    countries = (os.environ.get("BETFAIR_COUNTRIES") or "FR,GB,IE").split(",")

    missing = [k for k, v in {
        "BETFAIR_USER": user, "BETFAIR_PASS": password, "BETFAIR_APPKEY": appkey,
        "BLACKTURF_INGEST_URL": ingest_url, "BLACKTURF_INGEST_TOKEN": ingest_token,
    }.items() if not v]
    if missing:
        log(f"secrets manquants: {missing}")
        return 1

    log("login Betfair…")
    token = login(user, password, appkey)
    log("login OK, récupération des marchés…")
    markets = fetch_markets(appkey, token, [c.strip() for c in countries])
    log(f"{len(markets)} marchés récupérés ({sum(len(m['horses']) for m in markets)} partants)")

    if not markets:
        return 0

    resp = httpx.post(
        ingest_url,
        json={"source": "betfair", "fetched_at": datetime.now(timezone.utc).isoformat(), "markets": markets},
        headers={"X-Ingest-Token": ingest_token, "Content-Type": "application/json"},
        timeout=30,
    )
    log(f"ingest → HTTP {resp.status_code}: {resp.text[:200]}")
    return 0 if resp.status_code < 300 else 2


if __name__ == "__main__":
    sys.exit(main())
