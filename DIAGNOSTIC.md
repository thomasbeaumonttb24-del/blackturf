# DIAGNOSTIC BlackTurf — audit complet algo + site

> Audit read-only du 2026-06-11. Aucune modification effectuée. Liste exhaustive des problèmes à corriger.
> Chemins relatifs à `blackturf/`. Sévérité : **CRITIQUE** / **MAJEUR** / **MINEUR**.

---

## 0. TOP PRIORITÉS (à attaquer en premier)

| # | Fichier:ligne | Sév | Problème en 1 ligne |
|---|---|---|---|
| 1 | `backend/ml/pipeline.py:1018-1019` | ✅ FIXÉ | `numero`=rang_cote (pas le dossard) et `nom`="" → TOUS les tickets/recos/alertes désignent le mauvais cheval |
| 2 | `backend/ml/post_race_analyzer.py:545,612` | ✅ FIXÉ | Colonnes SQL inexistantes → synthèse perf + déclencheur ré-entraînement TOUJOURS en échec → auto-apprentissage mort |
| 3 | `backend/ml/signal_performance.py:54,122` + `edge_monitor.py:27` | ✅ FIXÉ | Leakage backfill : multiplicateurs de signaux appris sur features reconstruites a posteriori |
| 4 | `backend/ml/meta_learner.py:48-65` + `services/jobs.py:61` | ✅ FIXÉ | Encodage discipline/terrain toujours -1 (casse) + méta-modèle JAMAIS sauvegardé |
| 5 | `frontend` (9 pages) | ✅ FIXÉ | Palette dark résiduelle (`text-*-400` sur fond blanc) → contraste illisible, échec WCAG |
| 6 | `backend/ml/portfolio.py:455-495,562` | MAJEUR | EV inventées en dur (0.35/0.25/0.15) injectées dans l'allocation → viole « zéro fausse donnée » |
| 7 | `frontend/.env.local:5` | ✅ VÉRIFIÉ SÛR | `NEXTAUTH_SECRET` : NON tracké par git (gitignore OK), prod template = CHANGE_ME, next-auth installé mais inutilisé → aucune expo. Aucun changement code requis. |
| 8 | `frontend/src/hooks/useWebSocket.ts:19` | ✅ FIXÉ | JWT en query string → fuite credential dans logs proxy |

---

## 1. ALGORITHME — cœur prédiction & mise

### 1.1 Corruption d'identité des chevaux — CRITIQUE
- **`ml/pipeline.py:1018-1019`** — `"numero": feat.get("rang_cote", i+1)` et `"nom": feat.get("nom","")`. `features.py` n'émet jamais `numero` ni `nom`. Résultat : `numero` = rang par cote (1=favori), pas le dossard réel ; `nom` = "" constant. Ce dict alimente combo_bets, recommandations, mise_calculator, narrative, alertes → **tous les paris désignent le mauvais cheval, nom vide**. → corriger features.py pour émettre vrai numero/nom, ou récupérer depuis Participation/Cheval.

### 1.2 Probabilités combinées fausses — MAJEUR
- **`services/mise_calculator.py:781,826,874`** — Couplé `p1*p2*2`, Trio `p1*p2*p3`, 2sur4 produits indépendants : suppose l'indépendance alors que les victoires sont mutuellement exclusives → EV systématiquement biaisée (souvent surestimée). combo_bets le fait correctement par Plackett-Luce ; ces formules analytiques sont l'ancienne voie.
- **`ml/combo_bets.py:78-79`** + **`services/bet_settlement.py:145`** — Couplé Placé : proba calculée sur top-3 fixe quelle que soit la taille du champ, mais règlement sur places réelles (2 si <8 partants) → proba ≠ résultat, EV/rapport incohérents.

### 1.3 Kelly faux — ✅ FIXÉ
- **`ml/valuebets.py:392`** `calculer_mise_kelly` `/cote` → `/(cote-1)` + docstring corrigée.
- **`ml/portfolio.py:762`** `_kelly` `/cote` → `/(cote-1)`.
- **`ml/portfolio.py:772`** `_kelly_outsider` `/cote` → `/(cote-1)` (sizing signal documenté).
- **`ml/portfolio.py:1050`** `kelly_fraction_adaptatif` inversion proba `ev/b + 1/cote` → `(ev+1)/cote` (exacte).
- **`ml/recommendations.py:314`** `_kelly_mise` `/cote` → `/(cote-1)` + retour 0 (pas 2€) sur EV≤0.
- Tests (`test_ml_units` Kelly) = inégalités/ratios → passent inchangés. Vrais Kelly déjà OK ailleurs (monte_carlo, mise_calculator `_allocate_kelly`).

