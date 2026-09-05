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
 * barre du bas sur téléphone — cinq destinations, jamais plus, chacune avec son
 * icône ET son libellé (une barre d'icônes seules ne s'apprend pas).
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
  AlertTriangle, ArrowLeft, Brain, CreditCard, Gauge, Loader2, Server, Users,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { useRequireAuth } from "@/hooks/useAuth";
import { useAlertes, useEstAdmin } from "../data";

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

/** Nombre d'incidents porté par une entrée de navigation. */
function badgeDe(href: string, a: ReturnType<typeof useAlertes>): number {
  if (href === "/admin/systeme") return a.erreursOuvertes + a.scrapersKo;
  if (href === "/admin/abonnements") return a.incidentsPaiement;
  return 0;
}

function Pastille({ n, actif }: { n: number; actif: boolean }) {
  if (n <= 0) return null;
  return (
    <span
      aria-label={`${n} point${n > 1 ? "s" : ""} d'attention`}
      className={cn(
        "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1.5 text-[10px] font-bold tabular-nums",
        actif ? "bg-background/20 text-background" : "bg-destructive text-destructive-foreground",
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
    <div className="min-h-dvh bg-muted/25">
      {/* ── Barre du haut, téléphone et tablette ───────────────────────────
          Elle porte le nom de l'écran courant : sur mobile la navigation est
          en bas, et sans ce rappel une page défilée ne dit plus où l'on est. */}
      <header className="sticky top-0 z-30 flex h-14 items-center gap-3 border-b border-border/70 bg-background/90 px-4 backdrop-blur lg:hidden">
        <Link
          href="/"
          aria-label="Retour au site"
          className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
        </Link>
        <div className="min-w-0 flex-1">
          <div className="text-[11px] font-semibold uppercase leading-none tracking-[0.08em] text-brand-gold-dark">
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
        <aside className="sticky top-0 hidden h-dvh w-60 shrink-0 flex-col border-r border-border/70 bg-background lg:flex">
          <div className="px-5 py-5">
            <Link href="/" className="group flex items-center gap-2.5">
              <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-brand-dark text-sm font-bold text-brand-gold">
                BT
              </span>
              <span className="min-w-0">
                <span className="block text-sm font-semibold leading-tight">BlackTurf</span>
                <span className="block text-[11px] leading-tight text-muted-foreground">
                  Console d&apos;administration
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
                    "flex min-h-[2.75rem] items-center gap-3 rounded-xl px-3 text-[13px] font-semibold transition-colors",
                    actif
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  <Icone className="h-4 w-4 shrink-0" aria-hidden />
                  <span className="flex-1 truncate">{d.label}</span>
                  <Pastille n={badgeDe(d.href, alertes)} actif={actif} />
                </Link>
              );
            })}
          </nav>

          <div className="border-t border-border/70 px-5 py-4">
            <Link
              href="/"
              className="flex items-center gap-2 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
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
        className="fixed inset-x-0 bottom-0 z-30 border-t border-border/70 bg-background/95 pb-[env(safe-area-inset-bottom)] backdrop-blur lg:hidden"
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
                  actif ? "text-brand-gold-dark" : "text-muted-foreground",
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
                    className="absolute inset-x-4 top-0 h-0.5 rounded-full bg-brand-gold"
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
