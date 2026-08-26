/**
 * Fabrique les masques de discipline utilisés par les icônes (`*-v6.png`).
 *
 * Quatre passes, chacune corrige un défaut constaté à l'écran :
 *   1. roue de sulky reconstituée — l'illustration d'origine coupe le disque à
 *      hauteur d'essieu : à 26 px, ça se lit comme une image rognée ;
 *   2. décors isolés supprimés (drapeau d'obstacle), qui volaient la place au cheval ;
 *   3. dilatation de l'alpha par un noyau EN DISQUE : à 22-30 px, jambes et rênes
 *      tombent sous le pixel et se délavent. Un noyau CARRÉ (essai précédent)
 *      aplatit sabots et naseaux en moignons — le cheval paraît scié ;
 *   4. marge transparente de 7 % : sans elle les sabots touchent le bord de la zone
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

const disk = (r) => {
  const o = [];
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r + 0.25) o.push([dx, dy]);
  return o;
};

for (const name of ['attele', 'plat', 'monte', 'obstacle']) {
  const src = `public/img/disciplines/${name}-v2.png`;
  const meta = await sharp(src).metadata();
  // marge basse pour pouvoir reconstruire une roue tronquee
  const EXT = 60;
  const { data, info } = await sharp(src).ensureAlpha()
    .extend({ bottom: EXT, background: { r: 0, g: 0, b: 0, alpha: 0 } })
    .raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h, channels: c } = info;
  let a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) a[i] = data[i * c + 3];
  const at = (x, y) => a[y * w + x] > TH;

  /* Roue de sulky tronquee : l'illustration d'origine coupe le disque a l'essieu,
     ce qui se lit comme « image rognee » des 26 px. On reflechit la moitie haute
     pour reconstituer le disque. Detection : segment horizontal long (> 25 px) qui
     termine une masse dans la moitie gauche. */
  /* Roue de sulky tronquee : l'illustration d'origine coupe le disque a hauteur
     d'essieu (le bas de la roue n'existe pas). A 26 px ca se lit comme une image
     rognee. Cercle releve sur l'image source, on remplit la moitie manquante. */
  const ROUE = { attele: { cx: 74, cy: 207, r: 39 } }[name];
  if (ROUE) {
    const { cx, cy, r } = ROUE;
    for (let dy = 0; dy <= r; dy++) {
      const dx = Math.floor(Math.sqrt(r * r - dy * dy));
      for (let x = cx - dx; x <= cx + dx; x++) {
        const y = cy + dy;
        if (x < 0 || x >= w || y < 0 || y >= h) continue;
        a[y * w + x] = 255;
      }
    }
    console.log('  ' + name + ': roue completee (centre ' + cx + ',' + cy + ' rayon ' + r + ')');
  }
  // decors isoles (drapeau d'obstacle) : composantes < 8 % de la principale
  const lab = new Int32Array(w * h).fill(-1), comps = [], st = [];
  for (let i = 0; i < w * h; i++) {
    if (a[i] <= TH || lab[i] !== -1) continue;
    const id = comps.length; let n = 0; st.push(i); lab[i] = id;
    while (st.length) { const p = st.pop(); n++; const x = p % w, y = (p - x) / w;
      for (const q of [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, y > 0 ? p - w : -1, y < h - 1 ? p + w : -1])
        if (q >= 0 && lab[q] === -1 && a[q] > TH) { lab[q] = id; st.push(q); } }
    comps.push({ id, n });
  }
  const max = comps.reduce((m, x) => Math.max(m, x.n), 0);
  const keep = new Set(comps.filter((x) => x.n >= max * 0.08).map((x) => x.id));
  for (let i = 0; i < w * h; i++) if (lab[i] >= 0 && !keep.has(lab[i])) a[i] = 0;

  // dilatation par DISQUE (un noyau carre aplatirait sabots et naseaux)
  const offs = disk(Math.max(1, Math.round(w * R_FACTOR)));
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
  // marge transparente : sans elle les sabots touchent le bord de la zone peinte
  const pad = Math.round((maxY - minY + 1) * MARGE);
  const W2 = maxX - minX + 1 + 2 * pad, H2 = maxY - minY + 1 + 2 * pad;
  const rgba = Buffer.alloc(W2 * H2 * 4);
  for (let y = 0; y < H2; y++) for (let x = 0; x < W2; x++) {
    const sx = minX - pad + x, sy = minY - pad + y;
    if (sx < 0 || sy < 0 || sx >= w || sy >= h) continue;
    rgba[(y * W2 + x) * 4 + 3] = out[sy * w + sx];
  }
  const dst = (process.env.OUT || 'public/img/disciplines') + `/${name}-v6.png`;
  await sharp(rgba, { raw: { width: W2, height: H2, channels: 4 } }).png({ compressionLevel: 9 }).toFile(dst);
  console.log(name, `${meta.width}x${meta.height} → ${W2}x${H2}`);
}
