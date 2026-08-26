"use client";

import useSWR from "swr";
import Link from "next/link";
import { Trophy, Flame, Clock, ShieldCheck, ArrowRight, Lock } from "lucide-react";
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
  nb_paris_gagnes?: number;
  nb_courses_gagnantes?: number;
  nb_courses_reglees?: number;
  updated_at?: string;
}

const PROFIL: Record<string, { label: string; cls: string }> = {
  conservateur: { label: "Prudent", cls: "bg-emerald-50 text-emerald-700 ring-emerald-200" },
  equilibre: { label: "Modéré", cls: "bg-amber-50 text-amber-700 ring-amber-200" },
  agressif: { label: "Risqué", cls: "bg-orange-50 text-orange-700 ring-orange-200" },
};

// Podium : seuls les 3 premiers sont mis en valeur (or / argent / bronze). Au-delà,
// un simple rang neutre — hiérarchiser les 10 lignes à l'identique n'aide personne.
const PODIUM: Record<number, string> = {
  0: "bg-gradient-to-br from-amber-400 to-amber-600 text-white ring-amber-300",
  1: "bg-gradient-to-br from-slate-300 to-slate-400 text-white ring-slate-200",
  2: "bg-gradient-to-br from-orange-300 to-orange-500 text-white ring-orange-200",
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
  // `timeZone` explicite : sans lui, le rendu serveur prend le fuseau du
  // conteneur (UTC) et affiche une heure de course fausse de deux heures avant
  // que l'hydratation ne la corrige.
  return d.toLocaleString("fr-FR", {
    timeZone: "Europe/Paris",
    day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit",
  }).replace(",", " ·");
}
const fmtInt = (n: number) => n.toLocaleString("fr-FR");
/** Les montants du palmarès sont de l'argent : espace insécable avant l'euro et
 *  séparateur de milliers, comme partout ailleurs sur le site. « +4526€ » se lit
 *  moins vite que « +4 526 € », surtout empilé dix fois. */
const fmtEur = (n: number) =>
  `${n.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} €`;
const fmtRapport = (n: number) =>
  n.toLocaleString("fr-FR", { maximumFractionDigits: 1 });

// Endpoint PUBLIC : `palmaresGagnants` est gardé par require_admin (401 visiteur) —
// cette section, principale preuve sociale du site, n'était visible que par l'admin.
const fetcher = () => statsApi.palmaresPublic().then((r) => r.data as PalmaresResp);

function BadgeProfil({ profil, className = "" }: { profil: string; className?: string }) {
  const pr = PROFIL[profil] ?? { label: profil, cls: "bg-gray-50 text-gray-600 ring-gray-200" };
  return (
    <span className={`inline-flex items-center justify-center rounded-full px-2 py-[3px] text-[9.5px] font-bold uppercase tracking-[0.06em] ring-1 ${pr.cls} ${className}`}>
      {pr.label}
    </span>
  );
}

/** Une ligne de palmarès.
 *
 *  Mise en grille à colonnes FIXES, et non en `flex` : le bloc montant a une
 *  largeur variable (« +4 526 € » contre « +412 € »), si bien que le badge de
 *  profil qui le précédait se décalait d'une ligne à l'autre et la colonne
 *  n'existait plus visuellement. Une grille cale badge et montant sur le même
 *  axe pour les dix lignes. */
