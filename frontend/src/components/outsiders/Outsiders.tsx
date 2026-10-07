"use client";

/**
 * Outsiders du jour — les grosses cotes (≥ 15) que le cerveau des outsiders
 * (backend `ml/outsider_brain.py`) juge capables de se placer.
 *
 * Honnêteté : on affiche une CHANCE DE PLACE estimée et le bilan réel des
 * outsiders affichés (figés à T-10). Jamais de promesse de gain : mesuré, ces
 * outsiders se placent 2 à 3 fois plus souvent que les autres, sans rendement
 * positif prouvé.
 *
 * Rendu : cartes en relief sur scène sombre (même langage que le podium du
 * palmarès), animation volontairement sobre — une légère inclinaison au survol
 * de la souris et la jauge qui se remplit une fois. Rien qui tourne en boucle.
 */

import { useId, useState, type ReactNode } from "react";
import useSWR from "swr";
import Link from "next/link";
import { ArrowRight, ArrowUpRight, Check, Flame, Lock, Rocket, Target, Trophy } from "lucide-react";
import { outsidersApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { Tilt, useReveal } from "@/components/track-record/effets";

export interface Outsider {
  course_id: string;
  code: string;
  hippodrome: string | null;
  discipline: string | null;
  date_heure: string | null;
  est_quinte: boolean;
  numero: number | null;
  nom_cheval: string | null;
  casaque_image_url?: string | null;
  jockey?: string | null;
  cote_signal: number | null;
  cote_actuelle: number | null;
  chance_place: number | null;
  niveau: "fort" | "a_suivre";
  places_payees: number;
  raisons: string[];
  non_partant: boolean;
  termine: boolean;
  position: number | null;
  place: boolean | null;
  gagne: boolean | null;
  rapport_place: number | null;
  rapport_gagnant: number | null;
  /** Course à venir vue par un non-abonné : le serveur n'envoie alors QUE le niveau. */
  verrouille?: boolean;
}

interface JourResp {
  jour: string;
  acces_complet: boolean;
  outsiders: Outsider[];
}

interface BilanResp {
  jours: number;
  n: number;
  places: number;
  gagnes: number;
  taux_place: number | null;
  rendement_simple_place: number | null;
  par_niveau: Record<string, { n: number; places: number; taux_place: number | null }>;
  plus_beaux: Outsider[];
  validation: {
    entraine_le?: string;
    place_outsiders?: number;
    sel_a_suivre?: { n: number; places: number | null; par_jour: number };
    sel_fort?: { n: number; places: number | null; par_jour: number };
  } | null;
}

const pct = (v: number | null | undefined, d = 0) =>
  v == null ? "—" : `${(v * 100).toFixed(d).replace(".", ",")} %`;
const cote = (v: number | null | undefined) => (v == null ? "—" : v.toFixed(v < 10 ? 1 : 0).replace(".", ","));
/** Rapport PMU pour 1 € (« ×12,4 »), même écriture que le palmarès. */
const rapport = (v: number) => (Math.round(v * 10) / 10).toLocaleString("fr-FR", { maximumFractionDigits: 1 });
const heure = (iso: string | null) =>
  iso ? new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" }) : "";
const titre = (s: string | null) =>
  (s ?? "").toLowerCase().replace(/(^|[\s-])\p{L}/gu, (m) => m.toUpperCase());

export function useOutsidersJour() {
  return useSWR<JourResp>("outsiders-jour", () => outsidersApi.jour().then((r) => r.data), {
    refreshInterval: 120_000,
    revalidateOnFocus: true,
  });
}

export function useOutsidersBilan(jours = 30) {
  return useSWR<BilanResp>(`outsiders-bilan-${jours}`, () => outsidersApi.bilan(jours).then((r) => r.data), {
    refreshInterval: 300_000,
  });
}

/* ─── Habillage par niveau ───────────────────────────────────────────────── */
const THEME = {
  fort: {
    label: "Outsider fort",
    icone: Flame,
    badge: "bg-rose-50 text-rose-700 ring-rose-200",
    ring: ["#fb7185", "#f43f5e"],
    chiffre: "from-rose-500 to-rose-700",
    halo: "ring-rose-200 shadow-[inset_0_1px_0_#fff,0_2px_6px_rgba(28,25,23,.05),0_28px_50px_-30px_rgba(225,29,72,.45)]",
    jeton: "from-rose-300 via-rose-500 to-rose-700",
  },
  a_suivre: {
    label: "À suivre",
    icone: Target,
    badge: "bg-amber-50 text-amber-800 ring-amber-200",
    ring: ["#fbbf24", "#d97706"],
    chiffre: "from-amber-500 to-amber-700",
    halo: "ring-stone-200 shadow-[inset_0_1px_0_#fff,0_2px_6px_rgba(28,25,23,.05),0_28px_50px_-32px_rgba(217,119,6,.4)]",
    jeton: "from-amber-200 via-amber-400 to-amber-600",
  },
} as const;

/* ─── Briques ────────────────────────────────────────────────────────────── */

/** Scène claire en relief : fond crème, halos doux fixes, quadrillage léger. */
export function Scene({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "relative isolate overflow-hidden rounded-[28px] bg-gradient-to-b from-[#FFFDF8] to-[#F6F0E4] ring-1 ring-stone-200/80",
        "shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(28,25,23,.05),0_30px_60px_-42px_rgba(28,25,23,.35)]",
        className,
      )}
    >
      <span className="pointer-events-none absolute -left-24 -top-24 -z-10 h-72 w-72 rounded-full bg-rose-200/40 blur-3xl" aria-hidden />
      <span className="pointer-events-none absolute -bottom-28 -right-20 -z-10 h-80 w-80 rounded-full bg-amber-200/50 blur-3xl" aria-hidden />
      <span
        className="pointer-events-none absolute inset-0 -z-10 opacity-[0.06] [background-image:linear-gradient(rgba(120,90,40,.6)_1px,transparent_1px),linear-gradient(90deg,rgba(120,90,40,.6)_1px,transparent_1px)] [background-size:44px_44px] [mask-image:radial-gradient(ellipse_at_center,#000_30%,transparent_75%)]"
        aria-hidden
      />
      {children}
    </div>
  );
}

