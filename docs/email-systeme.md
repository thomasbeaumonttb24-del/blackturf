# Mails éditoriaux BlackTurf

**Envoi activé le 23/09/2026 après validation de l'exploitant.** `EMAIL_EDITORIAL_ENABLED` vaut `0` par défaut dans le code ; la production le fixe explicitement à `1`. Les campagnes quotidiennes et hebdomadaires sont donc planifiées. Les e-mails transactionnels déclenchés par une action du client (vérification d'adresse, réinitialisation de mot de passe, etc.) fonctionnent indépendamment.

Le compte de contrôle `thomas.beaumont.tb24@gmail.com` reçoit **un exemplaire par édition éditoriale réellement envoyée**, même s'il est en formule Free. S'il est déjà dans les destinataires normaux de l'hebdomadaire, il ne reçoit pas de doublon. La copie de contrôle n'inclut aucun lien de désabonnement d'un autre destinataire. Les e-mails de vérification d'adresse et de réinitialisation de mot de passe ne sont jamais copiés : ils contiennent des jetons personnels donnant accès aux comptes. Leur existence et leur statut doivent être contrôlés dans les journaux techniques, sans transmettre ces jetons.

| Famille | Déclencheur | Destinataires | Revue avant envoi |
| --- | --- | --- | --- |
| Valeurs du jour | Tous les jours à 10 h Paris, reprises à 10 h 15/30/45 si nécessaire | Comptes Starter, Standard, Expert éligibles et opt-in | Activé en production ; aperçu `docs/email-previews/quotidien.html` |
| Lettre hebdomadaire | Lundi et mardi, 9 h–20 h Paris, toutes les 30 minutes jusqu'au bilan complet | Inscrits confirmés et comptes actifs éligibles, sans doublon | Activé en production ; aperçu `docs/email-previews/hebdomadaire.html` |
| Confirmation de newsletter | Demande d'inscription | Adresse demandant l'inscription | Transactionnel immédiat |
| Vérification d'adresse et mot de passe | Inscription, renvoi ou demande de réinitialisation | Compte concerné | Transactionnel immédiat, jeton secret |
| Pronostic d'une course | Demande explicite sur la fiche course | Adresse demandant ce pronostic | Transactionnel immédiat, une fois par adresse et course |
| Abonnement et résiliation | Événement Stripe ou demande du compte | Compte concerné ; certaines alertes à l'administration | Transactionnel immédiat |
| Alertes d'exploitation | Incident ou seuil technique | Adresse d'administration | Automatique ; pas de campagne client |

## Cadence et contenu

- **Chaque jour dès 10 h (Paris)** : un relevé horodaté des valeurs encore visibles, pour les comptes Starter/Standard/Expert dont l'adresse est utilisable et la préférence `email_quotidien` active. Aucun mail si aucune valeur n'est disponible. Les passages suivants à 10 h 15, 10 h 30 et 10 h 45 servent uniquement aux reprises ; une campagne `jour-AAAA-MM-JJ` ne livre qu'une fois par adresse. Le seuil de niveau et le délai du plan Standard restent applicables. Les non-partants sont exclus.
- **Lundi dès 9 h (Paris)** : les trois plans de référence bénéficiaires les plus élevés en **bénéfice net du plan complet**, du lundi au dimanche précédents. La lettre précise que ce top 3 ne représente pas la performance globale. Elle compte aussi, parmi les courses avec classement IA live figé avant le départ et arrivée officielle vérifiée, les gagnants présents dans le top 3 annoncé et les premiers choix réellement gagnants. Le dénominateur est le nombre de courses évaluables, jamais toutes les courses sans distinction. Si la semaine n'est pas entièrement réglée, rien n'est publié et la tâche réessaie toutes les 30 minutes jusqu'au mardi 20 h. Aucun résultat partiel n'est présenté comme définitif. Un seul envoi par adresse et période.
- La lettre va aux inscrits **confirmés** et aux comptes actifs à adresse utilisable qui n'ont pas désactivé l'hebdomadaire. Une adresse présente dans les deux listes ne reçoit qu'un seul exemplaire. Le désabonnement newsletter et l'opposition marketing d'un compte restent prioritaires.

