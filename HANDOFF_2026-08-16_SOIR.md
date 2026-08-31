# Handoff BlackTurf — 2026-08-16 (soir)

Session d'audit + corrections. **19 commits**, tous déployés en prod **sauf le point 5** (e-mails hebdo).
Repo : `C:\Users\thoma\Desktop\BlackTurf\blackturf\`. VPS : `ssh -i ~/.ssh/blackturf_vps root@167.233.60.99`, code dans `/opt/blackturf`.

---

## ⚠️ À FAIRE EN PRIORITÉ

### 1. Vérifier le retrain de 02:00 UTC (demain matin)
C'est **le** point en suspens. Le modèle est gelé sur **v503 depuis le 29/06** (48 jours).
Deux causes corrigées aujourd'hui (commit `39d5340`), mais **le résultat réel n'est pas encore connu** — la première nuit avec le correctif est celle du 16→17/08.

✅ **AUTOMATISÉ** (commit `e2fbeef`) : un rapport e-mail arrive désormais **chaque matin à 07:00 Paris** avec le verdict et l'action à faire. Plus besoin de vérifier à la main — il suffit de lire l'e-mail. Cron installé sur le VPS (`0 5 * * *`), envoi réel testé (`envoi=True`).

Vérification manuelle si besoin :
```bash
ssh -i ~/.ssh/blackturf_vps root@167.233.60.99 \
  "docker logs blackturf_worker --since 12h | grep -E 'h2h.measured|retrain.deployed|retrain.rollback|signal 9'"
