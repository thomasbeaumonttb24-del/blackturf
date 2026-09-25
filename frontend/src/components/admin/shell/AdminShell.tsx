"use client";

/**
 * Coquille de la console d'administration.
 *
 * Ce que ça répare : les trois écrans d'admin n'avaient AUCUNE navigation. Ils
 * vivent sous `app/admin/`, donc hors du `(main)` qui porte la barre du site ;
 * pour passer du back-office à la supervision IA il fallait rouvrir le menu du
 * compte, et rien à l'écran ne disait qu'un troisième écran existait.
 *
 * Le remède est celui de n'importe quelle console : une navigation permanente,
 * au même endroit sur toutes les pages. Barre latérale au-delà de 1024 px,
 * barre du bas sur téléphone — six destinations depuis l'ajout de « Revenus »
 * (2026-09-25), chacune avec son icône ET son libellé (une barre d'icônes
 * seules ne s'apprend pas). À 360 px, six cases font 60 px : la cible tactile
 * reste au-dessus des 44 px.
 *
 * Les pastilles de la navigation ne sont pas décoratives : elles comptent des
 * incidents réels (erreurs ouvertes, scrapers muets, paiements échoués) et
 * viennent des mêmes requêtes que les pages — `components/admin/data.ts`
 * déduplique, la barre ne coûte pas un appel de plus.
 */

import * as React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  AlertTriangle, ArrowLeft, Brain, CreditCard, Euro, Gauge, Loader2, Server, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRequireAuth } from "@/hooks/useAuth";
import { useAlertes, useEnLigne, useEstAdmin } from "../data";
import { PointLive } from "../ui";

/** Compteur « en ligne » permanent, au pied de la barre latérale. */
function EnLigneMini() {
  const { data } = useEnLigne();
  if (!data?.disponible) return null;
  return (
    <Link
      href="/admin"
      className="flex items-center gap-2 rounded-xl border border-emerald-400/20 bg-emerald-400/[0.07] px-3 py-2.5 text-xs text-white/70 shadow-[0_0_24px_-10px_rgba(52,211,153,0.6)] transition-colors hover:bg-emerald-400/[0.12]"
    >
      <PointLive />
      <span><b className="font-semibold tabular-nums text-white">{data.total}</b> en ligne</span>
    </Link>
  );
}

/** Horloge du poste de pilotage — l'heure de Paris, à la seconde. */
function Horloge() {
  const [maintenant, setMaintenant] = React.useState<Date | null>(null);
  React.useEffect(() => {
    setMaintenant(new Date());
    const i = window.setInterval(() => setMaintenant(new Date()), 1000);
    return () => window.clearInterval(i);
  }, []);
  if (!maintenant) return null;
  return (
    <div className="rounded-xl border border-white/[0.07] bg-black/30 px-3 py-2.5 shadow-[inset_0_2px_6px_rgba(0,0,0,0.6)]">
      <div className="font-mono text-lg font-semibold tabular-nums tracking-wider text-white">
        {maintenant.toLocaleTimeString("fr-FR", { timeZone: "Europe/Paris" })}
      </div>
      <div className="text-[11px] capitalize text-white/45">
        {maintenant.toLocaleDateString("fr-FR", { weekday: "long", day: "numeric", month: "long", timeZone: "Europe/Paris" })}
      </div>
    </div>
  );
}

interface Destination {
  href: string;
  label: string;
  /** Version courte pour la barre du bas — « Abonnements » n'y tient pas. */
  court: string;
  icone: React.ElementType;
  /** Sous-chemins qui doivent allumer la même entrée. */
  prefixe?: string[];
}

const DESTINATIONS: Destination[] = [
  { href: "/admin", label: "Pilotage", court: "Pilotage", icone: Gauge },
  { href: "/admin/revenus", label: "Revenus", court: "Revenus", icone: Euro },
  { href: "/admin/abonnements", label: "Abonnements", court: "Abonnés", icone: CreditCard },
  { href: "/admin/comptes", label: "Comptes", court: "Comptes", icone: Users },
  { href: "/admin/algorithme", label: "Algorithme", court: "Algo", icone: Brain },
  {
    href: "/admin/systeme", label: "Système", court: "Système", icone: Server,
    prefixe: ["/admin/instagram"],
  },
];

function estActif(pathname: string, d: Destination) {
  if (d.href === "/admin") return pathname === "/admin";
  return pathname.startsWith(d.href) || (d.prefixe ?? []).some((p) => pathname.startsWith(p));
}

