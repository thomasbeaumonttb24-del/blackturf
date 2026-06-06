# Cotes Betfair Exchange (gratuit) — Guide de mise en route

Betfair Exchange = le marché le plus efficient (vrai argent, 0 % de marge). On l'utilise
comme **2ᵉ source de cotes indépendante** pour des value bets réels (modèle vs marché).

Le VPS étant en Allemagne (Betfair y géo-bloque le hippique), la récupération tourne sur
**GitHub Actions** (gratuit, hors VPS) qui POST les cotes vers l'API BlackTurf.

```
GitHub Action (/10 min) → API Betfair (clé gratuite) → POST /admin/api/ingest-betfair
   → mapping hippodrome + heure + nom cheval → écrit participations.cote_betfair_exchange
```

## Étapes (≈ 10 min, 100 % gratuit)

### 1. Compte Betfair
- Crée un compte sur https://www.betfair.com (gratuit, aucun dépôt requis pour la clé delayed).
- Note ton **identifiant** et ton **mot de passe**.

### 2. Clé Application "delayed" (gratuite)
- Va sur https://developer.betfair.com → connecte-toi → « Get API Access » / « Application Keys ».
- Récupère la **Delayed App Key** (gratuite ; la "live" à 299 £ est inutile ici).

### 3. Secrets GitHub
Dans le repo GitHub `thomasbeaumonttb24-del/blackturf` → **Settings → Secrets and variables → Actions → New repository secret**, ajoute :

| Nom | Valeur |
|-----|--------|
| `BETFAIR_USER` | ton identifiant Betfair |
| `BETFAIR_PASS` | ton mot de passe Betfair |
| `BETFAIR_APPKEY` | ta Delayed App Key |
| `BLACKTURF_INGEST_URL` | `https://api.blackturf.fr/admin/api/ingest-betfair` |
| `BLACKTURF_INGEST_TOKEN` | (le token d'ingestion fourni — déjà posé côté serveur) |

### 4. Démarrage
- Le workflow `.github/workflows/betfair-odds.yml` tourne automatiquement toutes les 10 min (10 h–23 h UTC).
- Test manuel : onglet **Actions** → « Cotes Betfair Exchange → BlackTurf » → **Run workflow**.
- Vérifie les logs : nb de marchés récupérés + réponse `matched_markets / matched_runners`.

## Notes
- **Couverture** : Betfair couvre surtout UK/Irlande ; le hippique français est liquide
  surtout sur les grandes courses (Quinté+, Vincennes, Longchamp…). Ailleurs, peu/pas de
  marché → on garde le PMU comme marché de référence.
- **Intégrité** : si un cheval/une course ne correspond pas, on ignore (aucune fausse cote).
- Une fois `cote_betfair_exchange` renseignée, le détecteur de value bets l'utilise en
  priorité (poids le plus fort = marché sans marge).
