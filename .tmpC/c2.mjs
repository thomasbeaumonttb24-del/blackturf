const lum = (h) => { const c = [1,3,5].map(i => parseInt(h.slice(i,i+2),16)/255).map(v => v <= 0.03928 ? v/12.92 : ((v+0.055)/1.055)**2.4); return 0.2126*c[0]+0.7152*c[1]+0.0722*c[2]; };
const r = (a,b) => { const [x,y] = [lum(a),lum(b)].sort((p,q)=>q-p); return ((x+0.05)/(y+0.05)).toFixed(2); };
const prune = '#86198F';
console.log('prune sur fonds de carte : blanc', r(prune,'#FFFFFF'), '| creme', r(prune,'#F5F4EF'), '| direct', r(prune,'#F0FDF8'));
for (const bg of ['#FAF2FC','#F7EBFA','#FDF4FF']) console.log('prune sur pastille', bg, '→', r(prune,bg));
console.log('pastille orange actuelle #FDF1EA →', r(prune,'#FDF1EA'));