Le top et le bilan proviennent de la même règle que les visuels publics : dernier plan du site émis avant le départ, dernier règlement définitif de ce plan, jamais un plan personnel. `mise`, `retour` (mise incluse) et `net` sont contrôlés entre la table de règlement et son bilan JSON avant de figer une édition dans `email_editions`. Les chiffres figés sont publics sur `/api/v1/newsletter/bilans/AAAA-MM-JJ` et ne contiennent ni adresse ni jeton personnel.

## Présentation et aperçu

Les modèles vivent dans `backend/services/email_templates.py`. Ils utilisent le logo public, un seul axe de lecture, des cartes et des styles intégrés compatibles avec les clients mail courants, plus une version texte. Le lien Instagram est présent dans les deux lettres. Générer des aperçus **fictifs**, sans base ni envoi :

Le bilan IA affiche les pourcentages à une décimale et les comptes bruts entre parenthèses. L'icône Instagram est servie depuis `frontend/public/img/email/instagram-glyph.png` ; sa [source est le glyphe Meta publié sur Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Instagram_Glyph_Gradient_RGB_logo.svg). L'image et le texte voisin renvoient au compte `@blackturf.fr`.

Comme la publication Instagram du dimanche, la lettre situe le taux Top 3 face au repère d'un choix aléatoire de trois chevaux, pondéré course par course par le nombre de partants. Le mail utilise sa propre période **lundi–dimanche**, tandis que la mosaïque Instagram du dimanche couvre **dimanche–samedi** : leurs chiffres peuvent donc différer sans contradiction. Le repère n'utilise que les courses dont le nombre de partants est connu ; si c'est un sous-ensemble, son effectif est indiqué explicitement.

```bash
python backend/scripts/preview_emails.py
```

Ouvrir `docs/email-previews/index.html` et inspecter les rendus à 320, 375 et 600 px. Ces fichiers contiennent des nombres de démonstration et ne doivent jamais être présentés comme des résultats réels.

## Livraison et contrôle

`email_livraisons` conserve la requête figée et une clé d'idempotence par campagne/adresse. Resend garantit la non-duplication d'une reprise avec la même clé pendant 24 h. Une tentative dont l'issue reste ambiguë au-delà de 23 h passe à `review` : comparer son identifiant dans Resend avant toute intervention, afin d'éviter un second mail. L'endpoint admin `/api/v1/newsletter/suivi` expose les comptes par campagne et statut, sans adresse.

Les liens de désinscription sont propres à chaque destinataire. Le pied de mail et les en-têtes `List-Unsubscribe`/`List-Unsubscribe-Post` sont actifs. Pour le suivi des rebonds et réclamations, créer **dans le tableau de bord Resend** un webhook pointant sur `https://blackturf.fr/api/v1/newsletter/resend-webhook`, avec les événements `email.delivered`, `email.bounced`, `email.complained`, `email.opened`, `email.clicked`. Placer sa clé de signature `whsec_…` dans `RESEND_WEBHOOK_SECRET` du `.env` serveur, puis recréer l'API. L'endpoint rejette les événements non signés. La clé d'envoi de production est limitée à l'envoi : elle ne peut pas configurer ce webhook. Sans cette configuration, les envois et les logs locaux fonctionnent, mais le suivi automatique des rebonds ne fonctionne pas.

Avant mise en production : exécuter la migration `0053`, les tests des campagnes, vérifier que l'édition de la semaine précédente se calcule à partir de la base de production et constater que la page publique ne révèle aucun jeton. Après déploiement : vérifier la santé API/frontend/scheduler, l'horaire du prochain job et les compteurs de livraison. La migration ne touche aucune table existante ; le retour arrière applicatif peut laisser les deux tables sans perturber les anciens lecteurs.
