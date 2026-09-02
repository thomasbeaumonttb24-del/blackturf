# Dépliant commercial BlackTurf

Dépliant trois volets, à laisser sur les tables des points PMU. Une feuille A4
paysage (297 × 210 mm), imprimée recto/verso et pliée en trois.

- `depliant-blackturf.pdf` — le document à donner à l'imprimeur, 2 pages
  (extérieur, intérieur).
- `Main.dc.html` — la face **extérieure**. De gauche à droite : rabat intérieur ·
  dos · couverture. La couverture est à droite parce que c'est elle qui se
  retrouve dessus une fois plié.
- `Interieur.dc.html` — la face **intérieure**, lue d'un seul tenant quand le
  dépliant s'ouvre : comment ça marche · l'algorithme · le plan de mise.
- `canvas.json` — la disposition des deux faces.
- `qr.png` — code QR vers `https://blackturf.fr`, présent sur la couverture et
  sur le dos. Il est décodable aux deux tailles imprimées (≈ 20 et 26 mm).

## Imprimer et plier

Recto/verso, **retournement sur le bord court**, sans marges, à **100 %** (aucune
mise à l'échelle : c'est ce qui garde les plis au bon endroit). Puis rabattre le
volet de gauche vers l'intérieur et le volet de droite par-dessus. Les deux traits
gris clair, en haut et en bas de la feuille, marquent les plis.

Le papier : un 170 g mat tient debout sur une table et ne gondole pas. En 80 g
ordinaire le dépliant s'affaisse.

## Modifier un texte ou un prix

Les deux faces sont du HTML à styles en ligne, sans dépendance : on ouvre le
fichier, on change le texte, on réimprime depuis le navigateur (format A4
paysage, sans marges). Les images sont dans le même dossier.

## Le plan de mise imprimé

Le volet de droite reproduit la sortie réelle du calculateur, pas un résumé :
profils Prudent / Modéré / Risqué, niveaux Sécurité / Rendement / Coup, espérance
estimée, mise totale. Les chiffres sont ceux que le site produit pour un plan
Modéré à 20 € — les pondérations viennent de `frontend/src/components/home/
CalculatorDemo.tsx` (0,40 / 0,35 / 0,15, renormalisées à 100 %), et les couleurs
de niveau des classes `.plan-securite` / `.plan-rendement` / `.plan-coup` de
`globals.css`. Si ces pondérations changent dans le produit, les pourcentages du
dépliant sont à refaire.

## Les silhouettes de disciplines

Recadrées au contenu depuis `frontend/public/img/disciplines/` : les fichiers
d'origine portent des marges transparentes inégales (17 à 32 px) qui posaient les
quatre chevaux sur quatre lignes de sol différentes. Elles sont imprimées à 38 px
de haut — en dessous de ~34 px les pattes disparaissent et les silhouettes
paraissent tronquées.

## Ce qui n'est pas imprimé, et pourquoi

Aucun taux de réussite ne figure sur le dépliant. Ces chiffres bougent à chaque
réunion et un imprimé les figerait ; le dépliant renvoie donc au palmarès public
de blackturf.fr. Les paris et les gains montrés au volet « plan de mise » sont
des exemples sur une course type, signalés comme tels sous le bloc.

La mention de jeu responsable et le numéro de joueurs-info-service figurent au
dos — ils doivent rester sur toute réimpression.