### 1.4 EV / probas fabriquées — MAJEUR (viole zéro-fausse-donnée)
- ✅ FIXÉ **`ml/portfolio.py` OMEGA (Quinté Flexi/Tiercé/2sur4)** — EV en dur 0.35/0.25/0.15 → `None` (EV combo parimutuel non calculable fiablement ; couverture réelle via `simulate_portfolio_coverage`). `ev_moyen` OMEGA → None.
- ✅ FIXÉ **`ml/portfolio.py` DELTA (`_detect_delta_candidates`)** — `ev_signal = cote*(proba_top3+force*0.3)-1` (placé + gonflement) → EV RÉELLE `cote*proba_top1 - 1` (souvent négative = honnête ; force_signal reste exposée à part). `ev_moyen` DELTA sur EV réelles, None si aucune.
- ✅ FIXÉ **consumers None-safe** — `priority_score` (`ev_moyen or 0`), `ev_scenarios` (filtre None), `_note_globale`/`_compute_allocation` OK.
- ✅ FIXÉ **`ml/recommendations.py`** — Trio `ev_calcule: 0.15` → None ; Tiercé `vbs_forts[0].ev_max` (EV d'un seul cheval pour un combo) → None (cohérent avec bloc Quarté+).
- ✅ FIXÉ (étape 9) : Kelly circulaire `portfolio:1050`, `_kelly_mise` défaut 2€, formule `/cote`→`/(cote-1)` partout. Reste `_P1_FROM_P3=0.35` (repli acceptable si proba_top1 absente — déjà préférée, MINEUR).

### 1.2 / 1.9 Code mort `mise_calculator._plan_*` (probas `p1·p2·2`) — ✅ SUPPRIMÉ (étape A)
~210 lignes mortes retirées : `_plan_micro/simple/standard/complet/premium` + `_rapport_*` (9 fns) + `PROFIL_ALLOCATION` + `_finaliser` + `_resume` (tous devenus 0-caller). Probas fausses (`p1·p2·2`, produits indépendants) + rapports magiques éliminés. Live `generer_plan` intact (`enumerate_bet_candidates`+`_select_conviction`+`_allocate_kelly`). Compile OK. `cout_combo` (recommendations) arrangements→`math.comb` ✅.

### 1.5 Calibration & biais longshot — MAJEUR/MINEUR
- **`ml/valuebets.py:274-275`** — cap court-cote discontinu : zone cote 3.9-4.1 traitée par seuils durs.
- **`ml/cote_calibration.py:52-53`** — détermine le gagnant via `classement->0` en supposant index 0 = 1ère place ; ailleurs le code trie par position car l'ordre n'est PAS garanti → calibration win faussée si `classement` non trié.
- **`ml/combo_bets.py:166,305,479`** — rapport `TRJ/p_market` plafonné 5000-100000 → EV jackpot structurellement gonflable sur proba minuscule, peut recommander jackpots à fausse EV+.
- **`ml/combo_bets.py:331`** vs **`valuebets`** — politiques OPPOSÉES sur longshots : combo réintroduit cotes ≥8 en « coup », valuebets les bloque. Incohérence de philosophie.
- **`ml/isotonic_calibration_top3.py:136`** — clip à 0.99 après mise à l'échelle casse la contrainte Σ=target.
- **`ml/longshot_calibration.py:48`** / **`cote_calibration.py:121`** — `FACTOR_MAX` 1.5-1.8 autorise un BOOST de proba (favorise faux VB court) ; capé shrink-only seulement dans valuebets, pas globalement.

### 1.6 Monte-Carlo / portfolio — MAJEUR/MINEUR
- **`ml/monte_carlo.py:203-209`** — max-drawdown calculé sur l'ordre arbitraire des paris (pas temporel) + normalisé par total_stake (pas le pic d'equity) → métrique trompeuse.
- **`ml/monte_carlo.py:180-181`** — paris modélisés en Bernoulli indépendants (faux intra-course, un seul gagnant). portfolio_simulator corrige via Plackett-Luce ; vérifier que monte_carlo n'est plus utilisé pour valider des paris intra-course.
- **`ml/monte_carlo.py:220`** — CVaR sur `roi < p5` strict → tail vide possible, sous-estime risque de queue (utiliser `<=`).
- **`ml/portfolio.py:843-864`** — Markowitz : matrice cov rank-1+diag souvent singulière → `inv` échoue silencieusement, dégénère en fallback ; mises négatives écrasées dénaturant l'optim.

