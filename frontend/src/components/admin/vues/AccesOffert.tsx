"use client";

/**
 * Offrir un accès Standard / Expert à un compte (gagnant du jeu concours, geste
 * commercial). Le don est journalisé et respecté par tous les recalculs de plan
 * côté Stripe ; à la date de fin, le compte retrouve seul le plan que ses
 * abonnements justifient.
 */

import * as React from "react";
import { Gift, Loader2 } from "lucide-react";
import { toast } from "sonner";
import { adminApi } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import type { UserDetail } from "../types";

const DUREES: Array<{ label: string; jours: number | null }> = [
  { label: "1 mois", jours: 30 },
  { label: "3 mois", jours: 90 },
  { label: "6 mois", jours: 180 },
  { label: "1 an", jours: 365 },
  { label: "Sans fin", jours: null },
];

export default function AccesOffert({ data, onChange }: { data: UserDetail; onChange: () => void }) {
  const don = data.acces_offert;
  const [plan, setPlan] = React.useState<"expert" | "standard">("expert");
  const [jours, setJours] = React.useState<number | null>(30);
  const [motif, setMotif] = React.useState("");
  const [enCours, setEnCours] = React.useState(false);

  async function offrir() {
    const duree = DUREES.find((d) => d.jours === jours)?.label ?? "";
    if (!window.confirm(`Offrir ${plan === "expert" ? "Expert" : "Standard"} (${duree}) à ${data.user.email} ?`)) return;
    setEnCours(true);
    try {
      await adminApi.offrirAcces(data.user.user_id, { plan, jours, motif: motif.trim() || undefined });
      toast.success("Accès offert");
      setMotif("");
      onChange();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Impossible d'offrir l'accès");
    } finally {
      setEnCours(false);
    }
  }

  async function retirer() {
    if (!window.confirm(`Retirer l'accès offert à ${data.user.email} ? Il garde ce que paie son abonnement éventuel.`)) return;
    setEnCours(true);
    try {
      await adminApi.retirerAcces(data.user.user_id);
      toast.success("Accès offert retiré");
      onChange();
    } catch {
      toast.error("Impossible de retirer l'accès");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <section>
      <h3 className="mb-2 flex items-center gap-2 text-[13px] font-semibold">
        <Gift className="h-4 w-4 text-[#6b5b95]" aria-hidden /> Accès offert
      </h3>
      <div className="space-y-3 rounded-xl border border-border p-3 text-xs">
        {don?.actif ? (
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div>
              <b className="font-semibold">{don.plan === "expert" ? "Expert" : "Standard"} offert</b>
              <span className="text-muted-foreground">
                {" "}· {don.jusqu_au ? `jusqu'au ${formatDateTime(don.jusqu_au)}` : "sans date de fin"}
                {don.motif ? ` · ${don.motif}` : ""}
              </span>
            </div>
            <button
              type="button" onClick={retirer} disabled={enCours}
              className="rounded-lg border border-border px-2.5 py-1 font-medium text-destructive hover:bg-muted disabled:opacity-60"
            >
              Retirer
            </button>
          </div>
        ) : (
          <p className="text-muted-foreground">
            Aucun accès offert en cours{don && !don.actif && don.jusqu_au ? ` (le dernier a pris fin le ${formatDateTime(don.jusqu_au)})` : ""}.
          </p>
        )}

        <div className="flex flex-wrap items-end gap-2 border-t border-border pt-3">
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Formule</span>
            <select value={plan} onChange={(e) => setPlan(e.target.value as "expert" | "standard")}
              className="h-8 rounded-lg border border-border bg-white px-2">
              <option value="expert">Expert</option>
              <option value="standard">Standard</option>
            </select>
          </label>
          <label className="flex flex-col gap-1">
            <span className="text-muted-foreground">Durée</span>
            <select value={jours ?? ""} onChange={(e) => setJours(e.target.value ? Number(e.target.value) : null)}
              className="h-8 rounded-lg border border-border bg-white px-2">
              {DUREES.map((d) => <option key={d.label} value={d.jours ?? ""}>{d.label}</option>)}
            </select>
          </label>
          <label className="flex min-w-[10rem] flex-1 flex-col gap-1">
            <span className="text-muted-foreground">Motif (visible par vous seul)</span>
            <input value={motif} onChange={(e) => setMotif(e.target.value)} maxLength={200}
              placeholder="Gagnant du défi d'octobre" className="h-8 rounded-lg border border-border bg-white px-2" />
          </label>
          <button
            type="button" onClick={offrir} disabled={enCours}
            className="inline-flex h-8 items-center gap-1.5 rounded-lg bg-[#1b2230] px-3 font-medium text-white hover:bg-[#2c3547] disabled:opacity-60"
          >
            {enCours && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            {don?.actif ? "Remplacer" : "Offrir"}
          </button>
        </div>
        {data.user.stripe_client && (
          <p className="text-[11px] text-muted-foreground">
            Ce compte a un client Stripe : un abonnement payant éventuel continue d&apos;être
            prélevé. Pour un mois vraiment gratuit à un abonné, préférez un avoir Stripe.
          </p>
        )}
      </div>
    </section>
  );
}
