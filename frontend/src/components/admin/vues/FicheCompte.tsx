"use client";

/**
 * Fiche d'un compte — portefeuille, abonnements, historique des paris.
 *
 * Sur téléphone, l'ancienne version ouvrait une carte flottante centrée dans
 * un fond noirci : sur 390 px, ça donnait une fenêtre de 374 px collée aux
 * bords, avec un tableau de huit colonnes dedans. Elle s'ouvre maintenant en
 * feuille plein écran sous `sm`, et en fenêtre classique au-dessus — le motif
 * que tout le monde connaît, et le seul qui laisse la place de lire.
 *
 * La fermeture par `Échap` et le retour du focus ne sont pas des raffinements :
 * une boîte modale sans échappatoire au clavier est un piège (WCAG 2.1.2).
 */

import * as React from "react";
import useSWR from "swr";
import { Loader2, X } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { adminApi } from "@/lib/api";
import { cn, formatDateTime, formatEuro } from "@/lib/utils";
import {
  Carte, CartesOuTableau, Champ, DefilementX, GrilleTuiles, TD, TH, Tuile, Vide,
  eur, num, pct, signedEur, signedPct, tone,
} from "../ui";
import { PROFIL_NET_LABELS, type UserDetail } from "../types";

function badgeResultat(r: string | null) {
  if (r === "gagne") return <Badge variant="success" className="text-[11px]">Gagné</Badge>;
  if (r === "perd") return <Badge variant="secondary" className="text-[11px] text-destructive">Perdu</Badge>;
  if (r === "annule") return <Badge variant="secondary" className="text-[11px]">Annulé</Badge>;
  return <Badge variant="warning" className="text-[11px]">En attente</Badge>;
}

function badgePlan(plan: string) {
  const variant = plan === "expert" ? "expert" : ["starter", "standard"].includes(plan) ? "gold" : "secondary";
  return <Badge variant={variant} className="text-[11px] capitalize">{plan}</Badge>;
}

/** Statuts Stripe bruts. Ils étaient affichés tels quels : « active », « past_due »,
 *  en anglais et en serpent, dans une console entièrement en français. */
const STATUTS_SUB: Record<string, string> = {
  active: "actif",
  trialing: "en essai",
  past_due: "impayé",
  unpaid: "impayé définitif",
  canceled: "résilié",
  cancel_at_period_end: "résilié en fin de période",
  incomplete: "paiement non finalisé",
  incomplete_expired: "paiement abandonné",
  paused: "suspendu",
};