/** Jauge circulaire de la chance de place (remplie une fois à l'entrée à l'écran). */
function Jauge({ valeur, niveau, verrouille }: { valeur: number | null; niveau: Outsider["niveau"]; verrouille: boolean }) {
  const id = useId().replace(/:/g, "");
  const { ref, hidden } = useReveal<HTMLDivElement>(0.3);
  const r = 30;
  const c = 2 * Math.PI * r;
  const v = verrouille || valeur == null ? 0 : Math.max(0, Math.min(1, valeur));
  const t = THEME[niveau];
  return (
    <div ref={ref} className="relative h-[76px] w-[76px] shrink-0">
      <svg viewBox="0 0 76 76" className="h-full w-full -rotate-90" aria-hidden>
        <defs>
          <linearGradient id={`g${id}`} x1="0" y1="0" x2="1" y2="1">
            <stop offset="0%" stopColor={t.ring[0]} />
            <stop offset="100%" stopColor={t.ring[1]} />
          </linearGradient>
        </defs>
        <circle cx="38" cy="38" r={r} fill="none" stroke="rgba(28,25,23,.07)" strokeWidth="7" />
        <circle
          cx="38"
          cy="38"
          r={r}
          fill="none"
          stroke={`url(#g${id})`}
          strokeWidth="7"
          strokeLinecap="round"
          strokeDasharray={c}
          strokeDashoffset={hidden ? c : c * (1 - v)}
          className="tr-ring"
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center leading-none">
        {verrouille ? (
          <Lock className="h-5 w-5 text-stone-500" aria-label="Réservé aux abonnés" />
        ) : (
          <>
            <span className="font-display text-[19px] font-black tabular-nums text-gray-900">
              {valeur == null ? "—" : Math.round(valeur * 100)}
              <span className="text-[11px] font-bold text-stone-500">%</span>
            </span>
          </>
        )}
      </div>
    </div>
  );
}

/**
 * Casaque officielle PMU (image de l'API) en médaillon à relief, numéro du
 * partant en pastille. Sans image (ou image en erreur) : numéro en grand sur
 * fond dégradé du niveau — jamais un cadre vide.
 */
