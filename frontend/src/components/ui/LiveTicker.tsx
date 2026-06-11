"use client";

// Aperçu ILLUSTRATIF de l'interface (pas des pronostics en direct — ceux-ci sont
// réservés aux abonnés). Marqué "Exemple" pour ne tromper personne (intégrité).
const TICKER_ITEMS = [
  { hippodrome: "DEAUVILLE",  course: "R4-C5", cheval: "PALADIN NOIR",   top3: 78, niveau: "★★★★", ev: "+14.2%" },
  { hippodrome: "LONGCHAMP",  course: "R2-C3", cheval: "BELLA VISTA",    top3: 65, niveau: "★★★",  ev: "+9.1%"  },
  { hippodrome: "VINCENNES",  course: "R1-C2", cheval: "TROT LEADER",    top3: 71, niveau: "★★★",  ev: "+11.8%", spi: true },
  { hippodrome: "CHANTILLY",  course: "R3-C1", cheval: "ÉCLAIR DU SOIR", top3: 82, niveau: "★★★★", ev: "+18.3%" },
  { hippodrome: "ENGHIEN",    course: "R1-C6", cheval: "STARLIGHT",      top3: 61, niveau: "★★",   ev: "+6.4%"  },
  { hippodrome: "PARIS-TURF", course: "R5-C4", cheval: "BOLD FIGHTER",   top3: 74, niveau: "★★★",  ev: "+12.7%", spi: true },
];

export function LiveTicker() {
  const items = [...TICKER_ITEMS, ...TICKER_ITEMS];
  return (
    <div className="relative border-y border-gray-200 bg-amber-50/60 py-2.5 overflow-hidden select-none">
      <span className="absolute left-0 top-0 bottom-0 z-10 flex items-center px-3 bg-gray-900 text-white text-[9px] font-bold uppercase tracking-wider">
        Exemple
      </span>
      <div className="flex items-center gap-0 ticker-track pl-20">
        {items.map((item, i) => (
          <span key={i} className="flex items-center gap-3 px-6 shrink-0">
            <span className="text-amber-700 font-bold text-[10px] tracking-wider font-mono">{item.hippodrome}</span>
            <span className="text-gray-400 text-[10px] font-mono">{item.course}</span>
            <span className="text-gray-800 text-xs font-semibold">{item.cheval}</span>
            <span className="text-xs text-gray-500">
              Top-3 : <span className="text-emerald-600 font-bold">{item.top3}%</span>
            </span>
            <span className="text-xs text-amber-600 font-mono font-medium">{item.niveau}</span>
            <span className="text-xs font-bold text-emerald-600 font-mono">{item.ev}</span>
            {item.spi && (
              <span className="text-[9px] px-1.5 py-0.5 rounded-full bg-amber-100 text-amber-700 border border-amber-200 font-bold">
                SPI
              </span>
            )}
            <span className="text-gray-300 text-lg mx-2">|</span>
          </span>
        ))}
      </div>
    </div>
  );
}
