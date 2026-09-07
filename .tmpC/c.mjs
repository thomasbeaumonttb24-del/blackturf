const lum = (h) => { const c = [1,3,5].map(i => parseInt(h.slice(i,i+2),16)/255).map(v => v <= 0.03928 ? v/12.92 : ((v+0.055)/1.055)**2.4); return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2]; };
const ratio = (a,b) => { const [x,y] = [lum(a),lum(b)].sort((p,q)=>q-p); return (x+0.05)/(y+0.05); };
const hue = (h) => { const [r,g,b] = [1,3,5].map(i => parseInt(h.slice(i,i+2),16)/255); const mx = Math.max(r,g,b), mn = Math.min(r,g,b), d = mx-mn; if (!d) return 0;
  let t = mx === r ? ((g-b)/d)%6 : mx === g ? (b-r)/d+2 : (r-g)/d+4; return Math.round(((t*60)+360)%360); };
const fonds = { blanc: '#FFFFFF', creme: '#F5F4EF', direct: '#F0FDF8' };
const existants = { attele: '#0E7C66', plat: '#B45309', monte: '#2A5BD7', steeple: '#A32C3E' };
const candidats = { 'actuel obstacle': '#A8441F', 'violet': '#6D28D9', 'prune': '#86198F', 'indigo fonce': '#4338CA', 'teal fonce': '#0F766E', 'brun sombre': '#78350F', 'rose fonce': '#9D174D' };
console.log('teinte'.padEnd(18), 'H°'.padEnd(5), 'blanc creme direct'.padEnd(20), 'ecart de teinte vs plat/monte/steeple');
for (const [n, c] of Object.entries(candidats)) {
  const dh = (a, b) => { const x = Math.abs(hue(a)-hue(b)); return Math.min(x, 360-x); };
  console.log(n.padEnd(18), String(hue(c)).padEnd(5),
    Object.values(fonds).map(f => ratio(c,f).toFixed(2)).join('  ').padEnd(20),
    Object.entries(existants).map(([k,v]) => `${k} ${dh(c,v)}°`).join('  '));
}