function Casaque({ numero, url, niveau, verrouille }: {
  numero: number | null; url: string | null; niveau: Outsider["niveau"]; verrouille: boolean;
}) {
  const [echec, setEchec] = useState<string | null>(null);
  const image = !verrouille && url && echec !== url ? url : null;
  return (
    <span className="relative shrink-0">
      <span
        className={cn(
          "flex h-16 w-16 items-center justify-center overflow-hidden rounded-2xl ring-1",
          "shadow-[inset_0_1px_0_#fff,0_1px_2px_rgba(28,25,23,.08),0_14px_24px_-12px_rgba(28,25,23,.45)]",
          verrouille
            ? "bg-stone-100 ring-stone-200"
            : image
              ? "bg-gradient-to-b from-white to-stone-50 ring-stone-200"
              : cn("bg-gradient-to-br ring-black/5", THEME[niveau].jeton),
        )}
      >
        {verrouille ? (
          <Lock className="h-5 w-5 text-stone-400" aria-hidden />
        ) : image ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={image}
            alt={`Casaque du n°${numero ?? ""}`}
            width={52}
            height={52}
            loading="lazy"
            onError={() => setEchec(image)}
            className="h-[52px] w-[52px] object-contain drop-shadow-[0_3px_3px_rgba(28,25,23,.25)]"
          />
        ) : (
          <span className="font-display text-2xl font-black text-gray-950">{numero ?? "?"}</span>
        )}
      </span>
      {image && numero != null && (
        <span
          className="absolute -bottom-1.5 -right-1.5 flex h-7 min-w-7 items-center justify-center rounded-lg bg-[#172033] px-1.5 font-display text-[13px] font-extrabold tabular-nums text-white shadow-[0_6px_12px_-4px_rgba(23,32,51,.6)] ring-2 ring-white"
          aria-label={`Numéro ${numero}`}
        >
          {numero}
        </span>
      )}
    </span>
  );
}

function Badge({ niveau }: { niveau: Outsider["niveau"] }) {
  const t = THEME[niveau];
  const Icone = t.icone;
  return (
    <span className={cn("inline-flex shrink-0 items-center gap-1 whitespace-nowrap rounded-full px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-[0.08em] ring-1", t.badge)}>
      <Icone className="h-3 w-3" aria-hidden /> {t.label}
    </span>
  );
}

function Resultat({ o }: { o: Outsider }) {
  if (o.non_partant)
    return <span className="rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-semibold text-stone-500">Non-partant</span>;
  if (!o.termine)
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-semibold text-stone-600 ring-1 ring-stone-200">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" aria-hidden /> Départ {heure(o.date_heure)}
      </span>
    );
  if (o.gagne)
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-gradient-to-b from-emerald-400 to-emerald-600 px-2.5 py-1 text-[11px] font-bold text-white shadow-[0_6px_16px_-6px_rgba(16,185,129,.8)]">
        <Trophy className="h-3 w-3" aria-hidden /> Gagnant{o.rapport_gagnant ? ` · ×${rapport(o.rapport_gagnant)}` : ""}
      </span>
    );
  if (o.place)
    return (
      <span className="inline-flex items-center gap-1 whitespace-nowrap rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-700 ring-1 ring-emerald-200">
        <Check className="h-3 w-3" aria-hidden /> {o.position}e · placé{o.rapport_place ? ` ×${rapport(o.rapport_place)}` : ""}
      </span>
    );
  return (
    <span className="whitespace-nowrap rounded-full bg-stone-100 px-2.5 py-1 text-[11px] font-semibold text-stone-500 ring-1 ring-stone-200">
      {o.position ? `Arrivé ${o.position}e` : "Non placé"}
    </span>
  );
}

/* ─── Carte verrouillée (non-abonné, course à venir) ─────────────────────── */

/** Ne montre que le niveau : aucune course, heure, numéro, casaque, jockey ni
 *  cote — le serveur ne les envoie d'ailleurs pas. */
