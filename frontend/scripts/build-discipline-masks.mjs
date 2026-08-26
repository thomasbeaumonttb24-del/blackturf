/**
 * Fabrique les masques de discipline utilisés par les icônes (`*-v4.png`).
 *
 * Pourquoi : les originaux `-v2` sont des silhouettes photo-réalistes. Affichées
 * à 22-30 px de haut, les jambes et la tête tombent sous le pixel : le navigateur
 * les rééchantillonne en gris pâle et l'œil lit « cheval rogné ».
 * Trois passes corrigent ça, à la source :
 *   1. décors isolés (drapeau, piquet) supprimés — ils volaient de la place au cheval ;
 *   2. dilatation de l'alpha (~0,5 % de la largeur) : jambes, rênes et brancards
 *      épaissis pour survivre à la réduction ;
 *   3. recadrage au plus juste, pour que `mask-size: contain` remplisse la boîte.
 *
 *   node scripts/build-discipline-masks.mjs
 */
import sharp from 'sharp';

const TH = 8;

async function alphaOf(path) {
  const { data, info } = await sharp(path).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h, channels: c } = info;
  const a = new Uint8Array(w * h);
  for (let i = 0; i < w * h; i++) a[i] = data[i * c + 3];
  return { a, w, h };
}

function bbox(a, w, h) {
  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) if (a[y * w + x] > TH) {
    if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y;
  }
  return { minX, minY, maxX, maxY };
}

/* Composantes connexes (4-voisins) : sert à jeter les décors isolés (drapeau, piquet). */
function components(a, w, h) {
  const lab = new Int32Array(w * h).fill(-1);
  const comps = [];
  const stack = [];
  for (let i = 0; i < w * h; i++) {
    if (a[i] <= TH || lab[i] !== -1) continue;
    const id = comps.length; let n = 0;
    stack.push(i); lab[i] = id;
    while (stack.length) {
      const p = stack.pop(); n++;
      const x = p % w, y = (p - x) / w;
      const nb = [x > 0 ? p - 1 : -1, x < w - 1 ? p + 1 : -1, y > 0 ? p - w : -1, y < h - 1 ? p + w : -1];
      for (const q of nb) if (q >= 0 && lab[q] === -1 && a[q] > TH) { lab[q] = id; stack.push(q); }
    }
    comps.push({ id, n });
  }
  return { lab, comps };
}

/* Dilatation (max-filter séparable) : épaissit jambes, rênes et brancards pour qu'ils
   survivent au rééchantillonnage du navigateur à 20-30 px. */
function dilate(a, w, h, r) {
  if (r <= 0) return a;
  const tmp = new Uint8Array(w * h), out = new Uint8Array(w * h);
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 0;
    for (let d = -r; d <= r; d++) { const xx = x + d; if (xx >= 0 && xx < w) { const v = a[y * w + xx]; if (v > m) m = v; } }
    tmp[y * w + x] = m;
  }
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    let m = 0;
    for (let d = -r; d <= r; d++) { const yy = y + d; if (yy >= 0 && yy < h) { const v = tmp[yy * w + x]; if (v > m) m = v; } }
    out[y * w + x] = m;
  }
  return out;
}

const JOBS = [
  { src: 'attele', dropGround: false },
  { src: 'plat', dropGround: false },
  { src: 'monte', dropGround: false },
  { src: 'obstacle', dropGround: false },
];

for (const job of JOBS) {
  const src = `public/img/disciplines/${job.src}-v2.png`;
  let { a, w, h } = await alphaOf(src);

  if (job.dropGround) {
    // bandes du bas couvrant > 45 % de la largeur = herbe//obstacle au sol → supprimées
    for (let y = h - 1; y > h * 0.5; y--) {
      let n = 0; for (let x = 0; x < w; x++) if (a[y * w + x] > TH) n++;
      if (n > w * 0.45) for (let x = 0; x < w; x++) a[y * w + x] = 0;
    }
  }

  // jette les petits décors détachés (drapeau, piquet) : < 8 % de la plus grosse pièce
  const { lab, comps } = components(a, w, h);
  const max = comps.reduce((m, c) => Math.max(m, c.n), 0);
  const keep = new Set(comps.filter((c) => c.n >= max * 0.08).map((c) => c.id));
  for (let i = 0; i < w * h; i++) if (lab[i] >= 0 && !keep.has(lab[i])) a[i] = 0;

  const r = Math.max(1, Math.round(w * 0.005));
  a = dilate(a, w, h, r);

  const b = bbox(a, w, h);
  const pad = 2;
  const left = Math.max(0, b.minX - pad), top = Math.max(0, b.minY - pad);
  const width = Math.min(w - left, b.maxX - b.minX + 1 + 2 * pad);
  const height = Math.min(h - top, b.maxY - b.minY + 1 + 2 * pad);

  const rgba = Buffer.alloc(w * h * 4);
  for (let i = 0; i < w * h; i++) { rgba[i * 4] = 0; rgba[i * 4 + 1] = 0; rgba[i * 4 + 2] = 0; rgba[i * 4 + 3] = a[i]; }
  await sharp(rgba, { raw: { width: w, height: h, channels: 4 } })
    .extract({ left, top, width, height })
    .png({ compressionLevel: 9 })
    .toFile(`public/img/disciplines/${job.src}-v4.png`);
  console.log(job.src, `dilate=${r}px`, `${width}x${height}`, `aspect=${(width / height).toFixed(2)}`);
}
