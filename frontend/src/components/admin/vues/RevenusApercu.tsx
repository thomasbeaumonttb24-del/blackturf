"use client";

/**
 * Aperçu des revenus sur le Pilotage : la courbe des encaissements réels des six
 * derniers mois, et les prochains prélèvements. Le détail complet vit dans
 * `/admin/revenus` — ce bloc répond seulement à « ça monte ou ça descend ? » et
 * « qu'est-ce qui tombe cette semaine ? ».
 */

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Area, AreaChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BadgeFormule, Panneau, Squelette, Vide, eur, num } from "../ui";
import { useRevenus } from "../data";
import { AXE, Infobulle, PALETTE } from "../graphes";
import CompteARebours from "./CompteARebours";

const nomMois = (cle: string, long = false) => {
  const [a, m] = cle.split("-").map(Number);
  return new Date(a, m - 1, 1).toLocaleDateString("fr-FR", long ? { month: "long", year: "numeric" } : { month: "short" }).replace(".", "");
};

export default function RevenusApercu({ className }: { className?: string }) {
  const { data } = useRevenus(6);
  const points = (data?.mois ?? []).map((m) => ({
    cle: m.mois, label: nomMois(m.mois), encaisse: m.ca_cents / 100, n: m.nb_paiements,
  }));
  const prochains = (data?.echeancier ?? []).filter((e) => e.montant_cents > 0).slice(0, 5);

  return (
    <Panneau
      titre="Revenus encaissés"
      desc="6 derniers mois · factures Stripe payées"
      className={className}
      actions={
        <Link href="/admin/revenus" className="inline-flex items-center gap-1 text-xs font-medium text-[#27456b] hover:underline">
          Voir le détail <ArrowRight className="h-3.5 w-3.5" />
        </Link>
      }
    >
      {!data ? <Squelette lignes={6} /> : (
        <div className="grid gap-6 lg:grid-cols-5">
          <div className="h-[230px] lg:col-span-3">
            <ResponsiveContainer width="100%" height="100%">
              <AreaChart data={points} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                <defs>
                  <linearGradient id="apercu-aire" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="0%" stopColor={PALETTE.ardoise} stopOpacity={0.16} />
                    <stop offset="100%" stopColor={PALETTE.ardoise} stopOpacity={0.01} />
                  </linearGradient>
                </defs>
                <CartesianGrid vertical={false} />
                <XAxis dataKey="label" {...AXE} dy={6} />
                <YAxis {...AXE} width={48} tickFormatter={(v: number) => `${Math.round(v)} €`} />
                <Tooltip
                  cursor={{ stroke: PALETTE.gris, strokeDasharray: "3 3" }}
                  content={({ active, payload }) => {
                    const p = payload?.[0]?.payload as (typeof points)[number] | undefined;
                    if (!active || !p) return null;
                    return (
                      <Infobulle
                        titre={<span className="capitalize">{nomMois(p.cle, true)}</span>}
                        lignes={[{ label: "Encaissé", valeur: eur(p.encaisse, 2), couleur: PALETTE.ardoise }]}
                        pied={`${num(p.n)} paiement${p.n > 1 ? "s" : ""}`}
                      />
                    );
                  }}
                />
                <Area
                  type="monotone" dataKey="encaisse" name="Encaissé"
                  stroke={PALETTE.ardoise} strokeWidth={2} fill="url(#apercu-aire)"
                  dot={{ r: 3, fill: "#fff", stroke: PALETTE.ardoise, strokeWidth: 1.5 }}
                  activeDot={{ r: 5, fill: PALETTE.ardoise, stroke: "#fff", strokeWidth: 2 }}
                />
              </AreaChart>
            </ResponsiveContainer>
          </div>
          <div className="lg:col-span-2">
            <div className="mb-2 flex items-baseline justify-between gap-2">
              <span className="text-sm font-semibold">Prochains prélèvements</span>
              <span className="text-xs text-muted-foreground">
                {eur(data.totaux.reste_a_encaisser_mois_cents / 100)} encore attendus ce mois
              </span>
            </div>
            {prochains.length === 0 ? <Vide>Aucune échéance à venir.</Vide> : (
              <ul className="divide-y divide-border rounded-lg border border-border">
                {prochains.map((e) => (
                  <li key={e.stripe_subscription_id ?? e.user_id} className="flex items-center gap-3 px-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-2">
                        <span className="truncate text-[13px] font-medium" title={e.email}>{e.email}</span>
                        <BadgeFormule plan={e.plan} />
                      </div>
                      <CompteARebours date={e.date} jours={e.jours_restants} nature={e.nature} />
                    </div>
                    <span className="shrink-0 text-sm font-semibold tabular-nums">{eur(e.montant_cents / 100, e.montant_cents % 100 ? 2 : 0)}</span>
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
