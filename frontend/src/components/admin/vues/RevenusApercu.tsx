"use client";

/**
 * Aperçu des revenus sur le Pilotage : six mois d'encaissements réels en barres
 * 3D, et les cinq prochains prélèvements. Le détail complet vit dans
 * `/admin/revenus` — ce bloc répond seulement à « ça monte ou ça descend ? »
 * et « qu'est-ce qui tombe cette semaine ? ».
 */

import Link from "next/link";
import { ArrowRight, Euro } from "lucide-react";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BadgeFormule, Initiales, Panneau, Puce, Squelette, Vide, eur } from "../ui";
import { useRevenus } from "../data";
import { InfobulleVerre, formeBarre3D } from "../relief";
import CompteARebours from "./CompteARebours";

const nomMois = (cle: string) => {
  const [a, m] = cle.split("-").map(Number);
  return new Date(a, m - 1, 1).toLocaleDateString("fr-FR", { month: "short" });
};

export default function RevenusApercu({ className }: { className?: string }) {
  const { data } = useRevenus(6);
  const points = (data?.mois ?? []).map((m) => ({ label: nomMois(m.mois), encaisse: m.encaisse_cents / 100 }));
  const prochains = (data?.echeancier ?? []).filter((e) => e.montant_cents > 0).slice(0, 5);

  return (
    <Panneau
      titre="Revenus encaissés"
      desc="6 derniers mois · factures Stripe payées"
      icone={<Euro className="h-3.5 w-3.5" />}
      ton="or"
      className={className}
      actions={
        <Link href="/admin/revenus" className="inline-flex items-center gap-1 text-xs font-semibold text-amber-300 hover:text-amber-200">
          Détail <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      }
    >
      {!data ? <Squelette lignes={6} /> : (
        <div className="grid gap-5 lg:grid-cols-5">
          <div className="h-[220px] lg:col-span-3">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={points} margin={{ top: 16, right: 4, bottom: 0, left: -12 }}>
                <CartesianGrid vertical={false} strokeDasharray="3 6" />
                <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fontSize: 11 }} />
                <YAxis tickLine={false} axisLine={false} tick={{ fontSize: 11 }} width={50} tickFormatter={(v: number) => eur(v)} />
                <Tooltip
                  cursor={{ fill: "rgba(255,255,255,0.04)" }}
                  content={(p) => <InfobulleVerre active={p.active} payload={p.payload as never} label={p.label} formatValeur={(v) => eur(v, 2)} />}
                />
                <Bar dataKey="encaisse" name="Encaissé" fill="#f5b544" maxBarSize={40} shape={formeBarre3D("#e39a1f", 9)} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="lg:col-span-2">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-white/50">Prochains prélèvements</span>
              <Puce ton="ok">{eur(data.totaux.reste_a_encaisser_mois_cents / 100)} ce mois</Puce>
            </div>
            {prochains.length === 0 ? <Vide>Aucune échéance à venir.</Vide> : (
              <ul className="space-y-2">
                {prochains.map((e) => (
                  <li key={e.stripe_subscription_id ?? e.user_id} className="flex items-center gap-3 rounded-xl border border-white/[0.06] bg-white/[0.02] p-2.5">
                    <Initiales email={e.email} />
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-medium" title={e.email}>{e.email}</span>
                        <BadgeFormule plan={e.plan} />
                      </div>
                      <CompteARebours date={e.date} jours={e.jours_restants} nature={e.nature} />
                    </div>
                    <span className="shrink-0 text-sm font-bold tabular-nums text-emerald-300">{eur(e.montant_cents / 100, e.montant_cents % 100 ? 2 : 0)}</span>
                  </li>
                ))}
              </ul>
            )}
          </div>
        </div>
      )}
    </Panneau>
  );
}