function BetRow({ g, rank }: { g: Gagnant; rank?: number }) {
  const podium = rank != null && rank < 3 ? PODIUM[rank] : null;

  return (
    <li
      className={`metric-row grid grid-cols-[1.75rem_minmax(0,1fr)_6.4rem] items-center gap-x-2 rounded-xl border border-transparent px-2 py-3 sm:grid-cols-[1.75rem_minmax(0,1fr)_4.75rem_6.75rem] sm:gap-x-3 sm:px-2.5 ${
        podium ? "bg-amber-50/50" : "hover:bg-gray-50/80"
      }`}
    >
      {rank != null ? (
        <span
          className={`num-display flex h-7 w-7 shrink-0 items-center justify-center rounded-lg text-[11.5px] font-black ring-1 ${
            podium ?? "bg-white text-gray-600 ring-gray-200"
          }`}
        >
          {rank + 1}
        </span>
      ) : (
        // Sans classement, la colonne reste : les deux tableaux se lisent côte à
        // côte, leurs libellés doivent démarrer au même endroit.
        <span className="flex h-7 w-7 items-center justify-center" aria-hidden="true">
          <span className="h-1.5 w-1.5 rounded-full bg-emerald-300" />
        </span>
      )}

      {/* `truncate` sur un conteneur flex ne tronque PAS ses enfants : il faut
          le poser sur le texte lui-même, avec `min-w-0` sur la cellule. Sans
          cela, à 390 px, « Couplé Gagnant » chevauchait ses numéros de chevaux
          et le badge de profil recouvrait le nom de l'hippodrome. */}
      <div className="min-w-0">
        <p className="flex items-baseline gap-1.5">
          <span className="truncate text-[13.5px] font-semibold tracking-tight text-gray-900">{g.type_pari}</span>
          <span className="num-display shrink-0 text-[11.5px] text-gray-500">{chevauxStr(g.chevaux)}</span>
        </p>
        <p className="mt-0.5 flex items-center gap-1.5">
          <span className="min-w-0 flex-1 truncate text-[10.5px] text-gray-500">
            {hippoCourt(g.hippodrome)}
            {g.code ? ` · ${g.code}` : ""}
            {rank == null && g.date ? ` · ${quand(g.date)}` : ""}
          </span>
          {/* En dessous de `sm`, la colonne dédiée réduirait le nom du pari à
              « Co… » : le badge redescend donc sous le libellé, où il reste
              aligné puisque le texte qui le précède est tronqué. */}
          <BadgeProfil profil={g.profil} className="w-[3.9rem] shrink-0 sm:hidden" />
        </p>
      </div>

      <BadgeProfil profil={g.profil} className="hidden w-full sm:inline-flex" />

      <div className="text-right">
        <div className="num-display text-[15px] font-extrabold tabular-nums text-emerald-700">
          +{fmtEur(g.gain)}
        </div>
        <div className="mt-0.5 text-[10.5px] tabular-nums text-gray-500">
          mise {fmtEur(g.mise)}
          {g.rapport ? ` · ×${fmtRapport(g.rapport)}` : ""}
        </div>
      </div>
    </li>
  );
}

/** Carte d'un tableau (top gains / derniers gagnés). Extraite pour que les deux
 *  colonnes partagent exactement la même mise en page — c'est ce qui les rend
 *  comparables d'un coup d'œil. */
export function PalmaresCarte({
  titre, aside, puce, lignes, avecRang,
}: {
  titre: string;
  aside: string;
  puce: React.ReactNode;
  lignes: Gagnant[];
  avecRang?: boolean;
}) {
  return (
    <div className="glass-card flex h-full flex-col rounded-2xl p-5 sm:p-6">
      <div className="mb-2 flex flex-col items-start gap-1 border-b border-gray-100 pb-4 sm:flex-row sm:items-center sm:justify-between sm:gap-2">
        <div className="flex items-center gap-2">
          {puce}
          <h3 className="font-display text-[15px] font-bold text-gray-900">{titre}</h3>
        </div>
        <span className="text-[10.5px] text-gray-500">{aside}</span>
      </div>
      <ul className="divide-y divide-gray-100/90">
        {lignes.map((g, i) => (
          <BetRow
            key={`${g.code}-${g.type_pari}-${i}`}
            g={g}
            rank={avecRang ? i : undefined}
          />
        ))}
      </ul>
    </div>
  );
}

