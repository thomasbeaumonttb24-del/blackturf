"use client";

/**
 * Défi du mois — clôture et remise des récompenses.
 *
 * Rien n'est automatique ici, volontairement : le serveur calcule le classement,
 * mais un humain regarde le compte avant de lui offrir un abonnement (compte créé
 * pendant le mois, adresse non confirmée…). Le serveur refuse de toute façon une
 * remise tant que le mois court ou que des paris attendent leur règlement.
 */

import { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { AlertTriangle, ArrowLeft, ChevronLeft, ChevronRight, Gift, Loader2, Medal } from "lucide-react";
import { adminApi } from "@/lib/api";
import { formatDateTime } from "@/lib/utils";
import { EnTetePage, Encart, Panneau, Puce, Squelette } from "@/components/admin/ui";
import { formatPts, moisLabel, planLabel } from "@/components/defi/kit";

interface LigneCloture {
  rang: number;
  nom: string;
  email: string;
  plan: string;
  solde: number;
  points_mises: number;
  nb_paris: number;
  nb_gagnes: number;
  roi: number | null;
  created_at: string | null;
  last_login_at: string | null;
  alertes: string[];
  recompense: { statut: string; plan_offert: string; expire_at: string } | null;
}

interface Cloture {
  mois: string;
  mois_termine: boolean;
  paris_en_attente: number;
  recompenses: { rang: number; plan: string; jours: number }[];
  lignes: LigneCloture[];
}

const STATUT_RECOMPENSE: Record<string, { txt: string; ton: "ok" | "attention" | "neutre" }> = {
  applique: { txt: "Plan offert en cours", ton: "ok" },
  manuel: { txt: "Abonné payant : geste à faire dans Stripe", ton: "attention" },
  termine: { txt: "Terminé, plan précédent rétabli", ton: "neutre" },
  conserve: { txt: "Terminé, le joueur a souscrit", ton: "ok" },
};

function moisParis(): string {
  const p = new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit" })
    .formatToParts(new Date());
  return `${p.find((x) => x.type === "year")?.value}-${p.find((x) => x.type === "month")?.value}`;
}

function decaler(mois: string, delta: number): string {
  const [a, m] = mois.split("-").map(Number);
  const d = new Date(Date.UTC(a, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

export default function AdminDefiPage() {
  const courant = useMemo(() => moisParis(), []);
  // Par défaut le mois précédent : c'est celui qu'on vient clôturer.
  const [mois, setMois] = useState(() => decaler(courant, -1));
  const [envoi, setEnvoi] = useState<number | null>(null);
  const { data, mutate, isLoading } = useSWR<Cloture>(["/admin/defi/cloture", mois],
    () => adminApi.defiCloture(mois).then((r) => r.data));

  async function recompenser(l: LigneCloture) {
    const lot = data?.recompenses.find((r) => r.rang === l.rang);
    if (!lot) return;
    if (!window.confirm(`Offrir ${lot.jours} jours ${planLabel(lot.plan)} à ${l.nom} (${l.email}), ${l.rang}${l.rang === 1 ? "er" : "e"} de ${moisLabel(mois)} ?\n\nVérifiez le compte avant : cette action notifie le joueur.`)) return;
    setEnvoi(l.rang);
    try {
      const { data: r } = await adminApi.defiRecompense(mois, l.rang);
      toast.success(r.statut === "manuel"
        ? "Enregistré. Abonné payant : appliquez le mois offert dans Stripe."
        : `${planLabel(r.plan_offert)} offert jusqu'au ${formatDateTime(r.expire_at)}.`);
      await mutate();
    } catch (e) {
      const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
      toast.error(typeof d === "string" ? d : "Remise impossible.");
    } finally {
      setEnvoi(null);
    }
  }

  return (
    <div className="space-y-5">
      <Link href="/admin/comptes" className="inline-flex items-center gap-1 text-[13px] font-medium text-muted-foreground hover:text-foreground">
        <ArrowLeft className="h-4 w-4" /> Comptes
      </Link>
      <EnTetePage
        titre="Défi du mois"
        icone={<Medal className="h-4 w-4" />}
        desc="Vérifiez les premiers du mois clos, puis remettez les récompenses. Le plan offert expire tout seul et le plan précédent revient, sauf si le joueur a souscrit entre-temps."
        actions={
          <div className="flex items-center gap-1 rounded-xl border border-border p-1">
            <button type="button" aria-label="Mois précédent" onClick={() => setMois(decaler(mois, -1))}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted"><ChevronLeft className="h-4 w-4" /></button>
            <span className="min-w-[120px] text-center text-[13px] font-semibold">{moisLabel(mois)}</span>
            <button type="button" aria-label="Mois suivant" disabled={mois >= courant} onClick={() => setMois(decaler(mois, 1))}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg hover:bg-muted disabled:opacity-30"><ChevronRight className="h-4 w-4" /></button>
          </div>
        }
      />

      {data && !data.mois_termine && (
        <Encart ton="attention" icone={<AlertTriangle className="h-4 w-4" />}>
          Mois en cours : le classement bouge encore, aucune récompense ne peut être remise.
        </Encart>
      )}
      {data && data.mois_termine && data.paris_en_attente > 0 && (
        <Encart ton="attention" icone={<AlertTriangle className="h-4 w-4" />}>
          {data.paris_en_attente} pari(s) attendent encore leur règlement (rapport PMU non publié). Les récompenses se débloquent quand ils sont réglés.
        </Encart>
      )}

      <Panneau titre="Top 10 du mois" desc="Joueurs classés uniquement (minimum de paris atteint, comptes admin et suspendus exclus).">
        {isLoading || !data ? <div className="p-5"><Squelette lignes={5} /></div> : data.lignes.length === 0 ? (
          <p className="p-5 text-[13px] text-muted-foreground">Aucun joueur classé ce mois-ci.</p>
        ) : (
          <ul className="divide-y divide-border/60">
            {data.lignes.map((l) => {
              const lot = data.recompenses.find((r) => r.rang === l.rang);
              const st = l.recompense ? STATUT_RECOMPENSE[l.recompense.statut] : null;
              return (
                <li key={l.rang} className="flex flex-col gap-3 px-4 py-4 sm:flex-row sm:items-center sm:justify-between sm:px-5">
                  <div className="min-w-0 space-y-1">
                    <div className="flex flex-wrap items-center gap-2 text-[14px] font-semibold">
                      <span className="tabular-nums">{l.rang}.</span> {l.nom}
                      <span className="font-normal text-muted-foreground">{l.email}</span>
                    </div>
                    <div className="text-[12px] tabular-nums text-muted-foreground">
                      {formatPts(l.solde)} · {l.nb_paris} paris ({formatPts(l.points_mises)} misés) · {l.nb_gagnes} gagnés · plan {l.plan}
                      {l.created_at && <> · inscrit le {formatDateTime(l.created_at)}</>}
                      {l.last_login_at && <> · vu le {formatDateTime(l.last_login_at)}</>}
                    </div>
                    <div className="flex flex-wrap gap-1.5">
                      {l.alertes.map((a) => <Puce key={a} ton="attention">{a}</Puce>)}
                      {st && <Puce ton={st.ton}>{st.txt}</Puce>}
                    </div>
                  </div>
                  {lot && !l.recompense && (
                    <button type="button" onClick={() => recompenser(l)}
                      disabled={!data.mois_termine || data.paris_en_attente > 0 || envoi !== null}
                      className="inline-flex min-h-[2.75rem] shrink-0 items-center justify-center gap-2 rounded-xl bg-brand-gold px-4 text-[13px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">
                      {envoi === l.rang ? <Loader2 className="h-4 w-4 animate-spin" /> : <Gift className="h-4 w-4" />}
                      Offrir {lot.jours} j {planLabel(lot.plan)}
                    </button>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </Panneau>

      <Encart>
        Un compte frauduleux (multi-comptes, automatisation) se suspend depuis sa fiche dans « Comptes » : il sort aussitôt du classement et le suivant remonte.
      </Encart>
    </div>
  );
}
