"use client";

/**
 * Rentabilité réelle par profil — le bénéfice NET, qui peut être négatif.
 *
 * Réservé à l'admin : le palmarès public montre la qualité d'analyse, pas un
 * gain. Ici on montre l'argent réellement encaissé, 10 €/profil/course, réglé
 * sur les rapports PMU.
 */

import { TrendingUp, Wallet } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  Carte, CartesOuTableau, Champ, DefilementX, GrilleTuiles, Panneau, Squelette, TD, TH, Tuile,
  eur, num, pct, signedEur, signedPct, tone,
} from "../ui";
import { usePalmaresNet } from "../data";
import { PROFIL_NET_LABELS } from "../types";

export default function RentabiliteProfils() {
  const { data } = usePalmaresNet();

  return (
    <Panneau
      titre="Rentabilité réelle par profil"
      desc="10 € par profil et par course, réglés sur les rapports PMU publiés. Net réel — il peut être négatif, et c'est justement ce qu'on suit."
      icone={<Wallet className="h-3.5 w-3.5" />}
      ton="or"
      pied={data?.updated_at ? (
        <span className="flex items-center gap-1.5">
          <TrendingUp className="h-3 w-3" aria-hidden />
          Mis à jour {formatDateTime(data.updated_at)} · recalculé à chaque fin de course
        </span>
      ) : undefined}
    >
      {!data ? (
        <Squelette lignes={4} />
      ) : (
        <div className="space-y-4">
          <GrilleTuiles colonnes={4}>
            <Tuile
              label="Bénéfice net total"
              valeur={signedEur(data.total_benefice ?? 0)}
              ton={(data.total_benefice ?? 0) >= 0 ? "ok" : "alerte"}
              aide="Somme des gains encaissés moins les mises engagées, sans plafond."
            />
            <Tuile label="Total gagné" valeur={eur(data.total_gain ?? 0)} ton="ok" />
            <Tuile label="Paris gagnés" valeur={num(data.n)} />
            <Tuile label="Courses" valeur={num(data.n_courses ?? 0)} />
          </GrilleTuiles>

          {data.profils && data.profils.length > 0 && (
            <CartesOuTableau
              cartes={data.profils.map((p) => (
                <Carte key={p.profil} ton={p.gain_net >= 0 ? "ok" : "neutre"}>
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-sm font-semibold">
                      {PROFIL_NET_LABELS[p.profil] ?? p.label}
                    </span>
                    <span className={cn("text-base font-semibold tabular-nums", tone(p.gain_net))}>
                      {signedEur(p.gain_net)}
                    </span>
                  </div>
                  <div className="mt-2 space-y-1 border-t border-border/60 pt-2">
                    <Champ label="Courses">{num(p.nb_courses)}</Champ>
                    <Champ label="Misé">{eur(p.mise_totale ?? 0)}</Champ>
                    <Champ label="Gagné">
                      <span className="text-emerald-700">{eur(p.gain_total ?? 0)}</span>
                    </Champ>
                    <Champ label="ROI">
                      <span className={tone(p.roi)}>{signedPct(p.roi)}</span>
                    </Champ>
                    <Champ label="Courses bénéficiaires">
                      {p.taux_courses_beneficiaires != null ? pct(p.taux_courses_beneficiaires, 0) : "—"}
                    </Champ>
                  </div>
                </Carte>
              ))}
              tableau={
                <DefilementX label="Rentabilité par profil">
                  <table className="w-full min-w-[560px] border-collapse">
                    <thead>
                      <tr className="border-b border-border">
                        <th className={TH}>Profil</th>
                        <th className={cn(TH, "text-right")}>Courses</th>
                        <th className={cn(TH, "text-right")}>Misé</th>
                        <th className={cn(TH, "text-right")}>Gagné</th>
                        <th className={cn(TH, "text-right")}>Net</th>
                        <th className={cn(TH, "text-right")}>ROI</th>
                        <th className={cn(TH, "text-right")}>% courses +</th>
                      </tr>
                    </thead>
                    <tbody>
                      {data.profils.map((p) => (
                        <tr key={p.profil} className="border-b border-border/40 last:border-0">
                          <td className={cn(TD, "font-medium")}>
                            {PROFIL_NET_LABELS[p.profil] ?? p.label}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>{num(p.nb_courses)}</td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>{eur(p.mise_totale ?? 0)}</td>
                          <td className={cn(TD, "text-right tabular-nums text-emerald-700")}>{eur(p.gain_total ?? 0)}</td>
                          <td className={cn(TD, "text-right font-semibold tabular-nums", tone(p.gain_net))}>{signedEur(p.gain_net)}</td>
                          <td className={cn(TD, "text-right font-semibold tabular-nums", tone(p.roi))}>{signedPct(p.roi)}</td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>
                            {p.taux_courses_beneficiaires != null ? pct(p.taux_courses_beneficiaires, 0) : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </DefilementX>
              }
            />
          )}
        </div>
      )}
    </Panneau>
  );
}
