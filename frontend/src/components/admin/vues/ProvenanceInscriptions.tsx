"use client";

/**
 * Provenance des inscriptions : ce que rapporte chaque publication ou publicité.
 *
 * La provenance est « source:campagne », lue dans les paramètres utm de la
 * première visite (cookie `bt_src`). Un lien de publicité sans utm tombe dans
 * « Direct ou inconnue », comme tous les comptes créés avant le suivi.
 */

import useSWR from "swr";
import { Megaphone } from "lucide-react";
import { adminApi } from "@/lib/api";
import { useEstAdmin, CADENCE } from "@/components/admin/data";
import { Panneau, Puce, Squelette, TD, TH, Vide, depuis, num } from "@/components/admin/ui";

type Ligne = { provenance: string | null; inscrits: number; confirmes: number; payants: number; dernier: string | null };

const taux = (n: number, sur: number) => (sur ? `${Math.round((n / sur) * 100)} %` : "—");

export default function ProvenanceInscriptions() {
  const { estAdmin } = useEstAdmin();
  const { data } = useSWR<{ jours: number; lignes: Ligne[] }>(
    estAdmin ? "/admin-provenance" : null,
    () => adminApi.provenance(90).then((r) => r.data),
    { refreshInterval: CADENCE.lent, keepPreviousData: true },
  );

  return (
    <Panneau
      titre="Provenance des inscriptions"
      desc="Comptes créés sur 90 jours selon le lien d'arrivée (utm_source:utm_campaign). Payant = formule en cours ou pass acheté."
      icone={<Megaphone className="h-3.5 w-3.5" />}
      actions={data && <Puce>{num(data.lignes.reduce((s, l) => s + l.inscrits, 0))} comptes</Puce>}
    >
      {!data ? (
        <Squelette lignes={4} />
      ) : data.lignes.length === 0 ? (
        <Vide>Aucune inscription sur la période.</Vide>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr>
                <th className={TH}>Provenance</th>
                <th className={`${TH} text-right`}>Inscrits</th>
                <th className={`${TH} text-right`}>Confirmés</th>
                <th className={`${TH} text-right`}>Payants</th>
                <th className={`${TH} text-right`}>Dernier</th>
              </tr>
            </thead>
            <tbody>
              {data.lignes.map((l) => (
                <tr key={l.provenance ?? "direct"} className="border-t border-border/70">
                  <td className={`${TD} font-medium`}>{l.provenance ?? <span className="text-muted-foreground">Direct ou inconnue</span>}</td>
                  <td className={`${TD} text-right tabular-nums`}>{num(l.inscrits)}</td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {num(l.confirmes)} <span className="text-muted-foreground">· {taux(l.confirmes, l.inscrits)}</span>
                  </td>
                  <td className={`${TD} text-right tabular-nums`}>
                    {num(l.payants)} <span className="text-muted-foreground">· {taux(l.payants, l.inscrits)}</span>
                  </td>
                  <td className={`${TD} text-right text-muted-foreground`}>{depuis(l.dernier)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panneau>
  );
}
