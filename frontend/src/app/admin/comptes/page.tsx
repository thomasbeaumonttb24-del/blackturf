"use client";

/**
 * Comptes — Défi du mois, abonnements, actions par compte.
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
import Link from "next/link";
import { toast } from "sonner";
import {
  Activity, Ban, CreditCard, Download, Medal, RotateCcw, Search, Trash2, Users,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { adminApi } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, Carte, CartesOuTableau, Champ, DefilementX, EnTetePage, PASS, Panneau, Puce,
  Kpi, Segments, Squelette, TD, TH, Vide, num, restant, signedPct, tone,
} from "@/components/admin/ui";
import { useComptes } from "@/components/admin/data";
import FicheCompte from "@/components/admin/vues/FicheCompte";
import { PROFIL_NET_LABELS, type CompteLigne } from "@/components/admin/types";

/** Un ROI calculé sur un ou deux paris n'apprend rien : « +600 % » sur un seul
 *  pari gagné se lisait comme une performance. En dessous, il reste grisé. */
const MIN_PARIS_ROI = 5;

/** Points du Défi du mois : « 1 155 pts », « +84 pts ». */
function pts(v: number, signe = false): string {
  const n = Math.round(v * 10) / 10;
  return `${signe && n > 0 ? "+" : ""}${n.toLocaleString("fr-FR")} pts`;
}

