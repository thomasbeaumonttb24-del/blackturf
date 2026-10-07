# BlackTurf — Algorithme de pronostics : phases & ops

Doc de référence pour l'algo de pronostics : ce qui le compose, comment l'activer
sur une base réelle, et les garanties d'intégrité des données.

> **Règle d'or — zéro donnée fabriquée.** Toute donnée incertaine est `NULL`, jamais
> inventée ou estimée et stockée comme réelle. Les estimations de modèle (cotes
> équitables en simulation) sont explicitement étiquetées et ne sont jamais écrites
> en base comme des faits.

---

## 1. Boucle d'apprentissage (déjà en place)

Course terminée → `ml/pipeline.run_post_course` :
ELO → attribution contrastive gagnant/perdants → `PostRaceAnalyzer` (Brier, surprises,
**autopsie causale**, matrice de biais) → `AdaptiveLearning` (calibration température +
**poids de features**) → `DriftDetector` (ADWIN + Page-Hinkley) → retrain si drift critique.

Prédiction → `ml/pipeline.predict_course` :
ensemble (XGBoost + LightGBM + CatBoost, stacking) → calibration adaptative → meta-learner
L3 → correcteur contextuel → **portefeuille diversifié** + value bets + Markowitz + dutching.

---

## 2. Ce qui a été ajouté (modules purs, testés)

| Module | Rôle |
|--------|------|
| `ml/race_dynamics.py` | Réduction km, accélération finale (accelere/regulier/faiblit) |
| `ml/confrontation_features.py` | Confrontations directes (head-to-head) en feature |
| `ml/causal_autopsy.py` | Tags causaux : *pourquoi* ce résultat (position à 500m) |
| `ml/backtest.py` | ROI réel : règlement simples (cote) + combinés (rapports) |
| `ml/portfolio_simulator.py` | Couverture cohérente (Plackett-Luce) + diversification garantie |
| `ml/strategy_tuner.py` | Grid search ROI avec validation out-of-sample (anti-surapprentissage) |
| `ml/backfill_dynamics.py` | Rétro-remplissage des signaux dynamiques sur l'historique |
| `scraper/validation.py` | Validation de plausibilité à l'écriture (cotes, distances…) |
| `services/confrontations.py` | Service confrontations (endpoint) |

**Boucle causale fermée** (`ml/adaptive_learning.py`) : une cause physique récurrente
(favori qui faiblit, gagnant qui finit fort, train lent…) renforce le groupe de features
que le modèle sous-estimait → pronostics suivants adaptés.

### Nouvelles features ML
- `dyn_*` : dyn_finit_fort, dyn_taux_accelere/faiblit, dyn_reduction_km_best/moy
- `conf_*` : conf_bilan_net, conf_taux_victoire, conf_nb_rivaux_battus/bourreaux

---

## 3. Activer sur une base réelle

Tant que ces 3 étapes ne sont pas faites, `dyn_*`/`conf_*` restent **neutres**
(`nb_data=0`) → aucune régression, juste inactif.

```bash
# 1. Migration : crée les colonnes dynamiques (historique_courses)
alembic upgrade head            # migration 0009

# 2. Backfill + recalcul features
python scripts/activate_phase1.py --features --jours 30

# 3. Retrain pour exploiter dyn_* / conf_*
python -c "import asyncio; from ml.pipeline import run_nightly_retraining; asyncio.run(run_nightly_retraining())"
```

`activate_phase1.py` vérifie d'abord que la migration est appliquée et s'arrête
proprement sinon.

---

## 4. Outils d'analyse

### Endpoints (`/admin`, require_admin)
- `GET /admin/backtest?date_from&date_to&strategy=value_bet|portfolio` — ROI réel sur l'historique
- `GET /admin/tune-strategy?date_from&date_to&strategy` — meilleure config, validée out-of-sample
- `GET /admin/causes-recurrentes?limite` — fréquence des causes physiques + part de surprises

### Endpoint course
- `GET /courses/{id}/portfolio` — portefeuille multi-scénarios + champ `coverage`
  (couverture cohérente Plackett-Luce, ≠ ancien MC indépendant)
- `GET /courses/{id}/confrontations` — duels directs entre partants

