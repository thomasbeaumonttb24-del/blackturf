# Parrainage — fonctionnement et mise en production

## Règles (décision de l'exploitant, 2026-09-27)

| | Filleul | Parrain |
|---|---|---|
| Ce qu'il obtient | 5 € de remise sur sa **première facture payante** (mensuelle ou annuelle) | 5 € de crédit, déduits **automatiquement** de sa prochaine mensualité ou de l'abonnement qu'il prendra |
| Quand | au checkout, sans rien saisir | **uniquement** quand le paiement du filleul est encaissé (facture > 0 €) |
| Essai gratuit | **aucun**, jamais (même après résiliation) | inchangé |
| Plafond | — | illimité en nombre ; Stripe n'impute jamais plus qu'une facture, le reste est reporté |

Aucun argent n'est versé : le crédit est posé sur le **solde client Stripe** du parrain
(`customer balance`), que Stripe applique seul aux factures suivantes.

Tout compte à l'adresse confirmée peut parrainer (abonné ou non).

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
- `backend/tests/test_parrainage_parcours_stripe.py` — parcours complet par le vrai webhook signé.
- `backend/tests/test_parrainage_stripe_mock.py` — appels Stripe validés contre la spécification
  officielle ; lancer `stripe-mock -http-port 12111` puis
  `STRIPE_MOCK_URL=http://localhost:12111 pytest tests/test_parrainage_stripe_mock.py`.
