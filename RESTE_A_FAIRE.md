# BlackTurf — reste à faire (état au 2026-08-16, 23h)

> **À coller tel quel au début d'une nouvelle conversation Claude Code.**
> Ce document est autoportant : il ne suppose aucun contexte des sessions précédentes.

---

## 0. Contexte projet (à lire avant tout)

**BlackTurf** = site de pronostics hippiques PMU avec ML. Objectif n°1 : **proposer des paris qui gagnent** (fiabilité, précision, rentabilité). Objectif n°2 : convertir les comptes Free en abonnés.

**Stack** : FastAPI + SQLAlchemy async + PostgreSQL/TimescaleDB · Next.js App Router · Docker Compose · XGBoost/LightGBM/CatBoost + calibration isotonique · RQ + APScheduler · Stripe (LIVE) · Resend (e-mail) · VAPID (push web).

**Accès**
- Repo local : `C:\Users\thoma\Desktop\BlackTurf\blackturf` (branche courante détachée sur `e2fbeef`)
- VPS prod : `ssh -i ~/.ssh/blackturf_vps root@167.233.60.99`, projet dans `/opt/blackturf`
- Prod : 18 comptes (**11 free**, 7 expert), disque à 28 % (105 Go libres)

### ⚠️ Comment se fait un déploiement (LIRE, c'est contre-intuitif)

**Il n'y a pas de CI/CD.** Le code est **baké dans les images Docker**. Déployer =

1. copier les fichiers modifiés du repo local vers `/opt/blackturf` sur le VPS (`scp`)
2. rebuilder l'image concernée (`api`, `frontend`, `worker`, `scraper`)
3. `docker compose ... up -d` sur le service

**Le dépôt git du VPS n'est PAS la source de vérité.** Son HEAD est resté sur `554ef08` et son arbre de travail contient **18 fichiers modifiés/non suivis** correspondant à tout le travail déployé mais jamais committé côté VPS. Le repo local (HEAD `e2fbeef`) est la référence. Ne jamais faire `git checkout`/`git reset` sur le VPS : ça effacerait du code en production.

---

## 1. 🔴 PRIORITÉ 1 — Lire le rapport de retrain du matin

**Le point le plus important.** Le modèle est **gelé sur v503 depuis le 29/06** (48 jours au 16/08). Deux causes ont été corrigées le 16/08 (commits `39d5340`, `bf08f22`) : gate de promotion cassé + OOM nocturne. **La première nuit avec le correctif est celle du 16→17/08 — le résultat n'était pas encore connu à la clôture de la session.**

Un rapport e-mail automatique arrive désormais **chaque matin à 07:00 Paris** sur `thomas.beaumont.tb24@gmail.com` (cron VPS `0 5 * * *` → `/opt/blackturf/scripts/check_retrain_cron.sh`, commit `e2fbeef`).

**Ce qu'il faut faire :** demander à Thomas le contenu du mail, ou relancer le rapport à la demande :

```bash
ssh -i ~/.ssh/blackturf_vps root@167.233.60.99 "/opt/blackturf/scripts/check_retrain_cron.sh"
```

**Action selon le verdict :**

| Verdict | Signification | Action |
|---|---|---|
| ✅ `promu` | 1re promotion depuis 48 jours | L'apprentissage est reparti. Surveiller le ROI 7 j. |
| ⚠️ `rejete` | Challenger battu par le champion | Normal ponctuellement. **Si ça se répète 3+ nuits** → le gate h2h est encore trop strict, comparer avec `backend/scripts/check_h2h_champion.py`, envisager d'assouplir `h2h_tolerance` (actuellement `0.002` dans `backend/ml/pipeline.py::_should_deploy`). |
| 🔴 `oom` | Tué par manque de mémoire | Réduire la fenêtre de données d'entraînement ou `BT_TRAIN_NJOBS`, ou augmenter la limite mémoire du worker dans `docker-compose.prod.yml`. Le swap de +4 Go déjà en place ne suffit alors pas. |
| ⚠️ `incomplet` | Démarré, ni promu ni rejeté ni OOM | Inspecter la `FailedJobRegistry` RQ et les logs worker. |
| 🔴 `absent` | Le job n'a pas démarré | Vérifier `blackturf_scheduler` et l'enregistrement du job 02:00 UTC. |
| ❓ `inconnu` | Logs illisibles | Droits Docker / conteneur worker absent. |