export default function FicheCompte({ userId, onClose }: { userId: string; onClose: () => void }) {
  const { data, isLoading } = useSWR<UserDetail>(
    ["/admin-user-detail", userId],
    () => adminApi.userDetail(userId).then((r) => r.data),
  );

  // Échap ferme, et le défilement de la page de fond est gelé : sans ça, le
  // doigt qui défile dans la fiche entraîne la liste derrière elle.
  React.useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    document.addEventListener("keydown", onKey);
    const overflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = overflow;
    };
  }, [onClose]);

  const nom = data ? [data.user.prenom, data.user.nom].filter(Boolean).join(" ") || "Sans nom" : "";

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Fiche du compte"
      className="fixed inset-0 z-50 flex items-end justify-center bg-black/50 backdrop-blur-sm sm:items-start sm:p-4"
      onClick={onClose}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        className="flex h-dvh w-full flex-col bg-background shadow-2xl sm:my-6 sm:h-auto sm:max-h-[90dvh] sm:max-w-4xl sm:rounded-2xl sm:border sm:border-border"
      >
        {/* En-tête collante : sur une fiche qui défile, le nom du compte et la
            sortie doivent rester atteignables. */}
        <header className="sticky top-0 z-10 flex items-start gap-3 border-b border-border bg-background/95 px-4 py-3 backdrop-blur sm:rounded-t-2xl sm:px-6 sm:py-4">
          <div className="min-w-0 flex-1">
            {isLoading || !data ? (
              <div className="h-5 w-40 animate-pulse rounded bg-muted" />
            ) : (
              <>
                <div className="flex flex-wrap items-center gap-2">
                  <h2 className="text-base font-semibold tracking-tight sm:text-lg">{nom}</h2>
                  {data.user.is_admin && <Badge variant="secondary" className="text-[10px]">ADMIN</Badge>}
                  {badgePlan(data.user.plan)}
                  {data.user.is_active
                    ? <Badge variant="success" className="text-[11px]">Actif</Badge>
                    : <Badge variant="secondary" className="text-[11px] text-destructive">Suspendu</Badge>}
                </div>
                <p className="mt-1 truncate text-xs text-muted-foreground" title={data.user.email}>
                  {data.user.email}
                </p>
              </>
            )}
          </div>
          <button
            onClick={onClose}
            aria-label="Fermer la fiche"
            className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </header>

        <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain px-4 py-4 pb-[calc(1rem+env(safe-area-inset-bottom))] sm:px-6 sm:py-5">
          {isLoading || !data ? (
            <div className="flex justify-center py-20">
              <Loader2 className="h-7 w-7 animate-spin text-muted-foreground" aria-label="Chargement" />
            </div>
          ) : (
            <div className="space-y-5">
              {/* Identité — en liste clé/valeur, pas en phrase à puces « · » qui
                  se cassait n'importe où sur mobile. */}
              <section className="rounded-xl border border-border bg-muted/20 p-3">
                <dl className="grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
                  <Champ label="Inscription">{data.user.auth_method === "google" ? "Google" : "E-mail"}</Champ>
                  <Champ label="Profil de risque">{PROFIL_NET_LABELS[data.user.profil_risque] ?? data.user.profil_risque}</Champ>
                  <Champ label="Inscrit le">{formatDateTime(data.user.created_at)}</Champ>
                  <Champ label="Dernière connexion">
                    {data.user.last_login ? formatDateTime(data.user.last_login) : "jamais"}
                  </Champ>
                </dl>
              </section>

              {/* Portefeuille */}
              <section>
                <h3 className="mb-2 text-[13px] font-semibold">Portefeuille</h3>
                <GrilleTuiles colonnes={4}>
                  <Tuile
                    label="Solde actuel"
                    valeur={formatEuro(data.portefeuille.solde_actuel)}
                    sub={`capital ${formatEuro(data.portefeuille.capital_initial)}`}
                  />
                  <Tuile
                    label="Gain net"
                    valeur={signedEur(data.portefeuille.gain_net, 2)}
                    ton={data.portefeuille.gain_net >= 0 ? "ok" : "alerte"}
                    sub={`misé ${formatEuro(data.portefeuille.mise_totale)}`}
                  />
                  <Tuile
                    label="ROI"
                    valeur={signedPct(data.portefeuille.roi, 1)}
                    ton={data.portefeuille.roi == null ? "neutre" : data.portefeuille.roi >= 0 ? "ok" : "alerte"}
                    sub={`${data.portefeuille.nb_predictions_used} suivis IA`}
                  />
                  <Tuile
                    label="Bilan paris"
                    valeur={`${data.portefeuille.nb_gagnes}/${data.portefeuille.nb_regles}`}
                    sub={
                      <>
                        {data.portefeuille.win_rate == null ? "—" : `${pct(data.portefeuille.win_rate)} de réussite`}
                        {data.portefeuille.nb_attente > 0 && ` · ${data.portefeuille.nb_attente} en attente`}
                      </>
                    }
                  />
                </GrilleTuiles>
              </section>

              {data.par_type.length > 0 && (
                <section>
                  <h3 className="mb-2 text-[13px] font-semibold">Par type de pari</h3>
                  <div className="flex flex-wrap gap-2">
                    {data.par_type.map((t) => (
                      <div key={t.type_pari} className="rounded-xl border border-border px-3 py-2 text-xs">
                        <span className="font-semibold capitalize">{t.type_pari}</span>
                        <span className="text-muted-foreground"> · {t.nb_gagnes}/{t.nb} · </span>
                        <span className={cn("tabular-nums font-semibold", tone(t.net))}>{signedEur(t.net, 2)}</span>
                        {t.roi != null && <span className="text-muted-foreground"> ({signedPct(t.roi, 0)})</span>}
                      </div>
                    ))}
                  </div>
                </section>
              )}

              {data.subscriptions.length > 0 && (
                <section>
                  <h3 className="mb-2 text-[13px] font-semibold">Abonnements</h3>
                  <ul className="space-y-1.5">
                    {data.subscriptions.map((s) => (
                      <li key={s.sub_id} className="flex flex-wrap items-center gap-2 rounded-lg border border-border/60 px-3 py-2 text-xs">
                        <Badge variant="secondary" className="text-[11px] capitalize">{s.plan}</Badge>
                        <span className="text-muted-foreground">
                          {s.periodicite === "annual" ? "annuel" : "mensuel"}
                        </span>
                        <span className={cn(s.statut === "active" ? "font-semibold text-emerald-700" : "text-muted-foreground")}>
                          {STATUTS_SUB[s.statut] ?? s.statut}
                        </span>
                        {s.periode_fin && (
                          <span className="text-muted-foreground">· jusqu&apos;au {formatDateTime(s.periode_fin)}</span>
                        )}
                      </li>
                    ))}
                  </ul>
                </section>
              )}

              <section>
                <h3 className="mb-2 text-[13px] font-semibold">
                  Historique des paris <span className="font-normal text-muted-foreground">({num(data.nb_bets)})</span>
                </h3>
                {data.bets.length === 0 ? (
                  <Vide>Aucun pari enregistré.</Vide>
                ) : (
                  <CartesOuTableau
                    cartes={
                      <div className="max-h-[24rem] space-y-2 overflow-y-auto">
                        {data.bets.map((b) => (
                          <Carte key={b.entry_id}>
                            <div className="flex items-start justify-between gap-2">
                              <span className="text-[13px] font-medium capitalize">
                                {b.type_pari}
                                {b.suivi_reco_ia && (
                                  <span className="ml-1.5 rounded bg-brand-gold/15 px-1 py-0.5 text-[10px] font-bold text-brand-gold-dark">IA</span>
                                )}
                              </span>
                              {badgeResultat(b.resultat)}
                            </div>
                            <p className="mt-1 truncate text-xs text-muted-foreground" title={b.chevaux || ""}>
                              {b.chevaux || "—"}
                            </p>
                            <div className="mt-2 space-y-1 border-t border-border/60 pt-2">
                              <Champ label="Course">
                                {b.course_code ? <span className="font-mono">{b.course_code}</span> : "—"}
                                {b.hippodrome ? ` · ${b.hippodrome}` : ""}
                              </Champ>
                              <Champ label="Mise">
                                {formatEuro(b.mise)}{b.cote ? ` @ ${b.cote.toFixed(2)}` : ""}
                              </Champ>
                              <Champ label="Résultat">
                                <span className={cn("font-semibold", tone(b.gain_perte))}>
                                  {b.gain_perte == null ? "—" : signedEur(b.gain_perte, 2)}
                                </span>
                              </Champ>
                            </div>
                          </Carte>
                        ))}
                      </div>
                    }
                    tableau={
                      <div className="max-h-[26rem] overflow-y-auto rounded-xl border border-border">
                        <DefilementX label="Historique des paris" bleed={false}>
                          <table className="w-full min-w-[760px] border-collapse">
                            <thead className="sticky top-0 z-10 bg-muted/80 backdrop-blur">
                              <tr>
                                <th className={TH}>Date</th>
                                <th className={TH}>Course</th>
                                <th className={TH}>Type</th>
                                <th className={TH}>Chevaux</th>
                                <th className={cn(TH, "text-right")}>Mise</th>
                                <th className={cn(TH, "text-right")}>Cote</th>
                                <th className={cn(TH, "text-center")}>Résultat</th>
                                <th className={cn(TH, "text-right")}>Gain / perte</th>
                              </tr>
                            </thead>
                            <tbody>
                              {data.bets.map((b) => (
                                <tr key={b.entry_id} className="border-t border-border/50 hover:bg-muted/25">
                                  <td className={cn(TD, "whitespace-nowrap text-muted-foreground")}>{formatDateTime(b.date)}</td>
                                  <td className={cn(TD, "whitespace-nowrap")}>
                                    {b.course_code && <span className="font-mono font-semibold">{b.course_code}</span>}
                                    {b.hippodrome && <span className="text-muted-foreground"> {b.hippodrome}</span>}
                                  </td>
                                  <td className={cn(TD, "whitespace-nowrap capitalize")}>
                                    {b.type_pari}
                                    {b.suivi_reco_ia && (
                                      <span className="ml-1 text-[10px] font-bold text-brand-gold-dark" title="Suivi de la reco IA">IA</span>
                                    )}
                                  </td>
                                  <td className={cn(TD, "max-w-[140px] truncate")} title={b.chevaux || ""}>{b.chevaux || "—"}</td>
                                  <td className={cn(TD, "text-right tabular-nums")}>{formatEuro(b.mise)}</td>
                                  <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>
                                    {b.cote ? b.cote.toFixed(2) : "—"}
                                  </td>
                                  <td className={cn(TD, "text-center")}>{badgeResultat(b.resultat)}</td>
                                  <td className={cn(TD, "text-right font-semibold tabular-nums", tone(b.gain_perte))}>
                                    {b.gain_perte == null ? "—" : signedEur(b.gain_perte, 2)}
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </DefilementX>
                      </div>
                    }
                  />
                )}
              </section>

              <p className="text-xs text-muted-foreground">
                Capital initial déclaré : {eur(data.portefeuille.capital_initial)}.
              </p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
