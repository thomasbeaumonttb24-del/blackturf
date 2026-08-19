# Handoff SUITE → prochaine session Claude Code (accès complet au dossier)

**Date :** 2026-07-21 (soir). **Repo de travail :** `C:\Users\thoma\Desktop\BlackTurf\blackturf\` (⚠️ le vrai repo git est dans le sous-dossier `blackturf/`, PAS à la racine `BlackTurf/` dont le `.git` est vide).

Ce document remplace/complète `HANDOFF_CLAUDE_CODE_2026-07-21.md` (dont **la prémisse était fausse** — voir §0). Deux mandats à **garantir** : (1) l'entraînement de l'algo ne doit **plus jamais** planter ; (2) les **déploiements automatiques** doivent marcher.

---

## 0. État réel découvert (à lire en premier — le 1er handoff se trompait)

Le 1er handoff supposait « prod en retard sur le local, pousse le local ». **FAUX.** Réalité vérifiée en SSH :

- **La prod tourne des images buildées LOCALEMENT sur le VPS** (`docker compose build` depuis `/opt/blackturf`, dernier build 2026-07-13). Les services api/worker/scheduler/frontend sont en `build:` dans `docker-compose.prod.yml`, **aucune image GHCR**. Le pipeline `.github/workflows/deploy.yml` (pull GHCR + `up --no-build`) est **cassé/déconnecté** — un push sur `main` déclenche un deploy qui échoue au `docker pull ghcr...`.
- **Le VPS `/opt/blackturf` était 92 commits EN AVANCE sur origin/main** (divergence à `e9572f4` ~mi-juin). L'algo honnête / anti-fuite était **déjà live**. Migration 0025 déjà appliquée. `proba_top1_raw`/`proba_top3_raw` remplis en prod (998/998) → bug 2.3 du 1er handoff = **non-problème**.
- Le repo local Windows + origin/main = **branche divergente périmée**. Le VPS = source de vérité.
- **Réconcilié via PR #1** : https://github.com/thomasbeaumonttb24-del/blackturf/pull/1 (branche `reconcile-prod` = 92 commits VPS + 8 commits thématiques capturant le travail non commité + merge d'origin/main). **PR non mergée** — à revoir/merger par Thomas. CI verte sauf 6 tests ML env (voir §4).

Mémoires persistantes écrites : `blackturf-git-prod-reality-0721`, `blackturf-retrain-oom-0721`.

---

## 1. Accès

- **SSH VPS :** `ssh -i ~/.ssh/blackturf_vps root@167.233.60.99` (user `root`, hostname `blackturf`, repo `/opt/blackturf`). Clé aussi en `C:\Users\thoma\.ssh\blackturf_vps`.
- **Push origin :** seulement depuis le **local Windows** (credential manager OK). Le VPS peut `git fetch`/`pull` mais **pas push** (remote https sans creds, pas de `gh`).
- **Créer une PR sans `gh` :** récupérer le token via `git credential fill` puis `curl` l'API GitHub (voir la méthode utilisée, POST sur `/repos/thomasbeaumonttb24-del/blackturf/pulls` avec `--data-binary @fichier.json`).
- **Remote local `vps`** ajouté : `ssh://root@167.233.60.99/opt/blackturf` (pour fetch les branches du VPS ; utiliser `GIT_SSH_COMMAND="ssh -i ~/.ssh/blackturf_vps"`).

---

## 2. MANDAT 1 — l'entraînement de l'algo ne doit PLUS JAMAIS planter

### Cause racine (confirmée)
`ml.pipeline.retrain_if_needed()` (nightly 02:00 UTC, `backend/services/jobs.py:30` → enqueue RQ queue `ml`) était **OOM-killed chaque nuit** (kernel `global_oom`, signal 9 ; `Killed process (rq) total-vm 5.7GB anon-rss 4.6GB`, 19/20/21-07). VPS = 7,6 Gio RAM, swap 2 Gio **plein à l'idle**. → le modèle ne se réentraînait jamais ; seul `post_course_sync` (ingestion) tournait.

