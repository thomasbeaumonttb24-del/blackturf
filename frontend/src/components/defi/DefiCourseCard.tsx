"use client";

/**
 * Défi du mois sur une course : engager un pari en points, voir ses paris et la
 * tendance des joueurs.
 *
 * Ouvert à TOUT compte connecté, sans quota et sans afficher le plan de mise : un
 * compte gratuit qui a épuisé son plan du jour joue ici ses propres chevaux. Le
 * serveur décide seul de la limite de dépôt, du rapport, du résultat et de
 * l'étiquette « Plan BlackTurf » / « Perso ».
 */

import { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import { toast } from "sonner";
import { ArrowRight, Calculator, Check, Info, Loader2, Lock, ShieldCheck, Sparkles, Ticket, TrendingUp, Users, Zap } from "lucide-react";
import { defiApi, type DefiCourse, type DefiPlanPari, type DefiRegles, type DefiTypeInfo, type DefiTypePari } from "@/lib/api";
import { CompteGratuitCta } from "@/components/billing/CompteGratuitCta";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import {
  BandeauEssai, CompteRebours, DEFI_CARTE, DEFI_REGLES_DEFAUT, DefiEntete, OriginePari, ResultatPari, StatutPari, chevauxLisibles, combinaisons, estAOrdre,
  dateLancement, formatPts, moisLabel, planLabel, formatNombre } from "@/components/defi/kit";
import { cn } from "@/lib/utils";

export type DefiPrefill = { type: DefiTypePari; chevaux: number[]; cle: number };

type PartantDefi = { numero: number; nom_cheval: string; non_partant?: boolean; cote_pmu?: number | null };

const PALIERS = [10, 25, 50, 100];

function detailErreur(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Le pari n'a pas pu être enregistré.";
}

/** Titre d'étape numéroté, identique pour les trois étapes. */
function Etape({ n, titre, droite, children }: { n: number; titre: string; droite?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="border-t border-stone-100 px-5 py-4 first:border-t-0">
      <div className="mb-3 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-[13px] font-bold text-slate-900">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-gradient-to-b from-amber-400 to-amber-600 text-[11px] font-bold text-white shadow-[inset_0_1px_0_rgba(255,255,255,.4)]">{n}</span>
          {titre}
        </h4>
        {droite}
      </div>
      {children}
    </section>
  );
}

const NIVEAUX: Record<string, { icone: typeof ShieldCheck; classe: string }> = {
  securite: { icone: ShieldCheck, classe: "bg-emerald-50 text-emerald-800 ring-emerald-200" },
  rendement: { icone: TrendingUp, classe: "bg-amber-50 text-amber-800 ring-amber-200" },
  coup: { icone: Zap, classe: "bg-rose-50 text-rose-800 ring-rose-200" },
};

/** Même ticket ? (l'ordre ne compte que pour les paris à l'ordre) */
function memeTicket(a: { type: string; chevaux: number[] }, type: string, chevaux: number[], ordre: boolean) {
  if (a.type !== type || a.chevaux.length !== chevaux.length) return false;
  const x = ordre ? a.chevaux : [...a.chevaux].sort((m, n) => m - n);
  const y = ordre ? chevaux : [...chevaux].sort((m, n) => m - n);
  return x.every((v, i) => v === y[i]);
}

/**
 * Les paris du plan de mise que le joueur a DÉJÀ consulté sur cette course, à
 * jouer d'un clic. Rien n'est révélé ici : sans plan consulté, la liste est vide.
 */
function PlanConsulte({ paris, types, onJouer, actif }: {
  paris: DefiPlanPari[];
  types: DefiTypeInfo[];
  onJouer: (p: DefiPlanPari) => void;
  actif: (p: DefiPlanPari) => boolean;
}) {
  return (
    <section className="border-b border-stone-100 bg-gradient-to-b from-amber-50/60 to-transparent px-5 py-4">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <h4 className="flex items-center gap-2 text-[13px] font-bold text-slate-900">
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-white text-amber-700 ring-1 ring-inset ring-amber-200">
            <Sparkles className="h-3.5 w-3.5" aria-hidden="true" />
          </span>
          Votre plan BlackTurf sur cette course
        </h4>
        <span className="text-[11px] text-slate-500">Un clic pour le reprendre</span>
      </div>
      <ul className="flex flex-col gap-1.5">
        {paris.map((p) => {
          const niv = NIVEAUX[p.niveau ?? ""];
          const Icone = niv?.icone ?? Calculator;
          const ordre = types.find((t) => t.type === p.type)?.ordre ?? false;
          const choisi = actif(p);
          return (
            <li key={`${p.libelle}-${p.chevaux.join("-")}`}
              className={cn("flex flex-wrap items-center gap-2 rounded-xl bg-white px-3 py-2 ring-1 ring-inset transition-all",
                choisi ? "ring-2 ring-amber-500" : "ring-stone-200")}>
              {p.niveau_label && (
                <span className={cn("inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[10.5px] font-bold ring-1 ring-inset", niv?.classe ?? "bg-stone-50 text-slate-600 ring-stone-200")}>
                  <Icone className="h-3 w-3" aria-hidden="true" /> {p.niveau_label}
                </span>
              )}
              <span className="text-[12.5px] font-bold text-slate-900">{p.libelle}</span>
              <span className="flex flex-wrap items-center gap-1">
                {p.chevaux.map((n, i) => (
                  <span key={n} className="inline-flex items-center gap-1">
                    {i > 0 && <span className="text-[11px] text-slate-400">{ordre ? "–" : "+"}</span>}
                    <CasaqueNumero numero={n} />
                  </span>
                ))}
              </span>
              <span className="ml-auto">
                {p.deja_joue ? (
                  <span className="inline-flex items-center gap-1 rounded-full bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-700 ring-1 ring-inset ring-emerald-200">
                    <Check className="h-3 w-3" aria-hidden="true" /> Joué
                  </span>
                ) : (
                  <button type="button" onClick={() => onJouer(p)} aria-pressed={choisi}
                    className={cn("inline-flex min-h-[34px] items-center gap-1 rounded-lg px-3 text-[12px] font-bold ring-1 ring-inset transition-colors",
                      choisi ? "bg-amber-600 text-white ring-amber-700" : "bg-amber-50 text-amber-900 ring-amber-300 hover:bg-amber-100")}>
                    {choisi ? <><Check className="h-3.5 w-3.5" aria-hidden="true" /> Sélectionné</> : "Jouer ce pari"}
                  </button>
                )}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export function DefiCourseCard({ courseId, partants, connecte, prefill, voirPlan }: {
  courseId: string;
  partants: PartantDefi[];
  connecte: boolean;
  prefill?: DefiPrefill | null;
  /** Ouvre l'onglet Plan de mise (lien affiché tant qu'aucun plan n'est consulté). */
  voirPlan?: () => void;
}) {
  const { data: regles = DEFI_REGLES_DEFAUT as unknown as DefiRegles } = useSWR(
    "/defi/regles", () => defiApi.regles().then((r) => r.data), { revalidateOnFocus: false });
  const { data, mutate, isLoading } = useSWR<DefiCourse>(
    connecte ? ["/defi/course", courseId] : null,
    () => defiApi.course(courseId).then((r) => r.data),
    { refreshInterval: 30_000 },
  );

  const [typeChoisi, setType] = useState<DefiTypePari>("Simple Gagnant");
  const [chevaux, setChevaux] = useState<number[]>([]);
  const [points, setPoints] = useState(25);
  const [envoi, setEnvoi] = useState(false);
  const carteRef = useRef<HTMLDivElement>(null);

  // Venu d'un ticket du plan de mise : on pré-remplit, le joueur garde la main
  // sur les points et valide lui-même.
  useEffect(() => {
    if (!prefill) return;
    setType(prefill.type);
    setChevaux(prefill.chevaux);
    carteRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
  }, [prefill]);

  // Paris ouverts par le PMU sur CETTE course (le serveur fait foi). Si le type
  // choisi n'y est pas (course à champ réduit, ticket du plan non proposé…), on
  // retombe sur le premier disponible.
  const types = useMemo(() => data?.types ?? [], [data?.types]);
  const spec = types.find((t) => t.type === typeChoisi) ?? types[0];
  const type = spec?.type ?? typeChoisi;
  const min = spec?.min ?? 1;
  const max = spec?.max ?? 1;
  const aOrdre = spec?.ordre ?? false;
  const familles = useMemo(() => {
    const m = new Map<string, DefiTypeInfo[]>();
    for (const t of types) m.set(t.famille, [...(m.get(t.famille) ?? []), t]);
    return [...m.entries()];
  }, [types]);
  const prefillRefuse = !!prefill && types.length > 0 && !types.some((t) => t.type === prefill.type);
  const nomTicket = type === "Multi" ? `${spec?.libelle ?? "Multi"} en ${Math.max(min, chevaux.length)}` : type;
  const nbCombis = combinaisons(type, chevaux.length);
  const jouables = useMemo(() => partants.filter((p) => !p.non_partant).sort((a, b) => a.numero - b.numero), [partants]);
  const mesParis = data?.mes_paris ?? [];
  const restants = regles.max_paris_par_course - mesParis.length;
  const solde = data?.solde ?? null;
  const pointsMax = Math.min(regles.points_max, Math.max(0, Math.floor(solde ?? regles.points_max)));
  const pointsJoues = Math.min(points, pointsMax);
  const pret = chevaux.length >= min && chevaux.length <= max && pointsJoues >= regles.points_min;
  const prix = regles.recompenses?.[0];
  const mois = data ? moisLabel(data.mois) : null;

  const planConsulte = data?.plan ?? [];
  const correspondPlan = planConsulte.some((p) => memeTicket(p, type, chevaux, aOrdre));

  function jouerDuPlan(p: DefiPlanPari) {
    setType(p.type);
    setChevaux(p.chevaux);
  }

  function choisirType(t: DefiTypeInfo) {
    setType(t.type);
    setChevaux((c) => c.slice(0, t.max));
  }

  // Cliquer un cheval l'ajoute à la fin (donc à la place suivante pour un pari à
  // l'ordre) ; le recliquer le retire. Un pari à un cheval remplace le choix.
  function basculer(n: number) {
    setChevaux((c) => {
      if (c.includes(n)) return c.filter((x) => x !== n);
      if (max === 1) return [n];
      return c.length >= max ? c : [...c, n];
    });
  }

  async function valider() {
    if (!pret || envoi) return;
    setEnvoi(true);
    try {
      const { data: pari } = await defiApi.engager({ course_id: courseId, type_pari: type, chevaux, points: pointsJoues });
      toast.success(`Pari validé : ${pari.points} pts sur ${pari.type_pari} ${chevauxLisibles(pari.type_pari, pari.chevaux)}`);
      setChevaux([]);
      await mutate();
    } catch (e) {
      toast.error(detailErreur(e));
      await mutate();
    } finally {
      setEnvoi(false);
    }
  }

  // Estimation indicative pour un Simple Gagnant : la cote PMU du moment. Le
  // rapport officiel à l'arrivée fait foi, on le dit en toutes lettres.
  const coteIndicative = type === "Simple Gagnant" && chevaux.length === 1
    ? jouables.find((p) => p.numero === chevaux[0])?.cote_pmu ?? null : null;

  return (
    <div ref={carteRef} className={DEFI_CARTE} style={{ scrollMarginTop: 120 }}>
      <DefiEntete
        surtitre={mois ? `Défi du mois · ${mois}` : "Défi du mois"}
        titre="Pariez vos points sur cette course"
        sousTitre={(data?.essai ?? regles.essai) ? <>Points × rapport PMU officiel. Mois d&apos;essai : récompenses dès le {dateLancement(regles.premier_mois)}.</>
          : prix && <>Points × rapport PMU officiel. Le 1<sup>er</sup> du mois gagne {prix.jours} jours {planLabel(prix.plan)}.</>}
        droite={connecte && solde != null ? (
          <div className="rounded-2xl bg-white/90 px-3 py-1.5 text-right shadow-sm ring-1 ring-inset ring-amber-200">
            <div className="text-[9.5px] font-bold uppercase tracking-[0.14em] text-amber-700">Mon solde</div>
            <div className="font-display text-[17px] font-bold tabular-nums text-slate-900">{formatPts(solde)}</div>
          </div>
        ) : undefined}
      />

      {!connecte ? (
        <div className="p-5">
          <CompteGratuitCta
            titre="Jouez le Défi du mois"
            texte={`${formatNombre(regles.capital_mensuel, 2)} points offerts chaque mois pour parier sur les courses. Le meilleur solde remporte un abonnement offert.`}
            avantages={[
              `${formatNombre(regles.capital_mensuel, 2)} points renouvelés chaque 1er du mois`,
              "Vos propres chevaux, ou ceux du plan de mise",
              "Classement en direct après chaque arrivée",
              "Aucun argent réel en jeu",
            ]}
            suite={`/courses/${courseId}#defi`}
          />
        </div>
      ) : isLoading || !data ? (
        <div className="flex justify-center py-10"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
      ) : (
        <>
          {data.essai && <BandeauEssai premierMois={regles.premier_mois} className="mx-5 mt-4" />}
          {data.ouvert && restants > 0 && pointsMax >= regles.points_min ? (
            <>
              {planConsulte.length > 0 ? (
                <PlanConsulte paris={planConsulte} types={types} onJouer={jouerDuPlan}
                  actif={(p) => memeTicket(p, type, chevaux, types.find((t) => t.type === p.type)?.ordre ?? false)} />
              ) : voirPlan && (
                <div className="flex flex-wrap items-center justify-between gap-2 border-b border-stone-100 px-5 py-3 text-[12px] text-slate-600">
                  <span className="inline-flex items-center gap-1.5">
                    <Calculator className="h-3.5 w-3.5 text-amber-700" aria-hidden="true" />
                    Besoin d&apos;une idée ? Le plan de mise propose des paris pour cette course.
                  </span>
                  <button type="button" onClick={voirPlan} className="inline-flex items-center gap-0.5 font-semibold text-amber-800 hover:underline">
                    Voir le plan <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                  </button>
                </div>
              )}
              <Etape n={1} titre="Type de pari"
                droite={<span className="text-[11px] text-slate-500">{types.length} pari{types.length > 1 ? "s" : ""} ouvert{types.length > 1 ? "s" : ""} sur cette course</span>}>
                {prefillRefuse && (
                  <p className="mb-3 rounded-xl bg-amber-50 px-3 py-2 text-[12px] text-amber-900 ring-1 ring-inset ring-amber-200">
                    Le {prefill?.type} n&apos;est pas ouvert par le PMU sur cette course : choisissez un autre pari.
                  </p>
                )}
                <div className="space-y-3">
                  {familles.map(([famille, liste]) => (
                    <div key={famille}>
                      <div className="mb-1.5 text-[10.5px] font-bold uppercase tracking-[0.12em] text-slate-400">{famille}</div>
                      <div className="flex flex-wrap gap-1.5">
                        {liste.map((t) => {
                          const actif = type === t.type;
                          return (
                            <button key={t.type} type="button" onClick={() => choisirType(t)} aria-pressed={actif}
                              className={cn("inline-flex min-h-[40px] items-center gap-1.5 rounded-xl px-3 text-[12.5px] font-semibold ring-1 ring-inset transition-all",
                                actif ? "bg-gradient-to-b from-amber-50 to-amber-100 text-amber-950 ring-2 ring-amber-500" : "bg-white text-slate-700 ring-stone-200 hover:bg-stone-50")}>
                              {actif && <Check className="h-3.5 w-3.5 text-amber-700" aria-hidden="true" />}
                              {t.type === "Multi" ? t.libelle ?? "Multi" : t.type}
                            </button>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
                {spec && (
                  <div className="mt-3 flex items-start gap-2.5 rounded-xl bg-stone-50 px-3 py-2.5 ring-1 ring-inset ring-stone-200">
                    <Info className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-700" aria-hidden="true" />
                    <div className="text-[12px] leading-relaxed text-slate-700">
                      <b className="text-slate-900">{type === "Multi" ? spec.libelle ?? "Multi" : type}</b> · {spec.aide}
                      <div className="mt-1 flex flex-wrap gap-1.5">
                        <span className="rounded-full bg-white px-2 py-0.5 text-[10.5px] font-semibold text-slate-600 ring-1 ring-inset ring-stone-200">
                          {min === max ? `${min} cheva${min > 1 ? "ux" : "l"}` : `${min} à ${max} chevaux`}
                        </span>
                        {aOrdre && <span className="rounded-full bg-amber-50 px-2 py-0.5 text-[10.5px] font-semibold text-amber-800 ring-1 ring-inset ring-amber-200">L&apos;ordre compte</span>}
                      </div>
                    </div>
                  </div>
                )}
              </Etape>

              <Etape n={2}
                titre={min === max ? (min === 1 ? "Votre cheval" : `Vos ${min} chevaux`) : `De ${min} à ${max} chevaux`}
                droite={
                  <span className="inline-flex items-center gap-2">
                    {chevaux.length > 0 && (
                      <button type="button" onClick={() => setChevaux([])} className="text-[11px] font-semibold text-slate-500 underline-offset-2 hover:underline">
                        Effacer
                      </button>
                    )}
                    <span className={cn("rounded-full px-2 py-0.5 text-[11px] font-bold tabular-nums",
                      chevaux.length >= min ? "bg-emerald-50 text-emerald-700" : "bg-stone-100 text-slate-600")}>
                      {chevaux.length}/{max}
                    </span>
                  </span>
                }>
                {aOrdre && (
                  <p className="mb-2.5 text-[11.5px] leading-snug text-slate-600">
                    Cliquez dans l&apos;<b className="text-slate-800">ordre d&apos;arrivée</b> que vous jouez : 1<sup>er</sup>, 2<sup>e</sup>… Recliquez un cheval pour le retirer.
                  </p>
                )}
                <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                  {jouables.map((p) => {
                    const place = chevaux.indexOf(p.numero);
                    const actif = place >= 0;
                    const plein = !actif && max > 1 && chevaux.length >= max;
                    return (
                      <button key={p.numero} type="button" onClick={() => basculer(p.numero)} aria-pressed={actif} disabled={plein}
                        className={cn("relative flex min-h-[48px] items-center gap-2 rounded-xl px-2.5 py-1.5 text-left ring-1 ring-inset transition-all disabled:cursor-not-allowed disabled:opacity-40",
                          actif ? "bg-amber-50 ring-2 ring-amber-500" : "bg-white ring-stone-200 hover:bg-stone-50")}>
                        <CasaqueNumero numero={p.numero} />
                        <span className="min-w-0 flex-1">
                          <span className="block break-words text-[12px] font-semibold leading-tight text-slate-800">{p.nom_cheval}</span>
                          {p.cote_pmu != null && <span className="block text-[10.5px] tabular-nums text-slate-500">cote {formatNombre(p.cote_pmu, 2)}</span>}
                        </span>
                        {actif && max > 1 && (
                          <span className="absolute -right-1.5 -top-1.5 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-gradient-to-b from-amber-500 to-amber-700 px-1 text-[10px] font-bold text-white shadow ring-2 ring-white">
                            {aOrdre ? `${place + 1}${place === 0 ? "er" : "e"}` : "✓"}
                          </span>
                        )}
                      </button>
                    );
                  })}
                </div>
              </Etape>

              <Etape n={3} titre="Points misés" droite={<span className="font-display text-[16px] font-bold tabular-nums text-slate-900">{pointsJoues} pts</span>}>
                <div className="flex gap-1.5">
                  {PALIERS.filter((v) => v >= regles.points_min && v <= pointsMax).map((v) => (
                    <button key={v} type="button" onClick={() => setPoints(v)} aria-pressed={pointsJoues === v}
                      className={cn("min-h-[42px] flex-1 rounded-xl text-[13px] font-bold tabular-nums ring-1 ring-inset transition-colors",
                        pointsJoues === v ? "bg-gradient-to-b from-amber-500 to-amber-700 text-white ring-amber-700 shadow-[inset_0_1px_0_rgba(255,255,255,.35)]" : "bg-white text-slate-700 ring-stone-200 hover:bg-stone-50")}>
                      {v}
                    </button>
                  ))}
                </div>
                <input type="range" min={regles.points_min} max={pointsMax} step={5}
                  value={pointsJoues} onChange={(e) => setPoints(Number(e.target.value))}
                  aria-label="Points misés" className="mt-3 w-full accent-amber-600" />
                <div className="flex justify-between text-[10.5px] tabular-nums text-slate-400">
                  <span>{regles.points_min}</span><span>{pointsMax}</span>
                </div>
              </Etape>

              {/* Le ticket : ce qui part, en un coup d'œil, avant de valider. */}
              <div className="px-5 pb-5">
                <div className="relative rounded-2xl border-2 border-dashed border-amber-300 bg-gradient-to-b from-amber-50/80 to-white p-4">
                  <div className="flex items-center justify-between gap-2">
                    <span className="flex items-center gap-2 text-[10.5px] font-bold uppercase tracking-[0.14em] text-amber-800">
                      <Ticket className="h-3.5 w-3.5" aria-hidden="true" /> Mon ticket
                    </span>
                    {chevaux.length >= min && (
                      <OriginePari origine={correspondPlan ? "plan" : "perso"} />
                    )}
                  </div>
                  <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-wrap items-center gap-1.5 text-[14px] font-bold text-slate-900">
                      {nomTicket}
                      {chevaux.length > 0
                        ? chevaux.map((n, i) => <span key={n} className="inline-flex items-center gap-1">{i > 0 && <span className="text-slate-400">{aOrdre ? "–" : "+"}</span>}<CasaqueNumero numero={n} /></span>)
                        : <span className="text-[12.5px] font-medium text-slate-400">choisissez {min === max ? `${min} cheva${min > 1 ? "ux" : "l"}` : `${min} à ${max} chevaux`}</span>}
                    </div>
                    <span className="font-display text-[15px] font-bold tabular-nums text-slate-900">{pointsJoues} pts</span>
                  </div>
                  {nbCombis > 1 && (
                    <p className="mt-2 text-[11.5px] leading-relaxed text-slate-600">
                      Formule {chevaux.length} chevaux : vos {pointsJoues} pts se répartissent sur <b className="text-slate-800">{nbCombis} combinaisons</b>,
                      seules les gagnantes paient.
                    </p>
                  )}
                  <p className="mt-2 text-[11.5px] leading-relaxed text-slate-600">
                    Si gagnant : <b className="text-slate-800">{pointsJoues} × rapport PMU officiel</b>{nbCombis > 1 && <> × part des combinaisons gagnantes</>}
                    {coteIndicative != null && <> (≈ {formatPts(pointsJoues * coteIndicative)} à la cote actuelle ; le rapport final fait foi)</>}.
                    {" "}Définitif une fois validé : ni modifiable, ni annulable.
                  </p>
                  <button type="button" onClick={valider} disabled={!pret || envoi}
                    className="mt-3 inline-flex min-h-[50px] w-full items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-amber-600 to-amber-800 px-4 text-[14px] font-bold text-white shadow-[inset_0_1px_0_rgba(255,255,255,.25),0_10px_20px_-12px_rgba(146,64,14,.9)] transition-opacity disabled:cursor-not-allowed disabled:opacity-45">
                    {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Check className="h-4 w-4" />}
                    {chevaux.length < min
                      ? `Choisissez encore ${min - chevaux.length} cheva${min - chevaux.length > 1 ? "ux" : "l"}`
                      : `Valider mon pari · ${pointsJoues} pts`}
                  </button>
                  <div className="mt-2 flex flex-wrap items-center justify-center gap-x-3 gap-y-1 text-[11px] text-slate-500">
                    <span>Fermeture à {new Date(data.limite).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}, heure de départ annoncée</span>
                    <span aria-hidden="true">·</span>
                    <span>{restants} pari{restants > 1 ? "s" : ""} restant{restants > 1 ? "s" : ""} sur cette course</span>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="px-5 pt-5">
              <div className="flex items-center gap-3 rounded-2xl bg-stone-50 px-4 py-3.5 text-[12.5px] text-slate-700 ring-1 ring-inset ring-stone-200">
                <span className="inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-white ring-1 ring-stone-200">
                  <Lock className="h-4 w-4 text-slate-500" aria-hidden="true" />
                </span>
                {!data.ouvert ? "Paris fermés : l'heure de départ annoncée est passée. Le résultat de vos paris s'affiche ici après l'arrivée."
                  : restants <= 0 ? `Vous avez joué vos ${regles.max_paris_par_course} paris sur cette course.`
                  : "Solde insuffisant pour ce mois. Nouvelle cagnotte le 1er du mois prochain !"}
              </div>
            </div>
          )}

          {mesParis.length > 0 && (
            <div className="px-5 pb-1 pt-4">
              <h4 className="mb-2 text-[11px] font-bold uppercase tracking-[0.14em] text-slate-500">Mes paris sur cette course</h4>
              <ul className="flex flex-col gap-2">
                {mesParis.map((p) => (
                  <li key={p.pari_id} className="flex flex-wrap items-center justify-between gap-2 rounded-2xl bg-white px-3.5 py-3 ring-1 ring-inset ring-stone-200">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-1.5 text-[13px] font-bold text-slate-900">
                        {p.type_pari}
                        {p.chevaux.map((n, i) => <span key={n} className="inline-flex items-center gap-1">{i > 0 && <span className="text-slate-400">{estAOrdre(p.type_pari) ? "–" : "+"}</span>}<CasaqueNumero numero={n} /></span>)}
                      </div>
                      <div className="mt-1.5 flex flex-wrap gap-1.5"><StatutPari statut={p.statut} /><OriginePari origine={p.origine} /></div>
                    </div>
                    <ResultatPari p={p} />
                  </li>
                ))}
              </ul>
            </div>
          )}

          <div className="mt-4 flex flex-wrap items-center justify-between gap-2 border-t border-stone-100 bg-stone-50/60 px-5 py-3 text-[11.5px] text-slate-600">
            <span className="inline-flex items-center gap-1.5">
              <Users className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
              {data.tendance.nb_joueurs === 0 ? "Soyez le premier joueur du défi sur cette course"
                : `${data.tendance.nb_joueurs} joueur${data.tendance.nb_joueurs > 1 ? "s" : ""} sur cette course`}
              {data.tendance.cheval_plus_joue != null && <> · n°{data.tendance.cheval_plus_joue} le plus joué</>}
            </span>
            <span className="inline-flex items-center gap-2">
              <CompteRebours mois={data.mois} />
              <Link href="/defi" className="inline-flex items-center gap-0.5 font-semibold text-amber-800 hover:underline">
                Classement <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </span>
          </div>
        </>
      )}
    </div>
  );
}
