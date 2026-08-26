"use client";
export const dynamic = "force-dynamic";

import { useState, useEffect, useCallback, Suspense } from "react";
import { useSearchParams, useRouter } from "next/navigation";
import { Search, User, MapPin, Clock, Loader2, ArrowRight } from "lucide-react";
import Link from "next/link";
import useSWR from "swr";
import { cn } from "@/lib/utils";
import { api } from "@/lib/api";

type SearchResult = {
  type: "cheval" | "jockey" | "hippodrome" | "course";
  id: string;
  label: string;
  sub: string;
  running_style?: string;
};

const TYPE_CONFIG: Record<string, { icon: React.ElementType; color: string; bg: string; label: string; link: (id: string) => string }> = {
  cheval:     { icon: Search, color: "text-amber-700",  bg: "bg-amber-50",  label: "Chevaux",     link: (id) => `/chevaux/${id}` },
  jockey:     { icon: User,   color: "text-blue-700",   bg: "bg-blue-50",   label: "Jockeys",     link: (id) => `/jockeys/${id}` },
  hippodrome: { icon: MapPin, color: "text-green-700",  bg: "bg-green-50",  label: "Hippodromes", link: (id) => `/programme?hippodrome=${encodeURIComponent(id)}` },
  course:     { icon: Clock,  color: "text-purple-700", bg: "bg-purple-50", label: "Courses",     link: (id) => `/courses/${id}` },
};

const RUNNING_STYLE_EMOJIS: Record<string, string> = {
  mene: "🔴", suit_tete: "🟠", placier: "🔵", ferme: "🟢", irregulier: "⚪"
};

const fetcher = (url: string) => api.get(url).then((r) => r.data);

function RechercheContent() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const [q, setQ] = useState(searchParams.get("q") || "");
  const [debouncedQ, setDebouncedQ] = useState(q);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedQ(q), 300);
    return () => clearTimeout(t);
  }, [q]);

  const { data, isLoading } = useSWR<SearchResult[]>(
    debouncedQ.length >= 2 ? `/recherche?q=${encodeURIComponent(debouncedQ)}&limit=20` : null,
    fetcher,
    { dedupingInterval: 500 },
  );

  // Grouper par type
  const grouped = data ? data.reduce((acc, r) => {
    if (!acc[r.type]) acc[r.type] = [];
    acc[r.type].push(r);
    return acc;
  }, {} as Record<string, SearchResult[]>) : {};

  const hasResults = data && data.length > 0;

  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-8">
      {/* Search input */}
      <div className="relative mb-8">
        <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-5 w-5 text-gray-600" />
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Rechercher un cheval, jockey, hippodrome..."
          className="w-full rounded-2xl border border-gray-200 bg-white pl-12 pr-4 py-4 text-base shadow-sm outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100 transition-all"
        />
        {isLoading && (
          <Loader2 className="absolute right-4 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-600 animate-spin" />
        )}
      </div>

      {/* Results */}
      {debouncedQ.length < 2 ? (
        <div className="text-center py-16 text-gray-600">
          <Search className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Tape au moins 2 caractères pour lancer la recherche</p>
          <p className="text-xs mt-1">Raccourci : ⌘K depuis n'importe quelle page</p>
        </div>
      ) : !hasResults && !isLoading ? (
        <div className="text-center py-16 text-gray-600">
          <Search className="h-10 w-10 mx-auto mb-3 opacity-30" />
          <p className="text-sm">Aucun résultat pour <strong>"{debouncedQ}"</strong></p>
        </div>
      ) : (
        <div className="space-y-6">
          {Object.entries(grouped).map(([type, items]) => {
            const cfg = TYPE_CONFIG[type];
            if (!cfg) return null;
            const Icon = cfg.icon;
            return (
              <div key={type}>
                <div className="flex items-center gap-2 mb-3">
                  <span className={cn("inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-semibold", cfg.bg, cfg.color)}>
                    <Icon className="h-3 w-3" />
                    {cfg.label}
                  </span>
                  <span className="text-xs text-gray-600">{items.length} résultat{items.length > 1 ? "s" : ""}</span>
                </div>
                <div className="space-y-1">
                  {items.map((r) => (
                    <Link
                      key={r.id}
                      href={cfg.link(r.id)}
                      className="flex items-center gap-3 rounded-xl border border-gray-100 bg-white px-4 py-3 hover:border-amber-200 hover:bg-amber-50/30 transition-all group"
                    >
                      <div className={cn("h-9 w-9 rounded-xl flex items-center justify-center flex-shrink-0", cfg.bg)}>
                        <Icon className={cn("h-4 w-4", cfg.color)} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="font-semibold text-gray-900 truncate">{r.label}</span>
                          {r.running_style && RUNNING_STYLE_EMOJIS[r.running_style] && (
                            <span title={r.running_style} className="text-sm">
                              {RUNNING_STYLE_EMOJIS[r.running_style]}
                            </span>
                          )}
                        </div>
                        <p className="text-xs text-gray-600 truncate mt-0.5">{r.sub}</p>
                      </div>
                      <ArrowRight className="h-4 w-4 text-gray-300 opacity-0 group-hover:opacity-100 flex-shrink-0 transition-opacity" />
                    </Link>
                  ))}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export default function RecherchePage() {
  return (
    <Suspense fallback={null}>
      <RechercheContent />
    </Suspense>
  );
}
