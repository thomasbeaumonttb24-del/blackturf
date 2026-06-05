# Déployer les scrapers automatiques — démarrage minimal

Objectif : faire tourner la collecte automatique 24/7 **sans proxy** d'abord
(coût ~25 €/mois), puis durcir plus tard. Le mode starter ralentit le rythme et
désactive les sources les plus protégées pour limiter les bans au démarrage.

---

## 1. Prérequis (~25 €/mois)

- **1 VPS** Linux 24/7 — recommandé : 4 vCPU / 8 Go RAM (Hetzner CPX31 ~15 €/mois,
  ou OVH/Contabo équivalent). Docker + Docker Compose installés.
- **1 clé OpenWeather** (gratuite) : https://openweathermap.org/api
- (Optionnel plus tard) un proxy résidentiel si des sources se font bannir.

---

## 2. Configuration

```bash
# Sur le VPS, à la racine du projet
cp .env.production.template .env
nano .env
```

Renseigne au minimum :

| Variable | Valeur |
|----------|--------|
| `POSTGRES_PASSWORD` / `REDIS_PASSWORD` | mots de passe forts (`openssl rand -hex 16`) |
| `DATABASE_URL` / `DATABASE_URL_SYNC` / `REDIS_URL` | mêmes mots de passe |
| `SECRET_KEY` | `openssl rand -hex 32` |
| `OPENWEATHER_API_KEY` | ta clé météo |
| `BRIGHTDATA_PROXY` | **laisser VIDE** au démarrage |
| `SCRAPER_INTERVAL_MULTIPLIER` | `2.0` (rythme prudent) |
| `SCRAPER_DISABLED_SOURCES` | `racing_post` (source la moins utile au début) |

> Stripe / Resend / Google / VAPID ne sont PAS nécessaires pour le scraping seul —
> uniquement pour le site public. Laisse les `CHANGE_ME` si tu ne lances que la collecte.

---

## 3. Lancer la stack

```bash
# Base + cache + scraper (+ api/worker)
docker compose -f docker-compose.prod.yml up -d db redis
# Attendre que la base soit prête (~10 s), appliquer les migrations :
docker compose -f docker-compose.prod.yml run --rm api alembic upgrade head
# Démarrer le scraper en daemon :
docker compose -f docker-compose.prod.yml up -d scraper
```

Le conteneur `scraper` tourne en boucle (`restart: unless-stopped`) : il se réveille
toutes les 5 min et scrape chaque source à sa fréquence (×2 en mode starter).

---

## 4. Vérifier que ça collecte

```bash
# Logs du scraper en direct
docker compose -f docker-compose.prod.yml logs -f scraper

# Tu dois voir : orchestrator.starter_mode, orchestrator.*_start, *_done.
```

Contrôle en base (quelques minutes après un horaire de courses) :

```bash
docker compose -f docker-compose.prod.yml exec db \
  psql -U blackturf -d blackturf -c \
  "SELECT source, count(*) FROM scrape_log GROUP BY source ORDER BY 2 DESC;"
```

Vérifie que des cotes arrivent :

```sql
SELECT count(*) FROM cotes_historique WHERE time > now() - interval '1 hour';
```

---

## 5. Réglage du rythme (sans redéployer le code)

Tout est piloté par variables d'env — édite `.env` puis
`docker compose -f docker-compose.prod.yml up -d scraper` :

- **Trop de bans** → monte `SCRAPER_INTERVAL_MULTIPLIER` (3.0, 4.0) ou ajoute des
  sources à `SCRAPER_DISABLED_SOURCES` (ex. `racing_post,france_galop,geny`).
- **Tout va bien, tu veux plus de fraîcheur** → baisse le multiplier vers `1.0`.
- Sources possibles à désactiver : `pmu, zeturf, bookmakers, pool_pmu, geny, letrot,
  paris_turf, turfoo, meteo, france_galop, racing_post, associations`.
  Garde **`pmu`** activé (cœur : partants, cotes, résultats).

---

## 6. Étape suivante (durcissement, plus tard)

Quand une source se fait bannir malgré le rythme prudent :

1. Prendre un proxy **résidentiel** (Webshare, Smartproxy, BrightData) — voir prix
   dans la discussion (~40–90 €/mois selon volume).
2. Renseigner `BRIGHTDATA_PROXY=http://user:pass@host:port` dans `.env`.
3. Remettre `SCRAPER_INTERVAL_MULTIPLIER=1.0` et vider `SCRAPER_DISABLED_SOURCES`.
4. `docker compose -f docker-compose.prod.yml up -d scraper`.

---

## Rappels intégrité

- Un parse qui échoue → la source renvoie vide (pas de fausse donnée).
- Une valeur aberrante (cote, distance…) → rejetée à l'écriture (`scraper/validation.py`).
- ⚠️ Scraper PMU/bookmakers peut violer leurs CGU — usage à tes risques.
