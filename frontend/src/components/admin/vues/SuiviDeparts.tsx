"use client";

/**
 * Qui part, qui ne paie pas, qui abandonne — demande de l'exploitant du 2026-09-16.
 *
 * L'écran des abonnements ne montrait que ceux qui RESTENT (payants, essais en
 * cours, offerts) et trois compteurs sur 30 jours noyés dans le journal. On ne
 * voyait donc ni qui avait résilié, ni qui n'avait pas payé à la fin de ses
 * 7 jours d'essai et était repassé gratuit, ni qui s'était arrêté à l'écran de
 * carte bancaire.
 *
 * Chaque compte passé par Stripe reçoit ici UNE issue (calculée côté serveur,
 * `admin._suivi_essais`) : une personne = une ligne, jamais une ligne par
 * relance de paiement.
 */

import { useState } from "react";
import { UserMinus } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, BarreRepartition, CelluleCompte, Etat, Panneau, Segments, Tableau, depuis, num, pct,
  type Colonne,
} from "../ui";
import type { CheckoutAbandonne, IssueSuivi, ParcoursAbo, SuiviEssais } from "../types";

type Vue = "impayes" | "resiliations" | "partis" | "abandons" | "tous";

const FORMULE: Record<string, string> = { expert: "Expert", pro: "Expert", standard: "Standard", starter: "Standard" };

const dateCourte = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short" }) : "—";

/** Date + ancienneté (dessous), la date exacte au survol. */
function Quand({ iso, futur = false }: { iso: string | null | undefined; futur?: boolean }) {
  if (!iso) return <span className="text-muted-foreground">—</span>;
  const jours = Math.ceil((new Date(iso).getTime() - Date.now()) / 86_400_000);
  return (
    <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap md:flex md:flex-col md:items-start md:gap-0" title={formatDateTime(iso)}>
      {dateCourte(iso)}
      <span className="text-xs text-muted-foreground">
        {futur ? (jours > 0 ? `dans ${jours} j` : "aujourd'hui") : depuis(iso)}
      </span>
    </span>
  );
}

const PARTIS: IssueSuivi[] = ["impaye_perdu", "resilie_pendant_essai", "resilie_apres_paiement", "essai_perdu_sans_carte"];

const ISSUE: Record<IssueSuivi, { label: string; ton: "ok" | "attention" | "alerte" | "neutre" }> = {
  impaye: { label: "Impayé — accès coupé", ton: "alerte" },
  impaye_perdu: { label: "Perdu — impayé", ton: "alerte" },
  resiliation_programmee: { label: "Résiliation en cours", ton: "attention" },
  en_essai: { label: "En essai", ton: "neutre" },
  converti: { label: "Payant", ton: "ok" },
  resilie_pendant_essai: { label: "Parti pendant l'essai", ton: "attention" },
  resilie_apres_paiement: { label: "Client perdu", ton: "alerte" },
  essai_perdu_sans_carte: { label: "Essai sans carte", ton: "neutre" },
};

function detailCompte(p: ParcoursAbo): string {
  const formule = FORMULE[p.formule] ?? p.formule;
  if (p.essai_refuse) return `${formule} · essai refusé (carte déjà utilisée)`;
  if (p.a_eu_essai && p.essai_fin) return `${formule} · essai jusqu'au ${dateCourte(p.essai_fin)}`;
  return formule;
}

const compte: Colonne<ParcoursAbo> = {
  titre: "Compte",
  rendu: (p) => <CelluleCompte email={p.email} detail={detailCompte(p)} />,
  className: "max-w-[300px]",
};

const compteActuel: Colonne<ParcoursAbo> = {
  titre: "Compte aujourd'hui",
  rendu: (p) => <BadgeFormule plan={p.plan_compte} />,
  droite: true,
};