Diagnostic manuel :
```bash
ssh -i ~/.ssh/blackturf_vps root@167.233.60.99 "docker logs blackturf_worker --since 12h | grep -E 'h2h.measured|retrain.deployed|retrain.rollback|signal 9|MemoryError'"
```

---

## 2. 🔴 PRIORITÉ 2 — Déployer le « point 5 » (e-mails hebdo de conversion)

**Seul code committé mais JAMAIS déployé.** Vérifié le 16/08 : `alerts.py` sur le VPS date du **5 juin**, et l'image `api` ne contient **aucune** des nouvelles fonctions (`grep -c job_weekly_recap` → `0`).

**Commits concernés :** `1904395` puis `07e92c4`.

**Fichiers à déployer :**
```
backend/services/alerts.py                          (+240 lignes)
backend/services/jobs.py                            (+25 lignes)
backend/api/routes/notifications.py                 (route de désabonnement)
backend/db/models.py                                (colonne marketing_opt_out_at)
backend/db/migrations/versions/0026_user_marketing_opt_out.py
frontend/src/app/(main)/desabonnement/page.tsx      ⚠️ FRONTEND AUSSI
```

**Ce que ça fait :** chaque **lundi 09:00 Paris**, un job APScheduler identifie le meilleur value bet **réellement gagnant** de la semaine écoulée (EV max parmi les ★★★+ gagnants, avec rapport PMU Simple Gagnant réellement publié) et l'envoie par e-mail + push aux comptes **Free/Découverte uniquement**, avec CTA vers `/tarifs`.

**Garde-fous déjà codés (ne pas les affaiblir) :** garde anti-backfill (le value bet doit avoir été détecté **avant le départ**) ; si aucun value bet ★★★+ n'a gagné, ou si le rapport PMU n'est pas publié, **le job n'envoie rien** — jamais de gain approximé. Lien de désabonnement RGPD + mention jeu responsable.

### ⚠️ Bloquant : la migration 0026 n'est PAS appliquée en prod

Vérifié : `alembic_version` = **0025**, colonne `users.marketing_opt_out_at` **absente**. Déployer le code sans la migration ferait planter le job et la route de désabonnement.

**Ordre impératif :**
1. `scp` des 6 fichiers vers le VPS
2. rebuild image `api` **et** image `frontend` (`--no-cache` pour le frontend, voir §8)
3. **appliquer la migration** : `docker compose ... run --rm api alembic upgrade head` → vérifier que `alembic_version` passe à `0026`
4. `up -d` sur `api`, `frontend`, `scheduler`
5. vérifier l'enregistrement du job : `docker logs blackturf_scheduler | grep -i weekly`

`RESEND_API_KEY` est **déjà en place et testée** en prod (envoi réel confirmé). Domaine `blackturf.fr` vérifié chez Resend (région Ireland), 3 enregistrements DNS posés dans OVH sur le sous-domaine `send` — les SPF/MX racine d'OVH sont **intacts**, aucun conflit.

---

## 3. 🟠 PRIORITÉ 3 — Vérifier en navigateur l'essai gratuit du calculateur

Le « point 2 » du tunnel de conversion (calculateur de mise offert 1×/jour aux comptes Free) est **déployé et testé unitairement**, mais **jamais vu fonctionner dans un vrai navigateur** — il n'y avait aucune course `a_venir` au moment du test.

**Backend :** `backend/api/routes/courses.py`, `MISE_PLAN_DAILY_LIMITS = {"free": 1, "decouverte": 1, "standard": 6, "starter": 6}` et `_mise_plan_quota_check()`, la réponse expose `quota_restant`.

**À faire :** créer un compte Free, aller sur une course à venir, utiliser le calculateur, vérifier que le 2ᵉ essai du jour affiche bien la limite + le CTA d'abonnement, puis **supprimer le compte de test** (la prod n'a que 18 comptes réels).

> ⚠️ **Piège vécu :** un test « déconnecté » qui n'en était pas. Un `localStorage` périmé contenait un utilisateur `plan:expert` d'un compte QA supprimé, ce qui masquait complètement la bannière. **Toujours vider le `localStorage`** avant un test de non-abonné, pas seulement se déconnecter.
> Ce même incident a révélé un **bug réel encore présent** : `useAuth` conserve le plan périmé quand les tokens disparaissent. À corriger (`frontend/src/hooks/useAuth.ts`).

---

