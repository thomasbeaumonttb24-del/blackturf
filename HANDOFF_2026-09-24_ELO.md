# Reprise — ELO et disqualifications (24/09/2026)

Branche : `claude/zealous-galileo-e6d500` (main du 24/09 19:32 déjà fusionné dedans).
**Rien n'est en production.** Aucune écriture n'a été faite sur la base de prod.

## Ce qui a été corrigé (code)

| Problème | Effet | Fichier |
|---|---|---|
| « 0 » de musique (non placé) lu comme 0ᵉ place | un non-placé valait **plus** qu'une victoire (1,11 contre 1,0) | `ml/features.py` `parse_musique` |
| Années « (25) » dans la musique | lues comme une 25ᵉ place | idem |
| Sorties sur incident sans position dans l'historique | **écartées** de la réussite distance / terrain / hippodrome : un cheval disqualifié 4 fois sur 5 affichait le taux de sa seule sortie classée | `ml/features.py` `POSITION_HISTORIQUE_SQL` |
| Scraper PMU des courses passées | la disqualification n'était pas enregistrée ; les lignes existantes sont complétées quand le cheval recourt | `scraper/sources/pmu.py` `_place_ou_incident`, `scraper/db_writer.py` |
| ELO : disqualifiés retirés des duels | **aucun point perdu** sur une faute ; ils sont maintenant battus par tous les classés | `ml/elo.py` `classement_elo` |
| ELO : nouveaux chevaux à 1500 fixe | un débutant de Groupe au niveau d'un réclamer ; maintenant amorcé à la moyenne des partants notés du lot | `ml/elo.py` `amorcer_inedits` |
| ELO : même K à 1 course qu'à 40 | un bon cheval mettait des dizaines de courses à rejoindre sa valeur ; K ×2,5 → ×1 sur 8 courses | `multiplicateur_provisoire` |
| ELO : poids des duels décroissant avec l'écart de places | battre le dernier comptait 3× moins que battre le 2ᵉ ; tous les duels pèsent pareil | `calculer_deltas_course` |
| `elo_historique` daté du jour du **calcul** | filtre point-in-time des features faux à chaque rejeu | `update_elo_after_race(date_course=…)` |
| Features : moyenne / max ELO du champ lus dans les ratings **actuels** | fuite du futur dans toute feature recalculée pour une course passée | `ml/features.py` (COALESCE `elo_avant_*`) |
| Features : ELO d'un inédit = 1500 | amorcé comme dans l'ELO | `_amorces_elo` |
| Réduction km après course | le chrono officiel PMU prime sur le recalcul depuis le temps brut | `ml/pipeline.py` |

Validation :
- Sur une base PostgreSQL locale (800 chevaux, 6 000 courses), le recalcul et la mise à jour en direct donnent les mêmes ratings, au centime.
- En simulation (valeur réelle connue), l'ancien ELO atteint une corrélation de rang de 0,09 et le nouveau 0,88. L'essentiel du gain vient de l'amorçage, puis des disqualifications. Sur les vraies courses, le gain sera plus faible.
- Suite de tests : 14 nouveaux tests verts ; les 14 échecs restants existent déjà sur main (f-string Python 3.12 et SQLite).

## À faire en production (dans l'ordre)

Depuis `/opt/blackturf` :

```bash
DC="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# 0. fusionner la branche dans main → le déploiement se lance

# 1. À BLANC : n'écrit rien, affiche la mesure ancien/nouveau sur 180 jours
$DC run --rm --no-deps -T worker python -m scripts.elo_recalcul

# 2. si la mesure est bonne : bascule en UNE transaction (quelques minutes)
$DC run --rm --no-deps -T worker python -m scripts.elo_recalcul --appliquer

# 3. features de la fenêtre du retrain, les plus récentes d'abord (long)
$DC run -d --rm --no-deps --name bt_recompute_features worker \
  sh -c "python -m scripts.recompute_features_prerace --depuis-jours 400 >> /app/models/recompute-features.log 2>&1"

# 4. rien : le retrain de nuit (gate champion/challenger) apprend sur le nouvel ELO
```

Ne pas utiliser `scripts/elo_rejeu.py`. Il remet tout à 1500 puis rejoue par lots de 500 : pendant des heures, le site sert des ELO à moitié recalculés.

Tant que l'étape 3 n'est pas finie, le modèle servi a appris sur l'ancien ELO. Un retrain lancé avant la fin mélange les deux.

## Non fait, à reprendre

- **Session « Audit classement - continuation » (PC local)**. Module Quinté+ risqué à 5 tickets : `mise_calculator.py` +128, `bet_settlement.py` +9 −4, `courses.py` +16 −2, plus un 4ᵉ fichier. Ces modifications ne sont ni commitées ni poussées. Il reste le règlement par combinaison explicite (Ordre possible) et l'enregistrement au capital en 5 lignes. La reprendre sur le PC (« Réessayer »), ou la pousser sur une branche pour une session cloud.
- **Format PMU d'une disqualification dans `performances-detaillees`**. Il n'a pas été observé : l'API était injoignable depuis la session. `_place_ou_incident` accepte une place non numérique (« DAI ») et un `statusArrivee`. À vérifier sur une vraie réponse.
- **Unité de `tempsObtenu`** : non vérifiée (ms ou cs). La réduction km officielle PMU passe désormais en premier, donc sans impact au trot.
