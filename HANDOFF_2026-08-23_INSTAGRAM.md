# Handoff — 23 août 2026 : SEO, newsletter, Instagram

Session longue. Tout ce qui suit est **déployé en production** sauf mention contraire.
Prod = build local sur le VPS ; `git push vps HEAD:main` puis rebuild du service concerné.

---

## Où en est le chantier

### SEO — terminé
- Bug racine : `alternates: { canonical: "/" }` dans `src/app/layout.tsx` était **hérité**
  par toutes les pages → Google fusionnait `/programme` et les ~250 fiches course avec
  l'accueil. Corrigé, chaque page pose son canonical.
- `/programme` et `/courses/[id]` sont passées en rendu serveur (`page.tsx` serveur qui
  passe les données en props au composant client renommé `ProgrammeClient` /
  `CourseClient`). Avant, le HTML servi était vide.
- Pages neuves : `/quinte-du-jour`, `/resultats`, `/resultats/[jour]` (archives).
- Audit officiel (`skill seo-google`) : **0 erreur, 0 alerte** sur 18 pages.
- Sitemap : 92 → 182 URLs, `lastmod` réels, `priority`/`changefreq` retirés.

### Newsletter — terminée (alembic 0039)
Double opt-in, formulaire sur accueil / programme / quinté / résultats / fiche course.
Invariants testés : pas d'énumération d'adresses, jeton à usage unique, ligne conservée
à la désinscription.

### IndexNow — terminé
Clé `c44de2aebaa349aa85a347c5c8027263`, job à 08:30 et 22:30. **Ne touche pas Google**,
seulement Bing / Yandex / Naver / Seznam.

### Instagram — TOUT est prêt, RIEN n'est publié
- App Meta **BlackTurf Publication** `1798925871293047`, ID d'app IG `2841796542886355`.
- Voie **Instagram Login** (`graph.instagram.com`) : **aucune Page Facebook requise**.
- `INSTAGRAM_USER_ID = 17841433070236786` dans le `.env` du VPS.
- Jeton déposé depuis `/admin/instagram`, stocké en base (`jetons_integration`,
  alembic 0040), renouvelé automatiquement (job 04:20, il expire à 60 jours).
- Vérifié : `quota_restant()` renvoie 100 → le jeton parle bien à l'API.
- **`INSTAGRAM_PUBLICATION_ACTIVE=0`.** C'est le seul réglage qui autorise une
  publication réelle. **Ne jamais l'ouvrir sans demande explicite de Thomas.**

---

## La mosaïque — l'objet de la dernière heure

Six publications qui forment **une seule image** sur la grille du profil.

### Géométrie (le cœur du sujet)
La grille de profil Instagram n'est plus carrée depuis 2025 : chaque vignette est rognée
en **3:4**. On publie donc en 4:5 (1080 × 1350), et la grille n'en montre que le centre :
1012 × 1350.

```
plan d'ensemble = 34 + 3 × 1012 + 34 = 3104 de large, 2 × 1350 = 2700 de haut
tuile (r,c)     = fenêtre 1080 × 1350, décalage ( −c × 1012 , −r × 1350 )
```

### Ordre de publication — INVERSÉ
La grille se remplit du plus récent en haut à gauche. Publier dans l'ordre de lecture
donnerait l'image tête-bêche. Ordre correct, déjà servi trié par le site :

```
1-2 → 1-1 → 1-0 → 0-2 → 0-1 → 0-0   (0-0 en dernier)
```

### Fichiers
| Rôle | Chemin |
|---|---|
| Composition | `frontend/src/lib/mosaique.tsx` |
| Rendu d'une tuile | `frontend/src/app/visuels/mosaique/[tuile]/route.tsx` |
| Tuiles + légendes triées | `frontend/src/app/visuels/mosaique/legendes.json/route.ts` |
| Polices embarquées | `frontend/src/assets/fonts/*.ttf` |
| Données | `GET /api/v1/stats/meilleurs-plans-jour` |
| Publication | `services/instagram.publier_mosaique()` |
| Déclencheur | `POST /admin/api/integrations/instagram/publier-mosaique` |

### Direction visuelle actuelle
Fond ivoire `#F5F2EA`, encre `#15181D`, or profond `#9C6B12` pour le texte, `#E0A63C`
pour les aplats. Photo de course en pleine lumière sur toute la rangée haute, cartes
blanches posées dessus sans remplir la largeur des colonnes (la photo respire entre
elles — c'est ce qui fait voir une seule image). Bandeau légal continu en bas.

Cinq photos en rotation selon le quantième : `showcase.webp`, `duel.webp`,
`hero-1600.webp`, `value.jpg`, `cta.jpg`.

### Pour prévisualiser sans publier
```bash
# rendre les six tuiles depuis la prod
for t in 0-0 0-1 0-2 1-0 1-1 1-2; do
  curl -sS "https://blackturf.fr/visuels/mosaique/$t" -o "tuile-$t.jpg"
done
```
Puis recomposer en n'assemblant que les **1012 px centraux** de chaque tuile (34 px de
débord de chaque côté), sinon l'aperçu ne correspond pas à ce que montre la grille.

---

## Pièges déjà payés — ne pas les repayer

