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

Comparaison **appariée course par course**, avec intervalle à 95 % — c'est la seule qui
tranche, et elle a démenti ma première lecture :

| Écart | 21 j (1 064 courses) | 90 j (4 430 courses) | Verdict |
|---|---|---|---|
| Modèle **nu** vs cote | −0,0152 [−0,0257 ; −0,0047] | **−0,0168** [−0,0224 ; −0,0112] | prouvé SOUS |
| Produit **servi** vs cote | +0,0030 [−0,0023 ; +0,0083] | **−0,0019** [−0,0051 ; +0,0014] | **non concluant → parité** |
| Apport de la **chaîne** | +0,0182 [+0,0104 ; +0,0261] | **+0,0146** [+0,0108 ; +0,0185] | prouvé POSITIF |

`model_versions.rank_delta_market` (v528 = **−0,0354**) juge le **modèle nu**, avant le
mélange avec le marché. C'est cohérent avec la ligne 1, et c'est **attendu** : le drapeau
`market_residual` a retiré la cote du vecteur d'apprentissage, le modèle apprend le RÉSIDU.

Ce que reçoit l'abonné est le mélange, et il est **à parité** avec la cote — ni au-dessus
ni en dessous, l'intervalle contient zéro. Ce qui est prouvé, c'est que **la chaîne de
correction rattrape le déficit du modèle nu**. C'est elle qui porte la valeur aujourd'hui.

> Ne jamais conclure sur une différence de moyennes agrégées : à 21 jours elle disait
> « +0,0030, bat le marché », à 90 jours « −0,0019, sous le marché ». Choisir la fenêtre,
> c'est choisir la conclusion. L'écart apparié dit « parité » dans les deux cas.

Mesuré en continu depuis cette nuit par l'étape `avantage_marche_servi`
(`ml/avantage_marche.py`), affiché dans l'onglet Modèle sous la bannière du modèle nu.

> **Ne pas activer `BT_MARKET_GATE` en l'état.** Il gate sur le delta du modèle nu,
> structurellement négatif par construction : plus aucun modèle ne serait jamais promu,
> gel à vie. Le rebrancher d'abord sur le delta du produit servi.

---

## Reste à faire (par valeur, non fait cette nuit)