### 1.7 Modèles / features — MAJEUR/MINEUR
- **`ml/models.py:758`** / pipeline:758 — fallback `p3**1.6` exposant arbitraire non normalisé probabilistiquement, injecté dans EV gagnant.
- **`ml/pipeline.py:657-665,731`** — calibration adaptative appliquée à top3, puis top1 DÉRIVÉE ; si `win_model` existe, P(victoire) court-circuite la calibration adaptative → EV incohérente selon présence du modèle.
- **`ml/pipeline.py:944`** — double conversion steam_move Betclic (`*100`) : unité non garantie, risque saturation permanente.
- **`ml/pipeline.py:913,927`** — `confidence_score` stocké ×100 mais relu en brut ailleurs → mélange d'échelles 0-1 / 0-100.
- **`ml/models.py:262,274`** — accès `.calibrated_classifiers_[0].estimator` fragile selon version sklearn, entouré de `try/except pass` → feature_importance/SHAP silencieusement vides.
- **`ml/models.py:35`** — `MODELS_DIR=Path("/app/models")` en dur + mkdir au niveau module → couplage Docker.
- **`ml/features.py`** (winrate jockey/sire/entraîneur, l.1029-1079, 1947-1959) — taux absent imputé `0.0` (= 0% de réussite avéré, pas neutre) → pénalise le cheval. Préférer moyenne population + flag `*_is_missing`.

### 1.8 ELO / dynamique / confrontations — MINEUR
- **`ml/elo.py:130-131`** — ELO global bougé de `Σ(delta)/2` sur tous les duels → inflation sur gros champs (16 duels) vs petits.
- **`ml/elo.py:94`** — `getattr(cheval, elo_field, ELO_INITIAL)` renvoie `None` si colonne NULL → TypeError dans expected_prob.
- **`ml/race_dynamics.py:60-61`** — parse temps ambigu : « 130 » = 130s ou 1'30 (90s) selon source.
- **`ml/confrontation_features.py:81`** — `setdefault` garde la 1ère ligne, pas la plus récente.
- **`services/confrontations.py:38-40,167`** — appariement courses par (date, hippodrome) seul → 8 courses d'une réunion fusionnées, chevaux jamais affrontés comptés comme rivaux. Ajouter n°/heure de course à la clé.

### 1.9 Code mort algo — MAJEUR
- **`services/mise_calculator.py:736-922`** — `_plan_micro/simple/standard/complet/premium` + `_rapport_*` : ~190 lignes jamais appelées par `generer_plan` (qui passe par enumerate_bet_candidates), avec probas/rapports hardcodés incohérents avec combo_bets. Confirmer non-appel puis supprimer.
- **`ml/adaptive_learning.py:354-416`** — `update_from_feature_attribution` jamais appelée (apprentissage contrastif non branché).
- **`ml/combo_bets.py:84-86`** — `p_tierce_ordre` jamais utilisé (Tiercé passe par désordre).

---

## 2. APPRENTISSAGE — sous-système largement inopérant

### 2.1 Boucles d'apprentissage mortes (mismatch schéma) — CRITIQUE
- **`ml/post_race_analyzer.py:545-558`** (`get_performance_summary`) — lit `brier_course/log_loss_course/top3_precision/created_at` ; vrais noms = `brier_score/log_loss/analyzed_at`, `top3_precision` inexistant → exception → renvoie `{}`. Synthèse perf TOUJOURS vide.
- **`ml/post_race_analyzer.py:612-637`** (`should_retrain`) — même mismatch → renvoie `(False,"erreur")` à chaque appel → ré-entraînement JAMAIS déclenché par ce chemin.
- **`ml/post_race_analyzer.py:575-599`** (`get_bias_report`) — `taux_erreur` n'existe pas sur `bias_matrix` → renvoie `[]`. Rapport biais toujours vide.

### 2.2 Méta-learner inopérant — CRITIQUE/MAJEUR
- **`ml/meta_learner.py:48-65,82-93`** — `_DISCIPLINE_MAP`/`_TERRAIN_MAP` clés capitalisées (`"Plat"`) mais rll stocke en minuscules → `_encode` renvoie -1 systématique → features discipline/terrain constantes, le méta-modèle n'apprend rien de sa raison d'être.
- **`services/jobs.py:61`** — teste `status=="trained"` mais train renvoie `status=="ok"` → branche `ml.save()` jamais prise → **modèle ré-entraîné nightly jamais persisté**.
- **`ml/meta_learner.py:96-100`** — `_encode_hippodrome` via `hash()` (PYTHONHASHSEED randomisé) → encodage différent entre entraînement et inférence.
- **`ml/meta_learner.py:355,369-374`** — `rang_cote=1/base_proba*0.5` (colinéaire), `jours_repos=20`, `elo_vs_moyenne=0`, `forme=0.5`, `spi=0` → 5/14 features sont des constantes à l'entraînement.

