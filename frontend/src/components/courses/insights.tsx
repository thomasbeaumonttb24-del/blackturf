"use client";

/**
 * Blocs d'information de la fiche course qui exploitent des données déjà
 * produites par l'API mais qu'aucun écran n'affichait :
 *
 *   - `/courses/{id}/paris-disponibles`  → les paris RÉELLEMENT jouables
 *   - `/courses/{id}/confrontations`     → qui a déjà battu qui dans ce champ
 *   - `/courses/{id}/pool-evolution`     → où va l'argent (abonnés)
 *   - `/courses/{id}/temps-passage`      → les fractions, après l'arrivée
 *
 * Chaque bloc est autonome : il charge sa donnée, se tait s'il n'y en a pas
 * (jamais de carte vide ni de « — » décoratif) et n'interrompt jamais la page
 * en cas d'erreur.
 */

import { useEffect, useState } from "react";
import { Check, Loader2, Minus, Sparkles, Swords, Ticket, Timer, TrendingUp, Trophy, Lock, Info } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

/** « 25082026R5C4 » → « R5C4 ». Le code réunion/course est ce que les parieurs lisent. */
const codeCourse = (id: string) => (id.match(/R\d+C\d+$/i)?.[0] ?? id).toUpperCase();

/** Les noms arrivent du PMU EN CAPITALES : illisibles en bloc dans une carte.
 *  Le préfixe « HIPPODROME DE … » est retiré comme partout ailleurs sur le site
 *  (cf. `titleCase` de lib/seo) : c'est « Cabourg », pas « Hippodrome De Cabourg ». */
