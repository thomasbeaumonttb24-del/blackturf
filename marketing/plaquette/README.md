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

## Les performances imprimées

La couverture porte les trois taux publiés sur `blackturf.fr/track-record` —
précision Top-3 60,1 %, favori placé 64,1 %, favori gagnant 30,7 % — avec le
dénominateur qui les rend lisibles : 4 265 courses réglées aux résultats PMU
officiels. **Ces chiffres bougent à chaque réunion.** Toute réimpression doit
les relire sur le site ; sinon le dépliant affiche un palmarès périmé. Le
dénominateur et la mention « palmarès public » doivent rester avec eux : des
pourcentages sans nombre de courses ne valent rien.

## Le plan de mise imprimé

Le volet de droite reproduit le plan tel qu'il sort sur la **page course**
(`frontend/src/app/(main)/courses/[id]/page.tsx`), pas la démo de la landing :
onglets de profil, cartes Budget et Rendement estimé, puis les niveaux
**SÉCURITÉ / RENDEMENT / GROS LOT** — les libellés viennent de `NIVEAU_META`
dans `backend/services/mise_calculator.py`. Les teintes sont celles du `CX` de la
page course : sécurité émeraude (`#ECFDF5` / `#A7F3D0` / `#047857`), rendement or
(`#FEF6E7` / `#F5DCA8` / `#92400E`), gros lot rouge (`#FEF2F2` / `#FECACA` /
`#B91C1C`). Chaque pari porte son type, ses chevaux en `N°x + N°y`, sa
probabilité estimée, sa mise et son gain estimé — comme à l'écran.

Les trois paris retenus respectent la configuration réelle du profil modéré
(`PROFIL_CONFIG["equilibre"]`) : bande de rapport ×4 à ×15, et pour le Simple
Gagnant une probabilité au-dessus de `sg_min_proba` (0,11). Un 2 sur 4 y figurait
au départ : sa mise et son rapport ne se calculent pas comme ceux d'un pari
simple, il a été remplacé.

Écarté volontairement pour le papier : « Lecture de l'algorithme », « Voir les
raisons », les paris écartés et le bloc de rendement réel observé. Le rendement
estimé affiché (+2,1 %) est de l'ordre de ce que le moteur produit réellement —
le commentaire de la page course note que l'espérance théorique ressort autour
de 0 à +2 %.

## Les silhouettes de disciplines

Elles ne viennent plus de `frontend/public/img/disciplines/` : `attele-v2.png` y
est défectueux — la roue du sulky y est tranchée en passant par son moyeu, et
aucun recadrage ne rattrape ça. Elles ont été refournies, complètes et mieux
dessinées, et sont conservées ici comme sources :

    src-plat.png  src-attele.png  src-monte.png  src-obstacle.png

Détourées du fond blanc par la luminance (`alpha = (240 − L) / 180`), ce qui
garde l'antialiasing des traits fins — rênes, crinière, rayons de roue — là où
un seuil sec les hacherait. Les taches d'artefact JPEG de moins de 60 px sont
supprimées.

`gen_disc.py` produit ensuite les quatre `disc-*.png` : recadrage au contenu,
mise à l'échelle, pose sur une toile de 200 px de haut avec une ligne de sol
commune à y=178 et 14 px de marge latérale. Toile de hauteur identique pour les
quatre, largeur propre à chacun — d'où l'alignement des sols en
`align-items: flex-end` avec `width: auto` côté HTML.

Les multiplicateurs `1.00 / 0.95 / 1.00 / 1.08` corrigent ce que la boîte
englobante ne mesure pas : elle englobe la haie de l'obstacle et le sulky de
l'attelé, si bien qu'à hauteur de boîte égale leurs **chevaux** ne font pas la
même taille que celui du plat. Pour régénérer :

    python3 gen_disc.py 1.00 0.95 1.00 1.08

Imprimées à 46 px de haut ; les quatre occupent 213 px dans une colonne de 314.

## Les critères affichés

Les 25 critères nommés au volet du milieu sont de vraies variables du moteur,
relevées dans `backend/ml/features.py` et `backend/ml/race_dynamics.py` — par
exemple `bounce_score` (contrecoup après un gros effort), `draw_bias_score`
(biais de corde), `pace_conflict_score` (combien de chevaux veulent mener),
`sire_terrain_winrate` (réussite du père sur ce terrain), `distance_deplacement`
(kilomètres faits pour venir courir), `spi_score` (argent professionnel). Elles
sont choisies pour être peu courantes : c'est ce qui distingue l'analyse d'une
lecture de la musique. Aucun détail d'implémentation du modèle n'est imprimé.

## Ce qui n'est pas imprimé, et pourquoi

Aucun taux de réussite ne figure sur le dépliant. Ces chiffres bougent à chaque
réunion et un imprimé les figerait ; le dépliant renvoie donc au palmarès public
de blackturf.fr. Les paris et les gains montrés au volet « plan de mise » sont
des exemples sur une course type, signalés comme tels sous le bloc.

La mention de jeu responsable et le numéro de joueurs-info-service figurent au
dos — ils doivent rester sur toute réimpression.