### 2.3 Leakage backfill dans l'apprentissage — CRITIQUE
> La règle « palmarès = pronos figés avant départ, hors backfill » est respectée côté API (stats.py:978-980, courses.py:1063) mais **absente de tout le ML**.
- **`ml/signal_performance.py:54-62,122-134`** + **`edge_monitor.py:27-36`** — jointures sans filtre `meta.backfill != true` ni `created_at < date_heure` → multiplicateurs de signaux (utilisés en prod pour sélectionner les value bets) appris sur features reconstruites.
- **`ml/post_race_analyzer.py:474-527`** (`_update_bias_matrix`) — `correction_factor` (appliqué en inférence) appris sur courses backfillées.
- **`ml/meta_learner.py:282`** — label `top3_precision` appris sur courses possiblement reconstruites.
- **`ml/signal_performance.py:56`** — win via `classement->0` (suppose ordre trié).

### 2.4 Drift detector — MAJEUR/MINEUR
- **`ml/drift_detector.py:468-472,256-282`** — Page-Hinkley alimenté par un taux DÉJÀ lissé (moyenne glissante) → `cumsum` dominé par `-alpha`, `ph≈0` en permanence → Signal 2 quasi mort.
- **`ml/drift_detector.py:685,511-514`** — `severity` persistée = CRITICAL dès qu'un drift a existé, jamais remis à NONE → DB affiche « critical » à vie.

### 2.5 Settlement / ROI — MAJEUR
- **`services/bet_settlement.py:253-256,229-236`** — ROI provisoire artificiellement négatif tant qu'un rapport manque (mise comptée, gain exclu) ; risque d'agrégation biaisée dans `compute_profil_weights`.
- **`services/bet_settlement.py:153-165`** — 2sur4 : vérifier si `mise` stockée est unitaire ou totale (risque gain divisé deux fois).
- **`ml/recommendations.py:199-211`** — 2sur4 `mise_suggeree`=coût total ET `cout_total` → si settlement traite comme mise/combinaison, multiplie encore.
- **`ml/recommendations.py:73-81`** — coûts Tiercé/Quarté/Quinté en arrangements `n(n-1)(n-2)` au lieu de `C(n,k)` désordre → surévalue ×6/×24.

### 2.6 Adaptive learning — MAJEUR/MINEUR
- **`ml/adaptive_learning.py:113,115`** — `FEATURE_TO_GROUP` définit `"form_vs_career_rate"` deux fois (bounce écrasé par career).
- **`ml/adaptive_learning.py:337-352`** — branche température `brier>0.22` applique double facteur 0.5 (≈0.25×), probablement non intentionnel.
- **`services/jobs.py:90-95`** — drift critique → `run_incremental_retraining` via `asyncio.create_task` non awaité dans job APScheduler → peut être GC avant exécution, exceptions silencieuses.

### 2.7 Profil learning — MINEUR
- **`ml/profil_learning.py:160-172`** — upsert n'écrase un run que si `statut='pending'` → un run `partial` n'est pas mis à jour avant départ (« dernier prono fait foi » non respecté).

---

## 3. BACKEND API — routes

### 3.1 Fausses données / métriques non masquées — CRITIQUE/MAJEUR
- ✅ FIXÉ **`api/routes/stats.py:47-62`** — `_STATIC_STATS`/`_STATIC_CURVE` supprimés (étaient morts ; bombe à retardement éliminée).
- ✅ FIXÉ **`api/routes/predictions.py:685-686`** (`GET /model/version`, **public**) — `auc_roc` → `m_real["auc_roc"]` (masqué) ; `brier_score` → `plausible_brier()` (nouveau helper, ]0,0.5]). AUC 0.06 / Brier seed plus exposés.
- ✅ FIXÉ **`api/routes/stats.py:254-255`** — drift défauts 0.20/0.30 → None si non mesuré.
- ✅ FIXÉ **`api/routes/assistant.py:191-210`** — remplacé par `real_model_metrics` (garde AUC + masquage unifié) → plus de précision publiée sans crédibilité AUC.
- **`api/routes/admin.py:421-423,82`** — `precision_top3`/`auc_roc` bruts (admin, mineur).
- **`api/routes/admin.py:1016`** — prix abonnement hardcodés pour MRR/ARR (peut diverger de Stripe).

> **✅ ÉTAPE C FIXÉE (backend API MAJEUR)** — compile OK :
> - `/jockeys` : requête morte à jointure cartésienne supprimée + `position` réelle (LEFT JOIN historique).
> - `stats` P&L mensuel : vrais mois calendaires (plus de `now − 30·i`). ROI par discipline : ne compte que les paris réglés (mise/gain cohérents).
> - `vb_performance` : pari sans arrivée publiée → ignoré (plus compté perdant → ROI faussé).
> - `auth PATCH /me` : validation profil_risque (enum) + bankroll_initiale (numérique, >0, plafonné).
> - `push-subscription` : forme validée + sous-ensemble assaini (anti stored-XSS).
> - `admin ingest` : `secrets.compare_digest` (anti timing-attack).
> - `strategies` : garde `elo_score_global or 0` (plus de crash None < float).
> - **rate-limit** : `rate_limit_predictions` branché sur `/predict`, `/analyse`, `/portfolio` (anti-abus calcul + coût Claude).

