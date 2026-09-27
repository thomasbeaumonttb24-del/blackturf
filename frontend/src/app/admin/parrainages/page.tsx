"use client";

/**
 * Parrainages — qui parraine qui, où en est chaque filleul, ce que le
 * programme coûte et ce qu'il rapporte, et ce qui ressemble à de la triche.
 *
 * Quatre questions, dans cet ordre : combien de parrainages et combien
 * aboutissent ; qui sont les meilleurs parrains ; le détail de chaque lien
 * parrain → filleul ; les anomalies. Un clic sur un compte ouvre sa fiche.
 */

import { useMemo, useState } from "react";
import { AlertTriangle, ArrowRight, Gift, Search, TrendingUp, UserPlus, Users } from "lucide-react";
import { cn, formatDateTime } from "@/lib/utils";
import {
  BadgeFormule, CelluleCompte, EnTetePage, Encart, Etat, GrilleKpi, Kpi, MiniRepartition, Panneau, Puce,
  Segments, Squelette, Tableau, Vide, depuis, eur, num, type Colonne, type Ton,
} from "@/components/admin/ui";
import { useParrainages } from "@/components/admin/data";
import { Fraicheur, useRecuLe } from "@/components/admin/graphes";
import FicheCompte from "@/components/admin/vues/FicheCompte";
import type { LienParrainage, ParrainClassement, ParrainagesData } from "@/components/admin/types";

type Filtre = "tous" | "attente" | "abonnes" | "anomalies";

const montant = (cents: number) => eur(cents / 100, cents % 100 ? 2 : 0);
const jourMois = (iso: string) => new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit" });
const dateCourte = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", year: "numeric" }) : "—";

/** Ton de la pastille selon l'étape du filleul. */
const TON_ETAPE: Record<string, Ton> = {
  credite: "ok",
  reporte: "or",
  verification: "ok",
  paiement_en_cours: "attention",
  attente_paiement: "attention",
  email_a_confirmer: "neutre",
  refuse: "alerte",
  parrain_inactif: "neutre",
  annule: "alerte",
};

const MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."];

/* ───────────────────────────── blocs ───────────────────────────── */

/** Compte cliquable : ouvre la fiche. */
function Compte({ email, detail, userId, onOuvrir }: {
  email: string | null; detail?: React.ReactNode; userId: string | null; onOuvrir: (id: string) => void;
}) {
  if (!userId || !email) return <span className="text-[13px] text-muted-foreground">compte supprimé</span>;
  return (
    <button type="button" onClick={() => onOuvrir(userId)} className="min-w-0 max-w-full rounded-md text-left transition-opacity hover:opacity-75">
      <CelluleCompte email={email} detail={detail} />
    </button>
  );
}

function Evolution({ data }: { data: ParrainagesData["evolution"] }) {
  const max = Math.max(1, ...data.map((m) => m.inscrits));
  return (
    <div>
      <div className="flex h-40 items-end gap-2 sm:gap-4">
        {data.map((m) => {
          const [, mm] = m.mois.split("-");
          return (
            <div key={m.mois} className="flex h-full min-w-0 flex-1 flex-col items-center justify-end gap-1.5">
              <div className="text-[11px] font-semibold tabular-nums text-foreground">{m.inscrits || ""}</div>
              <div className="relative flex w-full max-w-[3.25rem] flex-1 items-end">
                <div
                  className="w-full rounded-t-md bg-[#e8dcc3]"
                  style={{ height: `${(m.inscrits / max) * 100}%`, minHeight: m.inscrits ? 4 : 0 }}
                  title={`${m.inscrits} inscrit(s)`}
                >
                  <div
                    className="absolute bottom-0 w-full rounded-t-md bg-[#0f7b5a]"
                    style={{ height: `${(m.valides / max) * 100}%`, minHeight: m.valides ? 4 : 0 }}
                    title={`${m.valides} abonné(s)`}
                  />
                </div>
              </div>
              <div className="text-[11px] text-muted-foreground">{MOIS[Number(mm) - 1]}</div>
            </div>
          );
        })}
      </div>
      <div className="mt-3 flex flex-wrap gap-4 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-[#e8dcc3]" /> Filleuls inscrits</span>
        <span className="inline-flex items-center gap-1.5"><span className="h-2 w-2 rounded-sm bg-[#0f7b5a]" /> Devenus abonnés</span>
      </div>
    </div>
  );
}

