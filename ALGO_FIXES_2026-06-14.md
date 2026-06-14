# BlackTurf — Correctifs algo (audit edge 2026-06-14)

## Constat (audit 7 agents)
L'algo **n'a pas d'edge réel**. Le `+150% / +86%` ROI affiché par profil = **illusion in-sample**.
Le seul test honnête (`edge_monitor`, split temporel) dit **-52% ROI, win 9.6% vs 8.9% baseline** = vérité.

**3 causes racines :**
1. **Fuites (leakage)** gonflent l'entraînement : split train/test par CHEVAL pas COURSE ; OOF `StratifiedKFold(shuffle=True)` ; pas de garde `computed_at < date_heure` au training ; calibration fittée sur sa propre sortie.
2. **Edge = marché re-encodé** puis re-blendé vers le marché, et gates value comparés à `1/cote` **non dé-viggé** (overround 12-20%) → set EV>0 contaminé = ligne directe vers -52%.
3. **Staking + dashboard non gardés** : deploy gate ne check que l'AUC du classifieur, jamais le ROI paris ; `+150%` = backtest in-sample reféed en prod ; `_enforce_gain_target` jette Kelly et dump tout le budget sur le longshot ; pas de cap bankroll.

Détail complet : voir `memory/blackturf_edge_rootcause.md` et l'output d'audit.

---

## Ce qui a été livré (ce commit)

### Actif immédiatement (sans risque, pas de flag)
- **Frontend `admin/algorithme/page.tsx`** : `win {Math.round(s.win_rate)}%` et `roi` affichaient une fraction arrondie comme un % → tout montrait `win 0%` / `+0%`. Corrigé en `×100`. (le bug cosmétique qui faisait croire que "ROI réel par signal" était mort).
- **`api/model_metrics.py`** : `precision_top3` "réelle" ne compte plus QUE les courses dont le prono existait avant le départ (`predictions.created_at < courses.date_heure`), avec fallback ORM si la requête échoue. Exclut le hindsight des entrées backfillées.

### Sous feature flags — **DÉSACTIVÉS PAR DÉFAUT** (déploiement shadow/canary)
Tout est dans `ml/algo_flags.py`. Rien ne change tant qu'une var d'env n'est pas mise à `1`.

| Flag env | Module | Effet quand activé |
|---|---|---|
| `BT_TRAIN_PRERACE_ONLY` | `pipeline._build_training_dataset_from_db` | Entraîne uniquement sur features figées avant départ (`fm.computed_at < c.date_heure`). |
| `BT_GROUP_SPLIT` | `models.train` | Split train/test + OOF (`StratifiedGroupKFold`) + walk-forward **par course_id** (anti fuite frères de course). |
| `BT_CALIB_GUARD` | `cote_calibration.compute_cote_calibration` | N'apprend le facteur que sur prédictions pré-départ (`pr.created_at < c.date_heure`). |
| `BT_DEVIG_GATES` | `valuebets.detect_value_bet` (+ `pipeline` qui passe `field_overround`) | Gates longshot/court-cote comparent la proba modèle à la **proba juste dé-viggée** (overround du champ), pas à `1/cote` brut. |
| `BT_STAKING_SAFE` | `services/mise_calculator.generer_plan` | (a) cap dur de l'exposition par course à `BT_BANKROLL_CAP_FRAC` × bankroll ; (b) désactive le dump `_enforce_gain_target` (garde le demi-Kelly diversifié). |
| `BT_ROI_DEPLOY_GATE` | `pipeline._should_deploy` | Refuse de promouvoir un modèle si l'edge hors-échantillon (`edge_monitor.edge_ok`) est explicitement faux. |

Réglages numériques (env, optionnels) : `BT_KELLY_OOS_SHRINK` (def 0.10, réservé batch 2), `BT_BANKROLL_CAP_FRAC` (def 0.03).

---