function CarteVerrouillee({ niveau }: { niveau: Outsider["niveau"] }) {
  return (
    <Link
      href="/tarifs"
      aria-label="Outsider réservé aux abonnés — voir les formules"
      className={cn(
        "group flex h-full flex-col rounded-3xl bg-gradient-to-b from-white to-[#FFFBF3] p-4 ring-1 sm:p-5",
        "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500",
        THEME[niveau].halo,
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="rounded-lg bg-stone-100 px-2 py-1 text-[11px] font-bold uppercase tracking-wide text-stone-400 ring-1 ring-stone-200">
          Course à venir
        </span>
        <Badge niveau={niveau} />
      </div>
      <div className="mt-4 flex items-center gap-3.5">
        <span className="flex h-16 w-16 shrink-0 items-center justify-center rounded-2xl bg-stone-100 ring-1 ring-stone-200 shadow-[inset_0_1px_0_#fff,0_14px_24px_-12px_rgba(28,25,23,.35)]">
          <Lock className="h-6 w-6 text-stone-400" aria-hidden />
        </span>
        <div className="min-w-0 flex-1 space-y-2" aria-hidden>
          <span className="block h-4 w-3/4 rounded-full bg-stone-200/80" />
          <span className="block h-3 w-1/2 rounded-full bg-stone-200/60" />
          <span className="block h-5 w-16 rounded-lg bg-stone-100 ring-1 ring-stone-200" />
        </div>
        <Jauge valeur={null} niveau={niveau} verrouille />
      </div>
      <div className="mt-auto flex items-center justify-between gap-2 pt-4">
        <span className="text-xs font-semibold text-amber-700">Réservé aux abonnés Standard et Expert</span>
        <ArrowUpRight className="h-3.5 w-3.5 text-stone-400 group-hover:text-amber-700" aria-hidden />
      </div>
    </Link>
  );
}

/* ─── Carte ──────────────────────────────────────────────────────────────── */

export function OutsiderCarte({ o, compact = false }: { o: Outsider; compact?: boolean }) {
  if (o.verrouille) return <CarteVerrouillee niveau={o.niveau} />;
  const t = THEME[o.niveau];
  return (
    <Tilt max={4} className="h-full">
      <Link
        href={`/courses/${o.course_id}`}
        aria-label={`Course ${o.code}${o.nom_cheval ? ` — ${titre(o.nom_cheval)}` : ""}`}
        className={cn(
          "group flex h-full flex-col rounded-3xl bg-gradient-to-b from-white to-[#FFFBF3] p-4 ring-1 transition-shadow sm:p-5",
          "focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber-500",
          t.halo,
          o.termine && !o.place && "opacity-80",
        )}
      >
        {/* En-tête : course + niveau */}
        <div className="flex items-center justify-between gap-2">
          <div className="flex min-w-0 items-center gap-2">
            <span className="shrink-0 rounded-lg bg-[#172033] px-2 py-1 font-display text-[11px] font-extrabold tracking-wide text-white shadow-[inset_0_1px_0_rgba(255,255,255,.15)]">
              {o.code}
            </span>
            <span className="min-w-0 truncate text-[12px] font-semibold text-stone-600" title={titre(o.hippodrome)}>
              {titre(o.hippodrome)}
            </span>
          </div>
          <Badge niveau={o.niveau} />
        </div>

        {/* Cheval + jauge */}
        <div className="mt-4 flex items-center gap-3.5">
          <Casaque numero={o.numero} url={o.casaque_image_url ?? null} niveau={o.niveau} verrouille={!!o.verrouille} />
          <div className="min-w-0 flex-1">
            {o.verrouille ? (
              <>
                <p className="select-none font-display text-lg font-bold leading-tight text-stone-800 blur-[5px]" aria-hidden>
                  Nom masqué
                </p>
                <p className="mt-1 text-xs font-semibold text-amber-700">Cheval réservé aux abonnés</p>
              </>
            ) : (
              <>
                <p className="break-words font-display text-[17px] font-bold leading-snug text-gray-900">{titre(o.nom_cheval)}</p>
                {o.jockey && (
                  <p className="mt-0.5 break-words text-xs leading-4 text-stone-500">
                    {titre(o.jockey)}
                  </p>
                )}
              </>
            )}
            <div className="mt-2 flex flex-wrap items-center gap-1.5">
              <span className="inline-flex items-baseline gap-1 rounded-lg bg-stone-100 px-2 py-0.5 ring-1 ring-stone-200">
                <span className="text-[10px] font-semibold uppercase tracking-wide text-stone-500">Cote</span>
                <span className={cn("bg-gradient-to-b bg-clip-text font-display text-[15px] font-black tabular-nums text-transparent", t.chiffre)}>
                  {o.verrouille ? "15+" : cote(o.cote_actuelle ?? o.cote_signal)}
                </span>
              </span>
              {o.est_quinte && (
                <span className="rounded-lg bg-amber-100 px-2 py-0.5 text-[10.5px] font-bold text-amber-800 ring-1 ring-amber-200">
                  Quinté+
                </span>
              )}
              {!compact && !o.verrouille && o.cote_actuelle != null && o.cote_signal != null && Math.abs(o.cote_actuelle - o.cote_signal) >= 1 && (
                <span className="text-[11px] text-stone-400">repéré à {cote(o.cote_signal)}</span>
              )}
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-center">
            <Jauge valeur={o.chance_place} niveau={o.niveau} verrouille={!!o.verrouille} />
            <span className="mt-1 whitespace-nowrap text-[9.5px] font-semibold uppercase tracking-[0.1em] text-stone-400">
              Chance top {o.places_payees}
            </span>
          </div>
        </div>

        {/* Raisons */}
        {!compact && o.raisons.length > 0 && (
          <ul className="mt-4 space-y-1.5 border-t border-stone-200 pt-3">
            {o.raisons.map((r) => (
              <li key={r} className="flex gap-2 text-[13px] leading-5 text-stone-700">
                <span className="mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-amber-100 ring-1 ring-amber-200">
                  <Check className="h-2.5 w-2.5 text-amber-700" aria-hidden />
                </span>
                <span className="min-w-0 break-words">{r}</span>
              </li>
            ))}
          </ul>
        )}

        {/* Pied */}
        <div className="mt-auto flex flex-wrap items-center justify-between gap-2 pt-4">
          <Resultat o={o} />
          <span className="inline-flex items-center gap-1 text-xs font-semibold text-stone-500 transition-colors group-hover:text-amber-700">
            Voir la course <ArrowUpRight className="h-3.5 w-3.5" aria-hidden />
          </span>
        </div>
      </Link>
    </Tilt>
  );
}

function Grille({ children, cols = 3 }: { children: ReactNode; cols?: 2 | 3 }) {
  return (
    <div className={cn("grid grid-cols-1 gap-4 sm:grid-cols-2", cols === 3 && "lg:grid-cols-3")}>{children}</div>
  );
}

function Squelettes({ n = 3, cols = 3 }: { n?: number; cols?: 2 | 3 }) {
  return (
    <Grille cols={cols}>
      {Array.from({ length: n }).map((_, i) => (
        <div key={i} className="h-44 animate-pulse rounded-3xl bg-stone-100 ring-1 ring-stone-200" />
      ))}
    </Grille>
  );
}

function Eyebrow() {
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-rose-50 px-3 py-1 text-[11px] font-bold uppercase tracking-[0.16em] text-rose-700 ring-1 ring-rose-200">
      <Rocket className="h-3.5 w-3.5" aria-hidden /> Outsiders du jour
    </span>
  );
}

/** Ligne « preuve » : taux réel des outsiders affichés sur 30 jours (ou validation). */
export function PreuveOutsiders({ bilan, sombre = true }: { bilan?: BilanResp; sombre?: boolean }) {
  if (!bilan) return null;
  const fort = sombre ? "text-gray-900" : "text-gray-900";
  const base = sombre ? "text-stone-600" : "text-gray-600";
  if (bilan.n >= 30 && bilan.taux_place != null) {
    return (
      <p className={cn("text-sm", base)}>
        Sur {bilan.jours} jours : <strong className={fort}>{bilan.places} outsiders placés sur {bilan.n}</strong>{" "}
        ({pct(bilan.taux_place)}), dont {bilan.gagnes} gagnant{bilan.gagnes > 1 ? "s" : ""}.
      </p>
    );
  }
  const v = bilan.validation;
  if (v?.sel_a_suivre?.places != null && v.place_outsiders != null) {
    return (
      <p className={cn("text-sm", base)}>
        Testé sur 2 semaines de courses jamais vues : retenus placés{" "}
        <strong className={fort}>{pct(v.sel_a_suivre.places)}</strong> du temps, contre {pct(v.place_outsiders)} pour
        un outsider moyen.
      </p>
    );
  }
  return null;
}

const TEXTE_ABONNES =
  "Les outsiders des prochaines courses — course, cheval, casaque, cote et raisons — sont réservés aux abonnés Standard et Expert.";

function BandeauAbonnes({ texte = TEXTE_ABONNES }: { texte?: string }) {
  return (
    <div className="mt-5 flex flex-col gap-3 rounded-2xl bg-white/80 p-4 ring-1 ring-stone-200 sm:flex-row sm:items-center sm:justify-between">
      <p className="flex items-start gap-2 text-sm text-stone-700">
        <Lock className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden /> {texte}
      </p>
      <Link
        href="/tarifs"
        className="inline-flex shrink-0 items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-4 py-2 text-sm font-bold text-gray-950 shadow-[inset_0_1px_0_rgba(255,255,255,.5),0_10px_20px_-10px_rgba(245,158,11,.8)] hover:from-amber-200 hover:to-amber-400"
      >
        Voir les formules <ArrowRight className="h-4 w-4" aria-hidden />
      </Link>
    </div>
  );
}

/* ─── Bloc compact (accueil, programme) ──────────────────────────────────── */

export function OutsidersDuJour({ titreNiveau = "h2", max = 6 }: { titreNiveau?: "h2" | "h3"; max?: number }) {
  const { data, isLoading } = useOutsidersJour();
  const { data: bilan } = useOutsidersBilan(30);
  const complet = !!data?.acces_complet;
  const liste = (data?.outsiders ?? []).filter((o) => !o.non_partant);
  const aVenir = liste.filter((o) => !o.termine);
  const courus = liste.filter((o) => o.termine);
  // Rien aujourd'hui : un non-abonné voit les plus beaux coups récents (courus).
  const montres = (liste.length > 0 ? [...aVenir, ...courus] : complet ? [] : bilan?.plus_beaux ?? []).slice(0, max);
  const H = titreNiveau;

  if (!isLoading && montres.length === 0) return null;

  return (
    <Scene className="p-5 sm:p-8">
      <div className="mb-6 flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div className="min-w-0">
          <Eyebrow />
          <H className="mt-3 font-display text-[1.6rem] font-extrabold leading-tight tracking-tight text-gray-900 sm:text-3xl">
            Les grosses cotes{" "}
            <span className="bg-gradient-to-r from-rose-600 via-amber-600 to-amber-500 bg-clip-text text-transparent">
              capables de se placer
            </span>
          </H>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-stone-600">
            Cotes à 15 et plus que notre cerveau des outsiders juge sous-estimées, avec leur chance estimée de finir dans
            les places.
            {aVenir.length > 0
              ? ` ${aVenir.length} détecté${aVenir.length > 1 ? "s" : ""} pour les prochaines courses.`
              : liste.length === 0 && !complet
                ? " Voici les derniers qu'il avait repérés, et ce qu'ils ont fait."
                : ""}
          </p>
          <div className="mt-1.5">
            <PreuveOutsiders bilan={bilan} />
          </div>
        </div>
        <Link
          href="/outsiders"
          className="inline-flex shrink-0 items-center justify-center gap-1.5 self-start rounded-xl bg-gradient-to-b from-stone-800 to-stone-950 px-4 py-2.5 text-sm font-bold text-white shadow-[inset_0_1px_0_rgba(255,255,255,.15),0_12px_24px_-12px_rgba(28,25,23,.6)] hover:from-stone-700 hover:to-stone-900 lg:self-auto"
        >
          {complet ? "Tous les outsiders" : "Résultats et bilan"} <ArrowRight className="h-4 w-4" aria-hidden />
        </Link>
      </div>
      {isLoading ? (
        <Squelettes n={Math.min(max, 3)} />
      ) : (
        <Grille cols={max >= 3 ? 3 : 2}>
          {montres.map((o, i) => (
            <OutsiderCarte key={o.verrouille ? `v-${i}` : `${o.course_id}-${o.numero ?? i}`} o={o} compact />
          ))}
        </Grille>
      )}
      {data && !complet && <BandeauAbonnes />}
    </Scene>
  );
}

/* ─── Encart de la fiche course ──────────────────────────────────────────── */

export function OutsidersCourse({ courseId }: { courseId: string }) {
  const { data } = useSWR<{ acces_complet: boolean; outsiders: Outsider[] }>(
    `outsiders-course-${courseId}`,
    () => outsidersApi.course(courseId).then((r) => r.data),
    { refreshInterval: 120_000 },
  );
  const liste = (data?.outsiders ?? []).filter((o) => !o.non_partant);
  if (liste.length === 0) return null;
  return (
    <Scene className="p-4 sm:p-6">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
        <h2 className="flex items-center gap-2 font-display text-lg font-bold text-gray-900">
          <span className="flex h-8 w-8 items-center justify-center rounded-xl bg-rose-100 ring-1 ring-rose-200">
            <Rocket className="h-4 w-4 text-rose-600" aria-hidden />
          </span>
          {liste[0].termine
            ? liste.length > 1
              ? "Outsiders détectés avant le départ"
              : "Outsider détecté avant le départ"
            : liste.length > 1
              ? "Outsiders repérés dans cette course"
              : "Outsider repéré dans cette course"}
        </h2>
        <Link href="/outsiders" className="text-xs font-semibold text-stone-500 underline-offset-4 hover:text-amber-700 hover:underline">
          Tous les outsiders du jour
        </Link>
      </div>
      <p className="-mt-2 mb-4 text-sm text-stone-500">
        Cote 15 ou plus, que le cerveau des outsiders juge capable de finir dans les {liste[0].places_payees} premiers.
      </p>
      <Grille cols={2}>
        {liste.map((o, i) => (
          <OutsiderCarte key={`${o.numero ?? "x"}-${i}`} o={o} />
        ))}
      </Grille>
    </Scene>
  );
}

/* ─── Page complète /outsiders ───────────────────────────────────────────── */

function Kpi({ valeur, libelle, accent = false }: { valeur: string; libelle: string; accent?: boolean }) {
  return (
    <div
      className={cn(
        "rounded-2xl bg-gradient-to-b from-white to-[#FFFBF3] p-4 ring-1 ring-stone-200",
        "shadow-[inset_0_1px_0_#fff,0_2px_6px_rgba(28,25,23,.05),0_20px_40px_-30px_rgba(120,53,15,.35)]",
      )}
    >
      <p
        className={cn(
          "font-display text-2xl font-black tabular-nums leading-none sm:text-[1.75rem]",
          accent ? "bg-gradient-to-b from-amber-500 to-amber-700 bg-clip-text text-transparent" : "text-gray-900",
        )}
      >
        {valeur}
      </p>
      <p className="mt-2 text-xs leading-4 text-stone-500">{libelle}</p>
    </div>
  );
}

function TitreScene({ children, sous }: { children: ReactNode; sous?: ReactNode }) {
  return (
    <div className="mb-5">
      <h2 className="flex items-center gap-2.5 font-display text-xl font-bold tracking-tight text-gray-900 sm:text-2xl">
        <span className="h-5 w-1 rounded-full bg-gradient-to-b from-rose-400 to-amber-400" aria-hidden />
        {children}
      </h2>
      {sous && <p className="mt-1.5 text-sm text-stone-500">{sous}</p>}
    </div>
  );
}

export function OutsidersPage() {
  const { data, isLoading } = useOutsidersJour();
  const { data: bilan } = useOutsidersBilan(30);
  const liste = (data?.outsiders ?? []).filter((o) => !o.non_partant);
  const aVenir = liste.filter((o) => !o.termine);
  const finis = liste.filter((o) => o.termine);
  const v = bilan?.validation;

  return (
    <div className="space-y-8">
      <Scene className="p-5 sm:p-8">
        <TitreScene sous="Mis à jour toutes les 5 minutes jusqu'à 10 minutes du départ.">À courir aujourd&apos;hui</TitreScene>
        {isLoading ? (
          <Squelettes n={2} cols={2} />
        ) : aVenir.length === 0 ? (
          <p className="rounded-2xl bg-white/80 p-5 text-sm leading-6 text-stone-600 ring-1 ring-stone-200">
            Aucun outsider retenu pour les courses restantes. Le cerveau ne force jamais : sans grosse cote assez solide,
            pas de signal.
          </p>
        ) : (
          <Grille cols={2}>
            {aVenir.map((o, i) => (
              <OutsiderCarte key={o.verrouille ? `v-${i}` : `${o.course_id}-${o.numero ?? i}`} o={o} />
            ))}
          </Grille>
        )}
        {data && !data.acces_complet && <BandeauAbonnes />}

        {finis.length > 0 && (
          <div className="mt-10">
            <TitreScene>Déjà courus aujourd&apos;hui</TitreScene>
            <Grille cols={2}>
              {finis.map((o, i) => (
                <OutsiderCarte key={`${o.course_id}-${o.numero ?? i}`} o={o} />
              ))}
            </Grille>
          </div>
        )}
      </Scene>

      <Scene className="p-5 sm:p-8">
        <TitreScene sous="Chaque outsider est figé 10 minutes avant le départ. Tous comptent, placés ou non.">
          Le bilan réel, sans filtre
        </TitreScene>
        {bilan && bilan.n > 0 ? (
          <>
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Kpi valeur={String(bilan.n)} libelle={`outsiders affichés en ${bilan.jours} jours`} />
              <Kpi valeur={pct(bilan.taux_place)} libelle={`se sont placés (${bilan.places})`} accent />
              <Kpi valeur={String(bilan.gagnes)} libelle="ont gagné" />
              <Kpi valeur={pct(bilan.par_niveau?.fort?.taux_place)} libelle="des « Outsider fort » placés" accent />
            </div>
            {bilan.plus_beaux.length > 0 && (
              <div className="mt-8">
                <h3 className="mb-4 font-display text-lg font-bold text-gray-900">Les plus beaux coups</h3>
                <Grille cols={2}>
                  {bilan.plus_beaux.map((o, i) => (
                    <OutsiderCarte key={`${o.course_id}-${o.numero ?? i}`} o={o} compact />
                  ))}
                </Grille>
              </div>
            )}
          </>
        ) : (
          <p className="rounded-2xl bg-white/80 p-5 text-sm text-stone-600 ring-1 ring-stone-200">
            Le bilan se remplit au fil des courses.
            {v?.sel_a_suivre?.places != null && v.place_outsiders != null && (
              <>
                {" "}
                En attendant, le test sur 2 semaines de courses jamais vues : retenus placés{" "}
                <strong className="text-gray-900">{pct(v.sel_a_suivre.places)}</strong>, contre {pct(v.place_outsiders)} pour
                un outsider moyen.
              </>
            )}
          </p>
        )}
      </Scene>

      <section className="rounded-[28px] bg-white p-5 shadow-[0_1px_2px_rgba(28,25,23,.06),0_24px_48px_-32px_rgba(28,25,23,.35)] ring-1 ring-stone-200 sm:p-8">
        <h2 className="flex items-center gap-2.5 font-display text-xl font-bold tracking-tight text-gray-900 sm:text-2xl">
          <span className="h-5 w-1 rounded-full bg-gradient-to-b from-rose-400 to-amber-400" aria-hidden />
          Comment le cerveau repère un outsider
        </h2>
        <p className="mt-3 text-[15px] leading-7 text-gray-700">
          Un modèle dédié, entraîné chaque nuit uniquement sur les chevaux cotés 10 ou plus, estime la chance de finir
          dans les places payées (les 3 premiers, les 2 premiers à 7 partants ou moins). Il lit, tels qu&apos;ils étaient
          avant le départ :
        </p>
        <div className="mt-5 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {[
            { t: "Le marché au-delà du PMU", d: "Coté 25 au PMU mais 14 chez les bookmakers ou sur Betfair : sous-coté au PMU." },
            { t: "L'argent qui arrive", d: "Un outsider dont la cote baisse depuis le premier pronostic du jour est joué." },
            { t: "Sa valeur propre", d: "Forme, niveau (ELO), gains, jockey, entraîneur, terrain, distance, ferrure, presse." },
            { t: "Notre pronostic général", d: "Et sa place parmi les autres outsiders de la course." },
          ].map((x, i) => (
            <div key={x.t} className="flex gap-3 rounded-2xl bg-stone-50 p-4 ring-1 ring-stone-200">
              <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-gradient-to-b from-stone-800 to-stone-950 font-display text-sm font-bold text-amber-300 shadow-[inset_0_1px_0_rgba(255,255,255,.12)]">
                {i + 1}
              </span>
              <div className="min-w-0">
                <p className="font-semibold text-gray-900">{x.t}</p>
                <p className="mt-0.5 text-sm leading-6 text-gray-600">{x.d}</p>
              </div>
            </div>
          ))}
        </div>
        <p className="mt-5 text-[15px] leading-7 text-gray-700">
          Il ne retient que les cotes à 15 et plus dont la chance de place atteint 22 % (« À suivre ») ou 28 % (« Outsider
          fort »), au plus deux par course. Il n&apos;est remis en service chaque nuit que s&apos;il fait au moins aussi bien
          que notre modèle général sur deux semaines de courses jamais vues.
        </p>
        {v?.sel_a_suivre?.places != null && v.place_outsiders != null && (
          <p className="mt-4 rounded-2xl bg-amber-50 p-4 text-sm leading-6 text-gray-800 ring-1 ring-amber-200">
            Dernier test sur courses jamais vues : retenus placés <strong>{pct(v.sel_a_suivre.places)}</strong>
            {v.sel_fort?.places != null && (
              <>
                , « Outsider fort » <strong>{pct(v.sel_fort.places)}</strong>
              </>
            )}
            , contre {pct(v.place_outsiders)} pour un outsider moyen.
          </p>
        )}
        <p className="mt-4 text-sm leading-6 text-gray-500">
          Soyons clairs : un outsider reste un outsider. Même bien choisis, la plupart ne se placent pas, et les jouer
          systématiquement ne garantit aucun gain. C&apos;est un repérage, pas une promesse.
        </p>
      </section>
    </div>
  );
}