### 3.2 Bugs SQL / agrégations — MAJEUR
- **`api/routes/courses.py:1917-1935`** (`GET /jockeys/{id}`) — 1ère requête `participations_res` avec jointure cartésienne (`JOIN ON date_heure=date_heure`) JAMAIS lue mais exécutée à chaque appel → coûteux/timeout. Supprimer le bloc.
- **`api/routes/courses.py:1957-1968,2097`** — `position: None` hardcodé dans fiches jockey/entraîneur (feature non implémentée présentée comme donnée).
- **`api/routes/stats.py:494-503`** — buckets P&L mensuels via `now - 30*i` ≠ mois calendaires → dérive, mois sauté/dupliqué, paris exclus silencieusement.
- **`api/routes/stats.py:473-485`** — ROI par discipline : mise inclut paris en attente, numérateur non → ROI biaisé tant que non réglé.
- **`api/routes/stats.py:719,733`** (vb_performance) — pari sans `Resultat` (outerjoin None) compté perdant → ROI faussé à la baisse. `continue` si resultat None.

### 3.3 Sécurité — MAJEUR/MINEUR
- **`api/routes/auth.py:290-301`** (`PATCH /auth/me`) — `bankroll_initiale`/`profil_risque` posés sans validation type/enum/positivité → corrompt les calculs de mise downstream.
- **`api/routes/auth.py:434-443`** + **`notifications.py:166-183`** — `push_subscription`/`prefs` JSON arbitraire stocké tel quel et re-servi → stored XSS potentiel.
- **`api/routes/admin.py:1269,1285`** (ingest-betfair) — comparaison token sans `secrets.compare_digest` → timing attack.
- **`api/middleware/rate_limit.py:68`** — `rate_limit_predictions` DÉFINI mais jamais appliqué. Routes lourdes sans rate-limit : `predictions /analyse` (Claude+MC), `/portfolio` (MC 5000), `/predict`, `stats /track-record`, `/recherche`. → abus de calcul / coût Claude.
- **`api/main.py:69-75`** — CORS `allow_methods=["*"], allow_headers=["*"]` avec credentials (origines restreintes, à resserrer).
- **`api/routes/telegram.py:39`** — `asyncio.create_task` fire-and-forget → GC possible, exceptions silencieuses.

### 3.4 Gestion d'erreur — MAJEUR/MINEUR
- **`api/routes/predictions.py:181-189`** (`/predict` background) — client reçoit `{"ok":True}` même si le calcul échoue (faux positif UX).
- **`api/routes/stats.py:33-45`** — `_cache_get/set` avalent toutes exceptions sans log → pannes Redis invisibles.
- **`api/routes/strategies.py:248`** — `cheval.elo_score_global < elo_min` crash si elo None (TypeError). `:197` datetime naïf vs tz-aware.
- **`api/routes/stats.py:983-985`** — `palmares-gagnants` avale erreur SQL en renvoyant vide (table cassée indistinguable de vide légitime).
- **Réponse à shape variable** : `api/routes/stats.py:148-205` (equity-curve) renvoie 3 schémas différents → front doit gérer 3 cas, risque undefined.

> **Conformité OK** : `/stats/public` masque ROI +307%/précision 0%/AUC 0.06 ; pas d'IDOR ; webhook Stripe signature vérifiée ; `model_metrics.py` (plausible_auc/roi, real_model_metrics) est la bonne défense.

---

## 4. INTÉGRITÉ DES DONNÉES & SCRAPERS

### 4.1 Seeds / modèle — MAJEUR
- **`scripts/seed_dev_data.py:245-258`** — ModelVersion seed hardcode `precision_top3=0.0`, `roi_simule=3.07`, `auc_roc=0.9198` → **exactement** les valeurs « précision 0% / ROI +307% » signalées. Garde-fou `_assert_safe_target` présent (bien) mais ces champs DB ne sont pas fiables. Renforcer : refuser si users non-@blackturf.fr.
- **`scripts/seed_model.py:345-351`** — métriques calculées sur features SYNTHÉTIQUES ; `--deploy` publierait un AUC synthétique. Marquer `is_cold_start=True`.
- **`models/`** — vide (`.gitkeep` seul) → aucun `current_model.pkl` sur ce poste. Vérifier prod.
- **`catboost_info/catboost_training.json`** — `test_sets:[]`, `test_metrics:[]` → uniquement logloss d'apprentissage, aucune validation → tout AUC/Brier dérivé serait optimiste.

