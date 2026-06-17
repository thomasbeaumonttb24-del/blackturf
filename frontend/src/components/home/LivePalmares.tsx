"use client";

import useSWR from "swr";
import { Trophy, Flame, Clock, ShieldCheck } from "lucide-react";
import { statsApi } from "@/lib/api";
import { ScrollReveal } from "@/components/ui/ScrollReveal";

interface Gagnant {
  profil: string;
  code: string | null;
  hippodrome: string | null;
  date: string | null;
  type_pari: string | null;
  chevaux: number[];
  mise: number;
  gain: number;
  benefice: number;
  rapport: number | null;
  regle_le?: string | null;
}
interface PalmaresResp {
  gagnants: Gagnant[];
  top_gains: Gagnant[];
  total_gain?: number;
  updated_at?: string;
}

const PROFIL: Record<string, { label: string; cls: string }> = {
  conservateur: { label: "Prudent", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  equilibre: { label: "Modéré", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
  agressif: { label: "Risqué", cls: "bg-orange-50 text-orange-700 ring-orange-200" },
};

function hippoCourt(s: string | null): string {
  if (!s) return "";
  const t = s.replace(/^HIPPODROME\s+(DE\s+|D'|DU\s+|DES\s+|DE LA\s+)?/i, "");
  return t.charAt(0).toUpperCase() + t.slice(1).toLowerCase();
}
function chevauxStr(arr: number[]): string {
  if (!arr || arr.length === 0) return "";
  return arr.length === 1 ? `N°${arr[0]}` : arr.join(" · ");
}
function quand(iso: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" }).replace(",", " ·");
}

const fetcher = () => statsApi.palmaresGagnants().then((r) => r.data as PalmaresResp);

export function LivePalmares() {
  const { data } = useSWR<PalmaresResp>("palmares-gagnants", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });

  const top = (data?.top_gains ?? []).slice(0, 10);
  const recent = (data?.gagnants ?? []).slice(0, 10);
  const hasData = top.length > 0 || recent.length > 0;

  return (
    <section className="py-24 bg-white">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <ScrollReveal>
          <div className="text-center mb-12">
            <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
              <Trophy className="h-3.5 w-3.5" /> Palmarès en direct
            </span>
            <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
              Les paris gagnants du site,{" "}
              <span className="text-gradient">en temps réel</span>
            </h2>
            <p className="text-gray-500 text-sm mt-3 max-w-2xl mx-auto inline-flex items-center justify-center gap-1.5 flex-wrap">
              <span className="inline-flex items-center gap-1.5">
                <span className="live-dot inline-block w-2 h-2 rounded-full bg-emerald-500" />
                Mis à jour à chaque fin de course
              </span>
              · pronostics figés <strong className="text-gray-700">avant le départ</strong>, réglés aux vrais rapports PMU.
            </p>
          </div>
        </ScrollReveal>

        {!hasData ? (
          <div className="rounded-2xl border border-dashed border-gray-200 bg-brand-warm/40 px-6 py-12 text-center">
            <Clock className="h-8 w-8 mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-semibold text-gray-700">Les premiers paris gagnants s&apos;afficheront ici</p>
            <p className="text-xs text-gray-400 mt-1">Dès la fin des prochaines courses, chaque pari gagné apparaît automatiquement.</p>
          </div>
        ) : (
          <div className="grid lg:grid-cols-2 gap-5">
            {/* ── Top 10 plus gros gains ── */}
            <ScrollReveal>
              <div className="glass-card rounded-2xl p-5 sm:p-6 h-full">
                <div className="flex items-center gap-2 mb-4">
                  <Flame className="h-4 w-4 text-brand-gold-deep" />
                  <h3 className="font-semibold text-gray-900 text-sm">Top 10 des plus gros gains</h3>
                </div>
                <div className="space-y-1.5">
                  {top.map((g, i) => {
                    const pr = PROFIL[g.profil] ?? { label: g.profil, cls: "bg-gray-50 text-gray-600 ring-gray-200" };
                    return (
                      <div key={`${g.code}-${i}`} className="flex items-center gap-3 rounded-xl bg-gray-50/70 px-3 py-2.5">
                        <span className="num-display text-xs font-black w-5 text-center text-brand-gold-deep">{i + 1}</span>
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[13px] font-semibold text-gray-900 truncate">{g.type_pari}</span>
                            <span className="text-[11px] font-mono text-gray-400">{chevauxStr(g.chevaux)}</span>
                          </div>
                          <div className="text-[10px] text-gray-400 truncate">{hippoCourt(g.hippodrome)}{g.code ? ` · ${g.code}` : ""}</div>
                        </div>
                        <span className={`inline-flex justify-center items-center w-[54px] shrink-0 text-[9px] font-bold uppercase tracking-wide rounded-full py-0.5 ring-1 ${pr.cls}`}>{pr.label}</span>
                        <div className="text-right flex-shrink-0">
                          <div className="num-display text-sm font-extrabold text-emerald-600">+{g.gain.toFixed(0)}€</div>
                          <div className="text-[10px] text-gray-400">mise {g.mise.toFixed(0)}€{g.rapport ? ` · ×${g.rapport}` : ""}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </ScrollReveal>

            {/* ── 10 derniers paris gagnés ── */}
            <ScrollReveal delay={80}>
              <div className="glass-card rounded-2xl p-5 sm:p-6 h-full">
                <div className="flex items-center gap-2 mb-4">
                  <span className="live-dot inline-block w-2 h-2 rounded-full bg-emerald-500" />
                  <h3 className="font-semibold text-gray-900 text-sm">10 derniers paris gagnés</h3>
                </div>
                <div className="space-y-1.5">
                  {recent.map((g, i) => {
                    const pr = PROFIL[g.profil] ?? { label: g.profil, cls: "bg-gray-50 text-gray-600 ring-gray-200" };
                    return (
                      <div key={`${g.code}-${g.type_pari}-${i}`} className="flex items-center gap-3 rounded-xl bg-gray-50/70 px-3 py-2.5">
                        <div className="min-w-0 flex-1">
                          <div className="flex items-center gap-1.5">
                            <span className="text-[13px] font-semibold text-gray-900 truncate">{g.type_pari}</span>
                            <span className="text-[11px] font-mono text-gray-400">{chevauxStr(g.chevaux)}</span>
                          </div>
                          <div className="text-[10px] text-gray-400 truncate">{hippoCourt(g.hippodrome)}{g.code ? ` · ${g.code}` : ""} · {quand(g.date)}</div>
                        </div>
                        <span className={`inline-flex justify-center items-center w-[54px] shrink-0 text-[9px] font-bold uppercase tracking-wide rounded-full py-0.5 ring-1 ${pr.cls}`}>{pr.label}</span>
                        <div className="text-right flex-shrink-0">
                          <div className="num-display text-sm font-extrabold text-emerald-600">+{g.gain.toFixed(0)}€</div>
                          <div className="text-[10px] text-gray-400">mise {g.mise.toFixed(0)}€{g.rapport ? ` · ×${g.rapport}` : ""}</div>
                        </div>
                      </div>
                    );
                  })}
                </div>
              </div>
            </ScrollReveal>
          </div>
        )}

        <p className="mt-6 text-center text-[11px] text-gray-400 max-w-2xl mx-auto inline-flex items-center justify-center gap-1.5 w-full">
          <ShieldCheck className="h-3.5 w-3.5 text-gray-400" />
          Paris réellement figés avant le départ puis réglés aux rapports PMU officiels — aucune reconstruction a posteriori. Parier comporte un risque de perte.
        </p>
      </div>
    </section>
  );
}