const COLONNES: Record<Exclude<Vue, "abandons">, Colonne<ParcoursAbo>[]> = {
  impayes: [
    compte,
    { titre: "Accès coupé le", rendu: (p) => <Quand iso={p.fin_acces} /> },
    {
      titre: "Prélèvements refusés",
      rendu: (p) => (
        <span className="inline-flex items-baseline gap-1.5 whitespace-nowrap md:flex md:flex-col md:items-start md:gap-0">
          <b className="tabular-nums">{p.echecs_paiement}</b>
          {p.derniere_tentative && <span className="text-xs text-muted-foreground">dernier {depuis(p.derniere_tentative)}</span>}
        </span>
      ),
    },
    {
      titre: "Relances",
      rendu: (p) => (
        <div className="flex flex-col gap-0.5">
          <span className="whitespace-nowrap text-[13px]">
            <b className="tabular-nums">{Math.min(p.relances_faites, 2)}</b>
            <span className="text-muted-foreground"> / 2</span>
          </span>
          {p.prochaine_relance && (
            <span className="whitespace-nowrap text-xs text-muted-foreground" title={formatDateTime(p.prochaine_relance)}>
              prochaine le {dateCourte(p.prochaine_relance)}
            </span>
          )}
        </div>
      ),
    },
    compteActuel,
  ],
  resiliations: [
    compte,
    {
      titre: "Demandée",
      rendu: (p) => (
        <div className="flex flex-col gap-0.5">
          <Quand iso={p.resiliation_le} />
          {p.resiliation_pendant_essai && <span className="text-xs text-amber-700">pendant l&apos;essai</span>}
        </div>
      ),
    },
    { titre: "Accès jusqu'au", rendu: (p) => <Quand iso={p.fin_acces} futur /> },
    {
      titre: "Prélèvement",
      rendu: (p) => p.resiliation_pendant_essai && !p.a_paye
        ? <Etat ton="attention" titre="Résilié avant la fin de l'essai : aucun débit ne partira">Aucun — ne paiera pas</Etat>
        : <Etat ton="neutre">Payé jusqu&apos;à l&apos;échéance</Etat>,
    },
  ],
  partis: [
    compte,
    { titre: "Parti le", rendu: (p) => <Quand iso={p.date_issue} /> },
    {
      titre: "Motif",
      rendu: (p) => p.issue === "impaye_perdu"
        ? <Etat ton="alerte" titre="Prélèvement refusé, puis refusé encore à J+3 et J+7 : abonnement clos">Impayé après 2 relances</Etat>
        : p.issue === "resilie_apres_paiement"
        ? <Etat ton="alerte">Résilié après avoir payé</Etat>
        : p.issue === "essai_perdu_sans_carte"
          ? <Etat ton="neutre">Essai sans carte, expiré</Etat>
          : <Etat ton="attention">Résilié pendant l&apos;essai, jamais payé</Etat>,
    },
    compteActuel,
  ],
  tous: [
    compte,
    {
      titre: "Situation",
      rendu: (p) => (
        <div className="flex flex-col gap-0.5">
          <Etat ton={ISSUE[p.issue].ton}>{ISSUE[p.issue].label}</Etat>
          {p.impaye_regularise && <span className="text-xs text-muted-foreground">après un impayé régularisé</span>}
        </div>
      ),
    },
    { titre: "Depuis", rendu: (p) => <Quand iso={p.date_issue} /> },
    compteActuel,
  ],
};

const COLONNES_ABANDONS: Colonne<CheckoutAbandonne>[] = [
  { titre: "Compte", rendu: (a) => <CelluleCompte email={a.email} />, className: "max-w-[300px]" },
  { titre: "Inscrit le", rendu: (a) => <Quand iso={a.inscrit_le} /> },
  {
    titre: "Dernière connexion",
    rendu: (a) => <span className="whitespace-nowrap text-muted-foreground" title={a.derniere_connexion ? formatDateTime(a.derniere_connexion) : undefined}>{depuis(a.derniere_connexion)}</span>,
  },
  { titre: "Compte aujourd'hui", rendu: (a) => <BadgeFormule plan={a.plan} />, droite: true },
];

/** Chiffre cliquable : ouvre la liste des personnes qu'il compte. */
function Compteur({
  label, valeur, sub, ton, actif, onClick,
}: {
  label: string;
  valeur: string;
  sub: string;
  ton: "alerte" | "attention" | "neutre" | "ok";
  actif: boolean;
  onClick: () => void;
}) {
  const couleur = { alerte: "text-red-700", attention: "text-amber-700", neutre: "text-foreground", ok: "text-emerald-700" }[ton];
  return (
    <button
      type="button"
      onClick={onClick}
      aria-pressed={actif}
      className={cn(
        "min-h-[2.75rem] rounded-xl border p-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        actif ? "border-foreground/40 bg-muted/60" : "border-border/70 hover:bg-muted/40",
      )}
    >
      <div className="text-xs text-muted-foreground">{label}</div>
      <div className={cn("mt-0.5 text-2xl font-semibold leading-tight tabular-nums", couleur)}>{valeur}</div>
      <div className="mt-1 text-xs leading-snug text-muted-foreground">{sub}</div>
    </button>
  );
}