1. ~~Mesurer le delta marché du produit servi~~ — **fait cette nuit** (étape
   `avantage_marche_servi`, affichée dans l'onglet Modèle).
2. **Rebrancher `BT_MARKET_GATE` sur ce delta-là** — possible maintenant que la mesure
   existe. Attention : en l'état le produit est à parité (IC contient zéro), donc un gate
   strict « delta > 0 » bloquerait aussi. Le gate utile est plutôt « le delta ne
   RÉGRESSE pas », ou un plancher sur l'apport de la chaîne.
3. **PISTE LA PLUS SOLIDE — le post-traitement après mélange détruit du classement.**
   Décomposition appariée sur 4 274 courses (90 j), IC 95 % :

   | Étape | Écart | IC 95 % | Concluant |
   |---|---|---|---|
   | modèle nu vs marché | −0,0168 | [−0,0224 ; −0,0111] | **oui, négatif** |
   | apport du **mélange** (blend − brut) | **+0,0170** | [+0,0130 ; +0,0210] | **oui, positif** |
   | mélange seul vs marché | +0,0003 | [−0,0028 ; +0,0033] | non (parité) |
   | apport du **post-traitement** (servi − blend) | **−0,0024** | [−0,0044 ; −0,0004] | **oui, NÉGATIF** |
   | produit servi vs marché | −0,0021 | [−0,0054 ; +0,0012] | non (parité) |

   Autrement dit : le mélange amène le produit **exactement à parité** avec la cote, puis
   le post-traitement lui reprend 0,0024. C'est le seul maillon prouvé destructeur de la
   chaîne, et c'est là qu'il y a un gain à récupérer sans rien inventer.

   **Suspects, par construction** : une correction qui dépend de la TRANCHE DE COTE du
   partant n'est pas monotone et peut donc réordonner une course — `ml/longshot_calibration`
   et `ml/cote_calibration` sont les deux seules dans ce cas. L'isotone, la température et
   la netteté sont des transformations monotones globales : elles ne peuvent PAS changer un
   classement intra-course, donc elles sont hors de cause.

   Protocole : rejouer la chaîne en désactivant une correction à la fois, comparer en
   apparié sur les mêmes courses (`ml/avantage_marche._ecart_apparie` fait déjà le calcul).
   **Ne pas toucher à l'inférence sans cette mesure** : ces corrections existent pour
   redresser l'EV des paris, pas le classement — les retirer améliorerait le classement et
   pourrait dégrader les mises. Les deux effets doivent être mesurés ensemble.

   Reproduire : `ml/avantage_marche.py` + le script de décomposition décrit ci-dessus
   (mélange rejoué via `ml.blend_calibration.melange` sur `proba_top1_raw`).
4. **`edge_monitor` ne peut plus rien conclure** : 4 paris retenus sur 42 245
   (`n_filt = 4`, `enough_filt = false`) — 25 le mois dernier. Le filtre de conviction est
   à recalibrer ou à déclarer hors service ; en l'état la gate ROI ne se prononcera jamais.
5. `alpha_max` 0,42 vs optimum 0,50 = **+0,0002**. Bruit. Question close, ne pas y revenir.

---

## Points d'exploitation

### Déployer, c'est pousser sur `origin` — pas sur `vps`

Je me suis trompé une partie de la nuit là-dessus, et la mémoire du projet disait encore
la version de juillet (« le pipeline GitHub est déconnecté, il faut rebuilder sur le
VPS »). C'est faux depuis. Vérifié dans `.github/workflows/deploy.yml` :

un push sur `origin/main` → build GHCR → sur le VPS **`git reset --hard origin/main`** →
`docker compose build` **de tous les services** → `up -d` → **`alembic upgrade head`** →
health check → `docker image prune -f`. Bout en bout **~8 minutes**.

**Conséquence** : un commit poussé sur le remote `vps` SEUL est **effacé de la prod** par le
`reset --hard` du prochain push origin, par n'importe qui. Toujours pousser sur les deux,
`origin` d'abord. Vérifier avant : `git merge-base --is-ancestor origin/main HEAD`.

C'est exactement ce qui a failli arriver cette nuit : mes 7 premiers commits n'étaient que
sur `vps`. La session sœur les a rebasés sous les siens et poussés sur `origin` — sans quoi
ils auraient disparu au déploiement suivant.

Deux détails du workflow qui comptent :
- `paths-ignore: "**.md"` — un commit qui ne touche que du markdown ne déploie rien.
- `docker image prune -f` (sans `-a`) ne supprime que les images **dangling** : une image
  taguée avant le build survit, donc le point de retour ci-dessous est intact.

### Rollback

```bash
docker tag blackturf-api:avant-supervision-0907 blackturf-api:latest   # idem 4 autres svc
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d
```
Toujours les DEUX fichiers compose. Retour durable = `git revert` + push **origin**, sinon
le déploiement suivant réappliquera le code.

### Sessions parallèles

Deux sessions sur ce dépôt cette nuit. Travail fait dans un worktree isolé (`_wt_sup`,
branche `fix/supervision-verite-0907`) : le checkout partagé `blackturf/` n'a jamais été
touché. Les commits « paris de valeur » de la session sœur (`9065176`, `2d2ff2c`,
`af1edb5`, `cc15c0f`, `90a099e`) sont dans la même ligne d'histoire.

---

## Sous surveillance cette nuit

Le réentraînement de **02:00 UTC** est le premier à tourner avec le code de la
supervision. Rien n'y touche côté écriture (seuls les lecteurs ont changé), mais c'est
lui qui alimentera pour la première fois le bloc `retrain` de l'onglet Outils avec une
issue lue depuis `detail`. À vérifier au réveil : l'onglet doit annoncer soit
« modèle vXXX déployé », soit « challenger refusé » — plus jamais un simple « ok ».
