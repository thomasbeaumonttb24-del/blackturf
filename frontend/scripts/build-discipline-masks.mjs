/**
 * Fabrique les masques de discipline utilisés par les icônes (`*-v8.png`).
 *
 * Source : les illustrations `*-src.jpg` (1024 px, fond blanc). Les anciennes
 * `*-v2.png` (395 px, sujet rogné au ras et roue de sulky tronquée) sont
 * remplacées — les rustines de reconstruction (roue, museau) n'ont plus lieu
 * d'être, l'illustration est entière.
 *
 * Passes, chacune corrige un défaut constaté à l'écran :
 *   1. alpha tiré de la luminance (le JPEG n'a pas de couche alpha) : le seuil bas
 *      écarte le bruit de compression du fond, la rampe garde l'anticrénelage ;
 *   2. trous internes rebouchés : les liserés blancs de l'illustration (crinière,
 *      selle, harnais) se lisent comme des trous à 26 px. Seuls les trous FERMÉS
 *      sont remplis, les jours entre les jambes restent ouverts ;
 *   3. décors isolés supprimés (drapeau d'obstacle), qui volaient la place au cheval ;
 *   4. dilatation de l'alpha par un noyau EN DISQUE : à 22-30 px, jambes et rênes
 *      tombent sous le pixel et se délavent. Un noyau CARRÉ (essai précédent)
 *      aplatit sabots et naseaux en moignons — le cheval paraît scié ;
 *   5. marge transparente de 7 % : sans elle les sabots touchent le bord de la zone
 *      peinte par `mask-size: contain` et l'œil lit « coupé » sur une image entière.
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
// poche fermée à reboucher : au-delà, c'est un jour de l'illustration (triangle
// des brancards, dessous du cheval), pas un liseré de dessin.
const SEUIL_POCHE = 0.02;

const disk = (r) => {
  const o = [];
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r + 0.25) o.push([dx, dy]);
  return o;
};

for (const name of ['attele', 'plat', 'monte', 'obstacle']) {
  const src = `public/img/disciplines/${name}-src.jpg`;
  // marge : le sujet peut toucher le bord (ligne de sol de l'obstacle), on veut
  // un anneau de fond continu pour le remplissage des trous.
  const EXT = 16;
  const { data, info } = await sharp(src)
    .greyscale()
    .extend({ top: EXT, bottom: EXT, left: EXT, right: EXT, background: { r: 255, g: 255, b: 255 } })
    .raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h, channels: c } = info;

  // 1. alpha depuis la luminance, rampe douce pour garder l'anticrénelage
  let a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) {
    const l = data[i * c];
    const v = Math.round(((LUM_FOND - l) / (LUM_FOND - LUM_SUJET)) * 255);
    a[i] = v < 0 ? 0 : v > 255 ? 255 : v;
  }

  const rf = Math.max(1, Math.round(w * R_FACTOR));
  const morph = (buf, r, mode) => {
    const o = disk(r), res = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
      let m = mode === 'max' ? 0 : 255;
      for (const [dx, dy] of o) {
        const xx = x + dx, yy = y + dy;
        const v = xx < 0 || yy < 0 || xx >= w || yy >= h ? (mode === 'max' ? 0 : 255) : buf[yy * w + xx];
        if (mode === 'max' ? v > m : v < m) m = v;
      }
      res[y * w + x] = m;
    }
    return res;
  };
  // 2. liserés internes rebouchés. Le détecteur travaille sur une FERMETURE
  // (dilatation puis érosion) : les liserés de l'illustration font 8-10 px, la
  // fermeture les soude, ce qui referme les cuvettes que le remplissage de trous
  // laisserait ouvertes (selle du plat et du monté, qui débouchent sur le fond).
  // La fermeture ne sert QUE de détecteur : l'appliquer à l'alpha souderait aussi
  // les brancards du sulky à la croupe et rendrait un pâté à la place de l'attelage.
  const ferme = morph(morph(a, rf, 'max'), rf, 'min');
  const aire = a.reduce((n, v) => n + (v > TH ? 1 : 0), 0);
  const vu = new Uint8Array(w * h);
  let bouches = 0;
  for (let i0 = 0; i0 < w * h; i0++) {
    if (ferme[i0] > TH || vu[i0]) continue;
    const poche = [], st = [i0]; vu[i0] = 1; let bord = false;
    while (st.length) {
      const p = st.pop(); poche.push(p);
      const x = p % w, y = (p - x) / w;
      if (x === 0 || y === 0 || x === w - 1 || y === h - 1) bord = true;
      for (const q of [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, y > 0 ? p - w : -1, y < h - 1 ? p + w : -1])
        if (q >= 0 && !vu[q] && ferme[q] <= TH) { vu[q] = 1; st.push(q); }
    }
    // On ne rebouche que les PETITES poches : le triangle entre les brancards du
    // sulky et la croupe est fermé lui aussi, mais le boucher rend un pâté.
    // Seuls les pixels transparents AVANT fermeture sont remplis : ceux que la
    // fermeture a ajoutés resteraient sinon soudés (mêmes pâtés).
    if (bord || poche.length > aire * SEUIL_POCHE) continue;
    for (const p of poche) if (a[p] <= TH) { a[p] = 255; bouches++; }
  }

  // 3. decors isoles (drapeau d'obstacle) : composantes < 8 % de la principale
  const lab = new Int32Array(w * h).fill(-1), comps = [], sc = [];
  for (let i = 0; i < w * h; i++) {
    if (a[i] <= TH || lab[i] !== -1) continue;
    const id = comps.length; let n = 0; sc.push(i); lab[i] = id;
    while (sc.length) { const p = sc.pop(); n++; const x = p % w, y = (p - x) / w;
      for (const q of [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, y > 0 ? p - w : -1, y < h - 1 ? p + w : -1])
        if (q >= 0 && lab[q] === -1 && a[q] > TH) { lab[q] = id; sc.push(q); } }
    comps.push({ id, n });
  }
  const max = comps.reduce((m, x) => Math.max(m, x.n), 0);
  const keep = new Set(comps.filter((x) => x.n >= max * 0.08).map((x) => x.id));
  for (let i = 0; i < w * h; i++) if (lab[i] >= 0 && !keep.has(lab[i])) a[i] = 0;

  // 4. dilatation par DISQUE (un noyau carre aplatirait sabots et naseaux)
  const offs = disk(rf);
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 0;
    for (const [dx, dy] of offs) { const xx = x + dx, yy = y + dy; if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue; const v = a[yy * w + xx]; if (v > m) m = v; }
    out[y * w + x] = m;
  }

  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (out[y * w + x] > TH) {
    if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  // 5. marge transparente : sans elle les sabots touchent le bord de la zone peinte
  const pad = Math.round((maxY - minY + 1) * MARGE);
  const W2 = maxX - minX + 1 + 2 * pad, H2 = maxY - minY + 1 + 2 * pad;
  const rgba = Buffer.alloc(W2 * H2 * 4);
  for (let y = 0; y < H2; y++) for (let x = 0; x < W2; x++) {
    const sx = minX - pad + x, sy = minY - pad + y;
    if (sx < 0 || sy < 0 || sx >= w || sy >= h) continue;
    rgba[(y * W2 + x) * 4 + 3] = out[sy * w + sx];
  }
  const dst = (process.env.OUT || 'public/img/disciplines') + `/${name}-v8.png`;
  let img = sharp(rgba, { raw: { width: W2, height: H2, channels: 4 } });
  if (W2 > LARGEUR_MAX) img = img.resize({ width: LARGEUR_MAX });
  await img.png({ compressionLevel: 9 }).toFile(dst);
  console.log(name, `${w - 2 * EXT}x${h - 2 * EXT} → ${Math.min(W2, LARGEUR_MAX)}px`, `(${bouches} px de liseré rebouchés)`);
}