### 4.2 Dates / fuseaux — MAJEUR
- **`scraper/db_writer.py:132`** — `upsert_reunion` force `date_obj = date.today()` en ignorant la vraie date → fausse les regroupements / jours de repos (backfill, runs après minuit). Dériver de `course.date_heure`/course_id.
- **`scraper/db_writer.py:980-990`** — `_parse_datetime` renvoie `datetime.now()` en repli → fabrique une heure de départ (utilisée pour gel T-10, tri, fuseaux). Retourner None / rejeter.
- **`scraper/db_writer.py:686-687`** — pénétromètre : valeur brute `pen.coefficient` (non validée) propagée sur Course même si écartée du log. Propager la valeur validée.
- **Timezone mixte** — `date_heure` stocké naïf, mais `resolve_bookmaker_course_id` et track_record appliquent `AT TIME ZONE Europe/Paris` → décalage 1h/1j autour de minuit. Stocker UTC aware partout.

### 4.3 Scrapers fragiles — MAJEUR/MINEUR
- **`scraper/sources/geny.py:117`, `winamax.py:73`** + bookmakers HTML — sélecteurs positionnels (`td:nth-child(6)`, `[class*=odds]`) : si layout change, `safe_evaluate` renvoie default sans erreur → 0/None propagé OU mauvaise colonne lue (valeur plausible mais fausse). `valid_cote` (db_writer) nullifie les valeurs hors plage mais pas les « dans la plage » fausses. Ajouter contrôle cohérence (nb partants scrapés ≈ attendu) + alerte source morte.
- **`scraper/sources/winamax.py:77,134`** — `parseInt(...) || 0` → numéro illisible = 0, mauvaise association cote/partant.
- **`scraper/sources/pmu.py:218`** — `distance=get("distance",0)` → distance manquante = 0 (entre dans features). NULL+flag.

