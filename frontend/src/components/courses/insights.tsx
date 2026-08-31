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
import { Loader2, Swords, Ticket, Timer, TrendingUp, Lock, Info } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const nf = (n: number, d = 0) =>
  n.toLocaleString("fr-FR", { minimumFractionDigits: d, maximumFractionDigits: d });

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
                  {new Date(p.derniere_rencontre.date).toLocaleDateString("fr-FR", { day: "2-digit", month: "short", year: "2-digit" })}
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

// ─── Lecture publique du marché ───────────────────────────────────────────────
// Ce que la page peut montrer à un visiteur sans compte : la hiérarchie des
// cotes, qui est une donnée publique. Elle ne remplace pas le pronostic — elle
// montre précisément ce que le pronostic, lui, apporte en plus.
export function MarcheSnapshotCard({
  partants, nbPartants, connecte,
}: {
  partants: Array<{ numero: number; nom_cheval: string; cote_pmu: number | null; non_partant: boolean }>;
  nbPartants: number;
  connecte: boolean;
}) {
  const cotes = partants
    .filter((p) => !p.non_partant && typeof p.cote_pmu === "number" && (p.cote_pmu as number) > 1)
    .sort((a, b) => (a.cote_pmu as number) - (b.cote_pmu as number));
  if (cotes.length < 3) return null;

  const [fav, deux, trois] = cotes;
  const ecart = (deux.cote_pmu as number) / (fav.cote_pmu as number);
  const lecture =
    ecart >= 1.8 ? { txt: "Favori net", detail: "le marché a désigné un favori très détaché" }
    : ecart >= 1.25 ? { txt: "Favori marqué", detail: "un cheval se détache, sans écraser le lot" }
    : { txt: "Course ouverte", detail: "les cotes de tête sont serrées : rien n'est joué" };

  return (
    <Card title="Ce que dit le marché" icon={TrendingUp} aside="cotes publiques">
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full bg-slate-900 px-3 py-1 text-xs font-semibold text-white">{lecture.txt}</span>
        <span className="text-xs text-muted-foreground">{lecture.detail}</span>
      </div>

      <ol className="mt-4 space-y-2">
        {[fav, deux, trois].map((p, i) => (
          <li key={p.numero} className="flex items-center gap-3 rounded-xl border border-stone-100 bg-stone-50/60 px-3 py-2.5">
            <span className="w-5 text-center font-display text-sm font-bold text-stone-400">{i + 1}</span>
            <span className="font-mono text-xs text-muted-foreground">N°{p.numero}</span>
            <span className="min-w-0 flex-1 truncate text-[13.5px] font-medium text-slate-900">{p.nom_cheval}</span>
            <span className="font-display text-sm font-bold tabular-nums text-slate-900">{nf(p.cote_pmu as number, 1)}</span>
          </li>
        ))}
      </ol>

      <div className="mt-4 rounded-xl border border-amber-200 bg-amber-50/60 p-4">
        <p className="text-[13px] font-semibold text-amber-900">
          La cote dit qui les parieurs préfèrent. Elle ne dit pas qui a le plus de chances.
        </p>
        <p className="mt-1.5 text-xs leading-5 text-amber-900/80">
          Sur les {nbPartants} partants de cette course, l&apos;algorithme calcule une probabilité par cheval
          à partir de 80 critères — forme, terrain, jockey, vitesse, mouvements de cote — puis la compare
          au prix du marché pour repérer les écarts exploitables.
        </p>
        <a
          href={connecte ? "/tarifs" : "/inscription"}
          className="mt-3 inline-flex min-h-10 items-center gap-1.5 rounded-xl bg-amber-500 px-4 text-[13px] font-semibold text-white transition-colors hover:bg-amber-600"
        >
          {connecte ? "Débloquer le pronostic" : "Voir le pronostic — essai 7 jours gratuit"}
        </a>
      </div>
    </Card>
  );
}
