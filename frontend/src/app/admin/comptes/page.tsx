"use client";

/**
 * Comptes — portefeuilles, abonnements, actions par compte.
 *
 * Le tableau d'origine tenait sur 900 px minimum, avec une colonne « Actions »
 * de deux boutons de 10 px de haut. Ce qui change :
 *
 *   · la recherche et l'export sortent de l'en-tête repliable et deviennent une
 *     barre d'outils collante — on cherche un compte en haut de liste comme en
 *     bas de liste ;
 *   · sous 768 px la liste devient des cartes, avec des boutons d'action de
 *     44 px : « Suspendre » se ratait une fois sur deux au pouce ;
 *   · les huit pictogrammes cryptiques (🔵 G, ✉, ✓, ⚠, 💳) entassés sous
 *     l'adresse deviennent des mentions lisibles. Un symbole qui a besoin d'une
 *     infobulle pour se comprendre ne renseigne personne sur téléphone, où
 *     l'infobulle n'existe pas.
 */

import { useMemo, useState } from "react";
import { toast } from "sonner";
import {
  Ban, Download, RotateCcw, Search, Trash2, Users, Wallet,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { adminApi } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import {
  Carte, CartesOuTableau, Champ, DefilementX, EnTetePage, GrilleTuiles, Panneau, Puce,
  Segments, Squelette, TD, TH, Tuile, Vide, eur, num, signedEur, signedPct, tone,
} from "@/components/admin/ui";
import { useComptes } from "@/components/admin/data";
import FicheCompte from "@/components/admin/vues/FicheCompte";
import { PROFIL_NET_LABELS, type CompteLigne } from "@/components/admin/types";

/** Un ROI calculé sur un ou deux paris n'apprend rien : « +600 % » sur un seul
 *  pari gagné se lisait comme une performance. En dessous, il reste grisé. */
const MIN_PARIS_ROI = 5;

const FILTRES = [
  { key: "tous", label: "Tous" },
  { key: "abonnes", label: "Abonnés" },
  { key: "actifs", label: "Ont parié" },
  { key: "suspendus", label: "Suspendus" },
] as const;
type Filtre = (typeof FILTRES)[number]["key"];

// Statut réel de l'abonnement — distinct de « a un customer_id Stripe » (créé dès
// le clic sur « S'abonner », avant même que la personne remplisse sa carte).
// `null` avec `stripeClient=true` = checkout démarré et jamais terminé.
function badgeAbonnement(statut: string | null, stripeClient: boolean) {
  const B = (variant: "success" | "warning" | "secondary", texte: string, titre?: string, classe?: string) => (
    <Badge variant={variant} className={cn("whitespace-nowrap text-[11px]", classe)} title={titre}>{texte}</Badge>
  );
  if (statut === "active") return B("success", "Actif");
  if (statut === "trialing") return B("success", "Essai");
  if (statut === "cancel_at_period_end")
    return B("warning", "Fin de période", "Résilié, mais payé jusqu'à la fin de la période en cours");
  // Depuis le 2026-08-27, `past_due` ne donne PLUS accès au produit : Stripe
  // relance la carte pendant des semaines, l'accès est coupé dès le 1er échec.
  if (statut === "past_due")
    return B("secondary", "Impayé", "Impayé — accès coupé, relances Stripe en cours", "text-destructive");
  if (statut === "unpaid")
    return B("secondary", "Impayé définitif", "Relances Stripe épuisées", "text-destructive");
  if (statut === "canceled") return B("secondary", "Résilié", undefined, "text-muted-foreground");
  if (statut === "incomplete" || statut === "incomplete_expired")
    return B("secondary", "Incomplet", "Paiement jamais finalisé", "text-amber-700");
  if (statut === "essai_sans_carte")
    return B("warning", "Sans carte", "Essai ouvert sans carte — aucun accès tant qu'un moyen de paiement n'est pas rattaché");
  if (stripeClient)
    return B("secondary", "Checkout abandonné", "Client Stripe créé, jamais d'abonnement finalisé", "text-muted-foreground");
  return <span className="text-xs text-muted-foreground">—</span>;
}

function badgePlan(plan: string) {
  const variant = plan === "expert" ? "expert" : ["starter", "standard"].includes(plan) ? "gold" : "secondary";
  return <Badge variant={variant} className="text-[11px] capitalize">{plan}</Badge>;
}

/**
 * Les pictogrammes de l'ancienne version, écrits en toutes lettres — mais
 * seulement quand ils APPRENNENT quelque chose. « Adresse confirmée » sur les
 * vingt-et-une lignes qui le sont ne renseigne personne ; c'est l'exception qui
 * mérite d'être écrite.
 */
function mentionsCompte(u: CompteLigne) {
  const m: Array<{ texte: string; ton: "neutre" | "attention" }> = [
    { texte: u.auth_method === "google" ? "Google" : "E-mail", ton: "neutre" },
  ];
  if (!u.email_verified) m.push({ texte: "Adresse non confirmée", ton: "attention" });
  if (u.stripe_client) m.push({ texte: "Client Stripe", ton: "neutre" });
  return m;
}

function roiCellule(u: CompteLigne) {
  if (u.roi == null) return <span className="text-muted-foreground">—</span>;
  const fiable = u.nb_paris >= MIN_PARIS_ROI;
  return (
    <span
      className={cn("tabular-nums", fiable ? tone(u.roi) : "text-muted-foreground/60")}
      title={fiable ? "Retour sur investissement" : `ROI sur ${u.nb_paris} pari${u.nb_paris > 1 ? "s" : ""} — non significatif`}
    >
      {signedPct(u.roi, 0)}
    </span>
  );
}

export default function ComptesPage() {
  const [recherche, setRecherche] = useState("");
  const [filtre, setFiltre] = useState<Filtre>("tous");
  const [selection, setSelection] = useState<string | null>(null);
  const { data: comptes, mutate } = useComptes(recherche);

  const liste = useMemo(() => {
    const tous = comptes ?? [];
    if (filtre === "abonnes") return tous.filter((u) => ["active", "trialing", "cancel_at_period_end"].includes(u.abonnement_statut ?? ""));
    if (filtre === "actifs") return tous.filter((u) => u.nb_paris > 0);
    if (filtre === "suspendus") return tous.filter((u) => !u.is_active);
    return tous;
  }, [comptes, filtre]);

  const resume = useMemo(() => {
    const tous = comptes ?? [];
    return {
      total: tous.length,
      abonnes: tous.filter((u) => ["active", "trialing"].includes(u.abonnement_statut ?? "")).length,
      parieurs: tous.filter((u) => u.nb_paris > 0).length,
      suspendus: tous.filter((u) => !u.is_active).length,
      capital: tous.reduce((s, u) => s + (u.solde_actuel ?? 0), 0),
    };
  }, [comptes]);

  async function basculerActif(u: CompteLigne) {
    const verbe = u.is_active ? "Suspendre" : "Réactiver";
    if (!window.confirm(`${verbe} le compte ${u.email} ?`)) return;
    try {
      await adminApi.updateUser(u.user_id, { is_active: !u.is_active });
      toast.success(u.is_active ? "Compte suspendu" : "Compte réactivé");
      mutate();
    } catch {
      toast.error("Modification impossible");
    }
  }

  async function ajusterPortefeuille(u: CompteLigne) {
    const v = window.prompt(
      `Ajuster le portefeuille de ${u.email}\nMontant à créditer (+) ou débiter (−), en € :`,
      "",
    );
    if (v == null) return;
    const m = parseFloat(v.replace(",", "."));
    if (isNaN(m) || m === 0) {
      toast.error("Montant invalide");
      return;
    }
    try {
      await adminApi.adjustBankroll(u.user_id, m);
      toast.success(`Portefeuille ajusté de ${signedEur(m, 2)}`);
      mutate();
    } catch {
      toast.error("Ajustement impossible");
    }
  }

  async function supprimerCompte(u: CompteLigne) {
    // Confirmation par recopie de l'adresse : un « OK » réflexe ne doit pas
    // suffire à effacer un compte, et la ligne d'à côté a le même bouton.
    const saisie = window.prompt(
      `SUPPRESSION DÉFINITIVE de ${u.email}\n\n` +
      "Seront effacés : le compte, ses paris, portefeuilles, stratégies et alertes.\n" +
      "Sera conservé : l'historique d'abonnement (pièce comptable), détaché du compte.\n\n" +
      "Recopiez l'adresse e-mail pour confirmer :", "");
    if (saisie == null) return;
    if (saisie.trim().toLowerCase() !== u.email.toLowerCase()) {
      toast.error("Adresse non conforme — suppression annulée.");
      return;
    }
    try {
      const res = await adminApi.deleteUser(u.user_id);
      const n = (res.data?.supprime ?? {}) as Record<string, number>;
      toast.success(`${u.email} supprimé — ${n.paris ?? 0} pari(s), ${n.portefeuilles ?? 0} portefeuille(s).`);
      mutate();
    } catch (e: unknown) {
      const detail = (e as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      toast.error(detail || "Suppression impossible.");
    }
  }

  async function exporter() {
    try {
      const res = await adminApi.exportUsers();
      const url = URL.createObjectURL(new Blob([res.data], { type: "text/csv" }));
      const a = document.createElement("a");
      a.href = url;
      a.download = "blackturf_comptes.csv";
      a.click();
      URL.revokeObjectURL(url);
    } catch {
      toast.error("Export impossible");
    }
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <EnTetePage
        titre="Comptes"
        icone={<Users className="h-4 w-4" />}
        desc="Portefeuilles, abonnements et actions par compte. Cliquer un nom ouvre sa fiche complète."
        actions={
          <button
            onClick={exporter}
            className="inline-flex min-h-[2.75rem] items-center gap-2 rounded-xl border border-border px-4 text-[13px] font-semibold transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
          >
            <Download className="h-4 w-4" aria-hidden /> Export CSV
          </button>
        }
      />

      <GrilleTuiles colonnes={5}>
        <Tuile label="Comptes" valeur={num(resume.total)} icone={<Users className="h-3.5 w-3.5" />} />
        <Tuile label="Abonnés" valeur={num(resume.abonnes)} ton={resume.abonnes > 0 ? "ok" : "neutre"} />
        <Tuile label="Ont parié" valeur={num(resume.parieurs)} sub="au moins un pari enregistré" />
        <Tuile label="Suspendus" valeur={num(resume.suspendus)} ton={resume.suspendus > 0 ? "attention" : "neutre"} />
        <Tuile
          label="Capital cumulé"
          valeur={eur(resume.capital)}
          icone={<Wallet className="h-3.5 w-3.5" />}
          aide="Somme des soldes déclarés par les utilisateurs. Ce n'est pas de l'argent détenu par BlackTurf."
        />
      </GrilleTuiles>

      <Panneau
        titre="Liste des comptes"
        desc="La recherche interroge le serveur (nom, prénom, adresse) ; les filtres trient ce qu'il a renvoyé."
        actions={<Puce>{liste.length} affiché(s)</Puce>}
        bodyClassName="space-y-3"
      >
        <div className="flex flex-col gap-2.5 sm:flex-row sm:items-center">
          <div className="relative flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
              placeholder="Rechercher un nom ou une adresse…"
              aria-label="Rechercher un compte"
              // 16 px : en dessous, iOS zoome sur le champ à la mise au point et
              // la mise en page saute.
              className="h-11 w-full rounded-xl border border-input bg-background pl-9 pr-3 text-base focus:outline-none focus:ring-2 focus:ring-ring sm:text-[13px]"
            />
          </div>
          <Segments items={FILTRES} actif={filtre} onChange={setFiltre} className="sm:shrink-0" taille="compact" />
        </div>

        {!comptes ? (
          <Squelette lignes={6} />
        ) : liste.length === 0 ? (
          <Vide>
            {recherche
              ? `Aucun compte ne correspond à « ${recherche} ».`
              : "Aucun compte dans ce filtre."}
          </Vide>
        ) : (
          <CartesOuTableau
            cartes={liste.map((u) => {
              const nom = [u.prenom, u.nom].filter(Boolean).join(" ") || "Sans nom";
              return (
                <Carte key={u.user_id} ton={!u.is_active ? "attention" : "neutre"}>
                  <button
                    onClick={() => setSelection(u.user_id)}
                    className="flex w-full items-start justify-between gap-2 text-left"
                  >
                    <span className="min-w-0 flex-1">
                      <span className="flex flex-wrap items-center gap-1.5">
                        <span className="text-[13px] font-semibold">{nom}</span>
                        {u.is_admin && <Badge variant="secondary" className="text-[10px]">ADMIN</Badge>}
                        {!u.is_active && <Badge variant="secondary" className="text-[10px] text-destructive">SUSPENDU</Badge>}
                      </span>
                      <span className="mt-0.5 block truncate text-xs text-muted-foreground">{u.email}</span>
                    </span>
                    {badgePlan(u.plan)}
                  </button>

                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    {badgeAbonnement(u.abonnement_statut, u.stripe_client)}
                    {mentionsCompte(u).map((m) => (
                      <span
                        key={m.texte}
                        className={cn(
                          "rounded-full border px-2 py-0.5 text-[11px] font-medium",
                          m.ton === "attention"
                            ? "border-amber-200 bg-amber-50 text-amber-800"
                            : "border-border bg-muted/50 text-muted-foreground",
                        )}
                      >
                        {m.texte}
                      </span>
                    ))}
                  </div>

                  <div className="mt-2 space-y-1 border-t border-border/60 pt-2">
                    <Champ label="Portefeuille">
                      {eur(u.solde_actuel)}
                      <span className="ml-1 text-xs font-normal text-muted-foreground">
                        {u.mise_totale ? `· ${eur(u.mise_totale)} misés` : "· aucune mise"}
                      </span>
                    </Champ>
                    <Champ label="Résultat">
                      <span className={tone(u.gain_net)}>{signedEur(u.gain_net)}</span>
                      <span className="ml-1.5">{roiCellule(u)}</span>
                    </Champ>
                    <Champ label="Paris">{u.nb_paris === 0 ? "—" : `${u.nb_gagnes} / ${u.nb_paris}`}</Champ>
                    <Champ label="Profil">{PROFIL_NET_LABELS[u.profil_risque] ?? u.profil_risque}</Champ>
                    <Champ label="Vue">{u.last_login ? formatDateTime(u.last_login) : "jamais"}</Champ>
                  </div>

                  {/* La suppression est mise À L'ÉCART des deux autres actions :
                      elle est irréversible, et trois boutons de même poids côte
                      à côte invitent au clic réflexe. */}
                  <div className="mt-3 flex gap-2">
                    <button
                      onClick={() => basculerActif(u)}
                      className={cn(
                        "flex min-h-[2.5rem] flex-1 items-center justify-center gap-1.5 rounded-xl border text-xs font-semibold transition-colors",
                        u.is_active
                          ? "border-amber-500/40 text-amber-700 hover:bg-amber-500/10"
                          : "border-emerald-500/40 text-emerald-700 hover:bg-emerald-500/10",
                      )}
                    >
                      {u.is_active ? <Ban className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
                      {u.is_active ? "Suspendre" : "Réactiver"}
                    </button>
                    <button
                      onClick={() => ajusterPortefeuille(u)}
                      className="flex min-h-[2.5rem] flex-1 items-center justify-center gap-1.5 rounded-xl border border-border text-xs font-semibold text-muted-foreground transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
                    >
                      <Wallet className="h-3.5 w-3.5" /> Ajuster
                    </button>
                    <button
                      onClick={() => supprimerCompte(u)}
                      aria-label={`Supprimer définitivement ${u.email}`}
                      title="Supprimer définitivement le compte"
                      className="flex min-h-[2.5rem] w-10 shrink-0 items-center justify-center rounded-xl border border-destructive/30 text-destructive transition-colors hover:bg-destructive/10"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </Carte>
              );
            })}
            tableau={
              <DefilementX label="Liste des comptes">
                <table className="w-full min-w-[940px] border-collapse">
                  <thead>
                    <tr className="border-b border-border">
                      <th className={TH}>Utilisateur</th>
                      <th className={cn(TH, "text-center")}>Plan</th>
                      <th className={cn(TH, "text-center")}>Abonnement</th>
                      <th className={cn(TH, "text-right")}>Portefeuille</th>
                      <th className={cn(TH, "text-right")}>Résultat</th>
                      <th className={cn(TH, "text-center")}>Paris</th>
                      <th className={cn(TH, "text-right")}>Activité</th>
                      <th className={cn(TH, "text-center")}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liste.map((u) => {
                      const nom = [u.prenom, u.nom].filter(Boolean).join(" ") || "Sans nom";
                      return (
                        <tr
                          key={u.user_id}
                          className={cn(
                            "border-b border-border/40 transition-colors last:border-0 hover:bg-muted/30",
                            !u.is_active && "bg-amber-50/30",
                          )}
                        >
                          <td className={TD}>
                            <button
                              onClick={() => setSelection(u.user_id)}
                              className="flex items-center gap-1.5 text-left font-medium transition-colors hover:text-brand-gold-dark"
                              title="Voir la fiche complète"
                            >
                              {nom}
                              {u.is_admin && <Badge variant="secondary" className="text-[10px]">ADMIN</Badge>}
                              {/* Un compte suspendu se lisait à une coche dans une
                                  colonne dédiée, identique pour 21 lignes sur 22.
                                  Il se lit là où il compte : à côté du nom. */}
                              {!u.is_active && <Badge variant="secondary" className="text-[10px] text-destructive">SUSPENDU</Badge>}
                            </button>
                            <div className="truncate text-xs text-muted-foreground" title={u.email}>{u.email}</div>
                            <div className="mt-0.5 flex flex-wrap gap-1 text-[11px] text-muted-foreground/80">
                              <span>{PROFIL_NET_LABELS[u.profil_risque] ?? u.profil_risque}</span>
                              {mentionsCompte(u).map((m) => (
                                <span key={m.texte} className={m.ton === "attention" ? "text-amber-700" : undefined}>
                                  · {m.texte}
                                </span>
                              ))}
                            </div>
                          </td>
                          <td className={cn(TD, "text-center")}>{badgePlan(u.plan)}</td>
                          <td className={cn(TD, "text-center")}>{badgeAbonnement(u.abonnement_statut, u.stripe_client)}</td>
                          <td className={cn(TD, "text-right")}>
                            <div className="tabular-nums">{eur(u.solde_actuel)}</div>
                            <div className="text-[11px] tabular-nums text-muted-foreground">
                              {u.mise_totale ? `${eur(u.mise_totale)} misés` : "aucune mise"}
                            </div>
                          </td>
                          <td className={cn(TD, "text-right")}>
                            <div className={cn("font-semibold tabular-nums", tone(u.gain_net))}>{signedEur(u.gain_net)}</div>
                            <div className="text-[11px]">{roiCellule(u)}</div>
                          </td>
                          <td className={cn(TD, "text-center tabular-nums")}>
                            {u.nb_paris === 0 ? <span className="text-muted-foreground">—</span> : `${u.nb_gagnes}/${u.nb_paris}`}
                          </td>
                          <td className={cn(TD, "whitespace-nowrap text-right text-xs text-muted-foreground")}>
                            <div title="Dernière connexion">{u.last_login ? formatDateTime(u.last_login) : "jamais"}</div>
                            <div className="text-[11px] text-muted-foreground/70" title="Date d'inscription">
                              inscrit {formatDateTime(u.created_at)}
                            </div>
                          </td>
                          <td className={cn(TD, "whitespace-nowrap text-center")}>
                            <div className="flex items-center justify-center gap-1.5">
                              {/* Suspendre est réversible : ambre, pas rouge. Le
                                  rouge est gardé pour la seule action qui ne se
                                  reprend pas — sinon les deux se confondent. */}
                              <button
                                onClick={() => basculerActif(u)}
                                title={u.is_active ? "Suspendre le compte" : "Réactiver le compte"}
                                className={cn(
                                  "inline-flex h-8 items-center gap-1 rounded-lg border px-2 text-[11px] font-semibold transition-colors",
                                  u.is_active
                                    ? "border-amber-500/40 text-amber-700 hover:bg-amber-500/10"
                                    : "border-emerald-500/40 text-emerald-700 hover:bg-emerald-500/10",
                                )}
                              >
                                {u.is_active ? <Ban className="h-3.5 w-3.5" /> : <RotateCcw className="h-3.5 w-3.5" />}
                                {u.is_active ? "Suspendre" : "Réactiver"}
                              </button>
                              <button
                                onClick={() => ajusterPortefeuille(u)}
                                title="Créditer / débiter le portefeuille"
                                className="inline-flex h-8 items-center gap-1 rounded-lg border border-border px-2 text-[11px] font-semibold text-muted-foreground transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
                              >
                                <Wallet className="h-3.5 w-3.5" /> Ajuster
                              </button>
                              <button
                                onClick={() => supprimerCompte(u)}
                                aria-label={`Supprimer définitivement ${u.email}`}
                                title="Supprimer définitivement le compte"
                                className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-destructive/30 text-destructive transition-colors hover:bg-destructive/10"
                              >
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </DefilementX>
            }
          />
        )}
      </Panneau>

      {selection && <FicheCompte userId={selection} onClose={() => setSelection(null)} />}
    </div>
  );
}