export default function SuiviDeparts({ suivi }: { suivi: SuiviEssais }) {
  const r = suivi.resume;
  const impayes = suivi.comptes.filter((p) => p.issue === "impaye");
  const resiliations = suivi.comptes
    .filter((p) => p.issue === "resiliation_programmee")
    .sort((a, b) => (a.fin_acces ?? "").localeCompare(b.fin_acces ?? ""));
  const partis = suivi.comptes.filter((p) => PARTIS.includes(p.issue));
  const nbPartis = partis.length;
  const perdus = partis.filter((p) => p.issue === "impaye_perdu").length;
  const sansPayer = partis.filter((p) => p.issue === "resilie_pendant_essai" || p.issue === "essai_perdu_sans_carte").length;

  const [vue, setVue] = useState<Vue>(
    impayes.length ? "impayes" : resiliations.length ? "resiliations" : nbPartis ? "partis" : "tous",
  );

  const segments = [
    { key: "impayes", label: `Impayés · ${impayes.length}` },
    { key: "resiliations", label: `Résiliations en cours · ${resiliations.length}` },
    { key: "partis", label: `Partis · ${nbPartis}` },
    { key: "abandons", label: `Carte jamais saisie · ${suivi.checkouts_abandonnes.length}` },
    { key: "tous", label: `Tous · ${suivi.comptes.length}` },
  ] as const;

  const impayesApresEssai = impayes.filter((p) => p.a_eu_essai).length;

  return (
    <Panneau
      titre="Essais, résiliations et impayés"
      icone={<UserMinus className="h-3.5 w-3.5" />}
      actions={r.taux_conversion_essai != null ? (
        <span className="text-xs text-muted-foreground">
          Essais terminés : <b className="text-foreground">{r.essais_convertis} payé{r.essais_convertis > 1 ? "s" : ""} sur {r.essais_termines}</b>
          {" "}({pct(r.taux_conversion_essai, 0)})
        </span>
      ) : undefined}
    >
      <div className="grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <Compteur
          label="Impayés"
          valeur={num(impayes.length)}
          sub={impayes.length
            ? `${impayesApresEssai} en fin d'essai · relancés à J+3 et J+7`
            : "aucun prélèvement en échec"}
          ton={impayes.length ? "alerte" : "neutre"}
          actif={vue === "impayes"}
          onClick={() => setVue("impayes")}
        />
        <Compteur
          label="Résiliations en cours"
          valeur={num(resiliations.length)}
          sub={resiliations.length
            ? `accès jusqu'au ${dateCourte(resiliations[0].fin_acces)} pour la 1re`
            : "personne n'a demandé à partir"}
          ton={resiliations.length ? "attention" : "neutre"}
          actif={vue === "resiliations"}
          onClick={() => setVue("resiliations")}
        />
        <Compteur
          label="Partis"
          valeur={num(nbPartis)}
          sub={nbPartis
            ? [perdus && `${perdus} perdu${perdus > 1 ? "s" : ""} (impayé)`, sansPayer && `${sansPayer} résilié${sansPayer > 1 ? "s" : ""} pendant l'essai`]
              .filter(Boolean).join(" · ")
            : "aucun départ"}
          ton={nbPartis ? "attention" : "neutre"}
          actif={vue === "partis"}
          onClick={() => setVue("partis")}
        />
        <Compteur
          label="Carte jamais saisie"
          valeur={num(r.checkouts_abandonnes)}
          sub="ont ouvert le paiement sans aller au bout"
          ton="neutre"
          actif={vue === "abandons"}
          onClick={() => setVue("abandons")}
        />
      </div>

      {suivi.comptes.length > 0 && (
        <div className="mt-5">
          <div className="mb-2 text-xs font-medium text-muted-foreground">
            Où en sont les {num(suivi.comptes.length)} comptes passés par le paiement
          </div>
          <BarreRepartition
            total={suivi.comptes.length}
            segments={[
              { cle: "converti", label: "Payants", n: r.converti, couleur: "bg-emerald-500" },
              { cle: "en_essai", label: "En essai", n: r.en_essai, couleur: "bg-sky-500" },
              { cle: "resiliation", label: "Résiliation en cours", n: r.resiliation_programmee, couleur: "bg-amber-400" },
              { cle: "impaye", label: "Impayés", n: r.impaye, couleur: "bg-red-500" },
              { cle: "perdus", label: "Perdus (impayé)", n: perdus, couleur: "bg-red-900" },
              { cle: "partis", label: "Résiliés", n: nbPartis - perdus, couleur: "bg-slate-400" },
            ]}
          />
        </div>
      )}

      <div className="mt-5">
        <Segments items={segments} actif={vue} onChange={setVue} taille="compact" />
        <div className="mt-3">
          {vue === "abandons" ? (
            <Tableau
              lignes={suivi.checkouts_abandonnes}
              colonnes={COLONNES_ABANDONS}
              cle={(a) => a.user_id}
              label="Paiements abandonnés"
              vide="Personne ne s'est arrêté à l'écran de carte bancaire."
            />
          ) : (
            <Tableau
              lignes={vue === "impayes" ? impayes : vue === "resiliations" ? resiliations : vue === "partis" ? partis : suivi.comptes}
              colonnes={COLONNES[vue]}
              cle={(p) => p.user_id}
              label={segments.find((s) => s.key === vue)?.label ?? ""}
              vide={{
                impayes: "Aucun impayé : tous les prélèvements sont passés.",
                resiliations: "Aucune résiliation en attente.",
                partis: "Personne n'est parti.",
                tous: "Aucun compte n'est encore passé par le paiement.",
              }[vue]}
            />
          )}
        </div>
      </div>
    </Panneau>
  );
}
