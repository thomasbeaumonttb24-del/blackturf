"use client";

/** Contrôle visuel temporaire des pictogrammes de discipline (glyphes SVG vs masques PNG). */

import { DisciplineGlyph, DisciplineImg } from "@/components/ui/DisciplineIcon";

const DISC = ["Attelé", "Monté", "Plat", "Obstacle"];

export default function ApercuIcones() {
  return (
    <div className="min-h-screen bg-[#FFFDF6] p-8">
      <div className="mx-auto max-w-4xl space-y-10">
        <section>
          <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-amber-800">Glyphes SVG (vectoriels, jamais rognés)</h2>
          <div className="flex flex-wrap gap-8">
            {DISC.map((d) => (
              <div key={d} className="flex flex-col items-center gap-2 rounded-2xl border border-stone-200 bg-white p-5">
                <span className="text-slate-800" style={{ display: "inline-block", width: 96, height: 72 }}>
                  <DisciplineGlyph discipline={d} className="h-full w-full" />
                </span>
                <span className="text-xs text-slate-600">{d}</span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-amber-800">Masques PNG actuels</h2>
          <div className="flex flex-wrap gap-8">
            {DISC.map((d) => (
              <div key={d} className="flex flex-col items-center gap-2 rounded-2xl border border-stone-200 bg-white p-5">
                <DisciplineImg discipline={d} className="h-[72px] w-[96px]" />
                <span className="text-xs text-slate-600">{d}</span>
              </div>
            ))}
          </div>
        </section>

        <section>
          <h2 className="mb-4 text-sm font-bold uppercase tracking-wider text-amber-800">Petites tailles (chips)</h2>
          <div className="flex flex-wrap gap-3">
            {DISC.map((d) => (
              <span key={d} className="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white px-3 py-1.5 text-sm">
                <span className="text-slate-700" style={{ display: "inline-block", width: 26, height: 20 }}>
                  <DisciplineGlyph discipline={d} className="h-full w-full" />
                </span>
                {d}
              </span>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