### Déjà fait (mitigation)
- **+4 Go swap persistant** sur le VPS (`/swapfile2`, dans `/etc/fstab`, total 2→6 Go). Le pic 4,6 Go a désormais la marge.
- **À VALIDER** : après le prochain 02:00 UTC, sur le VPS :
  ```bash
  journalctl -k --since "-6h" | grep -i oom-kill   # doit être VIDE
  docker compose logs --since 6h worker | grep -iE "nightly_retrain|retrain_if_needed|FailedJobRegistry"
  # doit montrer un retrain qui TERMINE, pas un "terminated unexpectedly signal 9"
  ```

### Fix DURABLE à implémenter (nécessite rebuild local VPS — voir §3 pour déployer)
1. **Cap la parallélisation** (cause du pic mémoire) : `backend/ml/models.py` utilise `n_jobs=-1` partout (lignes ~164, 182, 242, 250, 281, 359, 393, 564). Passer à `n_jobs=2` (ou piloté par une env `BT_TRAIN_NJOBS`, défaut 2). Réduit fortement la RAM ET laisse du CPU aux autres conteneurs.
2. **Libérer la mémoire** dans `retrain_if_needed()` (`backend/ml/pipeline.py:1987`) et `run_incremental_retraining()` (`pipeline.py:494`) : `del` des gros DataFrames + `import gc; gc.collect()` après chaque entraînement de modèle. Envisager de downcaster les features en `float32`.
3. **Cap mémoire conteneur worker** dans `docker-compose.prod.yml` (service `worker`, ~ligne 194) : ajouter une limite (ex. `mem_limit: 4g` ou `deploy.resources.limits.memory`) pour qu'un dépassement tue proprement LE JOB (RQ le déplace en FailedJobRegistry et peut retry) au lieu de faire un OOM **global** qui menace toute la prod.
4. **Bug 2.1 (retrain incrémental dans le process API)** : `backend/services/jobs.py:~96` fait `asyncio.create_task(run_incremental_retraining())` dans `job_drift_check` — contredit le design (« heavy CPU, don't run in API process », cf. `job_retrain_trigger` juste au-dessus). Le remplacer par un enqueue RQ identique :
   ```python
   import redis as sync_redis
   from rq import Queue
   from api.config import get_settings
   r = sync_redis.from_url(get_settings().redis_url)
   Queue("ml", connection=r, default_timeout=3600).enqueue(
       "ml.pipeline.run_incremental_retraining", result_ttl=86400)
   ```
   (Vérifier que `run_incremental_retraining` est enqueuable par RQ ; sinon exposer un wrapper sync.)
5. **Monitoring / alerte** (pour « plus jamais d'erreur » = être prévenu si ça revient) : `backend/services/error_monitor.py` existe. Ajouter une vérif quotidienne « le nightly_retrain de cette nuit a-t-il terminé ? » qui alerte (log/email/webhook) sinon. Idéalement écrire un enregistrement de succès (timestamp + AUC) que le healthcheck peut lire.

### Garde-fou
**NE PAS lancer `backend/scripts/retrain_force_honest.py`** sans confirmation explicite de Thomas — il bypass le gate de déploiement walk-forward. Ne doit tourner qu'après `recompute_features_prerace` + confirmation du builder de features leak-free déployé.

---

## 3. MANDAT 2 — les déploiements automatiques doivent marcher

### Problème
`.github/workflows/deploy.yml` (job `deploy`) fait, en SSH sur le VPS :
```
docker pull ghcr.io/.../blackturf-api:latest
docker-compose ... pull
docker-compose ... up -d --no-build
```
Or le compose n'a **aucune image GHCR** (que des `build:`). Le `pull` échoue → `set -e` → deploy rouge. La prod n'a jamais été déployée par ce CI ; elle est buildée à la main sur le VPS.

### Fix recommandé (Option A — coller à la réalité : build local sur le VPS)
Réécrire le job `deploy` (`.github/workflows/deploy.yml`, étape `Deploy via SSH`, script) :
```bash
set -e
cd /opt/blackturf
git fetch origin main
git reset --hard origin/main          # ⚠️ voir PRÉREQUIS ci-dessous
docker compose -f docker-compose.yml -f docker-compose.prod.yml build
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
docker compose exec -T api alembic -c db/migrations/alembic.ini upgrade head
sleep 10
curl -f http://localhost:8000/api/v1/health || exit 1
docker image prune -f
```
- Le job `build-push` (GHCR) peut être **supprimé** (inutile) ou gardé comme sauvegarde d'images sans que `deploy` en dépende (`needs:` à retirer).
- Le VPS peut `git pull` sans creds (vérifié). Pas de nouvelle clé nécessaire.

### PRÉREQUIS AVANT le 1er auto-deploy (sinon perte de données)
`git reset --hard` **écrase l'arbre de travail du VPS**. Aujourd'hui le VPS a encore ~50 fichiers non commités (capturés dans la PR #1 mais **pas encore sur `main`**). Donc, dans l'ordre :
1. **Merger la PR #1 sur `main`** d'abord.
2. Sur le VPS, resynchroniser une fois proprement :
   ```bash
   cd /opt/blackturf
   git stash -u          # filet de sécurité (au cas où)
   git fetch origin && git checkout main && git reset --hard origin/main
   git branch -D reconcile-prod   # nettoyage
   ```
   Vérifier que le tree = origin/main et que la prod rebuild/repart bien.
3. **Seulement ensuite**, activer l'auto-deploy (le `git reset --hard` du CI sera sûr car plus rien d'important n'est non commité).

### Option B (alternative — vrai pipeline GHCR)
Ajouter des clés `image: ghcr.io/thomasbeaumonttb24-del/blackturf-<svc>:latest` à côté de chaque `build:` dans le compose, garder `build-push`, et faire `pull + up`. Plus « propre » CI/CD mais + de config (login GHCR sur le VPS, tags). **Option A est plus simple et suffit.**

### Valider l'auto-deploy
Après le fix : faire un commit trivial (ex. bump commentaire), push `main`, suivre le run Actions jusqu'au bout (build+SSH+alembic+health), puis sur le VPS `git log -1` doit = le nouveau commit et `curl https://api.blackturf.fr/api/v1/health` = ok. Ne pas laisser un deploy rouge en l'état.

---

## 4. Reste à traiter (moindre priorité)

- **CI — 6 tests ML rouges** (`test_ml_units.py::test_model_*`) : `PermissionError/FileNotFoundError: '/app/models'`. Les tests hardcodent le chemin conteneur `/app/models`, absent du runner CI. **Env, pas régression.** Fix : rendre le chemin modèle configurable (env/tmp) dans le test ou le code, pour une CI verte.
- **Bug 2.2 — ROI public gonflé** : `backend/api/routes/stats.py` `_vb_flat_backtest` (~ligne 67) produit `roi_simule_6mois` (+27,9 % affiché) sans garde pré-départ ni cote figée. Appliquer le correctif « cote figée » (`COALESCE(pr.cote_figee, p.cote_pmu)` comme `backtest.py`/`edge_monitor.py`) + garde anti-backfill (`created_at < date_heure`), **ou** publier `roi_reel` (`model_metrics.py:~148`) à la place. Cohérent avec l'objectif ROI≈0 honnête. Impact produit visible (chiffre home) → **confirmer avec Thomas** le choix A/B.
- **Conteneur `frontend` unhealthy** : healthcheck refuse la connexion (24k échecs) mais `blackturf.fr` répond `200`. `docker-compose.prod.yml` dit en commentaire « Frontend → Vercel » alors qu'un conteneur frontend tourne. **Clarifier ce qui sert réellement `blackturf.fr`** (lire `nginx/nginx.runtime.conf` sur le VPS) : si c'est Vercel, le conteneur frontend est vestigial (le rendre non-bloquant ou le retirer) ; si c'est le conteneur, réparer son healthcheck.
- **`ProgrammeClient.tsx`** (`frontend/src/app/(main)/programme/`) : code mort (importé nulle part), laissé non commité volontairement. Le câbler ou le supprimer.

---

## 5. Objectif rappelé
Système de paris hippiques visant un **ROI≈0 sur le long terme en jouant TOUS les paris** → priorité à **l'honnêteté du modèle** (pas de fuite, pas de ROI affiché gonflé) et à une **boucle d'apprentissage qui tourne vraiment en continu**. Les deux mandats ci-dessus servent directement ce but : sans retrain nocturne qui aboutit, la boucle n'apprend pas ; sans déploiement fiable, les correctifs honnêtes ne partent pas en prod.