/**
 * Nombre d'incidents JAMAIS VUS porté par une entrée de navigation.
 *
 * Pas le nombre d'incidents ouverts : un paiement échoué il y a huit heures
 * reste dans la fenêtre de sept jours, donc l'ancienne pastille restait allumée
 * après lecture, pour toujours. Une pastille qui ne s'éteint jamais finit par
 * ne plus rien vouloir dire.
 */
function badgeDe(href: string, a: ReturnType<typeof useAlertes>): number {
  return a.nouveaux[href] ?? 0;
}

function Pastille({ n, actif }: { n: number; actif: boolean }) {
  if (n <= 0) return null;
  return (
    <span
      aria-label={`${n} point${n > 1 ? "s" : ""} d'attention`}
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[10px] font-bold tabular-nums",
        actif ? "bg-[#1a1203]/30 text-[#1a1203]" : "bg-red-500 text-white shadow-[0_0_12px_rgba(239,68,68,0.8)]",
      )}
    >
      {n > 99 ? "99+" : n}
    </span>
  );
}

export default function AdminShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname() ?? "/admin";
  // Un visiteur non connecté part vers /login ; un connecté non-admin voit un
  // refus explicite. Distinguer les deux évite de renvoyer un exploitant déjà
  // authentifié vers un formulaire de connexion qu'il vient de remplir.
  useRequireAuth();
  const { estAdmin, chargement } = useEstAdmin();
  const alertes = useAlertes();
  const courante = DESTINATIONS.find((d) => estActif(pathname, d));

  // Ouvrir l'écran vaut lecture. L'effet se rejoue quand les données changent,
  // donc un incident qui arrive pendant qu'on regarde l'écran est acquitté sans
  // jamais allumer la pastille — c'est voulu : on est déjà devant.
  const { marquerVu } = alertes;
  const hrefCourant = courante?.href;
  React.useEffect(() => {
    if (hrefCourant) marquerVu(hrefCourant);
  }, [hrefCourant, marquerVu]);

  if (chargement) {
    return (
      <div className="flex min-h-dvh items-center justify-center">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" aria-label="Chargement" />
      </div>
    );
  }

  if (!estAdmin) {
    return (
      <div className="mx-auto flex min-h-dvh max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
        <span className="flex h-12 w-12 items-center justify-center rounded-2xl bg-destructive/10 text-destructive">
          <AlertTriangle className="h-6 w-6" />
        </span>
        <div>
          <h1 className="text-lg font-semibold">Accès réservé</h1>
          <p className="mt-1 text-[13px] text-muted-foreground">
            Cette console est réservée à l&apos;administration de BlackTurf.
          </p>
        </div>
        <Link
          href="/"
          className="inline-flex min-h-[2.75rem] items-center gap-2 rounded-xl border border-border px-4 text-[13px] font-semibold transition-colors hover:bg-muted"
        >
          <ArrowLeft className="h-4 w-4" /> Retour au site
        </Link>
      </div>
    );
  }

  return (
    <div className="bt-admin min-h-dvh">
      {/* ── Barre du haut, téléphone et tablette ───────────────────────────
          Elle porte le nom de l'écran courant : sur mobile la navigation est
          en bas, et sans ce rappel une page défilée ne dit plus où l'on est. */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-white/[0.07] bg-[#070912]/80 px-4 backdrop-blur-xl lg:hidden">
        <Link
          href="/"
          aria-label="Retour au site"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase leading-none tracking-[0.12em] text-amber-300/80">
            Administration
          </div>
          <div className="truncate text-sm font-semibold leading-tight">
            {courante?.label ?? "Console"}
          </div>
        </div>
        {alertes.total > 0 && (
          <Link
            href="/admin"
            className="flex h-9 shrink-0 items-center gap-1.5 rounded-full border border-destructive/30 bg-destructive/5 px-3 text-xs font-semibold text-destructive"
          >
            <AlertTriangle className="h-3.5 w-3.5" />
            {alertes.total}
          </Link>
        )}
      </header>

      <div className="mx-auto flex w-full max-w-[1500px]">
        {/* ── Barre latérale, à partir de 1024 px ─────────────────────────── */}
        <aside className="sticky top-0 hidden h-dvh w-64 shrink-0 flex-col border-r border-white/[0.06] bg-gradient-to-b from-[#0d1020]/90 via-[#090b16]/90 to-[#06070d]/95 text-white shadow-[20px_0_60px_-30px_rgba(0,0,0,0.9)] backdrop-blur-xl lg:flex">
          <div className="px-5 py-5">
            <Link href="/" className="group flex items-center gap-2.5">
              <span
                className="bt-halo flex h-11 w-11 items-center justify-center rounded-2xl bg-gradient-to-br from-amber-200 via-amber-500 to-amber-800 font-display text-base font-black text-[#1a1203] transition-transform duration-500 group-hover:[transform:perspective(300px)_rotateY(20deg)_rotateX(10deg)]"
              >
                BT
              </span>
              <span className="min-w-0">
                <span className="block font-display text-base font-bold leading-tight tracking-tight">BlackTurf</span>
                <span className="block text-[11px] font-semibold uppercase leading-tight tracking-[0.14em] text-amber-300/70">
                  Admin · Pro
                </span>
              </span>
            </Link>
          </div>

          <nav aria-label="Sections de l'administration" className="flex-1 space-y-1 px-3">
            {DESTINATIONS.map((d) => {
              const actif = estActif(pathname, d);
              const Icone = d.icone;
              return (
                <Link
                  key={d.href}
                  href={d.href}
                  aria-current={actif ? "page" : undefined}
                  className={cn(
                    "group/nav relative flex min-h-[2.9rem] items-center gap-3 rounded-xl px-3 text-[13px] font-semibold transition-all duration-300 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-brand-gold",
                    actif
                      ? "bg-gradient-to-r from-amber-300 to-amber-600 text-[#1a1203] shadow-[0_10px_24px_-10px_rgba(245,158,11,0.9),inset_0_1px_0_rgba(255,255,255,0.5)]"
                      : "text-white/60 hover:translate-x-1 hover:bg-white/[0.06] hover:text-white",
                  )}
                >
                  <Icone className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="flex-1 truncate">{d.label}</span>
                  <Pastille n={badgeDe(d.href, alertes)} actif={actif} />
                </Link>
              );
            })}
          </nav>

          <div className="space-y-3 border-t border-white/[0.07] px-4 py-4">
            <Horloge />
            <EnLigneMini />
            <Link
              href="/"
              className="flex items-center gap-2 px-1 text-xs font-medium text-white/50 transition-colors hover:text-white"
            >
              <ArrowLeft className="h-3.5 w-3.5" /> Retour au site public
            </Link>
          </div>
        </aside>

        {/* Le `pb-24` réserve la hauteur de la barre du bas : sans lui, la
            dernière ligne de chaque page passait dessous et devenait
            intouchable. */}
        <main className="min-w-0 flex-1 px-3 pb-24 pt-4 sm:px-5 sm:pt-6 lg:px-8 lg:pb-12">
          {children}
        </main>
      </div>

      {/* ── Barre du bas, téléphone ─────────────────────────────────────── */}
      <nav
        aria-label="Sections de l'administration"
        className="fixed inset-x-0 bottom-0 z-30 border-t border-white/[0.07] bg-[#070912]/90 pb-[env(safe-area-inset-bottom)] backdrop-blur-xl lg:hidden"
      >
        <div className="mx-auto flex max-w-lg">
          {DESTINATIONS.map((d) => {
            const actif = estActif(pathname, d);
            const Icone = d.icone;
            const n = badgeDe(d.href, alertes);
            return (
              <Link
                key={d.href}
                href={d.href}
                aria-current={actif ? "page" : undefined}
                className={cn(
                  "relative flex min-h-[3.5rem] flex-1 flex-col items-center justify-center gap-0.5 px-1 text-[10px] font-semibold transition-colors",
                  actif ? "text-amber-300 [text-shadow:0_0_12px_rgba(245,158,11,0.7)]" : "text-muted-foreground",
                )}
              >
                <span className="relative">
                  <Icone className="h-5 w-5" aria-hidden />
                  {n > 0 && (
                    <span
                      aria-label={`${n} point${n > 1 ? "s" : ""} d'attention`}
                      className="absolute -right-1.5 -top-1 flex h-4 min-w-4 items-center justify-center rounded-full bg-destructive px-1 text-[9px] font-bold text-destructive-foreground"
                    >
                      {n > 9 ? "9+" : n}
                    </span>
                  )}
                </span>
                {d.court}
                {actif && (
                  <span
                    aria-hidden
                    className="absolute inset-x-3 top-0 h-0.5 rounded-full bg-amber-400 shadow-[0_0_10px_rgba(245,158,11,0.9)]"
                  />
                )}
              </Link>
            );
          })}
        </div>
      </nav>
    </div>
  );
}
