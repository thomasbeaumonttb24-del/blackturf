"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { LayoutDashboard, CalendarDays, Star, Trophy, Wallet } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { cn } from "@/lib/utils";

const ITEMS = [
  { href: "/dashboard", label: "Accueil", icon: LayoutDashboard },
  { href: "/programme", label: "Programme", icon: CalendarDays },
  { href: "/value-bets", label: "Value bets", icon: Star },
  { href: "/track-record", label: "Palmarès", icon: Trophy },
  { href: "/bankroll", label: "Capital", icon: Wallet },
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
        {ITEMS.map(({ href, label, icon: Icon }) => {
          const active = pathname === href || pathname.startsWith(href + "/");
          return (
            <Link
              key={href}
              href={href}
              aria-current={active ? "page" : undefined}
              className={cn(
                "flex flex-col items-center justify-center gap-0.5 py-2 min-h-[52px]",
                active ? "text-brand-gold" : "text-muted-foreground"
              )}
            >
              <Icon className="h-5 w-5" strokeWidth={active ? 2.4 : 1.8} />
              <span className={cn("text-[10px] leading-none", active && "font-bold")}>
                {label}
              </span>
            </Link>
          );
        })}
      </div>
    </nav>
  );
}