> **Conformité OK** : `pmu.py` (no-fake, None partout), `validation.py` (NULL plutôt que faux), exclusion backfill du palmarès (backfill_profil_runs marque `meta.backfill=true`, lecture l'exclut).

---

## 5. FRONTEND — visuel, responsive, wiring

### 5.1 Palette dark résiduelle — CRITIQUE (desktop + mobile)
Design system = blanc premium, mais 9 pages écrites en dark-mode jamais migrées → `text-*-400` sur fond blanc = contraste insuffisant (échec WCAG), badges quasi invisibles. Remplacer `-400→-600`, fonds `/10-/20`→`-50`.
- `dashboard/page.tsx` (zinc/amber/emerald/blue/red-400)
- `statistiques/page.tsx` (KpiCard, BetTable, streak, ROI discipline -400)
- `chevaux/[id]/page.tsx` (RUNNING_STYLE_CONFIG, positionBadge, gains, trends)
- `jockeys/[id]/page.tsx` (roiColor, positionBadge, victoires)
- `notifications/page.tsx` (NotifIcon, cards unread)
- `admin/algorithme/page.tsx` (**page la plus touchée, quasi intégralement dark**)
- `admin/page.tsx` (`text-green-400/500`)
- `track-record/page.tsx` (hero `to-amber-950/10` invisible, stats -400)
- `value-bets/page.tsx` (NIVEAU_COLORS -400), `cgu/page.tsx` (encadré amber)
> Pages CORRECTES (cible à généraliser) : bankroll, programme, courses, profil, recherche, assistant (palette `-600/-700` + `-50`).

> **✅ ÉTAPE B FIXÉE (frontend MAJEUR)** — vérifié `tsc --noEmit` EXIT=0 :
> - Fuites mémoire : `ScrollReveal` (observer cleanup), `AnimatedCounter` (cancelAnimationFrame + reduced-motion + ré-anime si `end` change), `useWebSocket` (backoff exponentiel + plafond 8 + flag `closingRef` anti-zombie).
> - Spinner infini : `statistiques` + `track-record` (états erreur/vide, `shouldRetryOnError:false`).
> - Crashs/NaN : gardes `?? 0` dashboard (ev/proba/chevaux/profils), strategies (indicateurs).
> - Lien mort `/entraineurs/[id]` → texte simple. Pages auth (mot-de-passe-oublie / reinitialiser / verifier-email) déplacées `(main)`→`(auth)` (plus de double chrome).
> - BottomNav : `pb-[calc(68px+safe-area)]` (contenu plus masqué iPhone) + `aria-current` + libellés FR.
> - `api.ts` : `timeout:15000` + refresh **single-flight** + flag `_retry` anti-boucle.
> - `useAuth` → **`AuthProvider` (Context)** : état partagé (Navbar/BottomNav à jour sans refresh) + sync inter-onglets + rollback tokens si `me()` échoue.

### 5.2 Structure / routing — MAJEUR
- **Pages auth dans le mauvais group** : `mot-de-passe-oublie`, `reinitialiser-mot-de-passe`, `verifier-email` sous `(main)/` → reçoivent Navbar+Footer+BottomNav, `min-h-screen` pousse le footer hors écran, BottomNav recouvre le formulaire. Déplacer vers `(auth)/`.
- **Lien mort** : `jockeys/[id]/page.tsx:347` → `/entraineurs/${id}` (route inexistante) → 404.
- **`admin/` hors `(main)`** : pas de Navbar/Footer → aucune navigation retour.

### 5.3 États manquants → spinner infini / crash — MAJEUR
- **`statistiques/page.tsx`** — `if (isLoading || !data)` sans état d'erreur → si API 404 (user sans paris), spinner INFINI.
- **`track-record/page.tsx`** — `gagnantsData` undefined → « Chargement… » permanent si endpoint échoue.
- **`dashboard/page.tsx:173,189,201`** — `pariDuJour.ev*100`, `.proba_top1*100`, `p.chevaux.map` sans garde → `NaN%`/crash si champ null.
- **`strategies/page.tsx:77`** — `strat.indicateurs.proba_top3_min*100` sans garde → `NaN%` sur vieille stratégie.
- **`courses/[id]/page.tsx:1705`** — `handleTriggerPred` relance après `setTimeout(4000)` en aveugle ; si analyse >4s, predictions reste null, l'user doit recliquer.

### 5.4 Responsive / affichage — MINEUR
- **`bankroll/page.tsx:299`** — mini-analytics `grid-cols-3` non responsive (3 cols même à 320px). → `grid-cols-1 sm:grid-cols-3`.
- **`assistant/page.tsx`** — `h-[calc(100dvh-4rem-1px)]` ne soustrait pas la BottomNav (52px) → champ de saisie masqué derrière sur mobile.
- **`assistant/page.tsx:197`** — `h-4.5 w-4.5` : classe Tailwind inexistante → icône sans taille.
- **`tarifs/page.tsx:155-161`** — `text-muted/30` → croix quasi invisibles. Utiliser `text-muted-foreground/40`.
- **`profil/page.tsx:194`** — VAPID key passée brute (doit être Uint8Array base64→array) → souscription push échoue.

### 5.5 Cohérence / contenu — MINEUR
- **`BottomNav.tsx`** — libellés « Value Bets / Bankroll / Palmarès » (anglais) vs Navbar francisé (« Paris de valeur / Capital »).
- **`badge.tsx:18-19`** — variants `pro` et `expert` strictement identiques (indistinguables).
- **`tarifs` vs `landing`** — libellés plans divergents (Standard « 5 prédictions/jour » vs « Prédictions IA complètes »).
- **`components/home/CalculatorDemo.tsx:9-12`** — répartition 50/30/20 fixe ≠ moteur réel (Kelly+paliers) → attente trompée. `:41` `parseInt` casse décimaux/collage.

---

## 6. FRONTEND — hooks, API, fuites mémoire, config

### 6.1 Sécurité / secrets — CRITIQUE
- **`frontend/.env.local:5`** — `NEXTAUTH_SECRET=blackturf-dev-secret-change-in-production` en clair → vérifier qu'il n'est PAS dans git, rotation prod.
- **`hooks/useWebSocket.ts:19`** — `?token=${token}` JWT en query string (confirmé backend ws.py:99,185,281 `Query(...)`) → loggé par proxies. Envoyer le token dans le 1er message WS.
- **`.env.local:3`** — clé Stripe `pk_test_placeholder` (publique, non sensible) mais paiements cassés tant que non remplacée.

### 6.2 Auth — MAJEUR
- **`hooks/useAuth.ts:8-19`** — hook LOCAL sans Context partagé : chaque composant a son propre `useState(user)` → après `login()`, Navbar/BottomNav ne se mettent à jour qu'au refresh (cause « barre mobile n'apparaît qu'après refresh »). → AuthProvider + event `storage`.
- **`hooks/useAuth.ts:13-19`** — `user` chargé async → BottomNav absent au 1er paint puis apparaît → layout shift.
- **`hooks/useAuth.ts:21-30`** — `login` sans try/catch : si `me()` échoue, tokens stockés mais user null → état incohérent, pas de rollback.
- **`hooks/useAuth.ts:66-77`** — `useRequireAuth` recrée une instance → redirection possible sur état non hydraté.

### 6.3 API client — MAJEUR
- **`lib/api.ts:3,107`** — base URL fallback `localhost:8000` en prod si env manque → casse silencieuse ; URL réécrite en dur dans `chatStream:107`.
- **`lib/api.ts:21-44`** — refresh 401 sans single-flight : 5 appels dashboard en parallèle → 5 `POST /auth/refresh` concurrents → cascade d'échecs → `window.location="/login"`.
- **`lib/api.ts:24-39`** — pas de flag `_retry` → boucle de refresh infinie possible si nouveau token rejeté.
- **`lib/api.ts`** — pas de `timeout` axios → requête peut pendre (spinner infini).
- **`lib/api.ts:130`** — `markAllRead` fait `DELETE /notifications/all` pour « marquer lu » → verbe sémantiquement faux.
- **Incohérence transport token** : axios interceptor vs `Navbar.tsx:137` fetch manuel avec Bearer vs `SearchPalette:48` fetch sans token.

### 6.4 Fuites mémoire / re-renders — MAJEUR
- **`components/ui/ScrollReveal.tsx:42-45`** — `observer.disconnect()` placé DANS le `setTimeout`, pas dans le cleanup du useEffect → observer jamais déconnecté → fuite sur remount.
- **`components/ui/AnimatedCounter.tsx:18-39`** — deps `[end,duration]` + `started.current` one-shot → si `end` change (donnée live), n'anime jamais la nouvelle valeur, reste périmé ; RAF jamais annulé → setState après unmount ; pas de reduced-motion.
- **`hooks/useWebSocket.ts:30-44`** — reconnexion `setTimeout(connect,5000)` sans backoff/plafond/check `enabled` → tempête si serveur refuse ; timer ré-armé après cleanup → WS zombie reconnectant un composant démonté.
- **`hooks/useWebSocket.ts`** — token lu une seule fois à la connexion → si rafraîchi, WS garde l'ancien, rejeté au cycle suivant.

### 6.5 Accessibilité / interaction — MAJEUR/MINEUR
- **`components/layout/Navbar.tsx:221-315`** — menu user sans fermeture clic-extérieur/Échap, pas de focus-trap, pas de `role="menu"`.
- **`components/layout/BottomNav.tsx:31`** — actif via `startsWith(href+"/")` : sur `/` aucun onglet actif ; fragile sur préfixes sœurs.
- **`components/layout/BottomNav.tsx:21`** vs layout `pb-16` — barre réelle = `min-h-[52px]+safe-area(~34px)≈86px` > 64px → bas du contenu masqué sur iPhone à encoche. `pb-[calc(64px+env(safe-area-inset-bottom))]`.
- **`components/layout/BottomNav.tsx:30-46`** — pas de `aria-current="page"`.
- **`components/ui/button.tsx`** — pas d'état `loading` intégré → risque double-submit login/inscription.
- **`components/charts/chart-kit.tsx`** — pas de ResponsiveContainer ni empty-state au niveau kit → vérifier que track-record/statistiques wrappent (sinon largeur 0 sur mobile) ; `:76` `Number(value??0)` affiche 0 pour valeur manquante.

### 6.6 Config build — MAJEUR/MINEUR
- **`next.config.mjs:6`** — `eslint.ignoreDuringBuilds: true` → build prod ignore les erreurs ESLint (deps de hooks manquantes ci-dessus ne casseront jamais le build → régressions silencieuses).
- **`next.config.mjs:26-33`** — rewrite `/api/*`→localhost fallback + deux modes d'accès API (axios direct ET rewrite) → CORS/auth incohérents. Choisir un seul.
- **`next.config.mjs:17-25`** — en-têtes sécurité minimaux (manquent X-Frame-Options, Referrer-Policy, CSP).
- **`next.config.mjs:14-16`** — `experimental.optimizeCss`+critters (a cassé des builds Next 14).

> **Points sains** : globals.css gère overflow-x mobile + reduced-motion, images next/image dimensionnées, données factices taguées « Exemple » (LiveTicker, CalculatorDemo), `strict:true` TS actif, cleanups listeners Navbar corrects.

---

## 7. RÉCAP PAR SÉVÉRITÉ

**CRITIQUE (12)** : pipeline numero/nom · post_race colonnes SQL · leakage signal/edge · meta_learner encodage+save · palette dark 9 pages · NEXTAUTH_SECRET · JWT query string · predictions /model/version AUC public.

**MAJEUR (~45)** : EV inventées portfolio · Kelly faux valuebets · probas combinées mise_calculator · code mort _plan_* · drift Page-Hinkley mort · settlement ROI provisoire · coûts arrangements vs combinaisons · _STATIC_STATS latent · rate_limit absent · auth validation/XSS · jointure cartésienne jockeys · P&L mensuel faux · ROI discipline biaisé · vb perdant si pas de résultat · dates scraper now() · pénétromètre brut · pages auth mauvais group · spinner infini stats/track-record · gardes NaN dashboard/strategies · useAuth sans Context · api refresh non sérialisé · fuites ScrollReveal/AnimatedCounter/WS · ESLint désactivé build · BottomNav safe-area · lien mort entraineurs.

**MINEUR (~40)** : seuils magiques, ELO inflation, parse temps, confrontations clé, calibration clips, libellés EN/FR, badges pro/expert, VAPID key, tarifs croix invisibles, CalculatorDemo parseInt, timeout axios, CORS large, etc.

---

*Audit produit par 6 agents spécialisés (algo core, apprentissage, API, intégrité données, frontend visuel, frontend hooks/config). Read-only. Prochaine étape : prioriser et corriger.*
