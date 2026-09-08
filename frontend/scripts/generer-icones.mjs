/**
 * Fabrique les icônes de marque à partir du VRAI logo.
 *
 *   node scripts/generer-icones.mjs
 *
 * ─────────────────────────── CE QU'ON RÉPARE ───────────────────────────────────────────
 *
 * Les icônes PWA (`public/icons/icon-*.png`) étaient un carré orange portant « BT » —
 * un gabarit jamais remplacé. C'est ce que voyait un visiteur qui installait le site sur
 * son téléphone. Et `public/favicon.ico` mesurait 48 × 26 : une favicone NON CARRÉE est
 * écartée par Google, qui affiche alors un globe générique à côté du résultat de
 * recherche — la marque disparaît de la page de résultats.
 *
 * ─────────────────────────── POURQUOI UN MÉDAILLON SANS LE MOT ─────────────────────────
 *
 * Le logo complet porte « BLACKTURF » à l'intérieur de l'anneau. À 16 px — la taille
 * réelle d'une favicone d'onglet et d'un résultat Google — ce mot fait deux pixels de
 * haut : il ne se lit pas, il salit. On garde donc les deux éléments qui restent
 * reconnaissables à cette taille, le cheval et l'anneau doré, et on laisse le nom au
 * texte qui accompagne toujours l'icône (titre de l'onglet, nom du résultat).
 *
 * Le mot reste sur les surfaces où il se lit : `src/app/apple-icon.png` (180 px sur
 * l'écran d'accueil) et la vignette de partage `public/og-image.jpg`.
 *
 * ─────────────────────────── ZONE DE SÉCURITÉ ──────────────────────────────────────────
 *
 * Les icônes 192 et 512 sont déclarées `maskable` dans le manifeste : Android peut les
 * recadrer en cercle et rogne jusqu'à 10 % de chaque bord. Le médaillon y est donc réduit
 * à 78 % du carré — sinon l'anneau, qui touche presque le bord, serait tranché.
 */
import fs from 'node:fs/promises';
import path from 'node:path';
import sharp from 'sharp';

const RACINE = path.resolve(import.meta.dirname, '..');
const p = (...s) => path.join(RACINE, ...s);

/** Or relevé au pixel sur l'anneau du logo source — pas un doré approché. */
const OR = '#B29657';
const LOGO = p('public', 'img', 'logo-blackturf.png');
const CHEVAL = p('public', 'img', 'logo-horse.png');

/**
 * Le médaillon : anneau doré + cheval, sur blanc.
 *
 * `echelle` < 1 réserve la marge des icônes recadrables. `trait` suit la taille pour que
 * l'anneau ne devienne ni un cheveu à 512 px ni un beignet à 32 px.
 */
async function medaillon(taille, echelle = 1) {
  const c = taille / 2;
  const r = taille * 0.455 * echelle;
  const trait = Math.max(1, taille * 0.026 * echelle);
  const fond = Buffer.from(
    `<svg width="${taille}" height="${taille}" xmlns="http://www.w3.org/2000/svg">` +
      `<rect width="${taille}" height="${taille}" fill="#FFFFFF"/>` +
      `<circle cx="${c}" cy="${c}" r="${r}" fill="none" stroke="${OR}" stroke-width="${trait}"/>` +
      `</svg>`,
  );
  const cheval = await sharp(CHEVAL)
    .trim()
    .resize({ width: Math.max(8, Math.round(taille * 0.76 * echelle)) })
    .toBuffer();
  return sharp(fond).composite([{ input: cheval, gravity: 'center' }]).png().toBuffer();
}

/**
 * Assemble un .ico multi-tailles à charge PNG.
 *
 * Le format ICO accepte des images PNG telles quelles depuis Windows Vista, et tous les
 * navigateurs actuels les lisent : pas besoin de réencoder en BMP. Les trois tailles
 * couvrent l'onglet (16), le raccourci (32) et la favicone que Google demande — carrée et
 * multiple de 48.
 */
async function ico(tailles) {
  const images = [];
  for (const t of tailles) {
    const source = await medaillon(Math.max(t, 256));
    images.push({ taille: t, png: await sharp(source).resize(t, t).png({ compressionLevel: 9 }).toBuffer() });
  }
  const entete = Buffer.alloc(6);
  entete.writeUInt16LE(0, 0); // réservé
  entete.writeUInt16LE(1, 2); // 1 = icône
  entete.writeUInt16LE(images.length, 4);
  let decalage = 6 + images.length * 16;
  const repertoire = [];
  for (const { taille, png } of images) {
    const e = Buffer.alloc(16);
    e[0] = taille >= 256 ? 0 : taille; // 0 signifie 256
    e[1] = taille >= 256 ? 0 : taille;
    e[2] = 0; // palette
    e[3] = 0; // réservé
    e.writeUInt16LE(1, 4); // plans
    e.writeUInt16LE(32, 6); // bits par pixel
    e.writeUInt32LE(png.length, 8);
    e.writeUInt32LE(decalage, 12);
    decalage += png.length;
    repertoire.push(e);
  }
  return Buffer.concat([entete, ...repertoire, ...images.map((i) => i.png)]);
}

const TAILLES_PWA = [72, 96, 128, 144, 192, 512];
/** Recadrables côté Android : elles seules ont besoin de la marge. */
const RECADRABLES = new Set([192, 512]);

async function main() {
  await fs.writeFile(p('public', 'favicon.ico'), await ico([16, 32, 48]));
  console.log('favicon.ico  16/32/48 carrées');

  for (const t of TAILLES_PWA) {
    const source = await medaillon(512, RECADRABLES.has(t) ? 0.78 : 1);
    await sharp(source).resize(t, t).png().toFile(p('public', 'icons', `icon-${t}.png`));
    console.log(`icons/icon-${t}.png`);
  }

  // Icône d'onglet et de résultat de recherche : Next la sert depuis `src/app/icon.png`.
  await fs.writeFile(p('src', 'app', 'icon.png'), await medaillon(512));
  console.log('src/app/icon.png');

  // Logo d'entité (JSON-LD `Organization.logo`) : Google le veut d'au moins 112 px de
  // côté, l'ancien fichier faisait 160 × 87 — trop court en hauteur, donc ignoré.
  //
  // On ne ROGNE PAS la marge blanche ici : `logo.png` est aussi l'image de la barre de
  // navigation et du pied de page, posée dans une boîte carrée en `object-contain`. Un
  // fichier rogné (donc presque carré) y occuperait soudain toute la boîte et grossirait
  // le logo du site. Même cadrage qu'avant, seulement plus de pixels.
  await sharp(LOGO).resize({ width: 640 }).png({ compressionLevel: 9 }).toFile(p('public', 'logo.png'));
  const m = await sharp(p('public', 'logo.png')).metadata();
  console.log(`logo.png     ${m.width} × ${m.height}`);
}

await main();
