# Parrainage — fonctionnement et mise en production

## Règles (décision de l'exploitant, 2026-09-27)

| | Filleul | Parrain |
|---|---|---|
| Ce qu'il obtient | 5 € de remise sur sa **première facture payante** (mensuelle ou annuelle) | 5 € de crédit, déduits **automatiquement** de sa prochaine mensualité ou de l'abonnement qu'il prendra |
| Quand | au checkout, sans rien saisir | **uniquement** quand le paiement du filleul est encaissé (facture > 0 €) |
| Essai gratuit | **aucun**, jamais (même après résiliation) | inchangé |
| Plafond | — | par mois de facturation, de quoi rendre la mensualité gratuite : **4 en Expert** (19 € − 20 € → 0 €), **3 en Standard** (12 € − 15 € → 0 €). Au-delà : crédit gagné mais **reporté au mois suivant**, jamais perdu |

Aucun argent n'est versé : le crédit est posé sur le **solde client Stripe** du parrain
(`customer balance`), que Stripe applique seul aux factures suivantes.

Tout compte à l'adresse confirmée peut parrainer (abonné ou non).

### Calcul de la mensualité du parrain

Stripe impute le solde créditeur sur la facture jusqu'à 0 €, jamais en dessous ; le reste
demeure pour la facture suivante. Une facture à 0 € est réglée sans aucun prélèvement.

| Formule | Filleuls payants dans le mois | Prélevé | Reste au crédit |
|---|---|---|---|
| Expert 19 € | 3 | 19 − 15 = **4 €** | 0 € |
| Expert 19 € | 4 (plafond) | **0 €** | 1 € (déduit le mois suivant) |
| Expert 19 € | 6 | **0 €** | 1 € + 2 crédits reportés → mois suivant 19 − 11 = 8 € |
| Standard 12 € | 3 (plafond) | **0 €** | 3 € |

Le « mois » est la période de facturation Stripe pour un abonné mensuel, le mois civil sinon
(annuel, offert, gratuit — plafond d'Expert). Les crédits reportés sont posés : au paiement de la
facture du parrain (y compris à 0 €), à l'affichage de son suivi, et chaque nuit à 03 h 10
(`job_credits_parrainage`).

Parrain à l'abonnement **offert** (plan accordé à la main, ou code promo à 100 %) : il est crédité
normalement, mais n'ayant aucune facture, ses crédits restent en réserve jusqu'à un abonnement payant.
L'écran et l'e-mail le lui disent tel quel.

## Parcours

1. Le parrain ouvre **Profil → Parrainage** : lien `https://blackturf.fr/inscription?parrain=CODE`
   (code de 8 caractères, aléatoire), bouton copier / partager, suivi de chaque filleul.
2. L'ami s'inscrit par le lien. Le code est vérifié et mémorisé 30 jours dans le navigateur.
   Le parrain est **fixé à la création du compte**, jamais après.
3. Quand l'ami confirme son adresse, le parrain reçoit un e-mail « X a rejoint BlackTurf ».
4. Checkout du filleul : coupon `BLACKTURF_PARRAINAGE_5` (créé automatiquement chez Stripe au
   premier besoin), pas d'essai, pas de saisie de code promo.
5. `invoice.payment_succeeded` (montant > 0) → crédit −5 € sur le solde du parrain, e-mail
   « 5 € offerts », mouvement `parrainage_valide` dans le journal admin.
6. `charge.refunded` / `charge.dispute.created` sur ce premier paiement → crédit repris
   (+5 € sur le solde du parrain), mouvement `parrainage_annule`.

Suivi affiché au parrain, par filleul : `email_a_confirmer` → `attente_paiement` →
`paiement_en_cours` → `verification` → `credite` (ou `refuse` / `annule`).

## Verrous anti-abus

- **Inexploitable économiquement** : la récompense exige un paiement réel du filleul d'au moins
  « prix − 5 € », toujours supérieur aux 5 € de crédit. Remboursement et contestation reprennent le crédit.
- Parrain fixé à l'inscription uniquement ; un seul parrain par compte ; pas d'auto-parrainage.
- Carte du filleul déjà vue sur un autre compte (`cartes_connues`) : pas de remise au checkout si
  elle est déjà enregistrée ; sinon, au paiement, crédit parrain **refusé** et remise du filleul
  **refacturée** sur sa facture suivante.
- Pas de double crédit : clé d'idempotence Stripe + relecture du solde client avant chaque écriture
  (la clé Stripe expire en 24 h) + anti-rejeu des webhooks (`stripe_events`).
- Seul le **premier** paiement du filleul compte : rembourser une mensualité ultérieure ne touche à rien.

Limite connue : une même personne qui ouvre deux comptes avec **deux cartes différentes** et deux
adresses réelles peut se parrainer une fois ; elle paie malgré tout son abonnement (moins 5 €).

## Mise en production

1. **Migration** : `alembic upgrade head` (révision `0054` : colonnes `users.code_parrain`,
   `users.parraine_par_id`, table `parrainages`).
2. **Stripe → Développeurs → Webhooks** : ajouter au point de terminaison existant les événements
   `charge.refunded` et `charge.dispute.created` (les autres sont déjà abonnés).
3. Rien à créer dans Stripe : le coupon se crée seul au premier checkout d'un filleul.
4. CGV : ajouter un paragraphe « Programme de parrainage » reprenant les règles ci-dessus.

## Tests

- `backend/tests/test_parrainage.py` — règles, anti-abus, suivi.
- `backend/tests/test_parrainage_plafond.py` — plafond mensuel, report, montants réellement prélevés.
- `backend/tests/test_parrainage_situations.py` — parrain offert (Victor), abonné, en essai, résilié,
  gratuit, code promo 100 %, filleul lui-même parrain, chaîne, parrain désactivé, codes mal saisis.
- `backend/tests/test_parrainage_parcours_stripe.py` — parcours complet par le vrai webhook signé.
- `backend/tests/test_parrainage_stripe_mock.py` — appels Stripe validés contre la spécification
  officielle ; lancer `stripe-mock -http-port 12111` puis
  `STRIPE_MOCK_URL=http://localhost:12111 pytest tests/test_parrainage_stripe_mock.py`.
