"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, CalendarDays, Star, Trophy, Medal } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";
import { RUBRIQUES as R } from "@/lib/navigation";

// Mêmes rubriques, mêmes noms que la barre du haut (`@/lib/navigation`) : seule la
// forme courte change, faute de place sous le pouce.
const ITEMS = [
  { ...R.monEspace, icon: LayoutDashboard },
  { ...R.coursesDuJour, icon: CalendarDays },
  { ...R.parisDeValeur, icon: Star },
  { ...R.performances, icon: Trophy },
  { ...R.defi, icon: Medal },
];

/** Barre de navigation mobile (pouce) — utilisateurs connectés uniquement. */
export function BottomNav() {
  const { user } = useAuth();
  const pathname = usePathname();
  if (!user) return null;

  return (
    <nav
      className="fixed bottom-0 inset-x-0 z-40 md:hidden border-t border-border bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/85"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
      aria-label="Navigation mobile"
    >
      <div className="grid grid-cols-5">
        {ITEMS.map(({ href, label, court, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              aria-label={court !== label ? label : undefined}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 py-2 min-h-[52px]",
                active ? "text-brand-gold-dark" : "text-muted-foreground"
              )}
            >
              <Icon className="h-5 w-5" strokeWidth={active ? 2.4 : 1.8} />
              <span className={cn("text-center text-[10px] leading-tight", active && "font-bold")}>
                {court}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
