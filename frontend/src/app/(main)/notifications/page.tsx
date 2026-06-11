"use client";

import { useState, useCallback } from "react";
import useSWR from "swr";
import Link from "next/link";
import { toast } from "sonner";
import { formatDistanceToNow, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import {
  Bell, Zap, Trophy, Info, CheckCheck, ChevronRight,
  BellOff, Settings2, ToggleLeft, ToggleRight,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useRequireAuth } from "@/hooks/useAuth";
import { notificationsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

// ─── Types ───────────────────────────────────────────────────
interface NotifItem {
  alerte_id: string;
  type_alerte: string;
  canal: string;
  lue: boolean;
  envoye: boolean;
  created_at: string | null;
  titre: string;
  description: string;
  course_id: string | null;
  cheval: string | null;
  niveau: number | null;
}

interface NotifsResponse {
  items: NotifItem[];
  total_unread: number;
  page: number;
  limit: number;
}

interface Prefs {
  vb_niveau_min: number;
  resultats_suivis: boolean;
  alertes_systeme: boolean;
}

// ─── Helpers ─────────────────────────────────────────────────
type FilterTab = "tous" | "value_bet" | "resultat" | "systeme";

const TAB_LABELS: Record<FilterTab, string> = {
  tous: "Tous",
  value_bet: "Paris de valeur",
  resultat: "Résultats",
  systeme: "Système",
};

function typeCategory(type: string): FilterTab {
  if (type.includes("value_bet") || type.includes("vb")) return "value_bet";
  if (type.includes("resultat") || type.includes("course")) return "resultat";
  return "systeme";
}

function NotifIcon({ type }: { type: string }) {
  const cat = typeCategory(type);
  if (cat === "value_bet") return <Zap className="w-4 h-4 text-amber-600" />;
  if (cat === "resultat") return <Trophy className="w-4 h-4 text-emerald-600" />;
  return <Info className="w-4 h-4 text-blue-600" />;
}

function timeAgo(dateStr: string | null): string {
  if (!dateStr) return "";
  try {
    return formatDistanceToNow(parseISO(dateStr), { addSuffix: true, locale: fr });
  } catch {
    return "";
  }
}

// ─── Toggle switch ────────────────────────────────────────────
function ToggleSwitch({
  checked, onChange, label, description,
}: {
  checked: boolean; onChange: (v: boolean) => void; label: string; description?: string;
}) {
  return (
    <button
      onClick={() => onChange(!checked)}
      className="flex items-start gap-3 w-full text-left group"
    >
      <div className="mt-0.5 shrink-0">
        {checked
          ? <ToggleRight className="w-8 h-8 text-amber-600 transition-colors" />
          : <ToggleLeft className="w-8 h-8 text-muted-foreground transition-colors group-hover:text-muted-foreground/70" />
        }
      </div>
      <div>
        <div className="text-sm font-medium text-foreground">{label}</div>
        {description && (
          <div className="text-xs text-muted-foreground mt-0.5">{description}</div>
        )}
      </div>
    </button>
  );
}

// ─── Main page ────────────────────────────────────────────────
export default function NotificationsPage() {
  useRequireAuth();

  const [tab, setTab] = useState<FilterTab>("tous");
  const [savingPrefs, setSavingPrefs] = useState(false);
  const [markingAll, setMarkingAll] = useState(false);

  // Notifications list
  const {
    data: notifs,
    mutate: mutateNotifs,
    isLoading,
  } = useSWR<NotifsResponse>(
    "notifications",
    () => notificationsApi.list().then((r) => r.data),
    { refreshInterval: 30_000 }
  );

  // Prefs
  const {
    data: prefs,
    mutate: mutatePrefs,
  } = useSWR<Prefs>(
    "notif-prefs",
    () => notificationsApi.getPrefs().then((r) => r.data)
  );

  // ── Actions ─────────────────────────────────────────────────

  const markRead = useCallback(async (id: string) => {
    try {
      await notificationsApi.markRead(id);
      await mutateNotifs();
    } catch {
      // silent — optimistic UI
    }
  }, [mutateNotifs]);

  const markAllRead = useCallback(async () => {
    setMarkingAll(true);
    try {
      await notificationsApi.markAllRead();
      await mutateNotifs();
      toast.success("Toutes les notifications marquées comme lues");
    } catch {
      toast.error("Erreur lors du marquage");
    } finally {
      setMarkingAll(false);
    }
  }, [mutateNotifs]);

  const updatePref = useCallback(async (patch: Partial<Prefs>) => {
    if (!prefs) return;
    const next = { ...prefs, ...patch };
    mutatePrefs(next, false);
    setSavingPrefs(true);
    try {
      await notificationsApi.updatePrefs(patch);
    } catch {
      mutatePrefs(prefs, false);
      toast.error("Erreur lors de la mise à jour");
    } finally {
      setSavingPrefs(false);
    }
  }, [prefs, mutatePrefs]);

  // ── Filter ──────────────────────────────────────────────────
  const items = notifs?.items ?? [];
  const filtered = tab === "tous"
    ? items
    : items.filter((n) => typeCategory(n.type_alerte) === tab);

  const unread = notifs?.total_unread ?? 0;

  return (
    <div className="min-h-screen bg-background">
      <div className="max-w-3xl mx-auto px-4 py-8 space-y-6">

        {/* ── Header ────────────────────────────── */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
              <Bell className="w-6 h-6 text-amber-600" />
              Notifications
              {unread > 0 && (
                <Badge className="bg-amber-500 text-white text-xs px-2 py-0.5 ml-1">
                  {unread}
                </Badge>
              )}
            </h1>
            <p className="text-sm text-muted-foreground mt-0.5">
              {unread > 0 ? `${unread} non lue${unread > 1 ? "s" : ""}` : "Tout est lu"}
            </p>
          </div>
          {unread > 0 && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 text-xs"
              onClick={markAllRead}
              disabled={markingAll}
            >
              <CheckCheck className="w-3.5 h-3.5" />
              {markingAll ? "En cours…" : "Tout marquer lu"}
            </Button>
          )}
        </div>

        {/* ── Filter tabs ───────────────────────── */}
        <div className="flex items-center gap-1 p-1 rounded-xl bg-muted/50 border border-border/40 w-fit">
          {(Object.keys(TAB_LABELS) as FilterTab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              className={cn(
                "px-3 py-1.5 rounded-lg text-xs font-medium transition-all",
                tab === t
                  ? "bg-white text-foreground shadow-sm border border-border/40"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {TAB_LABELS[t]}
            </button>
          ))}
        </div>

        {/* ── Notifications list ────────────────── */}
        <div className="space-y-2">
          {isLoading && (
            <div className="py-12 text-center text-sm text-muted-foreground animate-pulse">
              Chargement…
            </div>
          )}

          {!isLoading && filtered.length === 0 && (
            <div className="py-16 flex flex-col items-center gap-3 text-center">
              <div className="p-4 rounded-full bg-muted/50">
                <BellOff className="w-8 h-8 text-muted-foreground" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground">Aucune notification</p>
                <p className="text-xs text-muted-foreground mt-1">
                  {tab === "tous"
                    ? "Vous recevrez des alertes ici dès qu'un pari de valeur ou un résultat arrive."
                    : `Aucune notification de type "${TAB_LABELS[tab]}".`}
                </p>
              </div>
            </div>
          )}

          {filtered.map((n) => (
            <div
              key={n.alerte_id}
              onClick={() => !n.lue && markRead(n.alerte_id)}
              className={cn(
                "relative flex items-start gap-3 p-4 rounded-xl border transition-all cursor-pointer",
                n.lue
                  ? "border-border/40 bg-card/50 hover:bg-accent/20"
                  : "border-amber-500/30 bg-amber-500/5 hover:bg-amber-500/10"
              )}
            >
              {/* Unread dot */}
              {!n.lue && (
                <span className="absolute top-4 right-4 w-2 h-2 rounded-full bg-amber-500 shrink-0" />
              )}

              {/* Icon */}
              <div className={cn(
                "mt-0.5 p-2 rounded-lg shrink-0",
                typeCategory(n.type_alerte) === "value_bet" ? "bg-amber-50" :
                typeCategory(n.type_alerte) === "resultat" ? "bg-emerald-50" :
                "bg-blue-50"
              )}>
                <NotifIcon type={n.type_alerte} />
              </div>

              {/* Body */}
              <div className="flex-1 min-w-0">
                <div className="flex items-start justify-between gap-2">
                  <p className={cn(
                    "text-sm leading-snug",
                    n.lue ? "text-foreground font-normal" : "text-foreground font-semibold"
                  )}>
                    {n.titre}
                  </p>
                  <span className="text-[10px] text-muted-foreground shrink-0 mt-0.5">
                    {timeAgo(n.created_at)}
                  </span>
                </div>
                {n.description && (
                  <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                    {n.description}
                  </p>
                )}
                {n.course_id && (
                  <Link
                    href={`/courses/${n.course_id}`}
                    onClick={(e) => e.stopPropagation()}
                    className="inline-flex items-center gap-1 text-xs text-amber-600 hover:text-amber-700 mt-1.5 transition-colors"
                  >
                    Voir la course <ChevronRight className="w-3 h-3" />
                  </Link>
                )}
              </div>
            </div>
          ))}
        </div>

        {/* ── Push preferences ──────────────────── */}
        <Card className="border-border/60">
          <CardHeader className="pb-3">
            <CardTitle className="text-base flex items-center gap-2">
              <Settings2 className="w-4 h-4 text-muted-foreground" />
              Préférences de notifications
              {savingPrefs && (
                <span className="text-xs text-muted-foreground font-normal ml-auto">
                  Sauvegarde…
                </span>
              )}
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-5">

            {/* VB niveau min */}
            <div>
              <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
                Paris de valeur
              </div>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                {([1, 2, 3, 4] as const).map((n) => {
                  const selected = (prefs?.vb_niveau_min ?? 2) <= n;
                  const isMin = prefs?.vb_niveau_min === n;
                  return (
                    <button
                      key={n}
                      onClick={() => updatePref({ vb_niveau_min: n })}
                      className={cn(
                        "flex flex-col items-center gap-1 p-3 rounded-xl border text-xs font-medium transition-all",
                        isMin
                          ? "border-amber-500/60 bg-amber-50 text-amber-700"
                          : selected
                          ? "border-border/60 bg-card text-foreground"
                          : "border-border/30 bg-card/50 text-muted-foreground hover:border-border/60"
                      )}
                    >
                      <span className="flex gap-0.5">
                        {Array.from({ length: n }).map((_, i) => (
                          <span
                            key={i}
                            className={cn("text-[10px]",
                              isMin ? "text-amber-600" : "text-muted-foreground"
                            )}
                          >★</span>
                        ))}
                      </span>
                      <span>{n === 1 ? "1+ étoile" : `${n}+ étoiles`}</span>
                      {isMin && (
                        <Badge className="bg-amber-50 text-amber-700 border-0 text-[9px] px-1.5 py-0 h-4">
                          Actif
                        </Badge>
                      )}
                    </button>
                  );
                })}
              </div>
              <p className="text-[11px] text-muted-foreground mt-2">
                Seuil minimum : vous serez alerté pour les paris de valeur de ce niveau ou plus.
              </p>
            </div>

            <div className="h-px bg-border/40" />

            {/* Other toggles */}
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-3">
              Autres alertes
            </div>
            <div className="space-y-4">
              <ToggleSwitch
                checked={prefs?.resultats_suivis ?? true}
                onChange={(v) => updatePref({ resultats_suivis: v })}
                label="Résultats des courses suivies"
                description="Notification dès qu'une course que vous suivez est terminée"
              />
              <ToggleSwitch
                checked={prefs?.alertes_systeme ?? true}
                onChange={(v) => updatePref({ alertes_systeme: v })}
                label="Alertes système"
                description="Maintenance, mises à jour du modèle IA, informations importantes"
              />
            </div>
          </CardContent>
        </Card>

      </div>
    </div>
  );
}