export function LivePalmares() {
  const { data } = useSWR<PalmaresResp>("palmares-public", fetcher, {
    refreshInterval: 60_000,
    revalidateOnFocus: true,
  });

  const top = (data?.top_gains ?? []).slice(0, 10);
  const recent = (data?.gagnants ?? []).slice(0, 10);
  const hasData = top.length > 0 || recent.length > 0;

  const nbGagnes = data?.nb_paris_gagnes ?? null;
  const nbCourses = data?.nb_courses_reglees ?? null;
  const meilleurGain = top.length > 0 ? top[0].gain : null;

  return (
    <section className="py-24 bg-white">
      <div className="mx-auto max-w-6xl px-4 sm:px-6 lg:px-8">
        <ScrollReveal>
          <div className="text-center mb-10">
            <span className="eyebrow text-amber-700 text-[11px] font-semibold mb-3">
              <Trophy className="h-3.5 w-3.5" /> Palmarès en direct
            </span>
            <h2 className="font-display text-3xl sm:text-4xl font-bold text-gray-900">
              Les paris gagnants du site,{" "}
              <span className="text-gradient">en temps réel</span>
            </h2>
            <p className="text-gray-600 text-sm mt-3 max-w-2xl mx-auto inline-flex items-center justify-center gap-1.5 flex-wrap">
              <span className="inline-flex items-center gap-1.5">
                <span className="live-dot inline-block w-2 h-2 rounded-full bg-emerald-500" />
                Mis à jour à chaque fin de course
              </span>
              · pronostics figés <strong className="text-gray-700">avant le départ</strong>, réglés aux vrais rapports PMU.
            </p>
          </div>
        </ScrollReveal>

        {/* ── Bandeau chiffres : les gagnants AVEC leur dénominateur ──
            Afficher les paris gagnants sans dire sur combien de courses ils ont été
            joués serait un biais du survivant. Les deux nombres vont ensemble. */}
        {hasData && nbGagnes != null && nbCourses != null && (
          <ScrollReveal>
            <div className="mb-8 grid grid-cols-1 sm:grid-cols-3 gap-3">
              <div className="glass-card rounded-2xl px-5 py-4 text-center">
                <div className="num-display text-2xl font-extrabold text-gray-900">{fmtInt(nbGagnes)}</div>
                <div className="text-[11px] text-gray-600 mt-1">paris gagnants enregistrés</div>
              </div>
              <div className="glass-card rounded-2xl px-5 py-4 text-center">
                <div className="num-display text-2xl font-extrabold text-gray-900">{fmtInt(nbCourses)}</div>
                <div className="text-[11px] text-gray-600 mt-1">courses réglées, gagnées <span className="text-gray-600">et perdues</span></div>
              </div>
              <div className="glass-card rounded-2xl px-5 py-4 text-center">
                <div className="num-display text-2xl font-extrabold text-emerald-700">
                  {meilleurGain != null ? `+${fmtEur(meilleurGain)}` : "—"}
                </div>
                <div className="text-[11px] text-gray-600 mt-1">meilleur gain sur un pari</div>
              </div>
            </div>
          </ScrollReveal>
        )}

        {!hasData ? (
          <div className="rounded-2xl border border-dashed border-gray-200 bg-brand-warm/40 px-6 py-12 text-center">
            <Clock className="h-8 w-8 mx-auto mb-3 text-gray-300" />
            <p className="text-sm font-semibold text-gray-700">Les premiers paris gagnants s&apos;afficheront ici</p>
            <p className="text-xs text-gray-600 mt-1">Dès la fin des prochaines courses, chaque pari gagné apparaît automatiquement.</p>
          </div>
        ) : (
          <div className="grid gap-5 lg:grid-cols-2">
            <ScrollReveal>
              <PalmaresCarte
                titre="Top 10 des plus gros gains"
                aside="depuis le lancement"
                puce={<Flame className="h-4 w-4 text-brand-gold-dark" />}
                lignes={top}
                avecRang
              />
            </ScrollReveal>

            <ScrollReveal delay={80}>
              <PalmaresCarte
                titre="10 derniers paris gagnés"
                aside="les plus récents"
                puce={<span className="live-dot inline-block h-2 w-2 rounded-full bg-emerald-500" />}
                lignes={recent}
              />
            </ScrollReveal>
          </div>
        )}

        {/* ── CTA abonnement — sans promesse de gain (contrainte ANJ) ── */}
        {hasData && (
          <ScrollReveal delay={120}>
            <div className="mt-8 rounded-2xl border border-brand-gold/20 bg-gradient-to-r from-amber-50/60 to-white px-5 py-5 sm:px-7 sm:py-6 flex flex-col sm:flex-row items-center justify-between gap-4">
              <div className="text-center sm:text-left">
                <p className="text-sm font-semibold text-gray-900">
                  Ces paris sont publiés <span className="text-brand-gold-dark">après</span> l&apos;arrivée. Les abonnés les reçoivent <span className="text-brand-gold-dark">avant le départ</span>.
                </p>
                <p className="text-xs text-gray-600 mt-1">
                  Paris de valeur, plan de mise et alertes en temps réel — dès 12€/mois, 7 jours d&apos;essai sans prélèvement.
                </p>
              </div>
              <div className="flex items-center gap-3 shrink-0">
                <Link href="/track-record" className="text-xs font-semibold text-gray-600 hover:text-gray-900 underline underline-offset-2">
                  Palmarès complet
                </Link>
                <Link
                  href="/inscription"
                  className="press btn-shimmer inline-flex items-center gap-1.5 rounded-xl bg-brand-gold px-4 py-2.5 text-sm font-bold text-brand-dark shadow-lg shadow-amber-500/25 hover:bg-brand-gold-deep transition-colors"
                >
                  <Lock className="h-3.5 w-3.5" /> Recevoir les paris en direct <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            </div>
          </ScrollReveal>
        )}

        <p className="mt-6 text-center text-[11px] text-gray-600 max-w-2xl mx-auto inline-flex items-center justify-center gap-1.5 w-full">
          <ShieldCheck className="h-3.5 w-3.5 text-gray-600 shrink-0" />
          Paris réellement figés avant le départ puis réglés aux rapports PMU officiels — aucune reconstruction a posteriori. Parier comporte un risque de perte.
        </p>
      </div>
    </section>
  );
}
