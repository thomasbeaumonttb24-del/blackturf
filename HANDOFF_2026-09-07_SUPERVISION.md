# Handoff — Supervision IA (`/admin/algorithme`), nuit du 07 au 08/09/2026

Prod : **`cc84d99`**. Gate de tests : **2069 passés, 0 échec**. `next build` vert.
Point de retour : images taguées `:avant-supervision-0907` (api, frontend, worker,
scheduler, scraper) — commit précédent `2d2ff2c`.

---

## Ce qui a été fait

Audit de la page puis six correctifs, chacun vérifié contre la base de production avant
d'être commité. Le rapport d'audit complet est dans le scratchpad de la session
(`AUDIT_admin_algorithme_2026-09-07.md`).

**Constat général : rien n'était inventé.** Tous les chiffres venaient d'une table. Les
défauts étaient d'une autre nature — périmé, mal étiqueté, ou jamais lu.

| # | Défaut | Correctif |
|---|---|---|
| 1 | `rank_delta_market` mesuré chaque nuit, jamais lu par la page | exposé avec `rank_auc`, `market_rank_auc` et surtout `rank_source` |
| 2 | Tuile « AUC walk-forward — la seule qui compte vraiment » (faux) ; cadence « aucun modèle produit » (faux) | libellés corrigés ; bannière « Le modèle bat-il la cote ? » ; colonne « vs cote » |
| 3 | `retrain: ok` identique pour une promotion et un rejet | `learning_step_runs.detail` lu ; bloc `retrain` avec issue, raison, `jours_sans_promotion`, `gel_suspect` |
| 4 | 8 sources mortes affichées `ok` | statut déduit sur 24 h : `alimentee` / `tourne_a_vide` / `silencieuse`, sources nommées dans le bandeau |
| 5 | État d'apprentissage figé au dernier redémarrage de l'API | relu en base à chaque appel, sur instances **détachées** |
| 6 | « Dernières victoires » sans dénominateur | 2 027 / 4 452 courses (45,5 %) + chiffrage du biais |

Bonus : suppression de deux photos orphelines qui rendaient le gate **rouge sur main**
depuis `a8ba02d` (retirées de la rotation, fichiers jamais supprimés).

---

## Le point à comprendre avant de toucher au modèle

Mesuré le 07/09 sur **1 024 courses réelles** des 21 derniers jours :

| Ce qui est classé | AUC intra-course |
|---|---|
| Cote PMU seule | 0,7486 |
| Modèle **brut** | 0,7326 → **−0,0160** |
| Produit **servi** (après blend) | 0,7519 → **+0,0033** |

`model_versions.rank_delta_market` (v528 = **−0,0354**) juge le **modèle nu**, avant le
mélange avec le marché. C'est cohérent, et c'est **attendu** : le drapeau `market_residual`
a retiré la cote du vecteur d'apprentissage, le modèle apprend le RÉSIDU. Ce que reçoit
l'abonné est le mélange, et lui bat le marché.

> **Ne pas activer `BT_MARKET_GATE` en l'état.** Il gate sur le delta du modèle nu,
> structurellement négatif par construction : plus aucun modèle ne serait jamais promu,
> gel à vie. Le rebrancher d'abord sur le delta du produit servi.

---

## Reste à faire (par valeur, non fait cette nuit)

1. **Mesurer et stocker le delta marché du PRODUIT SERVI**, à côté de celui du modèle nu.
   Deux colonnes, deux libellés. C'est le préalable au point suivant.
2. **Alors seulement**, rebrancher `BT_MARKET_GATE` sur ce delta-là.
3. **Post-traitement après blend : −0,0012 d'AUC de classement** (0,7531 → 0,7519).
   Identifier lequel des trois est responsable — la calibration longshot par tranche de
   cote est le suspect n°1, elle n'est pas monotone par construction.
4. **`edge_monitor` ne peut plus rien conclure** : 4 paris retenus sur 42 245
   (`n_filt = 4`, `enough_filt = false`) — 25 le mois dernier. Le filtre de conviction est
   à recalibrer ou à déclarer hors service ; en l'état la gate ROI ne se prononcera jamais.
5. `alpha_max` 0,42 vs optimum 0,50 = **+0,0002**. Bruit. Question close, ne pas y revenir.

---

## Points d'exploitation

- **`worker`, `scheduler` et `scraper`** ont été rebuildés puis redémarrés après la
  dernière course du jour. Ils portent aussi les correctifs « paris de valeur » de la
  session sœur (`9065176`, `2d2ff2c`), qui étaient poussés sans avoir jamais tourné.
- **Rollback** : `docker tag blackturf-<svc>:avant-supervision-0907 blackturf-<svc>:latest`
  puis `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d <svc>`.
  Toujours les DEUX fichiers compose.
- **Deux sessions travaillaient sur ce dépôt** cette nuit. Travail fait dans un worktree
  isolé (`_wt_sup`, branche `fix/supervision-verite-0907`), rebasé sur `vps/main` avant
  push : le checkout partagé `blackturf/` n'a jamais été touché.

---

## Sous surveillance cette nuit

Le réentraînement de **02:00 UTC** est le premier à tourner avec le code de la
supervision. Rien n'y touche côté écriture (seuls les lecteurs ont changé), mais c'est
lui qui alimentera pour la première fois le bloc `retrain` de l'onglet Outils avec une
issue lue depuis `detail`. À vérifier au réveil : l'onglet doit annoncer soit
« modèle vXXX déployé », soit « challenger refusé » — plus jamais un simple « ok ».
