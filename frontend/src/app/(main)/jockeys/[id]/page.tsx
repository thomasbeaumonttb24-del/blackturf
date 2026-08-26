"use client";

import { useParams } from "next/navigation";
import useSWR from "swr";
import Link from "next/link";
import { ArrowLeft, Activity, Trophy, Users } from "lucide-react";
import { coursesApi } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

// ─── Types ────────────────────────────────────────────────────────────────────
interface StatsSaison {
  victoires: number;
  places: number;
  courses: number;
  taux_victoire: number;
  taux_place: number;
  roi: number;
  montes_30j?: number;
}

interface TopHippo {
  hippodrome: string;
  nb_courses?: number;
  taux_victoire?: number;
  [key: string]: unknown;
}

interface TopDist {
  distance: string;
  nb_courses?: number;
  taux_victoire?: number;
  [key: string]: unknown;
}

interface TerrainStat {
  nb: number;
  taux_victoire: number;
}

interface AssociationEntraineur {
  entraineur_id: string;
  entraineur: string;
  nb_courses: number;
  nb_victoires: number;
  taux_victoire: number;
}

interface Participation {
  date: string;
  nom_cheval: string;
  cheval_id: string;
  hippodrome: string;
  discipline: string;
  numero: number;
  cote: number | null;
  position: number | null;
}

interface JockeyData {
  jockey_id: string;
  nom: string;
  nationalite: string | null;
  saison: number;
  stats_saison: StatsSaison;
  top_hippodromes: TopHippo[];
  top_distances: TopDist[];
  taux_par_terrain: Record<string, TerrainStat>;
  associations_entraineurs: AssociationEntraineur[];
  derniere_participations: Participation[];
}

// ─── Helpers ──────────────────────────────────────────────────────────────────
function pct(v: number) {
  return `${Math.round(v * 100)}%`;
}

function roiColor(roi: number) {
  if (roi > 0.05) return "text-emerald-700";
  if (roi < -0.05) return "text-red-700";
  return "text-muted-foreground";
}