### Scripts (lecture seule sauf activate)
- `python scripts/run_backtest.py --from --to --strategy portfolio` — backtest CLI
- `python scripts/activate_phase1.py [--features]` — activation Phase 1

---

## 5. Garanties d'intégrité

- **Scrapers** : échec de parse → `None`/`[]`, jamais de valeur par défaut fabriquée.
- **Écriture** (`scraper/validation.py`) : cote hors [1.01, 1000], distance hors
  [800, 8000], position > 40, pénétromètre hors [0, 9] → rejetés (rien écrit / `NULL`).
- **Calculs dérivés** (`race_dynamics`, `confrontation_features`) : `None` si données
  insuffisantes ou aberrantes ; bornes de plausibilité explicites.
- **Backtest** : paris gagnants réglés à la cote/rapport **réels** ; non réglable
  (combiné sans rapport, type inconnu) → exclu, jamais estimé.
- **seed_dev_data.py** : garde-fou `_assert_safe_target()` — refuse toute base non
  dev/test (override explicite `BLACKTURF_ALLOW_SEED=1`).

- **Cotes** : la cote de repli des features (`cote_pmu or 5.0`) n'existe que dans le
  vecteur du modèle (pas d'écart entraînement/service). Tout le reste lit
  `participations` (`ml.pipeline.cotes_reelles_de`) : `predictions.cote_figee` vaut
  `NULL` sans cote publiée, un partant non coté est « sans info marché » dans le blend
  et le mélange appris (il garde sa proba modèle ; le mélange appris ne s'applique
  qu'à un champ entièrement coté), et aucun pari de valeur ne sort sur une cote
  fabriquée.
- **Gagnant** : `position == 1` dans `resultats.classement` (dead-heat compris),
  jamais `classement->0` (`ml.signal_performance.sql_est_gagnant`, partagé par
  cote_calibration, edge_monitor, clv_monitor, servi_vs_marche).

---

## 6. Probabilités servies et paris de valeur (2026-10-07)

- **Une seule proba de victoire.** La proba affichée (mélange appris, sinon chaîne
  isotone → blend α → netteté) est AUSSI celle de la détection des paris de valeur :
  un pari de valeur vérifie toujours `proba_affichée × cote ≥ 1 + seuil`. Les gates
  restent (confiance, longshot, court-cote, `ev_band_gate`) ; les bandes d'EV sont
  apprises sur `proba_top1` persistée, donc sur cette même proba servie.
- **`cote_calibration`** : facteurs appris sur `proba_top1_raw` → plus appliqués à
  la proba servie (déjà calibrée par le marché : double correction favori-longshot).
  `detect_value_bet(..., proba_brute=True)` seulement.
- **P(top3) ≥ P(top1)** imposé par partant en fin de chaîne
  (`ml.pipeline.imposer_top3_sup_top1`), somme du champ conservée.
- **Modèle** (`ml.models`) : `roi_simule` et la plausibilité marché de
  `confidence_score` comparent une P(victoire) normalisée par course à la cote
  (dé-viggée pour la confiance), plus une P(top3). Le ranker LambdaRank n'est
  entraîné que si `BT_RANKER_BLEND=1`.

## 7. Drapeaux en production

Source de vérité : `docker-compose.prod.yml` (prime sur les défauts de
`ml/algo_flags.py`). Vérifié le 2026-10-07 :

| Drapeau | Prod | Défaut code | Conteneurs |
|---------|------|-------------|------------|
| `BT_MARKET_GATE` | 1 | ON | scraper, worker, scheduler |
| `BT_REFIT_FULL` | 1 | OFF | worker (réentraînement nocturne) |
| `BT_RANKER_BLEND` | 0 | OFF | scraper, worker, scheduler |

Les autres drapeaux anti-fuite (`BT_GROUP_SPLIT`, `BT_CALIB_ON_RAW`,
`BT_DEVIG_GATES`, …) sont à 1 en prod comme dans le code.

---

## 8. Reste à faire

- Scraper `commentaire_course` (déroulé textuel) — sélecteurs à valider sur le HTML live.
- Réconcilier entièrement le modèle `RaceLearningLog` si on veut exposer les champs
  hors schéma autrement que via `feature_autopsy["_meta"]`.
- Tuner les scénarios de portefeuille sur le ROI backtesté réel (une fois l'historique
  avec rapports peuplé).