1. **Satori ignore les fragments React** (`<>…</>`) comme enfants d'un flex : les
   éléments se superposent, sans aucune erreur. Tout en `div` explicites.
2. **Satori n'a pas de navigateur** : sans fichier de police fourni, il retombe sur une
   fonte générique. Les `.ttf` sont dans le dépôt.
3. **Satori ne décode pas le WebP** : conversion `sharp` à la volée.
4. **L'API Instagram n'accepte que du JPEG**, et va chercher l'image elle-même — elle
   doit être publique et en https.
5. **Les routes admin sont sur `/admin/api/*`, hors `/api/v1`.** Le client axios porte
   `/api/v1` dans sa `baseURL` : tout appel admin doit passer par `adminApi`. Sinon
   l'écran reste en chargement, sans erreur.
6. **Le jour d'une course est celui du PMU** (8 premiers caractères de `course_id`), pas
   `date_heure` : une course à 22 h 50 UTC bascule au lendemain heure de Paris.
7. **Ne jamais sommer `bet_plan_settlements`** (append-only) : partir de la vue
   `bet_plan_settlement_actuel`.
8. **Une date relue en base peut revenir sans fuseau** : normaliser avant toute
   soustraction.

---

## Règles produit — non négociables

- **Jamais de promesse de gain.** Le ROI mesuré est négatif (prélèvement PMU ~20 %,
  avantage du modèle ~+2,2 points). L'argument commercial est « le seul service qui
  publie ses pertes ».
- **Vocabulaire des montants** : « misés » et « rendus par le plan ». Jamais « gagné »
  ni « bénéfice » — ce sont des plans calculés et réglés aux rapports réels, pas de
  l'argent encaissé.
- **Mention de jeu responsable** sur chaque visuel et dans chaque légende. Les
  plateformes en sanctionnent l'absence avant l'ANJ.
- **Publicité Meta** : autorisation écrite obligatoire pour tout contenu lié aux jeux
  d'argent en France, pronostics inclus. Rien à lancer avant.

---

## LA TÂCHE IMMÉDIATE

**Retravailler les textes et la présentation des six tuiles** : plus accrocheur, mieux
composé, plus vendeur. Rien n'est publié, donc tout est modifiable librement.

Où se trouve quoi :
- **les textes affichés sur les visuels** → `frontend/src/lib/mosaique.tsx`, dans
  `PlanEnsemble` (une section commentée par tuile) ;
- **les légendes des publications** → `frontend/src/app/visuels/mosaique/legendes.json/route.ts`.

Contenu actuel des six tuiles :
| Tuile | Contenu |
|---|---|
| 0-0 | marque, date, « 46 courses analysées, 7 réunions » |
| 0-1 | meilleur plan du jour : Vincennes R1C4, 10 € misés → 883 € rendus |
| 0-2 | les deux suivants : Lion d'Angers R5C1 (478,80 €) et R5C2 (409 €) |
| 1-0 | cinq atouts du produit |
| 1-1 | « Le PMU prélève environ 20 % des enjeux » + l'argument d'honnêteté |
| 1-2 | 7 jours offerts, blackturf.fr, les trois formules |

Décision produit déjà arbitrée par Thomas : **on affiche les trois meilleurs plans avec
mise et retour, SANS le bilan net du jour** (qui était de −7 647 € sur 41 369 € misés).
Il a été prévenu du risque et a tranché. La tuile 1-1 sur le prélèvement de 20 % et
l'absence de promesse de gain est le contrepoids : **la garder**.

Méthode de travail qui a fonctionné : modifier, rendre les six tuiles, recomposer
l'aperçu de grille, REGARDER l'image, corriger. Trois allers-retours ont été nécessaires
(fragments Satori, photo délavée, chevauchement du bandeau légal). Ne pas livrer sans
avoir regardé le rendu.

---

## Ce qui attend une décision

**Publier la mosaïque.** Tout est prêt. Il manque `INSTAGRAM_PUBLICATION_ACTIVE=1` puis
l'appel à `/admin/api/integrations/instagram/publier-mosaique`.

Avertissement à redire : une mosaïque **fige la grille**. Toute publication ultérieure la
décale d'un cran et casse l'image. Deux stratégies possibles — publier ensuite par
paquets de 3 pour la faire glisser proprement, ou l'assumer comme vitrine de lancement.

---

## Reste à faire (plan de sprint)

| Jour | Objectif | État |
|---|---|---|
| 1 | Réparer l'invisibilité + référentiel Google | ✅ |
| 2 | Capture d'e-mail | ✅ |
| 3 | Lettre du lundi automatisée + archive indexable | à faire |
| 4 | Ouvrir `/track-record` et `/statistiques` à l'indexation | à faire |
| 5 | 16 → ~60 pages hippodrome | à faire |
| 6 | Fiches chevaux et jockeys indexables | à faire |
| 7 | Relevé Search Console, nouvel audit | à faire |

**Indicateur à surveiller** : le nombre de **pages indexées** dans Search Console
(31 au 23/08), pas les clics. Les positions ne bougent qu'à 4-8 semaines.

Comptes sociaux restant à créer par Thomas : X, Facebook, TikTok.
