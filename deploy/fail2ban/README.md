# Prison fail2ban — scanners web

Bannit les scanners automatises qui frappent le site. En 7 jours de journaux :
11 039 requetes cherchant un `.env`, 1 943 un `/config`, 878 tentatives de
remontee d'arborescence, 301 un `.git/`, 99 un `wp-admin`, 10 un `UNION SELECT`.
Toutes en 404 — mais elles noient le signal utile dans les journaux.

## Installation

```bash
cp filter.d/blackturf-scanners.conf   /etc/fail2ban/filter.d/
cp filter.d/blackturf-aspiration.conf /etc/fail2ban/filter.d/
cp jail.d/blackturf-nginx.conf      /etc/fail2ban/jail.d/
fail2ban-client reload
```

## Les deux points qui ne vont pas de soi

**`chain = DOCKER-USER`.** C'est le reglage decisif. Le trafic vers un conteneur
est ROUTE : il traverse `FORWARD`, jamais `INPUT`. Un bannissement pose dans
`INPUT` — le defaut de fail2ban — n'aurait donc strictement aucun effet, tout en
affichant « banned » dans `fail2ban-client status`. Avec ce reglage, la chaine
`f2b-blackturf-scanners` s'insere en tete de `DOCKER-USER`, donc AVANT les
`ACCEPT` sur 80 et 443.

Verification, avec une IP de la plage de documentation :

```bash
fail2ban-client set blackturf-scanners banip 198.51.100.1
iptables -L DOCKER-USER -n --line-numbers | head -3   # la chaine f2b doit etre en 1
iptables -L INPUT -n | grep f2b                       # doit etre VIDE
fail2ban-client set blackturf-scanners unbanip 198.51.100.1
```

**`ignoreip` contient l'IP de l'exploitant.** Une session d'audit demande
`/.env` et `/.git/config` exactement comme un scanner : sans cette ligne, auditer
son propre site se solde par 24 h de bannissement. C'est arrive pendant la mise
au point du filtre (4 correspondances sur l'IP de l'exploitant).

## Ce que le filtre ne fait pas

Il ne bannit pas sur le code 404. Un 404 est aussi ce que produit un lien casse
ou un explorateur legitime. Il bannit sur des CHEMINS qu'aucun visiteur ni aucun
robot d'indexation ne demande jamais. Mesure sur les journaux reels au moment de
sa mise en service : 8 946 correspondances sur 185 061 lignes, aucun faux positif.

## Prison `blackturf-aspiration`

Bannit une IP qui depasse **1 200 appels `/api/` en 5 min** (4/s soutenus).
Ajoutee le 2026-10-08 apres qu'une IP inconnue a envoye 1 626 requetes en 5 min,
sous la limite nginx de 20 r/s : rien ne l'arretait. Les OPTIONS (preflight
CORS) et les fichiers statiques ne comptent pas. Bannissement d'1 h, double a
chaque recidive, plafonne a une semaine.

Verifier le filtre sur les vrais journaux avant de recharger :

```bash
fail2ban-regex /opt/blackturf/nginx/logs/access.log /etc/fail2ban/filter.d/blackturf-aspiration.conf | grep -E 'Failregex|Lines'
fail2ban-client status blackturf-aspiration   # « File list » NE DOIT PAS etre vide
```

## Installation automatique et IP de l'exploitant

Le deploiement (`.github/workflows/deploy.yml`) recopie ces fichiers dans
`/etc/fail2ban/` puis recharge fail2ban, sans jamais bloquer le deploiement
(config invalide = ancienne config restauree). L'IP de l'exploitant va dans
`/etc/fail2ban/jail.d/blackturf-nginx.local` SUR LE SERVEUR, que le deploiement
ne touche jamais :

```ini
[blackturf-scanners]
ignoreip = 127.0.0.1/8 ::1 172.17.0.0/16 172.18.0.0/16 <IP>

[blackturf-aspiration]
ignoreip = 127.0.0.1/8 ::1 172.17.0.0/16 172.18.0.0/16 <IP>
```