## Ordre de déploiement recommandé
1. **Maintenant** : déployer ce commit tel quel (flags off). Seuls les 2 correctifs actifs s'appliquent (affichage honnête). Aucun impact sur les mises/sélection.
2. **Mesure d'abord** : activer `BT_CALIB_GUARD`, `BT_TRAIN_PRERACE_ONLY`, `BT_GROUP_SPLIT` sur un retrain → comparer le walk-forward AUC honnête à l'ancien (il VA baisser : c'est normal, l'ancien était gonflé).
3. **Edge** : activer `BT_DEVIG_GATES`, observer en shadow l'edge_monitor recalculé.
4. **Gate** : activer `BT_ROI_DEPLOY_GATE` une fois l'edge_monitor fiable.
5. **Staking** : activer `BT_STAKING_SAFE` (réduit l'exposition — sens sûr) une fois le gate vert.

> Tant que le gate held-out n'est pas positif, l'algo perd. Les flags ne créent pas d'edge : ils arrêtent les fuites et la mesure mensongère pour qu'on puisse en construire un honnêtement.

---

## Batch 2 — LIVRÉ (boucle auto-apprenante honnête, sous flags OFF)

> **Migration requise pour `BT_CALIB_ON_RAW`** : `alembic upgrade head` (migration **0024** ajoute `predictions.proba_top1_raw` / `proba_top3_raw`, nullable, rétro-compat).

| Flag env | Modules | Effet quand activé |
|---|---|---|
| `BT_CALIB_ON_RAW` | `pipeline` (écrit les raw) + `isotonic_calibration`, `isotonic_calibration_top3`, `longshot_calibration`, `cote_calibration` (fittent dessus) | Les calibrations apprennent sur la proba MODÈLE BRUTE (`COALESCE(proba_*_raw, proba_*)`) + garde pré-départ → **casse la boucle fermée** (la calibration ne chasse plus son propre résidu). |
| `BT_COLLAPSE_LONGSHOT` | `pipeline` | Ne ré-applique PAS `longshot_calibration` après le blend marché → fin du **triple-comptage** favori-longshot qui écrasait l'edge. |
| `BT_OOS_WEIGHTS` | `profil_learning.compute_profil_weights` | Les poids/ROI par profil ne comptent QUE les runs émis avant départ et non-backfillés (mêmes gardes que le palmarès) → tue le **+150% illusion** affiché. |
| `BT_COMBO_EV_NONE` | `combo_bets.enumerate_bet_candidates` | EV des combos (non-Simple) forcée à 0 → ne passent plus les gates EV comme faux "value" (EV combo = `trj/p_market` vs `p_model` était mécaniquement positive). Simple Gagnant/Placé gardent leur EV réelle. |
| `BT_TEMP_FIT` | `adaptive_learning._update_temperature` | Gèle le ratchet asymétrique par course (qui dérivait vers T>1 = aplatit le champ, remonte les outsiders). |

Vérifs batch 2 : `py_compile` OK ; `pytest test_ml_units test_deploy_gate test_calibration_longshots test_strategies` → **137 passed** (flags off) ; smoke flags on : combos EV→0 / simples gardent EV, temperature gelée (Δ=0), training group-split end-to-end OK.

### Ordre d'activation batch 2 (après batch 1)
1. `alembic upgrade head` (migration 0024) — sans risque (colonnes nullable).
2. Activer `BT_CALIB_ON_RAW`. Laisser tourner ≥ quelques jours pour que `predictions.proba_*_raw` se remplissent (les calibrateurs utilisent `COALESCE` → dégradé propre tant que peu de raw).
3. Activer `BT_OOS_WEIGHTS` → le dashboard "pronos émis réglés" devient honnête (le +150% va chuter, c'est la vérité).
4. Activer `BT_COLLAPSE_LONGSHOT` puis `BT_COMBO_EV_NONE` puis `BT_TEMP_FIT` un par un, en surveillant `edge_monitor`.

## Batch 3 (designé, NON wiré — besoin plumbing données/état)
- **`edge_monitor` rejoue le VRAI filtre prod** (`detect_value_bet` + dé-vig) : nécessite de joindre `predictions.proba_top1` dans la requête edge_monitor (actuellement features+cote seulement). ROI par niveau + par tranche de cote.
- **Fit temperature nightly 1-D** : `fit_temperature_holdout(raw_top1, outcomes)` minimisant Brier/NLL sur fenêtre held-out (utilise `proba_top1_raw` désormais stocké), persisté dans l'état adaptatif. Le gel (`BT_TEMP_FIT`) stoppe déjà la dérive ; ceci ajoute le réglage actif.
- **Backtest dashboard held-out + frozen replay** : `backtest_profils(cutoff_date=...)` apprend les poids sur < cutoff, ROI affiché sur >= cutoff, en rejouant les plans figés (`profil_run_log`) au lieu de les régénérer.

## Vérifs effectuées
- `py_compile` OK sur tous les fichiers édités (batch 1 + 2).
- `pytest test_ml_units test_deploy_gate test_calibration_longshots test_strategies` → **137 passed** (flags off = comportement identique).
- Smoke flags ON : de-vig (rejette avec ratio dé-viggé), deploy gate bloque/autorise, training group-split end-to-end, combos EV→0 / simples gardent EV, temperature gelée (Δ=0).
- **Non testé ici** : suite complète + chemins DB (calibration raw, oos_weights, calib_guard nécessitent postgres) → **à lancer sur VPS** (`pytest` + `alembic upgrade head`).

## Récap variables d'environnement (toutes OFF par défaut)
```
# Batch 1
BT_GROUP_SPLIT=1
BT_TRAIN_PRERACE_ONLY=1
BT_CALIB_GUARD=1
BT_DEVIG_GATES=1
BT_STAKING_SAFE=1        # + BT_BANKROLL_CAP_FRAC=0.03 (def)
BT_ROI_DEPLOY_GATE=1
# Batch 2 (BT_CALIB_ON_RAW exige migration 0024)
BT_CALIB_ON_RAW=1
BT_OOS_WEIGHTS=1
BT_COLLAPSE_LONGSHOT=1
BT_COMBO_EV_NONE=1
BT_TEMP_FIT=1
```