const FILTRES = [
  { key: "tous", label: "Tous" },
  { key: "abonnes", label: "Abonnés" },
  { key: "pass", label: "Pass" },
  { key: "actifs", label: "Joueurs du défi" },
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

const STATUTS_VIVANTS = ["active", "trialing", "cancel_at_period_end", "essai_sans_carte"];
const passVivant = (u: CompteLigne) => u.pass?.statut === "en_cours" || u.pass?.statut === "a_venir";
const aboVivant = (u: CompteLigne) => STATUTS_VIVANTS.includes(u.abonnement_statut ?? "");

/** D'où vient le plan payant du compte : un Expert au pass et un Expert abonné
 *  se lisaient pareil, alors que l'un s'arrête dans 24 h sans prévenir. */
function originePlan(u: CompteLigne): string | null {
  if (u.plan === "free" || u.is_admin) return null;
  if (aboVivant(u)) return "abonnement";
  if (passVivant(u)) return "via pass";
  return "offert / manuel";
}

function badgePlan(u: CompteLigne) {
  const plan = u.plan;
  const variant = plan === "expert" ? "expert" : ["starter", "standard"].includes(plan) ? "gold" : "secondary";
  const origine = originePlan(u);
  return (
    <span className="inline-flex flex-col items-center gap-0.5">
      <Badge variant={variant} className="text-[11px] capitalize">{plan}</Badge>
      {origine && <span className="whitespace-nowrap text-[10px] text-muted-foreground">{origine}</span>}
    </span>
  );
}

/** Échéance de l'abonnement, dite selon son état. */
function echeanceAbonnement(u: CompteLigne): string | null {
  const a = u.abonnement;
  if (!a) return null;
  if (a.statut === "trialing" && a.essai_fin) return `fin d'essai le ${formatDateTime(a.essai_fin)}`;
  if (!a.periode_fin) return null;
  if (a.statut === "active") return `renouvellement le ${formatDateTime(a.periode_fin)}`;
  if (a.statut === "cancel_at_period_end") return `accès jusqu'au ${formatDateTime(a.periode_fin)} · ${restant(a.periode_fin)}`;
  if (a.statut === "canceled") return `terminé le ${formatDateTime(a.periode_fin)}`;
  return null;
}

/**
 * Ce que le compte a payé et jusqu'à quand. Un pass s'achète via Stripe : son
 * client Stripe faisait afficher « Checkout abandonné » à quelqu'un qui avait
 * payé son Pass Jour — le pass passe donc avant ce constat, avec sa durée et
 * le temps qu'il lui reste.
 */
function celluleAcces(u: CompteLigne, aligne: "centre" | "gauche" = "centre") {
  const blocs: React.ReactNode[] = [];
  const a = u.abonnement;
  const ligne = (contenu: React.ReactNode, cle: string) => (
    <div key={cle} className={cn("flex flex-col gap-0.5", aligne === "centre" ? "items-center" : "items-start")}>{contenu}</div>
  );

  if (a && (aboVivant(u) || !u.pass)) {
    const echeance = echeanceAbonnement(u);
    blocs.push(ligne(<>
      <span className="flex flex-wrap items-center justify-center gap-1">
        <BadgeFormule plan={a.plan} periodicite={a.periodicite} />
        {badgeAbonnement(u.abonnement_statut, u.stripe_client)}
      </span>
      {echeance && <span className="whitespace-nowrap text-[11px] text-muted-foreground">{echeance}</span>}
    </>, "abo"));
  }

  const p = u.pass;
  if (p) {
    const acces = PASS[p.duree]?.acces;
    const vivant = passVivant(u);
    blocs.push(ligne(<>
      <span className="flex flex-wrap items-center justify-center gap-1">
        <span className={cn(!vivant && "opacity-60")}><BadgeFormule plan="pass" duree={p.duree} /></span>
        {p.statut === "en_cours" && <Badge variant="success" className="whitespace-nowrap text-[11px]">En cours</Badge>}
        {p.statut === "a_venir" && <Badge variant="warning" className="whitespace-nowrap text-[11px]">À venir</Badge>}
        {p.statut === "expire" && <Badge variant="secondary" className="whitespace-nowrap text-[11px] text-muted-foreground">Expiré</Badge>}
        {p.statut === "rembourse" && <Badge variant="secondary" className="whitespace-nowrap text-[11px] text-destructive">Remboursé</Badge>}
      </span>
      <span
        className={cn("whitespace-nowrap text-[11px]", vivant ? "font-medium text-emerald-700" : "text-muted-foreground")}
        title={`${acces ?? "Durée inconnue"} d'accès Expert · acheté le ${formatDateTime(p.achete_le)} · du ${formatDateTime(p.debut)} au ${formatDateTime(p.fin)}`}
      >
        {p.statut === "en_cours" && <>jusqu&apos;au {formatDateTime(p.fin)} · {restant(p.fin)}</>}
        {p.statut === "a_venir" && <>commence le {formatDateTime(p.debut)}</>}
        {p.statut === "expire" && <>terminé le {formatDateTime(p.fin)}</>}
        {p.statut === "rembourse" && <>accès retiré</>}
      </span>
      {vivant && p.nb_a_venir > 0 && (
        <span className="whitespace-nowrap text-[10px] text-muted-foreground">+{p.nb_a_venir} pass enchaîné{p.nb_a_venir > 1 ? "s" : ""} inclus</span>
      )}
    </>, "pass"));
  }

  if (blocs.length === 0) return badgeAbonnement(u.abonnement_statut, u.stripe_client);
  return <div className="flex flex-col gap-1.5">{blocs}</div>;
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
      title={fiable ? "Rendement au Défi du mois" : `Rendement sur ${u.nb_paris} pari${u.nb_paris > 1 ? "s" : ""} — non significatif`}
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
    if (filtre === "pass") {
      // Les pass en cours d'abord, la fin la plus proche en tête ; puis les anciens.
      const rang = (u: CompteLigne) => (passVivant(u) ? 0 : 1);
      return tous.filter((u) => u.pass).sort((a, b) =>
        rang(a) - rang(b) || (rang(a) === 0
          ? new Date(a.pass!.fin).getTime() - new Date(b.pass!.fin).getTime()
          : new Date(b.pass!.fin).getTime() - new Date(a.pass!.fin).getTime()));
    }
    if (filtre === "actifs") {
      // Les joueurs du défi, dans l'ordre du classement : classés par rang, puis
      // les autres par solde.
      return tous.filter((u) => u.nb_paris > 0).sort((a, b) =>
        (a.defi_rang ?? 1e9) - (b.defi_rang ?? 1e9) || b.defi_solde - a.defi_solde);
    }
    if (filtre === "suspendus") return tous.filter((u) => !u.is_active);
    return tous;
  }, [comptes, filtre]);

  const resume = useMemo(() => {
    // Le compte d'administration n'est pas un client : exclu comme sur Pilotage.
    const tous = (comptes ?? []).filter((u) => !u.is_admin);
    return {
      total: tous.length,
      // Payants + essais, comme le Pilotage : un abonné qui a résilié reste
      // abonné (et a payé) jusqu'à la fin de sa période.
      abonnes: tous.filter((u) => ["active", "trialing", "cancel_at_period_end"].includes(u.abonnement_statut ?? "")).length,
      passEnCours: tous.filter(passVivant).length,
      parieurs: tous.filter((u) => u.nb_paris > 0).length,
      suspendus: tous.filter((u) => !u.is_active).length,
      classes: tous.filter((u) => u.defi_rang != null).length,
      pointsMises: tous.reduce((s, u) => s + (u.defi_points_mises ?? 0), 0),
      parisJoues: tous.reduce((s, u) => s + u.nb_paris, 0),
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

  async function supprimerCompte(u: CompteLigne) {
    // Confirmation par recopie de l'adresse : un « OK » réflexe ne doit pas
    // suffire à effacer un compte, et la ligne d'à côté a le même bouton.
    const saisie = window.prompt(
      `SUPPRESSION DÉFINITIVE de ${u.email}\n\n` +
      "Seront effacés : le compte, ses paris du défi, son ancien historique de capital, ses stratégies et alertes.\n" +
      "Sera conservé : l'historique d'abonnement (pièce comptable), détaché du compte.\n\n" +
      "Recopiez l'adresse e-mail pour confirmer :", "");
    if (saisie == null) return;
    if (saisie.trim().toLowerCase() !== u.email.toLowerCase()) {
      toast.error("Adresse non conforme — suppression annulée.");
      return;
    }
    const supprimer = async (forcerPass: boolean) => {
      const res = await adminApi.deleteUser(u.user_id, forcerPass);
      const n = (res.data?.supprime ?? {}) as Record<string, number>;
      toast.success(`${u.email} supprimé — ${n.defi_paris ?? 0} pari(s) du défi.`);
      mutate();
    };
    try {
      await supprimer(false);
    } catch (e: unknown) {
      const reponse = (e as { response?: { status?: number; data?: { detail?: string } } })?.response;
      const detail = reponse?.data?.detail;
      // Pass payé encore en cours : seconde confirmation explicite.
      if (reponse?.status === 409 && detail?.includes("forcer_pass")) {
        if (window.confirm(`${detail.split(" Confirmez")[0]}

Supprimer quand même ?`)) {
          try {
            await supprimer(true);
          } catch {
            toast.error("Suppression impossible.");
          }
        }
        return;
      }
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
        desc="Défi du mois, abonnements et actions par compte. Cliquer un nom ouvre sa fiche complète."
        actions={
          <div className="flex flex-wrap gap-2">
            <Link
              href="/admin/defi"
              className="inline-flex min-h-[2.75rem] items-center gap-2 rounded-xl border border-border px-4 text-[13px] font-semibold transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
            >
              <Medal className="h-4 w-4" aria-hidden /> Défi du mois
            </Link>
            <button
              onClick={exporter}
              className="inline-flex min-h-[2.75rem] items-center gap-2 rounded-xl border border-border px-4 text-[13px] font-semibold transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark"
            >
              <Download className="h-4 w-4" aria-hidden /> Export CSV
            </button>
          </div>
        }
      />

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-5 lg:gap-4">
        <Kpi label="Comptes" nombre={resume.total} format={(v) => num(Math.round(v))} icone={<Users className="h-4 w-4" />} accent="violet" />
        <Kpi label="Abonnés" nombre={resume.abonnes} format={(v) => num(Math.round(v))} icone={<CreditCard className="h-4 w-4" />} accent="ok"
          sub={`+ ${num(resume.passEnCours)} pass en cours`} />
        <Kpi label="Joueurs du défi" nombre={resume.parieurs} format={(v) => num(Math.round(v))} icone={<Medal className="h-4 w-4" />} accent="or"
          sub={`${num(resume.classes)} classé${resume.classes > 1 ? "s" : ""} · mois en cours`} />
        <Kpi label="Points misés" nombre={resume.pointsMises} format={(v) => `${num(Math.round(v))} pts`} icone={<Activity className="h-4 w-4" />} accent="bleu"
          sub={`${num(resume.parisJoues)} paris engagés ce mois-ci`} />
        <Kpi label="Suspendus" nombre={resume.suspendus} format={(v) => num(Math.round(v))} icone={<Ban className="h-4 w-4" />} accent={resume.suspendus > 0 ? "rouge" : "neutre"} />
      </div>

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
              const nom = [u.prenom, u.nom].filter(Boolean).join(" ") || u.pseudo || "Sans nom";
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
                    {badgePlan(u)}
                  </button>

                  <div className="mt-2">{celluleAcces(u, "gauche")}</div>

                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
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
                    <Champ label="Défi du mois">
                      {pts(u.defi_solde)}
                      <span className="ml-1 text-xs font-normal text-muted-foreground">
                        {u.defi_rang != null ? `· ${u.defi_rang}${u.defi_rang === 1 ? "er" : "e"}` : "· non classé"}
                      </span>
                    </Champ>
                    <Champ label="Résultat">
                      <span className={tone(u.defi_points_nets)}>{pts(u.defi_points_nets, true)}</span>
                      <span className="ml-1.5">{roiCellule(u)}</span>
                    </Champ>
                    <Champ label="Misé">
                      {u.nb_paris === 0 ? "—" : <>{pts(u.defi_points_mises)} <span className="text-xs font-normal text-muted-foreground">· {u.nb_gagnes}/{u.nb_paris} gagnés</span></>}
                    </Champ>
                    {u.defi_dernier_pari_at && <Champ label="Dernier pari">{formatDateTime(u.defi_dernier_pari_at)}</Champ>}
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
                <table className="w-full min-w-[1040px] border-collapse">
                  <thead>
                    <tr className="border-b border-border">
                      <th className={TH}>Utilisateur</th>
                      <th className={cn(TH, "text-center")}>Plan</th>
                      <th className={cn(TH, "text-center")} title="Abonnement ou pass payé, et jusqu'à quand">Accès payé</th>
                      <th className={cn(TH, "text-right")}>Défi du mois</th>
                      <th className={cn(TH, "text-right")}>Résultat</th>
                      <th className={cn(TH, "text-right")}>Misé</th>
                      <th className={cn(TH, "text-right")}>Activité</th>
                      <th className={cn(TH, "text-center")}>Actions</th>
                    </tr>
                  </thead>
                  <tbody>
                    {liste.map((u) => {
                      const nom = [u.prenom, u.nom].filter(Boolean).join(" ") || u.pseudo || "Sans nom";
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
                          <td className={cn(TD, "text-center")}>{badgePlan(u)}</td>
                          <td className={cn(TD, "text-center")}>{celluleAcces(u)}</td>
                          <td className={cn(TD, "text-right")}>
                            <div className="tabular-nums">{pts(u.defi_solde)}</div>
                            <div className="text-[11px] tabular-nums text-muted-foreground">
                              {u.defi_rang != null ? `${u.defi_rang}${u.defi_rang === 1 ? "er" : "e"} du mois` : "non classé"}
                            </div>
                          </td>
                          <td className={cn(TD, "text-right")}>
                            <div className={cn("font-semibold tabular-nums", tone(u.defi_points_nets))}>{pts(u.defi_points_nets, true)}</div>
                            <div className="text-[11px]">{roiCellule(u)}</div>
                          </td>
                          <td className={cn(TD, "text-right tabular-nums")}>
                            {u.nb_paris === 0 ? <span className="text-muted-foreground">—</span> : (
                              <>
                                <div>{pts(u.defi_points_mises)}</div>
                                <div className="text-[11px] text-muted-foreground">
                                  {u.nb_gagnes}/{u.nb_paris} gagnés{u.defi_nb_en_attente > 0 ? ` · ${u.defi_nb_en_attente} en attente` : ""}
                                </div>
                              </>
                            )}
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