function StatBox({
  label,
  value,
  sub,
  color,
}: {
  label: string;
  value: string | number;
  sub?: string;
  color?: string;
}) {
  return (
    <div className="rounded-xl border border-border/40 bg-muted/20 p-3 space-y-0.5">
      <p className="text-[11px] text-muted-foreground uppercase tracking-wider">{label}</p>
      <p className="text-xl font-extrabold font-mono tabular-nums" style={color ? { color } : {}}>
        {value}
      </p>
      {sub && <p className="text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}

function WinBar({ taux, nb }: { taux: number | undefined; nb: number | undefined }) {
  const t = taux ?? 0;
  const p = Math.round(t * 100);
  const barColor = p >= 25 ? "#F59E0B" : p >= 12 ? "#3B82F6" : "#6B7280";
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs">
        <span className="font-bold font-mono" style={{ color: barColor }}>{p}%</span>
        <span className="text-muted-foreground">{nb ?? 0} courses</span>
      </div>
      <div className="h-1.5 rounded-full bg-muted/50 overflow-hidden">
        <div
          className="h-full rounded-full"
          style={{ width: `${Math.min(p * 2.5, 100)}%`, background: barColor }}
        />
      </div>
    </div>
  );
}

function positionBadge(pos: number | null) {
  if (!pos) return <span className="text-muted-foreground text-xs">—</span>;
  if (pos === 1)
    return (
      <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-amber-50 text-amber-700 text-xs font-bold border border-amber-500/30">
        1
      </span>
    );
  if (pos <= 3)
    return (
      <span className="inline-flex items-center justify-center w-6 h-6 rounded-full bg-emerald-50 text-emerald-700 text-xs font-bold border border-emerald-500/30">
        {pos}
      </span>
    );
  return <span className="text-muted-foreground text-xs font-mono">{pos}</span>;
}

// ─── Page ─────────────────────────────────────────────────────────────────────
export default function JockeyPage() {
  const { id } = useParams<{ id: string }>();

  const { data, error, isLoading } = useSWR(
    id ? `jockey-${id}` : null,
    () => coursesApi.jockey(id!).then((r) => r.data as JockeyData),
    { refreshInterval: 0 }
  );

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <Activity className="h-8 w-8 animate-spin text-brand-gold-dark" />
      </div>
    );
  }

  if (error || !data) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] gap-4">
        <p className="text-muted-foreground">Jockey introuvable.</p>
        <Link href="/programme">
          <Button variant="outline" size="sm">
            <ArrowLeft className="h-4 w-4 mr-2" />
            Retour
          </Button>
        </Link>
      </div>
    );
  }

  const s = data.stats_saison;

  return (
    <div className="max-w-4xl mx-auto px-3 sm:px-4 py-4 sm:py-6 space-y-4 sm:space-y-6">
      {/* Back */}
      <Link
        href="/programme"
        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
      >
        <ArrowLeft className="h-4 w-4" />
        Programme
      </Link>

      {/* ── Header ────────────────────────────────────────────────────── */}
      <Card className="bg-card/80 border-border/50">
        <CardHeader className="pb-4">
          <div className="flex items-start justify-between flex-wrap gap-4">
            <div className="space-y-1">
              <div className="flex items-center gap-2">
                <h1 className="text-xl sm:text-2xl font-extrabold tracking-tight">{data.nom}</h1>
                {data.nationalite && (
                  <Badge variant="outline" className="text-xs font-semibold">
                    {data.nationalite}
                  </Badge>
                )}
              </div>
              <p className="text-sm text-muted-foreground">Jockey — Saison {data.saison}</p>
            </div>
            {s.montes_30j !== undefined && (
              <div className="flex flex-col items-center rounded-xl border border-border/40 bg-muted/20 px-4 py-2">
                <span className="text-[10px] text-muted-foreground">30 derniers jours</span>
                <span className="text-2xl font-extrabold font-mono text-brand-gold-dark">
                  {s.montes_30j}
                </span>
                <span className="text-[10px] text-muted-foreground">montées</span>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            <StatBox
              label="Victoires"
              value={s.victoires}
              sub={`sur ${s.courses} courses`}
              color="#F59E0B"
            />
            <StatBox
              label="Taux victoire"
              value={pct(s.taux_victoire)}
              sub={`Place: ${pct(s.taux_place)}`}
              color={s.taux_victoire >= 0.2 ? "#10B981" : undefined}
            />
            <StatBox
              label="Rendement"
              value={`${s.roi > 0 ? "+" : ""}${(s.roi * 100).toFixed(1)}%`}
              color={s.roi > 0 ? "#10B981" : s.roi < -0.1 ? "#EF4444" : undefined}
            />
            <StatBox label="Places (top 3)" value={s.places} />
          </div>
        </CardContent>
      </Card>

      {/* ── Stats par terrain ─────────────────────────────────────────── */}
      {Object.keys(data.taux_par_terrain).length > 0 && (
        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
              Stats par terrain
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-3 gap-4">
              {["bon", "souple", "lourd"].map((t) => {
                const ts = data.taux_par_terrain[t];
                return (
                  <div key={t} className="rounded-lg border border-border/30 bg-muted/20 p-3 space-y-2">
                    <p className="text-xs font-semibold capitalize text-muted-foreground text-center">{t}</p>
                    {ts ? (
                      <WinBar taux={ts.taux_victoire} nb={ts.nb} />
                    ) : (
                      <p className="text-center text-xs text-muted-foreground">—</p>
                    )}
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Top hippodromes ───────────────────────────────────────────── */}
      {data.top_hippodromes.length > 0 && (
        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Trophy className="h-4 w-4 text-brand-gold-dark" />
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Top hippodromes (saison)
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {data.top_hippodromes.map((h, i) => {
                const nb = (h.nb_courses as number | undefined) ?? 0;
                const taux = (h.taux_victoire as number | undefined) ?? 0;
                const p = Math.round(taux * 100);
                const barColor = p >= 25 ? "#F59E0B" : p >= 12 ? "#3B82F6" : "#6B7280";
                return (
                  <div key={h.hippodrome} className="flex items-center gap-3">
                    <span className="w-5 text-center text-xs font-bold text-muted-foreground">
                      {i + 1}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-sm font-semibold truncate">{h.hippodrome}</span>
                        <div className="flex items-center gap-3 text-xs shrink-0">
                          <span className="text-muted-foreground">{nb} courses</span>
                          <span className="font-bold font-mono" style={{ color: barColor }}>
                            {p}%
                          </span>
                        </div>
                      </div>
                      <div className="h-1.5 rounded-full bg-muted/50 overflow-hidden">
                        <div
                          className="h-full rounded-full"
                          style={{ width: `${Math.min(p * 2.5, 100)}%`, background: barColor }}
                        />
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Associations entraîneurs ──────────────────────────────────── */}
      {data.associations_entraineurs.length > 0 && (
        <Card className="bg-card/60 border-border/40">
          <CardHeader className="pb-2">
            <div className="flex items-center gap-2">
              <Users className="h-4 w-4 text-blue-700" />
              <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                Top associations entraîneurs
              </CardTitle>
            </div>
          </CardHeader>
          <CardContent className="p-0">
            {/* Mobile: liste de cartes compactes */}
            <div className="sm:hidden space-y-2 p-3">
              {data.associations_entraineurs.map((a) => {
                const p = Math.round(a.taux_victoire * 100);
                return (
                  <div
                    key={a.entraineur_id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-border/30 bg-muted/20 p-2.5"
                  >
                    <p className="text-sm font-semibold truncate">{a.entraineur}</p>
                    <div className="flex items-center gap-3 text-xs shrink-0">
                      <span className="text-muted-foreground font-mono">{a.nb_courses}c</span>
                      <span className="font-mono text-amber-700">{a.nb_victoires}v</span>
                      <span
                        className="font-bold font-mono"
                        style={{ color: p >= 25 ? "#F59E0B" : p >= 15 ? "#3B82F6" : "#6B7280" }}
                      >
                        {p}%
                      </span>
                    </div>
                  </div>
                );
              })}
            </div>

            {/* Desktop: tableau complet */}
            <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-sm min-w-[420px]">
              <thead>
                <tr className="border-b border-border/30">
                  <th className="px-4 py-2 text-left text-xs text-muted-foreground font-medium">Entraîneur</th>
                  <th className="px-4 py-2 text-right text-xs text-muted-foreground font-medium">Courses</th>
                  <th className="px-4 py-2 text-right text-xs text-muted-foreground font-medium">Victoires</th>
                  <th className="px-4 py-2 text-right text-xs text-muted-foreground font-medium">Taux</th>
                </tr>
              </thead>
              <tbody>
                {data.associations_entraineurs.map((a) => {
                  const p = Math.round(a.taux_victoire * 100);
                  return (
                    <tr
                      key={a.entraineur_id}
                      className="border-b border-border/20 hover:bg-muted/20 transition-colors"
                    >
                      <td className="px-4 py-2 font-semibold">
                        {/* Pas de page /entraineurs/[id] → texte simple (évite un lien 404). */}
                        {a.entraineur}
                      </td>
                      <td className="px-4 py-2 text-right font-mono tabular-nums">{a.nb_courses}</td>
                      <td className="px-4 py-2 text-right font-mono tabular-nums text-amber-700">
                        {a.nb_victoires}
                      </td>
                      <td className="px-4 py-2 text-right">
                        <span
                          className="font-bold font-mono"
                          style={{
                            color: p >= 25 ? "#F59E0B" : p >= 15 ? "#3B82F6" : "#6B7280",
                          }}
                        >
                          {p}%
                        </span>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* ── Dernières 20 participations ───────────────────────────────── */}
      <Card className="bg-card/60 border-border/40">
        <CardHeader className="pb-2">
          <CardTitle className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
            Dernières 20 participations
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {/* Mobile: liste de cartes compactes */}
          <div className="sm:hidden space-y-2 p-3">
            {data.derniere_participations.map((p, i) => (
              <div
                key={i}
                className={cn(
                  "flex items-center justify-between gap-2 rounded-lg border border-border/30 bg-muted/20 p-2.5",
                  p.position === 1 && "border-amber-500/40 bg-amber-500/5"
                )}
              >
                <div className="min-w-0">
                  <Link
                    href={`/chevaux/${p.cheval_id}`}
                    className="text-sm font-semibold truncate block hover:text-brand-gold-dark transition-colors"
                  >
                    {p.nom_cheval}
                  </Link>
                  <p className="text-[11px] text-muted-foreground font-mono">
                    {p.date ? String(p.date).slice(0, 10) : "—"}
                    {p.hippodrome ? ` · ${p.hippodrome}` : ""}
                  </p>
                </div>
                <div className="flex items-center gap-3 shrink-0">
                  <span className="text-[11px] text-muted-foreground font-mono">
                    {p.cote ? p.cote.toFixed(1) : "—"}
                  </span>
                  {positionBadge(p.position)}
                </div>
              </div>
            ))}
            {data.derniere_participations.length === 0 && (
              <p className="py-8 text-center text-muted-foreground text-sm">
                Aucune participation disponible.
              </p>
            )}
          </div>

          {/* Desktop: tableau complet */}
          <div className="hidden sm:block overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="border-b border-border/30">
                  {([["Date", ""], ["Cheval", ""], ["Hippodrome", "hidden sm:table-cell"],
                     ["Disc.", "hidden sm:table-cell"], ["Pos.", ""], ["Cote", ""]] as const).map(([h, cls]) => (
                    <th
                      key={h}
                      className={cn("px-3 py-2 text-left text-muted-foreground font-medium whitespace-nowrap", cls)}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.derniere_participations.map((p, i) => (
                  <tr
                    key={i}
                    className={cn(
                      "border-b border-border/20 transition-colors hover:bg-muted/20",
                      p.position === 1 && "bg-amber-500/5"
                    )}
                  >
                    <td className="px-3 py-2 font-mono whitespace-nowrap">
                      {p.date ? String(p.date).slice(0, 10) : "—"}
                    </td>
                    <td className="px-3 py-2 font-semibold max-w-[120px] truncate">
                      <Link
                        href={`/chevaux/${p.cheval_id}`}
                        className="hover:text-brand-gold-dark transition-colors"
                      >
                        {p.nom_cheval}
                      </Link>
                    </td>
                    <td className="px-3 py-2 max-w-[110px] truncate hidden sm:table-cell">{p.hippodrome || "—"}</td>
                    <td className="px-3 py-2 whitespace-nowrap hidden sm:table-cell">{p.discipline || "—"}</td>
                    <td className="px-3 py-2 text-center">{positionBadge(p.position)}</td>
                    <td className="px-3 py-2 font-mono">
                      {p.cote ? p.cote.toFixed(1) : "—"}
                    </td>
                  </tr>
                ))}
                {data.derniere_participations.length === 0 && (
                  <tr>
                    <td colSpan={6} className="px-3 py-8 text-center text-muted-foreground">
                      Aucune participation disponible.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