# ou relancer le rapport à la demande :
ssh -i ~/.ssh/blackturf_vps root@167.233.60.99 "/opt/blackturf/scripts/check_retrain_cron.sh"
```

Trois issues, toutes informatives :
- `retrain.deployed` + `reason=better_h2h` → **première promotion depuis 48 jours**, l'apprentissage repart
- `retrain.rollback` + `reason=worse_h2h` → le gel était justifié, le vrai problème est ailleurs (features, drift) — creuser à partir de là
- `signal 9` / OOM → le point P0-3 n'est pas clos (float32 + worker 6 G insuffisants) ; réduire la fenêtre de données ou `n_jobs`

### 2. Déployer le point 5 (e-mails hebdo) — le seul code prêt mais non déployé
`RESEND_API_KEY` est maintenant **en place et testée** (un e-mail réel est parti vers thomas.beaumont.tb24@gmail.com et l'API a renvoyé `True`). Le blocage est levé.

Fichiers concernés, **restés à la version d'avant sur le VPS** : `backend/services/alerts.py`, `backend/services/jobs.py`.
Contenu : job APScheduler lundi 09:00 Paris → meilleur value bet ★★★+ réellement gagnant de la semaine → e-mail + push aux comptes Free/Découverte. Conformité RGPD incluse (commit `07e92c4`) : colonne `users.marketing_opt_out_at` (**migration 0026, à appliquer**), jeton signé d'audience `unsub`, endpoint public `POST /notifications/desabonnement`, exclusion des désabonnés à l'envoi, mentions jeu responsable.

⚠️ **La migration 0026 n'a pas été appliquée en prod.** À faire avant/avec ce déploiement.

### 3. Vérifier le point 2 du funnel en UI réelle (jamais validé)
L'essai gratuit du calculateur de mise (1/jour pour Free/Découverte) est déployé côté backend **et** frontend, tests verts, mais **jamais vu fonctionner dans un navigateur**. Impossible à vérifier ce soir : aucune course `a_venir` (le calculateur ne s'affiche que dans cette vue).

À faire demain quand il y a des courses au programme : créer un compte Free, ouvrir une course à venir, vérifier qu'une simulation passe puis que la seconde affiche le message d'essai épuisé + CTA `/tarifs`. **Supprimer le compte de test ensuite** (`DELETE FROM users WHERE email='...'`) — la prod doit rester à 18 utilisateurs.

---

## 📋 RESTE À FAIRE (par priorité)

### Revenu / conversion
- **E-mail d'annonce aux 11 utilisateurs** — brouillon rédigé et validé côté contenu honnête (chiffres réels : 18 090 courses, 60 % top-3, favori placé 65,7 %), **pas encore envoyé**, attend le feu vert de Thomas. ⚠️ Ne JAMAIS écrire « vous auriez gagné X€ » : les données disent l'inverse (voir section ROI).
- **Aucun abonnement payant à ce jour** (0 sur 18 users). Stripe est en LIVE et fonctionnel, le tunnel est câblé et testé bout-en-bout en mode test.
- ⚠️ **Le webhook Stripe LIVE n'a jamais reçu de vrai événement.** Le premier vrai abonné sera le premier vrai test. Si `user.plan` ne se met pas à jour après un paiement : `docker logs blackturf_api | grep stripe.webhook` en priorité.

### Réception e-mail `contact@blackturf.fr` — NON RÉSOLU
Mails envoyés à cette adresse **perdus silencieusement** (ni livraison, ni rebond), depuis ~23 juin. Testé depuis Gmail ET depuis un fournisseur externe : rien.
- Boîte Zimbra existe et fonctionne (offre Starter, 4/4 comptes, `blackturf.fr` actif, 1 compte) — dernier mail reçu le **23 juin**
- Diagnostics OVH Zimbra : **MX / SPF / DKIM tous "Configuration OK"**
- MAIS `blackturf.fr` est **aussi** dans MX Plan avec l'offre `redirect` (0 boîte, 0 redirection) → hypothèse principale : conflit de routage interne OVH, MX Plan intercepte et jette
- **Non vérifiable à distance** (port 25 sortant bloqué sur le VPS). Piste : créer une redirection dans MX Plan (réversible) pour tester, puis détacher MX Plan si confirmé. Un ticket support OVH règle ça vite.
- **N'impacte PAS Resend** : envoyer et recevoir sont deux services indépendants.

### P1 restants de l'audit
- Trou du 12→15/08 visible publiquement dans `/api/v1/stats/track-record` (données perdues, non récupérables — cosmétique)
- **Backups sans copie hors-site** : 16 × 750 Mo dans `/opt/blackturf/backups`, même disque que la base. Perte disque = perte totale.
- Presse `paris_turf` morte depuis le 07/07 (equidia + canalturf compensent)
- **`SCRAPER_DISABLED_SOURCES=racing_post,turfoo,france_galop,zeturf`** → `penetrometre_log` et `suspensions_professionnels` **VIDES**. Le pénétromètre (état du terrain) est un driver prédictif fort en hippisme, absent du modèle.
- Couverture cotes : PMU ~85 %, Unibet ~27 %, Geny ~9 %, Bet365/Ladbrokes/Betfair réalimentés depuis aujourd'hui

### Risques latents identifiés, non traités
- `zeturf_live_daemon.py` et `genybet_live_daemon.py` ont **le même pattern de gel** que le daemon oddschecker corrigé aujourd'hui (Camoufox synchrone, `while _run`, aucun watchdog). Sains actuellement, mais vulnérables si leur driver meurt.
- DMARC absent sur `blackturf.fr` (volontaire : ne pas y toucher tant que la réception Zimbra est cassée, ça s'applique à tout le domaine)

### P2 / hygiène
- 7 fichiers `.localbak` dans l'arbre
- Logs daemons sans rotation (`/var/log/{zeturf,genybet}-odds.log`, 30 Mo + 12 Mo)
- Non commités : `frontend/src/app/(auth)/inscription/page.tsx` (modifié), `backend/scraper/genybet_live_daemon.py` (jamais tracké)

---

## ✅ FAIT AUJOURD'HUI (ne pas refaire)

| # | Sujet | Commit |
|---|---|---|
| P0-1 | Gel scraper 4 j 16 h → timeout + watchdog thread + heartbeat/healthcheck | `60d8bbb` |
| P0-2 | Modèle gelé 48 j → arbitrage head-to-head + bug clé `insufficient`/`enough_filt` | `39d5340` |
| P0-4 | SSL expirait le 03/09 → webroot + montage répertoire. **Renouvelé jusqu'au 14/11** | `1b7cb50` |
| P0-5 | Tunnel Stripe jamais câblé → CTA + clés (test puis **LIVE**) | `3ddc613` |
| P0-6 | Daemon oddschecker zombie 92 % CPU 15 j → watchdog | `2a610f3` |
| P1 | `job_drift_check` échouait toutes les heures depuis toujours | `bb8bc97` |
| P1 | Value bets en extinction → seuils longshot recalibrés sur 37 970 prédictions | `bf08f22` |
| P1 | Paywall WebSocket contournable (value bets Standard+ en clair) | `3563641` |
| — | Suite de tests **100 % verte** (622 local / 602 conteneur) | `4ef13d6` |
| Funnel 1 | Badge "Recommandé" Standard → **Expert** | `8b0e131` |
| Funnel 3 | Endpoint `GET /courses/{id}/favori-ia-resultat` (honnête : montre aussi les échecs) | `e6d8a19` |
| Funnel 4 | Endpoint public `GET /value-bets/compteur` + bandeau `/programme` | `54b9257` |
| Bug réel | `useAuth` gardait un user en cache sans token → **tout user dont les tokens expirent gardait son ancien plan affiché** | `8beee97` |
| Infra | **84 Go** de cache Docker purgés (disque 81 % → 28 %) | — |
| Infra | Resend configuré : domaine vérifié, DNS OVH posés, clé "Sending access" en prod, **envoi réel testé OK** | — |

---

## 🔑 ROI RÉEL — à ne jamais ré-inventer

Mesuré sur 30 j de plans réglés (`profil_run_log`) :

| Profil | ROI moyen | **Médiane** | Plans gagnants |
|---|---|---|---|
| Conservateur | −2,5 % | **−100 %** | 446 / 1313 |
| Équilibré | −1,5 % | **−100 %** | 245 / 1312 |
| Agressif | +37 % | **−100 %** | **86 / 1314** (6,5 %) |

Le +37 % de l'agressif **n'est pas un gain reproductible** : médiane à −100 %, 93,5 % des plans perdent tout, la moyenne est portée par une poignée de gros coups.

**Conséquence produit, non négociable :** ne jamais écrire « avec l'abonnement vous auriez gagné X€ ». C'est faux, et en France c'est un risque ANJ (publicité jeux d'argent avec promesse de gain).

Ce qui est **vrai et vendeur** : 18 090 courses analysées, **60 % de précision top-3** (59,78 % réel), favori IA placé **65,7 %**, et des exemples individuels réels vérifiables (endpoint `favori-ia-resultat`).

---

## 🛠️ MÉTHODE DE DÉPLOIEMENT (pièges rencontrés aujourd'hui)

Pas de CI/CD fonctionnel. Déploiement = **build local sur le VPS**, jamais un push origin.

```bash
# 1. backup obligatoire
cp fichier "_backup_$(date +%Y%m%d_%H%M%S)_label/"
# 2. scp puis VÉRIFIER que le fichier est bien arrivé (grep d'une signature unique)
# 3. build
docker compose -f docker-compose.yml -f docker-compose.prod.yml build api
# 4. gate pytest DANS le conteneur — override ENVIRONMENT obligatoire
docker compose ... run --rm --no-deps -e ENVIRONMENT=test \
  -v /opt/blackturf/backend/tests:/app/tests api python -m pytest tests/ -q