const titre = (s: string) =>
  s
    .toLowerCase()
    .replace(/(^|[\s'-])([a-zà-ÿ])/g, (_m, p, c) => p + c.toUpperCase())
    .replace(/^Hippodrome (De |Du |D'|Des |La |Le )/i, "")
    .trim();

function Card({ title, icon: Icon, aside, children, className }: {
  title: string;
  icon: typeof Ticket;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={cn("rounded-2xl border border-stone-200 bg-white p-4 sm:p-5", className)}>
      <header className="mb-4 flex items-center gap-2">
        <span className="inline-flex h-8 w-8 items-center justify-center rounded-lg bg-amber-50 text-amber-800 ring-1 ring-amber-200">
          <Icon className="h-4 w-4" aria-hidden="true" />
        </span>
        <h3 className="font-display text-[15px] font-bold text-slate-900">{title}</h3>
        {aside && <div className="ml-auto text-[11px] text-muted-foreground">{aside}</div>}
      </header>
      {children}
    </section>
  );
}

function Chargement() {
  return (
    <div className="flex items-center justify-center py-6 text-xs text-muted-foreground">
      <Loader2 className="mr-2 h-4 w-4 animate-spin" /> Chargement…
    </div>
  );
}

/** Hook de chargement simple : null tant qu'on ne sait pas, `false` si indisponible. */
function useEndpoint<T>(url: string | null): { data: T | null; erreur: number | null; charge: boolean } {
  const [data, setData] = useState<T | null>(null);
  const [erreur, setErreur] = useState<number | null>(null);
  const [charge, setCharge] = useState(false);
  useEffect(() => {
    if (!url) return;
    let vivant = true;
    setCharge(false);
    api.get(url, { tolere401: true })
      .then((r) => { if (vivant) setData(r.data as T); })
      .catch((e) => { if (vivant) setErreur(e?.response?.status ?? 0); })
      .finally(() => { if (vivant) setCharge(true); });
    return () => { vivant = false; };
  }, [url]);
  return { data, erreur, charge };
}

// ─── Paris disponibles ────────────────────────────────────────────────────────
// Le PMU n'offre pas les mêmes paris sur toutes les courses : proposer un 2sur4
// là où il n'existe pas envoie le parieur au guichet pour rien.
interface ParisDispo {
  paris_disponibles: string[];
  designations: {
    est_tierce: boolean; est_quarte: boolean; est_quinte: boolean; est_2sur4: boolean;
    codes_pmu: string[] | null;
  };
}

const PARI_INFO: Record<string, string> = {
  "Simple Gagnant": "Le cheval doit gagner.",
  "Simple Placé": "Le cheval doit finir dans les premiers (2 ou 3 selon le champ).",
  "Couplé Gagnant": "Les 2 chevaux aux 2 premières places, ordre indifférent.",
  "Couplé Placé": "2 de vos chevaux dans les 3 premiers.",
  "Couplé Ordre": "Les 2 chevaux, dans l'ordre exact.",
  "Trio": "Les 3 premiers, ordre indifférent.",
  "Tiercé": "Les 3 premiers ; rapport majoré si l'ordre est exact.",
  "Quarté+": "Les 4 premiers ; rapport majoré dans l'ordre.",
  "Quinté+": "Les 5 premiers ; le pari à gros rapport du jour.",
  "2sur4": "2 chevaux parmi les 4 premiers — le plus accessible des paris combinés.",
  "Multi": "4 à 7 chevaux : vous gagnez si les 4 premiers sont dans votre sélection.",
  "Mini Multi": "Version réduite du Multi, sur les petits champs.",
};

export function ParisDisponiblesCard({ courseId }: { courseId: string }) {
  const { data, charge } = useEndpoint<ParisDispo>(`/courses/${courseId}/paris-disponibles`);
  if (!charge) return null;
  const paris = data?.paris_disponibles ?? [];
  if (paris.length === 0) return null;
  const majeur = (p: string) => ["Quinté+", "Quarté+", "Tiercé", "2sur4", "Multi"].includes(p);

  return (
    <Card title="Paris jouables sur cette course" icon={Ticket} aside={`${paris.length} formules`}>
      <ul className="flex flex-wrap gap-2">
        {paris.map((p) => (
          <li key={p}>
            <span
              title={PARI_INFO[p] ?? undefined}
              className={cn(
                "inline-flex cursor-help items-center rounded-full px-3 py-1.5 text-xs font-semibold ring-1",
                majeur(p)
                  ? "bg-amber-50 text-amber-900 ring-amber-200"
                  : "bg-stone-50 text-slate-700 ring-stone-200",
              )}
            >
              {p}
            </span>
          </li>
        ))}
      </ul>
      <p className="mt-3 flex items-start gap-1.5 text-[11px] leading-4 text-muted-foreground">
        <Info className="mt-px h-3 w-3 shrink-0" aria-hidden="true" />
        Liste tirée des désignations officielles PMU de la course : les formules absentes ne sont
        pas proposées au guichet. Survolez une formule pour sa règle.
      </p>
    </Card>
  );
}

// ─── Confrontations directes ──────────────────────────────────────────────────
interface Paire {
  a_numero: number; a_nom: string; b_numero: number; b_nom: string;
  nb_rencontres: number; a_victoires: number; b_victoires: number;
  derniere_rencontre: { date: string; hippodrome: string; a_position: number | null; b_position: number | null } | null;
}
interface ParCheval {
  numero: number; nom: string; victoires: number; defaites: number; bilan: number;
  top_victime: { nom: string; numero: number; nb: number } | null;
  bete_noire: { nom: string; numero: number; nb: number } | null;
}
interface ConfrontationsResp {
  nb_paires_avec_duel: number;
  paires: Paire[];
  par_cheval: ParCheval[];
}

export function ConfrontationsCard({ courseId }: { courseId: string }) {
  const [tout, setTout] = useState(false);
  const { data, charge } = useEndpoint<ConfrontationsResp>(`/courses/${courseId}/confrontations`);
  if (!charge) return <Card title="Confrontations directes" icon={Swords}><Chargement /></Card>;
  const paires = (data?.paires ?? []).filter((p) => p.nb_rencontres > 0);
  if (paires.length === 0) return null;

  // Les duels les plus fournis d'abord : trois rencontres disent quelque chose,
  // une seule est une anecdote.
  const triees = [...paires].sort((a, b) => b.nb_rencontres - a.nb_rencontres);
  const visibles = tout ? triees : triees.slice(0, 6);
  const bilans = (data?.par_cheval ?? []).filter((c) => c.victoires + c.defaites > 0);
  const meilleur = bilans.length ? [...bilans].sort((a, b) => b.bilan - a.bilan)[0] : null;

  return (
    <Card
      title="Confrontations directes"
      icon={Swords}
      aside={`${data?.nb_paires_avec_duel ?? paires.length} duels déjà courus`}
    >
      {meilleur && meilleur.bilan > 0 && (
        <p className="mb-4 rounded-xl bg-amber-50/70 px-3 py-2.5 text-xs leading-5 text-amber-900 ring-1 ring-amber-100">
          <strong className="font-semibold">N°{meilleur.numero} {meilleur.nom}</strong> a le meilleur bilan
          face à ce champ : {meilleur.victoires} victoire{meilleur.victoires > 1 ? "s" : ""} pour{" "}
          {meilleur.defaites} défaite{meilleur.defaites > 1 ? "s" : ""} en confrontation directe
          {meilleur.top_victime ? ` — dont ${meilleur.top_victime.nb}× devant N°${meilleur.top_victime.numero} ${meilleur.top_victime.nom}` : ""}.
        </p>
      )}

      <ul className="space-y-2">
        {visibles.map((p, i) => {
          const aMene = p.a_victoires > p.b_victoires;
          const bMene = p.b_victoires > p.a_victoires;
          return (
            <li key={i} className="rounded-xl border border-stone-100 bg-stone-50/60 px-3 py-2.5">
              <div className="flex items-center gap-2 text-[13px]">
                <span className={cn("min-w-0 flex-1 truncate", aMene ? "font-semibold text-slate-900" : "text-slate-600")}>
                  N°{p.a_numero} {p.a_nom}
                </span>
                <span className="shrink-0 rounded-md bg-white px-2 py-0.5 font-display text-xs font-bold tabular-nums text-slate-900 ring-1 ring-stone-200">
                  {p.a_victoires} – {p.b_victoires}
                </span>
                <span className={cn("min-w-0 flex-1 truncate text-right", bMene ? "font-semibold text-slate-900" : "text-slate-600")}>
                  {p.b_nom} N°{p.b_numero}
                </span>
              </div>
              {p.derniere_rencontre && (
                <p className="mt-1 text-[11px] text-muted-foreground">
                  Dernière rencontre le{" "}
                  {new Date(p.derniere_rencontre.date).toLocaleDateString("fr-FR", { timeZone: "Europe/Paris", day: "2-digit", month: "short", year: "2-digit" })}
                  {p.derniere_rencontre.a_position && p.derniere_rencontre.b_position
                    ? ` — ${p.derniere_rencontre.a_position}e contre ${p.derniere_rencontre.b_position}e`
                    : ""}
                  {p.nb_rencontres > 1 ? ` · ${p.nb_rencontres} duels au total` : ""}
                </p>
              )}
            </li>
          );
        })}
      </ul>

      {triees.length > 6 && (
        <button
          type="button"
          onClick={() => setTout((v) => !v)}
          className="mt-3 w-full rounded-xl border border-stone-200 py-2 text-xs font-semibold text-slate-700 transition-colors hover:bg-stone-50"
        >
          {tout ? "Réduire" : `Voir les ${triees.length - 6} autres duels`}
        </button>
      )}
    </Card>
  );
}

// ─── Masse des enjeux (pool PMU) ──────────────────────────────────────────────
interface PoolResp {
  evolution: Array<{ time: string; pool_total_eur: number; pool_gagnant_eur: number; nb_parieurs: number | null }>;
  smart_money_alerts: Array<{ time: string; variation_pct: number; pool_eur: number }>;
  dernier_pool_eur: number;
}

export function PoolEvolutionCard({ courseId, poolTotalEur }: { courseId: string; poolTotalEur?: number | null }) {
  const { data, erreur, charge } = useEndpoint<PoolResp>(`/courses/${courseId}/pool-evolution`);

  // Réservé aux abonnés : on le DIT au lieu de masquer la carte, c'est un
  // argument d'abonnement, pas une erreur.
  if (erreur === 401 || erreur === 403) {
    return (
      <Card title="Où va l'argent" icon={TrendingUp}>
        <p className="flex items-start gap-2 text-xs leading-5 text-muted-foreground">
          <Lock className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700" aria-hidden="true" />
          L&apos;évolution de la masse des enjeux — et les afflux soudains qui trahissent l&apos;argent
          averti — sont réservés aux abonnés.
        </p>
      </Card>
    );
  }
  if (!charge) return null;

  const pts = data?.evolution ?? [];
  const dernier = data?.dernier_pool_eur || poolTotalEur || 0;
  if (pts.length < 2 && !dernier) return null;

  const max = Math.max(1, ...pts.map((p) => p.pool_total_eur));
  const premier = pts[0]?.pool_total_eur ?? 0;
  const variation = premier > 0 ? ((dernier - premier) / premier) * 100 : null;
  const alertes = data?.smart_money_alerts ?? [];

  return (
    <Card
      title="Où va l'argent"
      icon={TrendingUp}
      aside={pts.length > 1 ? `${pts.length} relevés` : undefined}
    >
      <div className="flex items-end justify-between gap-4">
        <div>
          <p className="font-display text-2xl font-bold tabular-nums text-slate-900">{nf(dernier)} €</p>
          <p className="mt-1 text-[11px] text-muted-foreground">misés sur cette course (toutes formules)</p>
        </div>
        {variation != null && (
          <span className={cn("rounded-full px-2.5 py-1 text-[11px] font-semibold tabular-nums ring-1",
            variation >= 0 ? "bg-emerald-50 text-emerald-700 ring-emerald-200" : "bg-stone-50 text-slate-600 ring-stone-200")}>
            {variation >= 0 ? "+" : ""}{nf(variation, 0)} % depuis le premier relevé
          </span>
        )}
      </div>

      {pts.length > 1 && (
        <div className="mt-4 flex h-16 items-end gap-[3px]" role="img" aria-label="Évolution de la masse des enjeux">
          {pts.slice(-40).map((p, i) => (
            <div
              key={i}
              className="flex-1 rounded-t bg-gradient-to-t from-amber-200 to-amber-400"
              style={{ height: `${Math.max(4, (p.pool_total_eur / max) * 100)}%` }}
              title={`${new Date(p.time).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })} · ${nf(p.pool_total_eur)} €`}
            />
          ))}
        </div>
      )}

      {alertes.length > 0 && (
        <p className="mt-3 rounded-xl bg-amber-50/70 px-3 py-2 text-[11px] leading-4 text-amber-900 ring-1 ring-amber-100">
          <strong className="font-semibold">Afflux détecté</strong> — {alertes.length} accélération
          {alertes.length > 1 ? "s" : ""} de plus de 20 % de la masse en moins d&apos;un quart d&apos;heure.
          Un pari massif vient d&apos;entrer.
        </p>
      )}
    </Card>
  );
}

// ─── Temps de passage (post-course) ───────────────────────────────────────────
interface TempsPassage {
  numero: number; nom: string;
  passage_400m: number | null; passage_800m: number | null; passage_1000m: number | null;
  passage_1600m: number | null; passage_dernier_400m: number | null;
  vitesse_max_kmh: number | null; position_500m: number | null;
}

export function TempsPassageCard({ courseId }: { courseId: string }) {
  const { data, charge } = useEndpoint<TempsPassage[]>(`/courses/${courseId}/temps-passage`);
  if (!charge) return null;
  const lignes = data ?? [];
  if (lignes.length === 0) return null;

  // On n'affiche que les colonnes réellement renseignées : une colonne de tirets
  // n'apprend rien et donne l'impression d'une donnée manquante.
  const COLONNES: Array<{ cle: keyof TempsPassage; label: string; unite?: string }> = [
    { cle: "passage_400m", label: "400 m" },
    { cle: "passage_800m", label: "800 m" },
    { cle: "passage_1000m", label: "1000 m" },
    { cle: "passage_1600m", label: "1600 m" },
    { cle: "passage_dernier_400m", label: "Dernier 400 m" },
    { cle: "vitesse_max_kmh", label: "V. max", unite: " km/h" },
  ];
  const cols = COLONNES.filter((c) => lignes.some((l) => l[c.cle] != null));
  if (cols.length === 0) return null;

  return (
    <Card title="Temps de passage" icon={Timer} aside={`${lignes.length} chevaux chronométrés`}>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-stone-200 text-[10px] uppercase tracking-wider text-muted-foreground">
              <th scope="col" className="py-2 pr-3 text-left font-semibold">Cheval</th>
              {cols.map((c) => (
                <th key={String(c.cle)} scope="col" className="py-2 px-2 text-right font-semibold whitespace-nowrap">{c.label}</th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-stone-100">
            {lignes.map((l) => (
              <tr key={l.numero}>
                <td className="py-2 pr-3">
                  <span className="font-mono text-xs text-muted-foreground">N°{l.numero}</span>{" "}
                  <span className="font-medium text-slate-900">{l.nom}</span>
                </td>
                {cols.map((c) => {
                  const v = l[c.cle];
                  return (
                    <td key={String(c.cle)} className="px-2 py-2 text-right font-mono text-xs tabular-nums text-slate-700">
                      {typeof v === "number" ? `${nf(v, c.unite ? 1 : 2)}${c.unite ?? ""}` : "—"}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="mt-3 text-[11px] leading-4 text-muted-foreground">
        Fractions relevées pendant la course : elles disent qui a mené, qui a fini vite, et si le
        temps du vainqueur doit beaucoup à un train lent.
      </p>
    </Card>
  );
}

// ─── Compte à rebours avant le départ ─────────────────────────────────────────
// Une heure de départ seule oblige le lecteur à faire la soustraction. Le temps
// restant est l'information qui décide s'il a encore le temps de jouer.
export function CompteurDepart({ dateHeure, statut }: { dateHeure: string; statut: string }) {
  const [restant, setRestant] = useState<number | null>(null);
  useEffect(() => {
    if (statut !== "a_venir") return;
    const calc = () => setRestant(new Date(dateHeure).getTime() - Date.now());
    calc();
    const iv = setInterval(calc, 1000);
    return () => clearInterval(iv);
  }, [dateHeure, statut]);

  if (statut !== "a_venir" || restant == null || restant <= 0) return null;
  const tot = Math.floor(restant / 1000);
  const h = Math.floor(tot / 3600);
  const m = Math.floor((tot % 3600) / 60);
  const s = tot % 60;
  const imminent = tot < 600; // moins de 10 min : le pronostic est figé

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold tabular-nums ring-1",
        imminent ? "bg-rose-50 text-rose-700 ring-rose-200" : "bg-slate-900 text-white ring-slate-900",
      )}
      title={`Départ à ${new Date(dateHeure).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}`}
    >
      <Timer className="h-3.5 w-3.5" aria-hidden="true" />
      {h > 0 ? `${h} h ${String(m).padStart(2, "0")}` : `${m}:${String(s).padStart(2, "0")}`}
      <span className="font-normal opacity-70">avant le départ</span>
    </span>
  );
}

// ─── Aperçu public de l'analyse ───────────────────────────────────────────────
// Le funnel : un visiteur sans abonnement ne voyait que les cotes publiques —
// aucune raison de croire qu'une analyse existe, donc aucune raison de payer.
// Cette carte montre la FORME de l'analyse sans son contenu exploitable :
//   • course à venir  → agrégats anonymes (confiance, accord/désaccord avec le
//     marché, bande de cote du n°1, chevaux écartés, écarts de prix détectés) ;
//     aucun numéro, aucun nom : le pronostic du jour reste payant ;
//   • course terminée → tout est révélé. Elle n'est plus jouable : montrer ce que
//     le modèle avait dit AVANT le départ est la meilleure preuve disponible, et
//     elle est donnée telle quelle, réussie comme ratée.
export interface ApercuLigneApercu {
  rang: number;
  proba_top1: number | null;
  proba_top3: number | null;
  revele: boolean;
  numero?: number;
  nom?: string;
  cote?: number | null;
  cote_juste?: number | null;
  position?: number;
}

export interface ApercuAnalyse {
  disponible: boolean;
  revele: boolean;
  nb_analyses: number;
  confiance: number | null;
  proba_top1: number | null;
  accord_marche: boolean | null;
  bande_cote: string | null;
  nb_ecartes: number;
  nb_value_bets: number;
  ev_max_pct: number | null;
  verdict: {
    arrivee: Array<{ position: number; numero: number; nom: string | null }>;
    top3_modele: Array<{ rang: number; numero: number; nom: string; proba_top1: number | null; cote: number | null }>;
    rang_predit_gagnant: number | null;
    gagnant_top1: boolean;
    gagnant_top3: boolean;
  } | null;
  classement: ApercuLigneApercu[];
  nb_lignes_revelees: number;
}

/** Aperçu public d'une course. `null` en courseId = on ne charge rien (l'abonné
 *  qui a déjà ses prédictions n'a aucune raison de déclencher cet appel). */
export function useApercuAnalyse(courseId: string | null) {
  return useEndpoint<ApercuAnalyse>(courseId ? `/courses/${courseId}/apercu` : null);
}

function Tuile({ valeur, unite, libelle, ton = "neutre" }: {
  valeur: string; unite?: string; libelle: string; ton?: "neutre" | "or" | "vert";
}) {
  const couleur = ton === "or" ? "text-amber-600" : ton === "vert" ? "text-emerald-600" : "text-slate-900";
  return (
    <div className="rounded-xl border border-stone-200 bg-stone-50/60 px-3 py-2.5">
      <div className="flex items-baseline gap-1">
        <span className={cn("font-display text-xl font-bold tabular-nums leading-none", couleur)}>{valeur}</span>
        {unite && <span className="text-[11px] text-muted-foreground">{unite}</span>}
      </div>
      <div className="mt-1.5 text-[11px] leading-tight text-muted-foreground">{libelle}</div>
    </div>
  );
}

export function ApercuAnalyseCard({
  statut, partants, nbPartants, connecte, abonne = false, apercu,
}: {
  statut: string;
  partants: Array<{ numero: number; nom_cheval: string; cote_pmu: number | null; non_partant: boolean }>;
  nbPartants: number;
  connecte: boolean;
  /** Plan payant : la carte ne lui vend rien. Elle n'apparaît chez lui que si le
   *  classement n'a pas pu être chargé — lui montrer un CTA d'abonnement serait
   *  lui réclamer ce qu'il paie déjà. */
  abonne?: boolean;
  /** Chargé une seule fois par la page (`useApercuAnalyse`) et partagé avec la
   *  table du classement : deux appels au même endpoint n'apporteraient rien. */
  apercu: ApercuAnalyse | null;
}) {
  // Preuve chiffrée et réelle : fréquence à laquelle le gagnant sort du top 3 du
  // modèle sur l'historique. `null` tant qu'elle n'est pas mesurable → rien affiché.
  const { data: stats } = useEndpoint<{ precision_top3: number | null }>("/stats/public");

  const cotes = partants
    .filter((p) => !p.non_partant && typeof p.cote_pmu === "number" && (p.cote_pmu as number) > 1)
    .sort((a, b) => (a.cote_pmu as number) - (b.cote_pmu as number));
  const fav = cotes[0];
  const ecart = cotes.length >= 2 ? (cotes[1].cote_pmu as number) / (fav.cote_pmu as number) : null;
  const lectureMarche =
    ecart == null ? null
    : ecart >= 1.8 ? "favori très détaché"
    : ecart >= 1.25 ? "un favori se détache"
    : "cotes de tête serrées";

  // Ni cotes ni analyse : la carte n'aurait rien à dire.
  if (!fav && !apercu?.disponible) return null;

  const v = apercu?.verdict ?? null;
  const revele = Boolean(apercu?.revele && v);
  const precision = stats?.precision_top3 ?? null;
  const phrasePreuve =
    precision != null
      ? ` Sur l'historique vérifié, le gagnant figure dans le top 3 du modèle ${Math.round(precision * 100)} % du temps.`
      : "";

  const cta = revele
    ? { href: connecte ? "/programme" : "/inscription", txt: connecte ? "Voir les courses à venir" : "Essayer 7 jours gratuitement" }
    : connecte
      ? { href: "/tarifs", txt: "Débloquer le pronostic" }
      : { href: "/inscription", txt: "Voir le pronostic — essai 7 jours gratuit" };

  return (
    <Card
      title={revele ? "Ce que le modèle avait dit avant le départ" : "L'analyse de cette course"}
      icon={revele ? Trophy : Sparkles}
      aside="aperçu gratuit"
    >
      {/* Le marché tient en une ligne : la hiérarchie complète des cotes vit dans
          l'onglet Partants — la répéter ici volait la place de l'analyse. */}
      {fav && (
        <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
          <span className="rounded-full bg-slate-900 px-2.5 py-0.5 text-[11px] font-semibold text-white">Marché</span>
          favori N°{fav.numero} {fav.nom_cheval} à {nf(fav.cote_pmu as number, 1)}
          {lectureMarche ? ` · ${lectureMarche}` : ""}
        </p>
      )}

      {/* ═══ Course courue : on lève le voile, résultat réussi comme raté ═══ */}
      {revele && v && (
        <>
          <div className="mt-4 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                "rounded-full px-3 py-1 text-xs font-semibold",
                v.gagnant_top1 ? "bg-emerald-600 text-white"
                : v.gagnant_top3 ? "bg-amber-500 text-white"
                : "bg-stone-200 text-stone-700",
              )}
            >
              {v.gagnant_top1 ? "Gagnant trouvé"
                : v.gagnant_top3 ? "Gagnant dans le top 3"
                : v.rang_predit_gagnant
                  ? `Gagnant classé ${v.rang_predit_gagnant}ᵉ`
                  : "Gagnant hors classement"}
            </span>
            <span className="text-xs text-muted-foreground">
              arrivée : {v.arrivee.map((l) => l.numero).join(" - ")}
            </span>
          </div>

          <ol className="mt-4 space-y-2">
            {v.top3_modele.map((p) => {
              const place = v.arrivee.find((l) => l.numero === p.numero)?.position ?? null;
              return (
                <li
                  key={p.numero}
                  className={cn(
                    "flex items-center gap-3 rounded-xl border px-3 py-2.5",
                    place ? "border-emerald-200 bg-emerald-50/50" : "border-stone-100 bg-stone-50/60",
                  )}
                >
                  <span className="w-5 text-center font-display text-sm font-bold text-stone-400">{p.rang}</span>
                  <span className="font-mono text-xs text-muted-foreground">N°{p.numero}</span>
                  <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-slate-900">{p.nom}</span>
                  {place != null && (
                    <span className="rounded-full bg-emerald-600/10 px-2 py-0.5 text-[11px] font-semibold text-emerald-700">
                      {place === 1 ? "1ᵉʳ" : `${place}ᵉ`} à l&apos;arrivée
                    </span>
                  )}
                  {p.proba_top1 != null && (
                    <span className="font-display text-sm font-bold tabular-nums text-slate-900">
                      {Math.round(p.proba_top1 * 100)}%
                    </span>
                  )}
                </li>
              );
            })}
          </ol>

          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
            <p className="text-[13px] font-semibold text-amber-900">
              Ce classement était affiché sur cette page avant le départ.
            </p>
            <p className="mt-1.5 text-xs leading-5 text-amber-900/80">
              Probabilité de victoire et de place par cheval, cote juste, signaux retenus pour et contre :
              c&apos;est ce que les abonnés lisent sur les courses de ce soir, avant qu&apos;elles ne soient
              courues.{phrasePreuve}
            </p>
            {!abonne && (
              <a
                href={cta.href}
                className="mt-3 inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-amber-500 px-4 text-[13px] font-semibold text-white transition-colors hover:bg-amber-600"
              >
                {cta.txt}
              </a>
            )}
          </div>
        </>
      )}

      {/* ═══ Course à venir : la forme de l'analyse, jamais son contenu ═══ */}
      {!revele && apercu?.disponible && (
        <>
          <div className="mt-4 grid gap-2 sm:grid-cols-3">
            {apercu.confiance != null && (
              <Tuile valeur={String(apercu.confiance)} unite="/ 100" libelle="confiance du modèle sur cette course" />
            )}
            {apercu.proba_top1 != null && (
              <Tuile
                valeur={`${Math.round(apercu.proba_top1 * 100)}%`}
                libelle="chances de victoire de son n°1"
                ton="or"
              />
            )}
            <Tuile
              valeur={String(apercu.nb_value_bets)}
              libelle={
                apercu.nb_value_bets > 0 && apercu.ev_max_pct != null
                  ? `écart prix / probabilité — jusqu'à +${apercu.ev_max_pct} % d'espérance`
                  : "écart prix / probabilité détecté"
              }
              ton={apercu.nb_value_bets > 0 ? "vert" : "neutre"}
            />
          </div>

          {apercu.accord_marche != null && (
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <span
                className={cn(
                  "rounded-full px-3 py-1 text-xs font-semibold",
                  apercu.accord_marche ? "bg-slate-900 text-white" : "bg-amber-500 text-white",
                )}
              >
                {apercu.accord_marche ? "Le modèle confirme le favori" : "Le modèle ne suit pas le marché"}
              </span>
              <span className="text-xs text-muted-foreground">
                {apercu.accord_marche
                  ? "il place le favori des parieurs en tête, avec sa propre probabilité"
                  : `son n°1 n'est pas le favori des parieurs${apercu.bande_cote ? ` — il est coté ${apercu.bande_cote}` : ""}`}
              </span>
            </div>
          )}

          <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
            <p className="text-[13px] font-semibold text-amber-900">
              La cote dit qui les parieurs préfèrent. Elle ne dit pas qui a le plus de chances.
            </p>
            <p className="mt-1.5 text-xs leading-5 text-amber-900/80">
              Sur les {nbPartants} partants, l&apos;algorithme calcule une probabilité par cheval à partir de
              80 critères — forme, terrain, jockey, vitesse, mouvements de cote — puis la compare au prix du
              marché. L&apos;abonnement ouvre les noms, la probabilité de chaque cheval et le plan de mise
              ajusté à votre budget.{phrasePreuve}
            </p>
            {!abonne && (
              <a
                href={cta.href}
                className="mt-3 inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-amber-500 px-4 text-[13px] font-semibold text-white transition-colors hover:bg-amber-600"
              >
                {cta.txt}
              </a>
            )}
          </div>
        </>
      )}

      {/* ═══ Aucune analyse en base : on le dit, sans carte vide ni promesse ═══ */}
      {!revele && apercu && !apercu.disponible && (
        <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
          <p className="text-[13px] font-semibold text-amber-900">
            {statut === "termine"
              ? "Cette course n'a pas été analysée par le modèle."
              : "L'analyse de cette course n'est pas encore publiée."}
          </p>
          <p className="mt-1.5 text-xs leading-5 text-amber-900/80">
            Sur les courses couvertes, l&apos;algorithme calcule une probabilité par cheval à partir de
            80 critères, la compare au prix du marché et en tire un plan de mise sur votre budget.
            {phrasePreuve}
          </p>
          <a
            href={connecte ? "/programme" : "/inscription"}
            className="mt-3 inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-amber-500 px-4 text-[13px] font-semibold text-white transition-colors hover:bg-amber-600"
          >
            {connecte ? "Voir les courses analysées" : "Essayer 7 jours gratuitement"}
          </a>
        </div>
      )}
    </Card>
  );
}

// ─── Ce que le modèle a dit sur les dernières courses courues ─────────────────
// Un prospect qui arrive ici depuis une recherche ne connaît pas le site. Un
// pourcentage global reste abstrait ; six courses réelles, nommées, avec le rang
// que le modèle donnait au gagnant, se vérifient en un clic.
// Les trois règles qui tiennent ce bloc, côté serveur comme ici :
//   • ce sont les courses les PLUS RÉCENTES, jamais les mieux réussies ;
//   • le pronostic était figé avant le départ ;
//   • le compteur global est affiché à côté des exemples — sans lui, montrer
//     six exemples serait un biais du survivant.
interface PreuveCourse {
  course_id: string;
  nom: string | null;
  hippodrome: string;
  date_heure: string | null;
  nb_partants: number | null;
  est_quinte: boolean;
  gagnant_numero: number | null;
  gagnant_nom: string | null;
  rang_du_gagnant: number | null;
  gagnant_top1: boolean;
  gagnant_top3: boolean;
  favori_cote: number | null;
  rapport_gagnant: number | null;
}

interface PreuvesResp {
  courses: PreuveCourse[];
  n_courses: number;
  n_gagnant_top1: number;
  n_gagnant_top3: number;
}

const ordinal = (n: number) => (n === 1 ? "1ᵉʳ" : `${n}ᵉ`);

export function PreuvesRecentesCard() {
  const { data } = useEndpoint<PreuvesResp>("/stats/preuves-recentes?limite=6");
  if (!data || !data.courses?.length) return null;

  const { courses, n_courses, n_gagnant_top1, n_gagnant_top3 } = data;

  return (
    <Card
      title="Ce que le modèle a dit sur les dernières courses"
      icon={Trophy}
      aside="vérifiable, une par une"
    >
      {/* Le compteur AVANT les exemples : c'est lui qui empêche de lire la
          rangée de cartes comme une vitrine de réussites choisies. */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 rounded-xl border border-stone-200 bg-stone-50/70 px-3.5 py-3">
        <span className="flex items-baseline gap-1.5">
          <span className="font-display text-xl font-bold tabular-nums text-emerald-600">{n_gagnant_top1}</span>
          <span className="text-[12px] text-stone-600">gagnants donnés n°1</span>
        </span>
        <span className="h-6 w-px bg-stone-200" aria-hidden="true" />
        <span className="flex items-baseline gap-1.5">
          <span className="font-display text-xl font-bold tabular-nums text-amber-600">{n_gagnant_top3}</span>
          <span className="text-[12px] text-stone-600">gagnants dans le top 3</span>
        </span>
        <span className="h-6 w-px bg-stone-200" aria-hidden="true" />
        <span className="text-[12px] text-stone-500">
          sur les <span className="font-semibold text-slate-900 tabular-nums">{n_courses}</span> dernières
          courses courues — les plus récentes, pas les mieux réussies
        </span>
      </div>

      <ul className="mt-3 flex gap-2.5 overflow-x-auto pb-1.5">
        {courses.map((c) => {
          const rang = c.rang_du_gagnant;
          const ton = c.gagnant_top1
            ? { bd: "border-emerald-200", bg: "bg-emerald-50/60", fg: "text-emerald-700", txt: "gagnant donné 1ᵉʳ" }
            : c.gagnant_top3
              ? { bd: "border-amber-200", bg: "bg-amber-50/60", fg: "text-amber-700", txt: `gagnant donné ${rang ? ordinal(rang) : ""}` }
              : { bd: "border-stone-200", bg: "bg-white", fg: "text-stone-500", txt: rang ? `gagnant donné ${ordinal(rang)}` : "gagnant hors classement" };
          return (
            <li key={c.course_id} className="min-w-[15rem] flex-shrink-0">
              <a
                href={`/courses/${c.course_id}`}
                className={cn(
                  "flex h-full flex-col rounded-xl border p-3 transition-colors hover:border-amber-300",
                  ton.bd, ton.bg,
                )}
              >
                <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                  <span className="font-mono">{codeCourse(c.course_id)}</span>
                  <span className="truncate">{titre(c.hippodrome)}</span>
                  {c.est_quinte && (
                    <span className="ml-auto rounded-full bg-amber-500 px-1.5 py-0.5 text-[9.5px] font-bold text-white">Q+</span>
                  )}
                </span>

                <span className={cn("mt-1.5 flex items-center gap-1 text-[12px] font-semibold", ton.fg)}>
                  {c.gagnant_top3
                    ? <Check className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />
                    : <Minus className="h-3.5 w-3.5 flex-shrink-0" aria-hidden="true" />}
                  {ton.txt}
                </span>

                <span className="mt-1.5 truncate text-[13px] font-semibold text-slate-900">
                  <span className="font-mono text-[11px] font-normal text-muted-foreground">N°{c.gagnant_numero}</span>{" "}
                  {c.gagnant_nom ? titre(c.gagnant_nom) : "—"}
                </span>

                <span className="mt-0.5 text-[11px] text-muted-foreground">
                  {c.nb_partants ? `${c.nb_partants} partants` : ""}
                  {c.rapport_gagnant ? ` · gagnant payé ${nf(c.rapport_gagnant, 2)} pour 1 €` : ""}
                </span>
              </a>
            </li>
          );
        })}
      </ul>

      <p className="mt-2.5 text-[11px] leading-4 text-muted-foreground">
        Chaque carte ouvre la fiche de la course : le classement complet du modèle y est
        affiché, avec la place réelle de chaque cheval. Les courses ratées y figurent comme
        les autres.
      </p>
    </Card>
  );
}
