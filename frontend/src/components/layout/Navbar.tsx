"use client";

import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useState, useEffect, useRef, useCallback } from "react";
import useSWR from "swr";
import { LucideIcon, Menu, X, Bell, User, LogOut, ChevronDown, Zap, LayoutDashboard, Gauge, Search, BarChart2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/hooks/useAuth";
import { useAlertesStream } from "@/hooks/useWebSocket";
import { notificationsApi } from "@/lib/api";
import { planLabel, cn } from "@/lib/utils";

/**
 * `prive` → `rel="nofollow"`, même raison qu'au pied de page : ces destinations sont
 * soit interdites d'exploration par robots.txt (`/assistant`, `/bankroll`), soit en
 * `noindex` (`/value-bets`). Les lier depuis la barre de navigation de CHAQUE page, sans
 * marque, revient à insister auprès de Google sur des adresses qu'il n'a pas le droit de
 * lire — c'est ainsi qu'une URL finit « indexée malgré le blocage », sans contenu.
 */
type NavLink = { href: string; label: string; icon?: LucideIcon; prive?: boolean };

const NAV_LINKS_PUBLIC: NavLink[] = [
  { href: "/programme", label: "Programme" },
  { href: "/quinte-du-jour", label: "Quinté+" },
  { href: "/resultats", label: "Résultats" },
  { href: "/value-bets", label: "Paris de valeur", prive: true },
  { href: "/track-record", label: "Palmarès" },
  { href: "/assistant", label: "Assistant IA", prive: true },
  { href: "/tarifs", label: "Tarifs" },
];

// Jamais rendu pour un visiteur anonyme — donc jamais vu par un robot — mais marqué de
// la même façon pour que les deux listes ne divergent pas.
const NAV_LINKS_AUTH: NavLink[] = [
  { href: "/dashboard", label: "Tableau de bord", icon: LayoutDashboard, prive: true },
  { href: "/programme", label: "Programme" },
  { href: "/value-bets", label: "Paris de valeur", prive: true },
  { href: "/track-record", label: "Palmarès" },
  { href: "/bankroll", label: "Capital", prive: true },
  { href: "/assistant", label: "Assistant IA", prive: true },
];

// ── Search palette ──────────────────────────────────────────────────────────
function SearchPalette({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const { data: results } = useSWR(
    debouncedQ.length >= 2 ? `/api/v1/recherche?q=${encodeURIComponent(debouncedQ)}&limit=8` : null,
    (url) => fetch(url).then((r) => r.json()),
    { dedupingInterval: 500 },
  );

  const TYPE_ICONS: Record<string, string> = { cheval: "🐴", jockey: "👤", hippodrome: "📍", course: "🏇" };
  const TYPE_LINKS: Record<string, (id: string) => string> = {
    cheval: (id) => `/chevaux/${id}`,
    jockey: (id) => `/jockeys/${id}`,
    hippodrome: (id) => `/programme?hippodrome=${encodeURIComponent(id)}`,
    course: (id) => `/courses/${id}`,
  };

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-[200] bg-black/40 backdrop-blur-sm flex items-start justify-center pt-16 px-4" onClick={onClose}>
      <div className="w-full max-w-xl rounded-2xl bg-white shadow-2xl overflow-hidden" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center gap-3 px-4 py-3 border-b border-gray-100">
          <Search className="h-4 w-4 text-gray-600 flex-shrink-0" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Rechercher un cheval, jockey, hippodrome..."
            className="flex-1 outline-none text-sm bg-transparent text-gray-900 placeholder-gray-400"
          />
          <kbd className="text-[10px] text-gray-600 bg-gray-100 rounded px-1.5 py-0.5">Esc</kbd>
        </div>
        {results && results.length > 0 ? (
          <ul className="py-2 max-h-80 overflow-y-auto">
            {results.map((r: { type: string; id: string; label: string; sub: string }, i: number) => (
              <li key={i}>
                <button
                  className="w-full flex items-center gap-3 px-4 py-2.5 hover:bg-gray-50 text-left transition-colors"
                  onClick={() => { router.push(TYPE_LINKS[r.type]?.(r.id) ?? "/"); onClose(); }}
                >
                  <span className="text-base flex-shrink-0">{TYPE_ICONS[r.type] ?? "🔍"}</span>
                  <div className="min-w-0">
                    <div className="text-sm font-medium text-gray-900 truncate">{r.label}</div>
                    <div className="text-xs text-gray-600 truncate">{r.sub}</div>
                  </div>
                </button>
              </li>
            ))}
          </ul>
        ) : debouncedQ.length >= 2 ? (
          <div className="py-8 text-center text-sm text-gray-600">Aucun résultat pour "{debouncedQ}"</div>
        ) : (
          <div className="py-6 text-center text-xs text-gray-600">Saisissez au moins 2 caractères</div>
        )}
      </div>
    </div>
  );
}

export function Navbar() {
  const pathname = usePathname();
  const router = useRouter();
  const { user, logout } = useAuth();
  const [menuOpen, setMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [searchOpen, setSearchOpen] = useState(false);

  // Thème CLAIR forcé : on retire toute classe "dark" persistée (ancien toggle).
  // Le design BlackTurf est blanc premium + or — pas de mode sombre.
  useEffect(() => {
    document.documentElement.classList.remove("dark");
    try { localStorage.removeItem("blackturf-dark"); } catch {}
  }, []);

  // Keyboard shortcut ⌘K / Ctrl+K
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "k") {
        e.preventDefault();
        setSearchOpen((v) => !v);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  // Compteur de notifications non lues. Passe par le client axios (`notificationsApi`)
  // et non par un `fetch` d'URL relative : l'API vit sur un autre hôte
  // (api.blackturf.fr) et c'est le client axios qui porte la baseURL, le
  // rafraîchissement de jeton et l'en-tête Authorization.
  const { data: notifData, mutate: mutateNotifCount } = useSWR(
    user ? "notif-count-unread" : null,
    () => notificationsApi.countUnread().then((r) => r.data as { count: number }),
    { refreshInterval: 60000 },
  );

  // Alerte poussée en direct (WS `/ws/user/alertes`) → le badge monte immédiatement
  // au lieu d'attendre le prochain sondage de 60 s. Le canal existait côté backend
  // depuis le début mais AUCUN écran ne s'y abonnait.
  const { alertes } = useAlertesStream(!!user);
  const nbAlertesWs = alertes.length;
  useEffect(() => {
    if (nbAlertesWs > 0) mutateNotifCount();
  }, [nbAlertesWs, mutateNotifCount]);

  const nbNonLues = notifData?.count ?? 0;

  return (
    <nav className="sticky top-0 z-50 border-b border-border bg-white/90 backdrop-blur-md shadow-sm shadow-black/[0.04]">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="flex h-16 items-center justify-between">

          {/* Logo */}
          <Link href="/" className="flex items-center gap-2 flex-shrink-0" aria-label="BlackTurf — Accueil">
            <Image
              src="/logo.png"
              alt="BlackTurf"
              width={52}
              height={52}
              className="h-12 w-12 sm:h-[52px] sm:w-[52px] object-contain"
              priority
            />
            <span className="text-xl font-bold tracking-tight text-gray-900">
              Black<span className="text-brand-gold-dark">Turf</span>
            </span>
          </Link>

          {/* Desktop nav */}
          <div className="hidden md:flex items-center gap-0.5">
            {(user ? NAV_LINKS_AUTH : NAV_LINKS_PUBLIC).map((link) => {
              const Icon = (link as { icon?: LucideIcon }).icon;
              return (
                <Link
                  key={link.href}
                  href={link.href}
                  rel={link.prive ? "nofollow" : undefined}
                  className={cn(
                    "relative px-3.5 py-2 rounded-lg text-sm font-medium transition-all duration-150 flex items-center gap-1.5",
                    "after:absolute after:left-3.5 after:right-3.5 after:-bottom-0.5 after:h-0.5 after:rounded-full after:bg-gradient-gold after:transition-transform after:duration-200 after:origin-left",
                    pathname === link.href
                      ? "text-brand-gold-dark font-semibold after:scale-x-100"
                      : "text-gray-600 hover:text-gray-900 after:scale-x-0 hover:after:scale-x-100"
                  )}
                >
                  {Icon && <Icon className="h-3.5 w-3.5" />}
                  {link.label}
                </Link>
              );
            })}
          </div>

          {/* Right side */}
          <div className="flex items-center gap-1.5">
            {/* Search button (tous) */}
            <Button
              variant="ghost"
              size="icon"
              className="text-gray-600 hover:text-gray-800 hover:bg-gray-100"
              onClick={() => setSearchOpen(true)}
              aria-label="Rechercher (⌘K)"
            >
              <Search className="h-4 w-4" />
            </Button>

            {/* Dark mode toggle */}

            {searchOpen && <SearchPalette onClose={() => setSearchOpen(false)} />}

            {user ? (
              <>
                {/* Alerts bell with unread count */}
                <Button
                  variant="ghost"
                  size="icon"
                  className="relative text-gray-600 hover:text-gray-800 hover:bg-gray-100"
                  aria-label="Notifications"
                  onClick={() => router.push("/notifications")}
                >
                  <Bell className="h-4 w-4" />
                  {nbNonLues > 0 && (
                    <span className="absolute -top-0.5 -right-0.5 h-4 w-4 rounded-full bg-amber-500 text-[9px] font-bold text-brand-dark flex items-center justify-center">
                      {nbNonLues > 9 ? "9+" : nbNonLues}
                    </span>
                  )}
                </Button>

                {/* User menu */}
                <div className="relative">
                  <button
                    onClick={() => setUserMenuOpen(!userMenuOpen)}
                    className="flex items-center gap-2 rounded-xl border border-gray-200 bg-white px-3 py-1.5 text-sm hover:border-brand-gold/40 hover:bg-brand-gold-tint/50 transition-all"
                    aria-expanded={userMenuOpen}
                    aria-haspopup="true"
                  >
                    <div className="h-6 w-6 rounded-full bg-brand-gold-tint flex items-center justify-center ring-1 ring-brand-gold/30">
                      <User className="h-3 w-3 text-brand-gold-dark" />
                    </div>
                    <span className="hidden sm:block max-w-[100px] truncate text-gray-700 font-medium">
                      {user.prenom || user.email.split("@")[0]}
                    </span>
                    <Badge
                      variant={
                        user.plan === "expert"
                          ? "expert"
                          : ["starter", "standard"].includes(user.plan)
                          ? "gold"
                          : "secondary"
                      }
                      className="hidden sm:flex text-[10px] px-1.5 py-0"
                    >
                      {planLabel(user.plan)}
                    </Badge>
                    <ChevronDown className="h-3 w-3 text-gray-600" />
                  </button>

                  {userMenuOpen && (
                    <div className="absolute right-0 top-11 w-48 rounded-2xl border border-gray-200 bg-white shadow-xl shadow-black/10 z-50">
                      <div className="p-1.5">
                        <Link
                          href="/profil"
                          className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                          onClick={() => setUserMenuOpen(false)}
                        >
                          <User className="h-4 w-4 text-gray-600" /> Mon profil
                        </Link>
                        <Link
                          href="/statistiques"
                          className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                          onClick={() => setUserMenuOpen(false)}
                        >
                          <BarChart2 className="h-4 w-4 text-blue-400" /> Mes statistiques
                        </Link>
                        <Link
                          href="/notifications"
                          className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                          onClick={() => setUserMenuOpen(false)}
                        >
                          <Bell className="h-4 w-4 text-gray-600" /> Notifications
                          {nbNonLues > 0 && (
                            <span className="ml-auto h-4 w-4 rounded-full bg-amber-500 text-[9px] font-bold text-brand-dark flex items-center justify-center">
                              {nbNonLues > 9 ? "9+" : nbNonLues}
                            </span>
                          )}
                        </Link>
                        {["free", "decouverte"].includes(user.plan) && (
                          <Link
                            href="/tarifs"
                            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-brand-gold-dark font-medium hover:bg-brand-gold-tint/60 transition-colors"
                            onClick={() => setUserMenuOpen(false)}
                          >
                            <Zap className="h-4 w-4" /> Passer Standard
                          </Link>
                        )}
                        {/* Une seule porte vers l'administration.
                            « Supervision IA » était une seconde entrée vers
                            `/admin/algorithme` parce que la console n'avait
                            aucune navigation interne : les trois écrans d'admin
                            vivent hors du groupe `(main)`, donc sans la barre du
                            site, et ce menu était le seul chemin vers eux.
                            Depuis la refonte du 2026-09-05, `/admin` porte sa
                            propre navigation permanente — garder le raccourci
                            revenait à afficher deux entrées pour un seul outil,
                            dont une qui saute par-dessus l'écran d'accueil.
                            L'icône manquait par ailleurs sur « Admin », seul
                            élément nu d'un menu où tout le reste en a une. */}
                        {user.is_admin && (
                          <Link
                            href="/admin"
                            className="flex items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-gray-700 hover:bg-gray-50 transition-colors"
                            onClick={() => setUserMenuOpen(false)}
                          >
                            <Gauge className="h-4 w-4 text-brand-gold-dark" /> Administration
                          </Link>
                        )}
                        <div className="my-1 h-px bg-gray-100" />
                        <button
                          onClick={() => { setUserMenuOpen(false); logout(); }}
                          className="flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-sm text-red-700 hover:bg-red-50 transition-colors"
                        >
                          <LogOut className="h-4 w-4" /> Déconnexion
                        </button>
                      </div>
                    </div>
                  )}
                </div>
              </>
            ) : (
              <div className="hidden md:flex items-center gap-2">
                <Button
                  variant="ghost"
                  size="sm"
                  className="text-gray-600 hover:text-gray-900 hover:bg-gray-100"
                  onClick={() => router.push("/login")}
                >
                  Connexion
                </Button>
                <Button
                  size="sm"
                  className="btn-shimmer active:scale-[0.97] bg-brand-gold hover:bg-brand-gold-deep text-brand-dark font-semibold shadow-sm shadow-brand-gold/25 ring-1 ring-brand-gold/30 transition-all"
                  onClick={() => router.push("/inscription")}
                >
                  Essai gratuit
                </Button>
              </div>
            )}

            {/* Mobile hamburger */}
            <Button
              variant="ghost"
              size="icon"
              className="md:hidden text-gray-600 hover:bg-gray-100"
              onClick={() => setMenuOpen(!menuOpen)}
              aria-label={menuOpen ? "Fermer le menu" : "Ouvrir le menu"}
            >
              {menuOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </Button>
          </div>
        </div>
      </div>

      {/* Mobile menu */}
      {menuOpen && (
        <div className="md:hidden border-t border-gray-100 bg-white p-4 space-y-1 shadow-lg">
          {(user ? NAV_LINKS_AUTH : NAV_LINKS_PUBLIC).map((link) => (
            <Link
              key={link.href}
              href={link.href}
              rel={link.prive ? "nofollow" : undefined}
              className={cn(
                "block rounded-xl px-4 py-2.5 text-sm font-medium transition-colors",
                pathname === link.href
                  ? "bg-brand-gold-tint text-brand-gold-dark"
                  : "text-gray-600 hover:bg-gray-50 hover:text-gray-900"
              )}
              onClick={() => setMenuOpen(false)}
            >
              {link.label}
            </Link>
          ))}
          {!user && (
            <div className="pt-2 flex gap-2">
              <Button
                variant="ghost"
                size="sm"
                className="flex-1 text-gray-600 hover:bg-gray-100"
                onClick={() => { router.push("/login"); setMenuOpen(false); }}
              >
                Connexion
              </Button>
              <Button
                size="sm"
                className="flex-1 bg-brand-gold hover:bg-brand-gold-deep text-brand-dark font-semibold"
                onClick={() => { router.push("/inscription"); setMenuOpen(false); }}
              >
                Essai gratuit
              </Button>
            </div>
          )}
        </div>
      )}
    </nav>
  );
}