/** Barre « abonnés / inscrits » d'un parrain. */
function Conversion({ p }: { p: ParrainClassement }) {
  const taux = p.filleuls ? (p.valides / p.filleuls) * 100 : 0;
  return (
    <div className="ml-auto w-full min-w-[7rem] max-w-[10rem] md:ml-0">
      <div className="flex items-baseline justify-between text-xs">
        <span className="font-semibold tabular-nums text-foreground">{p.valides} / {p.filleuls}</span>
        <span className="text-muted-foreground tabular-nums">{Math.round(taux)} %</span>
      </div>
      <div className="mt-1 h-1.5 overflow-hidden rounded-full bg-muted">
        <div className="h-full rounded-full bg-[#0f7b5a]" style={{ width: `${Math.max(taux ? 4 : 0, taux)}%` }} />
      </div>
    </div>
  );
}

/* ───────────────────────────── page ───────────────────────────── */

export default function ParrainagesPage() {
  const { data } = useParrainages();
  const recu = useRecuLe(data);
  const [filtre, setFiltre] = useState<Filtre>("tous");
  const [recherche, setRecherche] = useState("");
  const [fiche, setFiche] = useState<string | null>(null);

  const liens = useMemo(() => {
    if (!data) return [];
    const q = recherche.trim().toLowerCase();
    return data.liens.filter((l) => {
      if (filtre === "attente" && l.statut !== "en_attente") return false;
      if (filtre === "abonnes" && l.statut !== "valide") return false;
      if (filtre === "anomalies" && l.statut !== "refuse" && l.statut !== "annule") return false;
      if (!q) return true;
      return [l.parrain.email, l.filleul.email, l.parrain.prenom, l.filleul.prenom]
        .some((v) => (v ?? "").toLowerCase().includes(q));
    });
  }, [data, filtre, recherche]);

  const entete = (
    <EnTetePage
      titre="Parrainages"
      icone={<Gift className="h-4 w-4" />}
      desc="Qui parraine qui, où en est chaque filleul, ce que le programme coûte et ce qu'il rapporte."
      actions={<Fraicheur depuis={recu} cadence={30_000} />}
    />
  );

  if (!data) {
    return (
      <div className="space-y-5 sm:space-y-6">
        {entete}
        <GrilleKpi>{[0, 1, 2, 3].map((i) => <div key={i} className="bt-verre h-[8rem] animate-pulse rounded-xl" />)}</GrilleKpi>
        <Panneau><Squelette lignes={6} /></Panneau>
      </div>
    );
  }

  const s = data.resume;
  const anomalies = s.refuses + s.annules;

  const colonnesParrains: Colonne<ParrainClassement>[] = [
    {
      titre: "Parrain",
      rendu: (p) => (
        <Compte
          email={p.email} userId={p.user_id} onOuvrir={setFiche}
          detail={<>code <span className="font-mono tracking-wider">{p.code ?? "—"}</span></>}
        />
      ),
      className: "max-w-[280px]",
    },
    { titre: "Formule", rendu: (p) => <BadgeFormule plan={p.plan} /> },
    { titre: "Abonnés / inscrits", rendu: (p) => <Conversion p={p} /> },
    {
      titre: "En cours",
      rendu: (p) => (
        <span className="whitespace-nowrap text-[13px]">
          {p.en_attente > 0 ? <Etat ton="attention">{p.en_attente} en attente</Etat> : <span className="text-muted-foreground">—</span>}
          {p.refuses + p.annules > 0 && <span className="ml-2"><Etat ton="alerte">{p.refuses + p.annules} refusé(s)</Etat></span>}
        </span>
      ),
    },
    {
      titre: "Crédits gagnés",
      rendu: (p) => (
        <div className="text-right">
          <div className="font-semibold tabular-nums">{montant(p.gagne_cents)}</div>
          {p.reportes > 0 && <div className="text-[11px] text-amber-700">dont {p.reportes} reporté(s)</div>}
        </div>
      ),
      droite: true,
    },
    {
      titre: "Payé par ses filleuls",
      rendu: (p) => <span className="font-semibold tabular-nums text-emerald-700">{montant(p.ca_filleuls_cents)}</span>,
      droite: true,
    },
    {
      titre: "Dernier filleul",
      rendu: (p) => <span className="whitespace-nowrap text-muted-foreground" title={p.dernier_filleul_at ? formatDateTime(p.dernier_filleul_at) : undefined}>{depuis(p.dernier_filleul_at)}</span>,
      droite: true,
    },
  ];

  const colonnesLiens: Colonne<LienParrainage>[] = [
    {
      titre: "Parrain → filleul",
      rendu: (l) => (
        <div className="flex min-w-0 flex-col gap-1.5 lg:flex-row lg:items-center lg:gap-2">
          <Compte email={l.parrain.email} userId={l.parrain.user_id} onOuvrir={setFiche} />
          <ArrowRight className="hidden h-4 w-4 shrink-0 text-muted-foreground lg:block" aria-hidden />
          <Compte email={l.filleul.email} userId={l.filleul.user_id} onOuvrir={setFiche} />
        </div>
      ),
      className: "max-w-[520px]",
    },
    {
      titre: "Étape",
      rendu: (l) => (
        <div>
          <Etat ton={TON_ETAPE[l.etape] ?? "neutre"} titre={l.etape_libelle}>{l.etape_libelle.split(" — ")[0]}</Etat>
          {(l.motif_libelle || l.etape_libelle.includes(" — ")) && (
            <div className="mt-0.5 max-w-[18rem] text-[11px] leading-snug text-muted-foreground">
              {l.motif_libelle ?? l.etape_libelle.split(" — ")[1]}
            </div>
          )}
        </div>
      ),
    },
    {
      titre: "Remise / crédit",
      rendu: (l) => (
        <div className="space-y-0.5 whitespace-nowrap text-[11px] leading-snug">
          <div className={l.remise_filleul_at ? "text-foreground" : "text-muted-foreground"}>
            Filleul : {l.remise_filleul_at ? `−5 € le ${jourMois(l.remise_filleul_at)}` : "remise pas encore utilisée"}
          </div>
          <div className={l.credit_pose_at ? "font-medium text-emerald-700" : "text-muted-foreground"}>
            Parrain : {l.credit_pose_at ? `+5 € le ${jourMois(l.credit_pose_at)}`
              : l.statut === "valide" ? "+5 € gagnés, pose à venir" : "rien pour l'instant"}
          </div>
        </div>
      ),
    },
    {
      titre: "Payé par le filleul",
      rendu: (l) => l.paye_filleul_cents
        ? <span className="font-semibold tabular-nums">{montant(l.paye_filleul_cents)}</span>
        : <span className="text-muted-foreground">—</span>,
      droite: true,
    },
    {
      titre: "Inscrit",
      rendu: (l) => <span className="whitespace-nowrap text-muted-foreground" title={formatDateTime(l.created_at)}>{dateCourte(l.created_at)}</span>,
      droite: true,
    },
  ];

  const filtres = [
    { key: "tous", label: `Tous · ${data.liens.length}` },
    { key: "attente", label: `En attente · ${s.en_attente}` },
    { key: "abonnes", label: `Abonnés · ${s.valides}` },
    { key: "anomalies", label: `Refusés / annulés · ${anomalies}` },
  ] as const;

  return (
    <div className="space-y-5 sm:space-y-6">
      {entete}

      {anomalies > 0 && (
        <Encart ton="attention" icone={<AlertTriangle className="h-4 w-4" />}>
          <b>{anomalies} parrainage{anomalies > 1 ? "s" : ""} refusé{anomalies > 1 ? "s" : ""} ou annulé{anomalies > 1 ? "s" : ""}</b>
          {" "}(carte déjà utilisée, auto-parrainage, remboursement ou litige).{" "}
          <button type="button" onClick={() => setFiltre("anomalies")} className="font-semibold underline underline-offset-2">
            Voir le détail
          </button>
        </Encart>
      )}

      <GrilleKpi>
        <Kpi
          label="Parrains actifs"
          nombre={s.parrains_actifs}
          format={(v) => num(Math.round(v))}
          sub={`${num(s.liens_generes)} compte${s.liens_generes > 1 ? "s ont ouvert leur" : " a ouvert son"} lien de parrainage`}
          icone={<Users className="h-4 w-4" />}
          accent="or"
        />
        <Kpi
          label="Filleuls inscrits"
          nombre={s.filleuls}
          format={(v) => num(Math.round(v))}
          sub={<MiniRepartition parts={[
            { label: "Abonnés", n: s.valides, couleur: "#0f7b5a" },
            { label: "En attente", n: s.en_attente, couleur: "#d9a441" },
            { label: "Refusés", n: anomalies, couleur: "#b42318" },
          ]} />}
          icone={<UserPlus className="h-4 w-4" />}
          accent="bleu"
        />
        <Kpi
          label="Taux de conversion"
          valeur={s.taux_conversion == null ? "—" : `${s.taux_conversion.toLocaleString("fr-FR")} %`}
          sub={`${num(s.valides)} filleul${s.valides > 1 ? "s" : ""} devenu${s.valides > 1 ? "s" : ""} abonné${s.valides > 1 ? "s" : ""}`}
          icone={<TrendingUp className="h-4 w-4" />}
          accent="ok"
        />
        <Kpi
          label="Payé par les filleuls"
          nombre={s.ca_filleuls_cents / 100}
          format={(v) => eur(v)}
          sub={
            <>
              Coût : {montant(s.cout_total_cents)} ({montant(s.remises_filleuls_cents)} de remises
              {" "}+ {montant(s.credits_parrains_cents)} de crédits)
              {s.rendement != null && <div className="mt-1 font-semibold text-emerald-700">× {s.rendement.toLocaleString("fr-FR")} ce que le programme coûte</div>}
            </>
          }
          icone={<Gift className="h-4 w-4" />}
          accent="violet"
        />
      </GrilleKpi>

      <div className="grid gap-5 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] sm:gap-6">
        <Panneau titre="Six derniers mois" desc="Filleuls inscrits chaque mois, et combien sont devenus abonnés.">
          <Evolution data={data.evolution} />
        </Panneau>

        <Panneau
          titre="Classement des parrains"
          desc="Du parrain qui a amené le plus d'abonnés au moins actif."
          actions={<Puce>{num(data.parrains.length)} parrain{data.parrains.length > 1 ? "s" : ""}</Puce>}
        >
          {data.parrains.length === 0 ? (
            <Vide>Aucun parrainage pour l&apos;instant.</Vide>
          ) : (
            <ol className="space-y-2">
              {data.parrains.slice(0, 5).map((p, i) => (
                <li key={p.user_id} className="flex items-center gap-3 rounded-lg border border-border/60 px-3 py-2.5">
                  <span className={cn(
                    "flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-bold",
                    i === 0 ? "bg-[#faf3e4] text-[#7a5412] ring-1 ring-[#ecd9b0]" : "bg-muted text-muted-foreground",
                  )}>{i + 1}</span>
                  <div className="min-w-0 flex-1"><Compte email={p.email} userId={p.user_id} onOuvrir={setFiche} /></div>
                  <div className="shrink-0 text-right">
                    <div className="text-[13px] font-semibold tabular-nums">{p.valides} abonné{p.valides > 1 ? "s" : ""}</div>
                    <div className="text-[11px] text-muted-foreground">{p.filleuls} inscrit{p.filleuls > 1 ? "s" : ""} · {montant(p.gagne_cents)}</div>
                  </div>
                </li>
              ))}
            </ol>
          )}
        </Panneau>
      </div>

      <Panneau titre="Tous les parrains" desc="Un clic sur un compte ouvre sa fiche." bodyClassName="p-4 sm:p-5">
        <Tableau
          lignes={data.parrains}
          colonnes={colonnesParrains}
          cle={(p) => p.user_id}
          label="Parrains"
          vide="Aucun parrain pour l'instant."
        />
      </Panneau>

      <Panneau bodyClassName="p-0 sm:p-0">
        <div className="flex flex-col gap-3 border-b border-border/80 p-3 sm:flex-row sm:items-center sm:justify-between sm:px-4">
          <div>
            <h2 className="text-[15px] font-semibold tracking-tight">Qui parraine qui</h2>
            <p className="text-xs text-muted-foreground">Chaque lien parrain → filleul, avec son étape exacte.</p>
          </div>
          <label className="relative block sm:w-72">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" aria-hidden />
            <input
              value={recherche}
              onChange={(e) => setRecherche(e.target.value)}
              placeholder="Rechercher un e-mail ou un prénom"
              className="h-9 w-full rounded-lg border border-border bg-white pl-8 pr-3 text-[13px] outline-none focus:ring-2 focus:ring-ring"
            />
          </label>
        </div>
        <div className="border-b border-border/80 p-2 sm:px-4">
          <Segments items={filtres} actif={filtre} onChange={setFiltre} className="border-0 bg-transparent p-0 shadow-none" />
        </div>
        <div className="p-4 sm:p-5">
          <Tableau
            lignes={liens}
            colonnes={colonnesLiens}
            cle={(l) => l.parrainage_id}
            label="Parrainages"
            vide={recherche ? "Aucun parrainage ne correspond à cette recherche." : "Aucun parrainage dans cette catégorie."}
            limite={20}
          />
        </div>
      </Panneau>

      {fiche && <FicheCompte userId={fiche} onClose={() => setFiche(null)} />}
    </div>
  );
}
