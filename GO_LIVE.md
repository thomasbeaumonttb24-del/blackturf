# GO LIVE — mettre BlackTurf en ligne

Tout le code, les scripts et l'automatisation sont prêts. Il te reste seulement :
**créer les comptes, payer, et coller 2 blocs de commandes.** Le reste se fait seul.

Remplace partout :
- `<USER>` = ton identifiant GitHub
- `<DOMAINE>` = ton domaine (ex. `blackturf.fr`)
- `<CLE_METEO>` = ta clé OpenWeather
- `<EMAIL>` = ton email
- `<IP_VPS>` = l'IP de ton serveur

---

## Étape 1 — Comptes & achats (toi)

| # | Action | Où |
|---|--------|-----|
| 1 | Créer un compte **GitHub** (gratuit) | github.com |
| 2 | Créer un **repo vide** nommé `blackturf` (coche **Public** = plus simple) | github.com/new |
| 3 | Créer un compte **Hetzner** + commander un **CPX31** (~15 €/mois) → noter l'**IP** | hetzner.com/cloud |
| 4 | Acheter un **domaine** | OVH / Namecheap / Gandi |
| 5 | **DNS** : créer 3 enregistrements **A** → `<IP_VPS>` : `@`, `www`, `api` | chez le registrar |
| 6 | Clé **OpenWeather** (gratuite) | openweathermap.org/api |

> Attends ~15 min que le DNS se propage avant l'étape 3.

---

## Étape 2 — Envoyer le code sur GitHub (depuis TON PC Windows)

Le repo est déjà initialisé et commité. Colle dans PowerShell :

```powershell
cd "C:\Users\thoma\Desktop\BlackTurf\blackturf"
git branch -M main
git remote add origin https://github.com/<USER>/blackturf.git
git push -u origin main
```

GitHub te demandera de te connecter (identifiant + token). Une fois poussé, c'est en ligne.

---

## Étape 3 — Tout déployer sur le VPS (UNE fois)

Connecte-toi au serveur (depuis PowerShell) :

```powershell
ssh root@<IP_VPS>
```

Puis colle ce **bloc unique** (provisionne le serveur, récupère le code, déploie tout) :

```bash
curl -fsSL https://raw.githubusercontent.com/<USER>/blackturf/main/setup_server.sh -o /tmp/setup_server.sh
bash /tmp/setup_server.sh
git clone https://github.com/<USER>/blackturf.git /opt/blackturf
cd /opt/blackturf
./scripts/bootstrap.sh <DOMAINE> <CLE_METEO> <EMAIL>
```

Ça installe Docker, le pare-feu, les certificats HTTPS, la base, les migrations,
le modèle, l'API, le scraper et le frontend — puis vérifie que tout répond.

À la fin, le script affiche l'URL du site et la commande pour te passer admin.

---

## Étape 4 — Premier accès (toi)

1. Ouvre `https://<DOMAINE>` → crée ton compte.
2. Passe-toi admin (le script t'affiche la commande exacte) :
   ```bash
   docker compose -f docker-compose.prod.yml exec db psql -U blackturf -d blackturf \
     -c "UPDATE users SET plan='expert', is_admin=true WHERE email='<EMAIL>';"
   ```
3. Explore : programme, fiche course, portefeuille de paris, `/admin`.

---

## Mises à jour futures = automatiques

Une fois en place, le CI/CD (`.github/workflows/deploy.yml`) redéploie tout seul
à chaque `git push` — à condition d'ajouter dans GitHub → Settings → Secrets :
`VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_PORT`. (Optionnel, pour plus tard.)

---

## Important — patience sur les pronostics

Le site est **actif immédiatement**, mais l'algo apprend des résultats réels :
les pronostics ne deviennent **pertinents qu'après quelques jours** de collecte.
C'est normal et voulu — il s'améliore à chaque course.

## Coût mensuel de départ
VPS ~15 € + domaine ~1 €/mois + OpenWeather gratuit + **pas de proxy** ≈ **~16 €/mois**.
On ajoute un proxy résidentiel plus tard seulement si des sources se font bannir.
