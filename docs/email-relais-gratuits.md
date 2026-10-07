# Mails : fournisseurs gratuits en chaîne (≈ 600 mails/jour, 0 €)

| Ordre | Fournisseur | Gratuit | Sert à |
|---|---|---|---|
| 1 | Resend | 100/jour | **Mails vitaux seulement** (`transactionnel=True`) : confirmation d'adresse, mot de passe, paiement/pass, résiliation |
| 2 | Brevo (`SMTP_*`) | 300/jour, à vie | Tout le reste (alertes, digests, campagnes) + secours des vitaux |
| 3 | Mailjet (`SMTP2_*`) | 200/jour (6 000/mois) | Secours de Brevo |

Code : `backend/services/alerts.py` → `send_email`. Un fournisseur qui répond « quota
dépassé » est mis en pause jusqu'à 00 h 05 UTC ; le suivant prend le relais. Un délai
dépassé (envoi ambigu) n'est JAMAIS doublé. Sans `SMTP_*`, tout repasse par Resend comme avant.

## Mise en place (une fois, ~15 min)

### 1. Brevo
1. Créer un compte gratuit sur https://www.brevo.com (offre *Free*).
2. *Expéditeurs, domaines et IP dédiées* → *Domaines* → ajouter `blackturf.fr`,
   choisir « authentifier » : Brevo affiche 3-4 enregistrements DNS (code Brevo TXT,
   DKIM, DMARC). Les ajouter chez le registraire du domaine (zone DNS de blackturf.fr).
   **Ne pas toucher aux enregistrements Resend existants** : ils cohabitent. Si un SPF
   `v=spf1 …` existe déjà, y AJOUTER `include:spf.brevo.com` (un seul enregistrement SPF).
3. *Expéditeurs* → ajouter `noreply@blackturf.fr`.
4. *SMTP & API* → onglet *SMTP* → *Générer une nouvelle clé SMTP*. Noter :
   l'identifiant affiché (`xxxx@smtp-brevo.com`) et la clé.

### 2. Mailjet (facultatif mais recommandé)
1. Compte gratuit sur https://www.mailjet.com.
2. *Expéditeurs et domaines* → ajouter `blackturf.fr` → poser les enregistrements
   SPF (`include:spf.mailjet.com` dans le même SPF) et DKIM indiqués.
3. *Paramètres du compte* → *Clés API* : clé API = utilisateur SMTP, clé secrète = mot de passe.

### 3. Sur le VPS (`/opt/blackturf/.env`)
```
SMTP_HOST=smtp-relay.brevo.com
SMTP_PORT=587
SMTP_USER=xxxx@smtp-brevo.com
SMTP_PASSWORD=<clé SMTP Brevo>
SMTP2_HOST=in-v3.mailjet.com
SMTP2_PORT=587
SMTP2_USER=<clé API Mailjet>
SMTP2_PASSWORD=<clé secrète Mailjet>
```
Puis : `cd /opt/blackturf && docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
(recrée les conteneurs avec les nouvelles variables, pas de rebuild).

### 4. Vérifier
`docker logs blackturf_api 2>&1 | grep -E "smtp_ok|smtp_refus|quota_pause"` après une inscription test.
