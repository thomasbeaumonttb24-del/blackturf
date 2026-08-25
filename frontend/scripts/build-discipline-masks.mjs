/**
 * Recadre les silhouettes de discipline sur leur contenu réel (bbox alpha).
 * Les masques -v2 gardaient ~12 % de vide autour du cheval : à 30 px de large
 * le cheval tombait à ~14 px de haut et paraissait rogné. Les -v3 sont détourés
 * au plus juste, donc `mask-size: contain` les rend au maximum de la boîte.
 *   node scripts/build-discipline-masks.mjs
 */
import sharp from 'sharp';
const files = ['plat', 'attele', 'monte', 'obstacle'];
for (const f of files) {
  const src = `public/img/disciplines/${f}-v2.png`;
  const dst = `public/img/disciplines/${f}-v3.png`;
  const { data, info } = await sharp(src).ensureAlpha().raw().toBuffer({ resolveWithObject: true });
  const { width: w, height: h, channels: c } = info;
  let minX = w, minY = h, maxX = -1, maxY = -1;
  for (let y = 0; y < h; y++) for (let x = 0; x < w; x++) {
    if (data[(y * w + x) * c + 3] > 8) { if (x < minX) minX = x; if (x > maxX) maxX = x; if (y < minY) minY = y; if (y > maxY) maxY = y; }
  }
  const bw = maxX - minX + 1, bh = maxY - minY + 1;
  // marge de 2 % pour ne pas raboter l'antialiasing des extrémités (sabots, fouet)
  const pad = Math.round(Math.max(bw, bh) * 0.02);
  const left = Math.max(0, minX - pad), top = Math.max(0, minY - pad);
  const width = Math.min(w - left, bw + 2 * pad), height = Math.min(h - top, bh + 2 * pad);
  await sharp(src).extract({ left, top, width, height }).png({ compressionLevel: 9 }).toFile(dst);
  console.log(f, `v2=${w}x${h}`, `v3=${width}x${height}`, `aspect=${(width / height).toFixed(2)}`);
}
