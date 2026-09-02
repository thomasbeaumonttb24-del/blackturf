# Plaquette commerciale BlackTurf

Plaquette 4 pages A4 (210 × 297 mm), destinée à la publicité : envoi par e-mail,
impression, publication en ligne.

- `plaquette-blackturf.pdf` — le document prêt à diffuser (4 pages, 96 px/pouce).
- `Main.dc.html` · `Methode.dc.html` · `Produit.dc.html` · `Formules.dc.html` —
  une page par fichier, HTML pur avec styles en ligne. Ce sont les sources : pour
  corriger un texte ou un prix, on édite ici.
- `canvas.json` — l'ordre et la position des quatre pages.
- Images : recadrées et recompressées depuis `frontend/public/img/`.
  `mark-white.png` / `mark-ink.png` sont le cheval du logo, décliné pour fond
  sombre et fond clair.

## Contenu

| Page | Sujet |
|------|-------|
| 1 | Couverture — promesse, trois faits clés |
| 2 | La méthode — les trois étapes, les 80+ critères en 4 familles |
| 3 | Le produit — plan de mise par profil, pari de valeur, suivi du capital |
| 4 | Formules — les trois plans, ce qui ne change pas, appel à l'action |

## Régénérer le PDF

Les pages sont du HTML classique : n'importe quel navigateur en mode
« Imprimer → Enregistrer au format PDF », format A4 sans marges, produit le
document. Les chiffres montrés (paris, capital, cote 8,5) sont des exemples
illustratifs, marqués comme tels sur les pages.

## Ce qui reste à décider

Aucun taux de réussite n'est imprimé : les statistiques du palmarès évoluent à
chaque réunion, et une plaquette imprimée les fige. La plaquette renvoie donc au
palmarès public de blackturf.fr plutôt que d'avancer un pourcentage.