# 5. bascule
docker compose ... up -d --no-deps api
```

**Pièges découverts aujourd'hui, tous coûteux :**
1. **Gate pytest sans `-e ENVIRONMENT=test`** → 34 faux échecs (`Invalid host header` de TrustedHostMiddleware, car `ENVIRONMENT=production` est réel dans le conteneur et écrase le `setdefault` de conftest.py). Les tests ne sont pas dans l'image prod : monter `/opt/blackturf/backend/tests`.
2. **Build frontend servi par le cache Docker** (1,5 s au lieu de ~50 s) → n'embarque AUCUN changement tout en affichant "Built". Si un build frontend prend moins de 10 s, il n'a rien construit → `--no-cache`.
3. **Sessions Claude parallèles sur le même repo/VPS** : un fix (`ws.py`) a disparu du disque VPS entre deux déploiements. Toujours re-vérifier qu'un fix précédent est encore là avant de rebuilder. Et **toujours lister les fichiers explicitement dans `git add`** — un `git add` depuis le mauvais dossier a fait committer le travail d'une autre session sous un message erroné (`554ef08`).
4. **Interface OVH Manager non pilotable** par les outils navigateur (contenu inaccessible au DOM/scroll). Contournement qui marche : **glisser la barre de défilement** (`left_click_drag` sur x≈1140) puis clics aux coordonnées.

---

## 📍 ÉTAT PROD AU MOMENT DU HANDOFF

```
Modèle actif      : v503 du 2026-06-29 (gelé, verdict au retrain de 02:00 UTC)
Users             : 11 free + 7 expert = 18 · 0 abonnement payant
Value bets ★★★+   : 3 actifs
Disque            : 28 % (39/150 Go) après purge de 84 Go
Cert SSL          : valide jusqu'au 14/11/2026, renouvellement auto réparé
Stripe            : LIVE, tunnel testé bout-en-bout (en mode test)
Resend            : opérationnel, envoi réel confirmé
Tests             : 622 local / 602 conteneur — 100 % verts
Conteneurs        : api, worker, scheduler, scraper, frontend, db, redis, nginx — tous up
```
