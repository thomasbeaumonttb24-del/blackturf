/**
 * Fabrique les masques de discipline utilisés par les icônes (`*-v5.png`).
 *
 * Trois passes, toutes motivées par un défaut vu à l'écran :
 *   1. décors isolés supprimés (drapeau d'obstacle) — ils volaient la place au cheval ;
 *   2. dilatation de l'alpha par un noyau EN DISQUE : à 22-30 px de haut, jambes et
 *      rênes tombent sous le pixel et se délavent. Un noyau carré (essai precedent)
 *      aplatit sabots et naseaux en moignons : le cheval parait scie. Le disque
 *      epaissit sans casser les arrondis ;
 *   3. marge transparente de 7 % conservee autour du sujet : sans elle, les sabots
 *      touchent le bord de la zone peinte par `mask-size: contain` et l'oeil lit
 *      « cheval coupe », meme quand l'image est entiere.
 *
 *   node scripts/build-discipline-masks.mjs
 */
import sharp from 'sharp';
const TH = 8;
const R = Number(process.env.R || 2);

function disk(r) {
  const offs = [];
  for (let dy = -r; dy <= r; dy++) for (let dx = -r; dx <= r; dx++) if (dx * dx + dy * dy <= r * r + 0.25) offs.push([dx, dy]);
  return offs;
}

for (const name of ['attele', 'plat', 'monte', 'obstacle']) {
  const { data, info } = await sharp(`public/img/disciplines/${name}-v2.png`).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h, channels: c } = info;
  const a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) a[i] = data[i * c + 3];

  // décors isolés (drapeau d'obstacle, piquet) : composantes < 8 % de la principale
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

  // dilatation DISQUE : un noyau carré aplatirait sabots, naseaux et roue en moignons
  const offs = disk(R);
  const out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 0;
    for (const [dx, dy] of offs) {
      const xx = x + dx, yy = y + dy;
      if (xx < 0 || yy < 0 || xx >= w || yy >= h) continue;
      const v = a[yy * w + xx]; if (v > m) m = v;
    }
    out[y * w + x] = m;
  }

  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (out[y * w + x] > TH) {
    if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  const pad = Math.round((maxY - minY + 1) * (Number(process.env.MARGE)||0.07));
  const left = Math.max(0, minX - pad), top = Math.max(0, minY - pad);
  const width = Math.min(w - left, maxX - minX + 1 + 2 * pad), height = Math.min(h - top, maxY - minY + 1 + 2 * pad);

  const rgba = Buffer.alloc(w * h * 4);
  for (let i = 0; i < w * h; i++) rgba[i * 4 + 3] = out[i];
  const dst = process.env.OUT ? `${process.env.OUT}/${name}-v5.png` : `public/img/disciplines/${name}-v5.png`;
  await sharp(rgba, { raw: { width: w, height: h, channels: 4 } }).extract({ left, top, width, height }).png({ compressionLevel: 9 }).toFile(dst);
  console.log(name, `disque r=${R}`, `${width}x${height}`);
}