## 4. 🟠 PRIORITÉ 4 — Envoyer l'e-mail d'annonce aux 11 comptes Free

Un e-mail d'annonce a été rédigé mais **jamais envoyé** — il attend le feu vert de Thomas. Resend est opérationnel.

### ❌ Règle non négociable sur le contenu

**Ne JAMAIS écrire « avec l'abonnement vous auriez gagné X € ».**

Deux raisons, et Thomas a validé cette contrainte :
1. **C'est factuellement faux.** ROI réel sur 30 jours réglés : conservateur **−2,5 %**, équilibré **−1,5 %**, agressif **+37 % MAIS médiane −100 %** et seulement **86 gagnants sur 1314**. Le +37 % est porté par quelques gros coups, non reproductible pour un utilisateur moyen.
2. **Risque légal ANJ** (régulateur français des jeux d'argent) : promesse de gain interdite.

**Arguments vrais et utilisables :** 18 090 courses analysées · 60 % de réussite top-3 · favori IA placé dans 65,7 % des cas · exemples individuels réels via `GET /courses/{id}/favori-ia-resultat`.

---

### Grille de quotas (arrêtée le 16/08, déployée — commits `29ed480` + `0587327`)

| | Free / Découverte | Standard / Starter | Expert |
|---|---|---|---|
| Classement IA (`PRONO_DAILY_LIMITS`) | 1/jour | 5/jour | illimité |
| Plan de mise (`MISE_PLAN_DAILY_LIMITS`) | 1/jour | 5/jour | illimité |
| Paris de valeur | ❌ | délai 15 min | temps réel |

Les deux tables doivent rester **strictement identiques** — elles avaient divergé en silence (Free 2 vs 1). 3 tests le verrouillent dans `backend/tests/test_mise_plan_quota.py`. Expert est illimité **par absence de la table** : ne jamais y ajouter `expert`.

---

## 5. 🟡 Non résolu — Réception de `contact@blackturf.fr`

**Symptôme :** les mails entrants sont **perdus silencieusement** (ni livraison, ni rebond) depuis environ le **23 juin**. Testé depuis Gmail **et** depuis un autre fournisseur : rien n'arrive, ni sur Zimbra ni en redirection.

**Ce qui a été écarté :** Zimbra fonctionne (dernier mail reçu le 23/06 bien visible) ; les diagnostics OVH MX/SPF/DKIM affichent tous « Configuration OK ».

> ⚠️ Ce diagnostic OVH vérifie les **enregistrements DNS**, pas la **propriété interne du service**. Il ne prouve donc rien sur l'hypothèse ci-dessous — j'ai eu tort de conclure trop vite que l'hypothèse était fausse sur cette seule base.

**Hypothèse restante :** le domaine est **aussi** rattaché à une offre **MX Plan** `redirect` (0 boîte, 0 redirection) → conflit de routage interne côté OVH, qui absorbe les mails avant Zimbra.

**Test réversible proposé :** créer une redirection dans MX Plan et voir si les mails réapparaissent.

**Non vérifiable à distance** : le port 25 sortant est bloqué sur le VPS, impossible de tester la livraison SMTP depuis là.

**Sans impact sur Resend** (envoi ≠ réception) — les e-mails sortants fonctionnent.

---

## 6. 🟡 Risque latent — Daemons live sans watchdog

`backend/scraper/orchestrator.py` a reçu un anti-gel le 16/08 (commit `60d8bbb`) après un **freeze silencieux de 4 j 16 h** :
`CYCLE_TIMEOUT_S=1200`, `WATCHDOG_GRACE_S=120`, heartbeat sur disque, watchdog en **`threading.Thread`** (délibérément pas une tâche asyncio : une tâche asyncio ne s'exécute jamais si la boucle est affamée — c'était précisément le cas de panne) qui appelle `os._exit(1)`.

**Deux daemons ont le même schéma de gel et AUCUN watchdog :**
- `backend/scraper/zeturf_live_daemon.py`
- `backend/scraper/genybet_live_daemon.py`

À traiter en réappliquant le même patron (heartbeat + watchdog thread + `healthcheck.py`).

---

## 7. 🟡 Autres points ouverts

- **Webhook Stripe LIVE jamais exercé.** Stripe est en LIVE (compte `acct_1TkiLHFiAG0jVlcj`), le tunnel a été testé bout-en-bout **en mode test uniquement**. **Le premier abonné réel sera le premier test.** Si son `user.plan` ne change pas : `docker logs blackturf_api | grep stripe.webhook`.
- **Juger les correctifs ROI à J+7 / J+14.** Déployés le 02/07 : gate bande EV, cap combo 1.55, calibration globale des rapports, catchup de règlement, suppression des 0-gain. Références ROI 7 j avant correctif : −29 / −39 / −14 %.
- **Value bets — seuils recalibrés le 16/08** (`backend/ml/valuebets.py`, commit `bf08f22`) : `MAX_MODEL_MARKET_RATIO` 1.55→1.67, `LONGSHOT_COTE_MIN` 4.0→20.0, `COTE_MAX_VB` 25→40, nouveau `SHORT_COTE_MAX = 4.0` découplé. Cause racine : seuils périmés jamais recalibrés (il y avait un TODO en commentaire dans le code). **Vérifier que les value bets sont bien réapparus en volume.**
- **Scrapers désactivés en prod** : `SCRAPER_DISABLED_SOURCES=racing_post,turfoo,france_galop,zeturf`. Vérifier si `zeturf` peut être réactivé, ou si c'était volontaire.
- **Cache Docker** : 84 Go purgés le 16/08 (81 % → 28 %). Ça regrossit à chaque rebuild → purge périodique à prévoir.
- **Ménage VPS** : un fichier `_backup_20260816_205725_env_resend` traîne dans `/opt/blackturf` — **c'est une sauvegarde de `.env`, elle contient des secrets**. À supprimer après vérification.
- **Modifications locales non committées** : `frontend/src/app/(auth)/inscription/page.tsx` est modifié dans le repo local. Vérifier ce que c'est avant de committer ou jeter.
- **Certificat SSL** valide jusqu'au **14/11/2026**, renouvellement auto réparé.

---

## 8. ⚠️ Pièges de déploiement (chacun a coûté du temps le 16/08)

1. **Gate pytest en conteneur** → `-e ENVIRONMENT=test` **obligatoire**, sinon **34 faux échecs** `Invalid host header` (le vrai `ENVIRONMENT=production` du conteneur écrase le `setdefault` de `conftest`). Il faut aussi monter `/opt/blackturf/backend/tests`, absent de l'image.
2. **Build frontend en moins de 10 s = build entièrement caché** qui n'embarque **aucune** modification, tout en affichant « Built ». Un vrai build prend ~50 s. → utiliser `--no-cache`.
3. **Sessions Claude parallèles sur le même repo/VPS.** Deux incidents réels : un correctif a **disparu du disque du VPS** entre deux déploiements ; un `git add` lancé depuis le mauvais dossier a committé le travail d'une autre session sous un message qui ne lui correspondait pas. → toujours vérifier `pwd`, lister les fichiers explicitement, et **re-vérifier qu'un correctif précédent est toujours en place** avant de rebuilder.
4. **OVH Manager non pilotable** par les outils navigateur (DOM et scroll inaccessibles). Contournement : `left_click_drag` sur la barre de défilement (x ≈ 1140) puis clics aux coordonnées.
5. **Ne jamais confondre « la ligne existe » et « la variable a une valeur ».** Erreur commise sur les 7 variables Stripe : toutes présentes dans `.env`, toutes **vides** (0 caractère). → vérifier la longueur des valeurs, pas la présence des clés.

---

## 9. Procédure de test avant déploiement

```bash
# Suite complète : 636 tests, tous verts au 2026-08-16
cd backend && python -m pytest -q
```

Toute régression sous 636 doit être expliquée avant de déployer.

---

## 10. Historique — ce qui a déjà été corrigé (ne pas re-auditer)

Gel silencieux du scraper (4 j 16 h) · modèle gelé 48 jours (deux causes cumulées) · renouvellement SSL + piège de bind-mount caché · tunnel Stripe inexistant + clés vides + endpoint webhook orphelin au secret inconnu · zombie oddschecker · échec du drift-check **toutes les heures depuis toujours** (`bb8bc97`) · extinction des value bets (seuils périmés) · contournement du paywall WebSocket (`3563641`) · quotas du calculateur de mise (`4ef13d6`) · 7 échecs de tests (dont un révélant un correctif de prod jamais déployé) · 84 Go de disque récupérés · surveillance automatique du retrain (`e2fbeef`).

**Documents de référence dans le repo :** `HANDOFF_2026-08-16_SOIR.md` (détail complet de la session d'audit).
