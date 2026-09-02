/**
 * Fabrique les masques de discipline utilisés par les icônes (`*-v9.png`).
 *
 * Source : les illustrations `*-src.jpg` (1024 px, fond blanc), reprises TELLES
 * QUELLES. Le masque ne doit rien retrancher au dessin : chaque passe ci-dessous
 * ne fait que le rendre lisible à 26 px.
 *
 *   1. alpha tiré de la luminance (le JPEG n'a pas de couche alpha) : le seuil
 *      haut écarte le bruit de compression du fond, la rampe garde l'anticrénelage ;
 *   2. dilatation de l'alpha par un noyau EN DISQUE : à 22-30 px, jambes et rênes
 *      tombent sous le pixel et se délavent. Un noyau CARRÉ (essai précédent)
 *      aplatit sabots et naseaux en moignons — le cheval paraît scié ;
 *   3. marge transparente de 7 % : sans elle les sabots touchent le bord de la zone
 *      peinte par `mask-size: contain` et l'œil lit « coupé » sur une image entière.
 *
 * CE QU'IL NE FAUT PAS REMETTRE (deux passes retirées le 02/09, elles amputaient
 * le dessin — l'utilisateur a vu la jambe manquante avant moi) :
 *   - « suppression des décors isolés » (composantes < 8 % de la principale) :
 *     dans ces illustrations les membres du côté opposé sont dessinés DÉTACHÉS du
 *     corps. Mesuré : jambe du plat 6,4 %, jambe du monté 6,1 %, quatre morceaux
 *     de l'attelage entre 0,7 et 5,6 %. Le seuil les emportait tous ;
 *   - « rebouchage des liserés internes » : les traits blancs (crinière, selle,
 *     harnais) appartiennent au dessin. Invisibles à 26 px de toute façon.
 * Toute passe qui SUPPRIME des pixels doit être prouvée sur les quatre
 * illustrations avant d'être ajoutée, jamais réglée sur une seule.
 *
 * Vérification obligatoire : capturer en DPR 1 ET au DPR réel de l'écran visé
 * (Windows à 125 % → 1,25), puis agrandir au plus proche voisin. Une capture en
 * DPR ≥ 2 ment : le masque y est rastérisé plus finement qu'en vrai.
 *
 *   node scripts/build-discipline-masks.mjs
 */
import sharp from 'sharp';
const TH = 8;
const R_FACTOR = 0.005;
const MARGE = 0.07;
const LARGEUR_MAX = 512; // affiché à 26 px : au-delà on ne stocke que du poids
// luminance → alpha : sous LUM_FOND c'est du sujet, au-dessus du fond blanc
const LUM_FOND = 230;
const LUM_SUJET = 60;

const disk = (r) => {
  const o = [];
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r + 0.25) o.push([dx, dy]);
  return o;
};

for (const name of ['attele', 'plat', 'monte', 'obstacle']) {
  const src = `public/img/disciplines/${name}-src.jpg`;
  // le sujet peut toucher le bord (ligne de sol de l'obstacle) : on lui donne de
  // la place pour que la dilatation ne soit pas tronquée.
  const EXT = 16;
  const { data, info } = await sharp(src)
    .greyscale()
    .extend({ top: EXT, bottom: EXT, left: EXT, right: EXT, background: { r: 255, g: 255, b: 255 } })
    .raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h, channels: c } = info;

  // 1. alpha depuis la luminance, rampe douce pour garder l'anticrénelage
  const a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const l = data[i * c];
    const v = Math.round(((LUM_FOND - l) / (LUM_FOND - LUM_SUJET)) * 255);
    a[i] = v < 0 ? 0 : v > 255 ? 255 : v;
  }

  // 2. dilatation par DISQUE (un noyau carre aplatirait sabots et naseaux)
  const offs = disk(Math.max(1, Math.round(w * R_FACTOR)));
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 0;
    for (const [dx, dy] of offs) { const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue; const v = a[yy * w + xx]; if (v > m) m = v; }
    out[y * w + x] = m;
  }

  // garde : le masque ne doit RIEN retrancher au dessin. Une passe soustractive
  // ajoutée plus tard (filtre de composantes, seuil trop dur) casse ici au lieu
  // de partir en prod avec un cheval à trois jambes.
  for (let i = 0; i < w * h; i++) if (a[i] > TH && out[i] <= TH) {
    throw new Error(`${name}: le masque perd des pixels du dessin (index ${i})`);
  }

  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (out[y * w + x] > TH) {
    if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  // 3. marge transparente : sans elle les sabots touchent le bord de la zone peinte
  const pad = Math.round((maxY - minY + 1) * MARGE);
  const W2 = maxX - minX + 1 + 2 * pad, H2 = maxY - minY + 1 + 2 * pad;
  const rgba = Buffer.alloc(W2 * H2 * 4);
  for (let y = 0; y < H2; y++) for (let x = 0; x < W2; x++) {
    const sx = minX - pad + x, sy = minY - pad + y;
    if (sx < 0 || sy < 0 || sx >= w || sy >= h) continue;
    rgba[(y * W2 + x) * 4 + 3] = out[sy * w + sx];
  }
  const dst = (process.env.OUT || 'public/img/disciplines') + `/${name}-v9.png`;
  let img = sharp(rgba, { raw: { width: W2, height: H2, channels: 4 } });
  if (W2 > LARGEUR_MAX) img = img.resize({ width: LARGEUR_MAX });
  await img.png({ compressionLevel: 9 }).toFile(dst);
  console.log(name, `${w - 2 * EXT}x${h - 2 * EXT} → ${Math.min(W2, LARGEUR_MAX)}px`);
}
