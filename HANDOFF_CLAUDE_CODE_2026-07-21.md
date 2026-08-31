# Handoff → Claude Code : finir la vérification VPS + déployer le travail en attente

**Contexte.** Cet audit a été fait depuis un environnement Cowork sans accès SSH au VPS ni aux credentials. Toi (Claude Code, en local sur la machine de Thomas) as l'accès réel au repo, à git, et potentiellement au VPS via SSH — prends le relais sur tout ce qui suit. Lis d'abord `AUDIT_COMPLET_2026-07-21.md` (à la racine de `C:\Users\thoma\Desktop\BlackTurf\`) pour le détail complet de l'audit. Ce document-ci est le plan d'action à exécuter.

**Objectif rappelé par Thomas** : un système de paris hippiques dont le but est un **ROI proche de 0 sur le long terme en jouant TOUS les paris** — donc priorité absolue à l'honnêteté du modèle (pas de fuite de données, pas de ROI affiché gonflé) et à une boucle d'apprentissage qui tourne vraiment en continu, en plus d'un site/déploiement qui fonctionne.

Repo : `C:\Users\thoma\Desktop\BlackTurf\blackturf\` (aussi backup à la racine dans `_vps_live/`, `_vps_merge/`, `_desktop_backup_20260630_003009/` — **ignore ces dossiers de backup**, ils ne sont pas la source de vérité).

---

## Résumé de ce qui a déjà été trouvé (audit du 2026-07-21)

- **Le site est en ligne et sain** : `blackturf.fr` répond, design abouti ; `api.blackturf.fr/api/v1/health` → `{"status":"ok","version":"1.0.0","environment":"production"}` ; `api/v1/stats/public` → AUC 0,783, 16 969 courses analysées, précision Top-3 58,5 %.
- **Mais la prod tourne sur le commit `f2f6135` du 2026-07-02.** Depuis, **80 fichiers modifiés (+10 091/−3 522 lignes)** + ~40 fichiers nouveaux sont **écrits, terminés, compilent (0 erreur `py_compile`), mais jamais commités ni poussés**. Le déploiement se fait via `.github/workflows/deploy.yml` sur push `main` → donc rien de ce travail n'est en ligne.
- Ce travail non déployé, c'est justement **les correctifs « algo honnête / anti-fuite »** (entraînement pré-départ only, group-split par course, de-vig, calibration isotonic par segment, gating de déploiement, staking Kelly shrinké/capé), une refonte du calculateur de mise (+955 lignes), de nouveaux daemons de cotes live (ZEturf, GenyBet), une refonte frontend + billing Stripe.
- **Le ROI de +27,9 % affiché en prod (`stats/public` → `roi_simule_6mois`) n'est pas honnête** : c'est un backtest optimiste (pas de garde pré-départ, réglé à une cote potentiellement de clôture, sélection biaisée niveau≥3). Le code local sait que le vrai ROI (`roi_reel`) est probablement ~négatif tant que la CLV mesurée (~+2-7 %) reste sous la marge PMU (~15 %).
- **3 bugs identifiés à corriger avant de pousser** (détail §2 ci-dessous).
- **Nettoyage nécessaire** : 7 fichiers `.localbak` non suivis à exclure, `frontend/tsconfig.tsbuildinfo` versionné à tort, un `.git/index.lock` traînant a été observé.

---

## Étape 0 — Reprendre la main sur git

```powershell
cd "C:\Users\thoma\Desktop\BlackTurf\blackturf"
git status
```

- Si `.git/index.lock` existe et bloque une commande git : vérifier qu'aucun process git n'est en cours, puis le supprimer.
- Confirmer qu'on est bien sur `main`, à jour avec `origin/main` (dernier commit `f2f6135`), et que les ~80 fichiers modifiés + fichiers non suivis correspondent à la description ci-dessus (`git diff --stat`, `git status -s`).

---

## Étape 1 — Vérifier le VPS (ce que je n'ai pas pu faire depuis Cowork)

Récupérer l'IP/hôte du VPS Hetzner (Thomas l'a — pas dans le repo) et lancer :

```bash
ssh root@<IP_VPS> '
echo "=== containers ===" && docker compose -f /opt/blackturf/docker-compose.yml -f /opt/blackturf/docker-compose.prod.yml ps
echo "=== dernier commit déployé ===" && cd /opt/blackturf && git log -1 --oneline
echo "=== api health ===" && curl -s http://localhost:8000/api/v1/health
echo "=== logs api (100 lignes) ===" && docker compose logs --tail=100 api
echo "=== logs worker RQ (100 lignes) ===" && docker compose logs --tail=100 worker
echo "=== logs scraper (50 lignes) ===" && docker compose logs --tail=50 scraper
echo "=== redis ping ===" && docker compose exec -T redis redis-cli ping
echo "=== espace disque ===" && df -h /
echo "=== dernières migrations appliquées ===" && docker compose exec -T api alembic -c db/migrations/alembic.ini current
'
```

Points à valider (objectif : confirmer que l'apprentissage tourne *vraiment*, pas juste câblé dans le code) :

1. Tous les conteneurs `api`, `worker`, `scraper`, `frontend`, `redis`, `nginx` (selon `docker-compose.prod.yml`) sont **Up** et pas en `Restarting`/`unhealthy`.
2. Le **worker RQ** traite bien la queue `ml` — chercher dans ses logs des jobs `ml.pipeline.retrain_if_needed` exécutés récemment (le nightly tourne à 02:00 UTC, le meta-learner à 03:00 UTC — vérifier les logs autour de ces heures sur les derniers jours).
3. **Redis répond** (`PONG`).
4. Le **scraper/settlement** alimente bien `race_learning_log` avec les résultats réels (chercher des logs de règlement de courses récentes, pas d'erreurs répétées de scraping).
5. Le commit déployé (`git log -1` sur le VPS) — confirmer qu'il correspond bien à `f2f6135`, cohérent avec l'audit.

Si un service est down ou en boucle de crash, diagnostiquer avant de déployer par-dessus (ne pas empiler un nouveau déploiement sur une prod cassée).

---

## Étape 2 — Corriger les 3 points chauds AVANT de pousser

### 2.1 Retrain incrémental hors du process API
`backend/services/jobs.py` ligne ~96, dans `job_drift_check` :
```python
asyncio.create_task(run_incremental_retraining())
```
Contredit le design voulu (commenté juste au-dessus dans `job_retrain_trigger` : *"heavy CPU, don't run in API process"*). Le remplacer par un enqueue RQ, à l'identique de `job_retrain_trigger` :
```python
import redis as sync_redis
from rq import Queue
from api.config import get_settings
settings = get_settings()
r = sync_redis.from_url(settings.redis_url)
q = Queue("ml", connection=r, default_timeout=3600)
q.enqueue("ml.pipeline.run_incremental_retraining", result_ttl=86400)
```
(Vérifier que `ml.pipeline.run_incremental_retraining` est bien importable/enqueuable tel quel par RQ — sinon exposer un wrapper synchrone comme `retrain_if_needed`.)

### 2.2 Chiffre ROI public non honnête
`backend/api/routes/stats.py`, fonction `_vb_flat_backtest` (~ligne 67), utilisée par l'endpoint `/api/v1/stats/public` (~ligne 103-138) pour produire `roi_simule_6mois` (le +27,9 % affiché sur la home). Deux corrections possibles, à choisir selon ce que veut Thomas — recommandation : la première.

- **Option A (recommandée)** : appliquer le même correctif « cote figée » que `backend/ml/backtest.py` (`COALESCE(pr.cote_figee, p.cote_pmu)`) et `backend/ml/edge_monitor.py` dans `_vb_flat_backtest`, **et** ajouter la garde anti-backfill (`created_at < date_heure` de la course, comme fait dans `real_model_metrics` de `model_metrics.py` et dans `scripts/audit_reel.py`). Le chiffre restera peut-être positif mais sera honnête.
- **Option B** : remplacer purement `roi_simule_6mois` par `roi_reel` (déjà calculé dans `backend/api/model_metrics.py` ~ligne 148-159) sur la home publique, et déplacer/renommer le backtest optimiste en indicateur interne clairement labellisé « simulation ».

Demander confirmation à Thomas seulement si le choix A/B a un impact produit visible (le chiffre affiché sur la home pourrait devenir moins flatteur) — sinon avancer avec l'option A par défaut, plus fidèle à l'esprit « ROI≈0 honnête » du projet.

### 2.3 Vérifier `proba_*_raw`
`isotonic_calibration.py` avec le flag `calib_on_raw` (par défaut `True` dans le code local) suppose que `predict_course` (dans `pipeline.py`) écrit bien les colonnes `proba_top1_raw`/`proba_top3_raw` (migration `0024`). Si ces colonnes ne sont pas peuplées en prod, le `COALESCE` retombe silencieusement sur la proba déjà calibrée → boucle fermée réactivée sans erreur visible.

Vérifier : `grep -n "proba_top1_raw\|proba_top3_raw" backend/ml/pipeline.py` pour confirmer l'écriture, puis une fois déployé, sonder la table en prod (`SELECT proba_top1_raw FROM predictions ORDER BY created_at DESC LIMIT 20;`) pour confirmer que ce n'est pas NULL partout.

---

## Étape 3 — Nettoyage avant commit

```powershell
cd "C:\Users\thoma\Desktop\BlackTurf\blackturf"
echo "*.localbak" >> .gitignore
git rm --cached frontend/tsconfig.tsbuildinfo
git status -s | Select-String '\.localbak$'   # doit être vide de fichiers suivis
```

Fichiers `.localbak` à exclure (non suivis, à ne pas ajouter) :
`backend/api/routes/courses.py.localbak`, `backend/ml/bet_performance.py.localbak`, `backend/ml/features.py.localbak`, `backend/ml/models.py.localbak`, `backend/ml/pipeline.py.localbak`, `backend/ml/profil_learning.py.localbak`, `backend/services/mise_calculator.py.localbak`.

Vérifier aussi que `.env.production.template` modifié ne contient aucun vrai secret collé par erreur (c'est censé rester un template).

---

## Étape 4 — Commiter par thèmes (pas un seul commit fourre-tout)

Regrouper et commiter séparément pour garder un historique/rollback exploitable :

1. **Algo honnête / anti-fuite** : `backend/ml/features.py`, `pipeline.py`, `models.py`, `profil_learning.py`, `combo_bets.py`, `isotonic_calibration.py`, `algo_flags.py`, `elo.py`, `narrative.py`, `signal_performance.py` + nouveaux `ml/clv_monitor.py`, `ml/feature_health.py`.
2. **Mise / staking** : `backend/services/mise_calculator.py`, `backend/api/routes/bankroll.py`, `services/bet_catalog.py`, `bet_settlement.py`, + tests `test_mise_plan_quota.py`, `test_paris_multi_variance.py`.
3. **Scrapers live** : `backend/scraper/zeturf_live_daemon.py`, `genybet_live_daemon.py`, `paris_turf.py`, `geny.py`, `pmu.py`, `orchestrator.py`, `db_writer.py`.
4. **Frontend** : pages/composants modifiés + nouveaux `billing/CheckoutButton.tsx`, `HeroStats.tsx`, `LivePalmares.tsx` + images.
5. **Billing / Stripe** : `stripe_routes.py`, `setup_stripe_catalog.py`, `middleware/throttle.py`, `services/error_monitor.py`.
6. **Migration DB** : `backend/db/migrations/versions/0025_participation_valeur_handicap.py` + `db/models.py` (colonne nullable, idempotente, sûre — RAS).
7. **Scripts d'audit/ops** (utilitaires, sûrs) : `scripts/audit_reel.py`, `edge_leak_check.py`, `edge_truth_test.py`, `retrain_force_honest.py`, `backtest_edge.py`, etc.
8. **Tests restants**.

Messages de commit clairs (français, cohérents avec l'historique existant du projet, ex. `fix(ml): ...`, `feat(mise): ...`).

---

## Étape 5 — Vérifier l'`.env` prod avant/juste après le push

Sur le VPS, dans `/opt/blackturf/.env`, confirmer que ces flags valent `1`/`true` (défauts honnêtes du code local — s'assurer qu'ils sont bien explicités en prod et pas laissés à un défaut différent d'une ancienne version du code) :
`BT_TRAIN_PRERACE_ONLY`, `BT_GROUP_SPLIT`, `BT_DEVIG_GATES`, `BT_CALIB_ON_RAW`, `BT_EV_BAND_GATE`, `BT_ROI_DEPLOY_GATE`, `BT_STAKING_SAFE` (déjà activé selon commit `a15a0c3`).

---

## Étape 6 — Pousser et laisser le pipeline tourner

```powershell
git push origin main
```

Le pipeline (`.github/workflows/deploy.yml`) va : build+push images GHCR → SSH VPS → `docker-compose pull/up --no-build` → `alembic upgrade head` (applique la migration 0025, sûre) → health check → smoke test (`api.blackturf.fr/health` + `blackturf.fr`).

Suivre le run GitHub Actions jusqu'au bout. Si le smoke test échoue, ne pas laisser en l'état — investiguer les logs du conteneur `api` sur le VPS avant de considérer le déploiement terminé.

---

## Étape 7 — Vérification post-déploiement

```bash
ssh root@<IP_VPS> 'cd /opt/blackturf && git log -1 --oneline'
curl -s https://api.blackturf.fr/api/v1/health
curl -s https://api.blackturf.fr/api/v1/stats/public
```

Puis, idéalement, lancer `backend/scripts/audit_reel.py` contre la prod (lecture seule) pour mesurer le ROI honnête réel post-déploiement et confirmer l'absence de fuite — c'est l'outil de référence écrit spécifiquement pour ça.

**Ne pas lancer `retrain_force_honest.py`** sans confirmation explicite de Thomas : il bypass le gate de déploiement walk-forward et ne doit tourner qu'après `recompute_features_prerace` + confirmation que le builder de features leak-free est bien celui déployé.

---

## Ce qui reste au jugement de Claude Code / Thomas

- Le choix Option A vs B à l'étape 2.2 (impact sur le chiffre affiché publiquement).
- L'ordre exact des commits thématiques si des dépendances de code apparaissent entre thèmes (ex. le frontend `HeroStats`/`LivePalmares` consomme peut-être des champs ajoutés côté API — vérifier avant de commiter le frontend séparément du backend si un couplage fort existe).
- Si un service VPS est down à l'étape 1, prioriser sa remise en état avant tout push.

Rapport d'audit complet et détaillé (contexte, preuves, citations de lignes) : `C:\Users\thoma\Desktop\BlackTurf\AUDIT_COMPLET_2026-07-21.md`.
