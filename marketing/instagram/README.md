# Visuels Instagram — BlackTurf

Sources HTML des visuels publiés sur Instagram, dans le style des stories et
publications existantes : carte blanche sur photo de course, logo dans un anneau
or, titres or en petites capitales, gros chiffres noirs, bouton noir `blackturf.fr`.

| Dossier | Contenu |
|---|---|
| `pub-site/post.html` | Publication feed **1080 × 1350** (4:5) — publicité du site |
| `pub-site/story.html` | Story **1080 × 1920** (9:16) — même contenu, photo plus haute |
| `fonts/` | Outfit + Inter (Google Fonts, licence OFL) pour un rendu hors ligne |
| `render.sh` | Rend les PNG avec un Chromium headless |

Les photos et le cheval du logo viennent de `frontend/public/img/` : les
visuels utilisent les vrais assets du site.

## Mettre à jour les chiffres

Tout est en clair dans le HTML : période, `65,1 %`, `235 sur 361`, les trois
meilleurs gains, le total rendu par les plans, etc. Modifier le texte puis :

```bash
marketing/instagram/render.sh pub-site
```

Les PNG `post.png` / `story.png` sont écrasés. Les `@2x.png` sont des rendus
haute définition (2160 px de large) pour un éventuel usage print ou recadrage.

## Règles à respecter (ANJ)

- Jamais de promesse de gain (« vous auriez gagné X € »). On montre des
  résultats réels, réglés aux rapports PMU, et le mot « hasard » sert de
  comparaison (tirage au sort : 30,4 %).
- Conserver la mention légale en bas : risques, 09 74 75 13 13, interdit aux
  mineurs.
