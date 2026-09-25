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
import { ChevronRight, Loader2, Lock, Medal, Users } from "lucide-react";
import { defiApi, type DefiCourse, type DefiRegles, type DefiTypePari } from "@/lib/api";
import { CompteGratuitCta } from "@/components/billing/CompteGratuitCta";
import { CasaqueNumero } from "@/components/courses/identite-cheval";
import { CARTE_STYLE, IconeTuile } from "@/components/courses/course-ui";
import {
  DEFI_REGLES_DEFAUT, OriginePari, ResultatPari, StatutPari, TYPES_DEFI, formatPts, planLabel,
} from "@/components/defi/kit";
import { cn } from "@/lib/utils";

export type DefiPrefill = { type: DefiTypePari; chevaux: number[]; cle: number };

type PartantDefi = { numero: number; nom_cheval: string; non_partant?: boolean; cote_pmu?: number | null };

const PALIERS = [10, 25, 50, 100];

function detailErreur(e: unknown): string {
  const d = (e as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof d === "string" ? d : "Le pari n'a pas pu être enregistré.";
}

export function DefiCourseCard({ courseId, partants, connecte, prefill }: {
  courseId: string;
  partants: PartantDefi[];
  connecte: boolean;
  prefill?: DefiPrefill | null;
}) {
  const { data: regles = DEFI_REGLES_DEFAUT as unknown as DefiRegles } = useSWR(
    "/defi/regles", () => defiApi.regles().then((r) => r.data), { revalidateOnFocus: false });
  const { data, mutate, isLoading } = useSWR<DefiCourse>(
    connecte ? ["/defi/course", courseId] : null,
    () => defiApi.course(courseId).then((r) => r.data),
    { refreshInterval: 30_000 },
  );

  const [type, setType] = useState<DefiTypePari>("Simple Gagnant");
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

  const nbRequis = TYPES_DEFI.find((t) => t.type === type)?.nb ?? 1;
  const jouables = useMemo(() => partants.filter((p) => !p.non_partant).sort((a, b) => a.numero - b.numero), [partants]);
  const mesParis = data?.mes_paris ?? [];
  const restants = regles.max_paris_par_course - mesParis.length;
  const solde = data?.solde ?? null;
  const pointsMax = Math.min(regles.points_max, Math.max(0, Math.floor(solde ?? regles.points_max)));

  function choisirType(t: DefiTypePari) {
    setType(t);
    const nb = TYPES_DEFI.find((x) => x.type === t)?.nb ?? 1;
    setChevaux((c) => c.slice(0, nb));
  }

  function basculer(n: number) {
    setChevaux((c) => {
      if (c.includes(n)) return c.filter((x) => x !== n);
      if (nbRequis === 1) return [n];
      return c.length >= nbRequis ? [...c.slice(1), n] : [...c, n];
    });
  }

  async function valider() {
    if (chevaux.length !== nbRequis || envoi) return;
    setEnvoi(true);
    try {
      const { data: pari } = await defiApi.engager({ course_id: courseId, type_pari: type, chevaux, points });
      toast.success(`Pari validé : ${pari.points} pts sur ${pari.type_pari} ${pari.chevaux.map((n) => `n°${n}`).join(" + ")}`);
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

  const recompense = regles.recompenses?.[0];

  return (
    <div ref={carteRef} style={{ ...CARTE_STYLE, overflow: "hidden", scrollMarginTop: 120 }}>
      <div className="flex items-start gap-3 px-5 pb-4 pt-5">
        <IconeTuile icone={Medal} />
        <div className="min-w-0 flex-1">
          <h3 className="font-display text-[15px] font-bold text-slate-800">Défi du mois</h3>
          <p className="mt-0.5 text-[11.5px] leading-snug text-slate-600">
            Misez vos points, gagnez-en avec le rapport officiel.
            {recompense && <> Le 1er du mois gagne {recompense.jours} jours {planLabel(recompense.plan)} offerts.</>}
          </p>
        </div>
        {connecte && solde != null && (
          <div className="shrink-0 text-right">
            <div className="text-[10.5px] font-semibold text-slate-500">Mon solde</div>
            <div className="font-display text-[18px] font-bold tabular-nums text-slate-900">{formatPts(solde)}</div>
          </div>
        )}
      </div>

      <div className="px-5 pb-5">
        {!connecte ? (
          <CompteGratuitCta
            icone={Medal}
            titre="Jouez le Défi du mois"
            texte={`${regles.capital_mensuel} points offerts chaque mois pour parier sur les courses. Le meilleur solde remporte un abonnement offert.`}
            avantages={[
              `${regles.capital_mensuel} points de jeu remis à zéro chaque 1er du mois`,
              "Vos propres chevaux, ou ceux du plan de mise",
              "Classement en direct après chaque arrivée",
              "Aucun argent réel en jeu",
            ]}
            suite={`/courses/${courseId}#defi`}
          />
        ) : isLoading || !data ? (
          <div className="flex justify-center py-6"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        ) : (
          <div className="flex flex-col gap-4">
            {data.ouvert && restants > 0 && pointsMax >= regles.points_min ? (
              <div className="flex flex-col gap-4">
                {/* Type de pari */}
                <div>
                  <div className="mb-1.5 text-[11.5px] font-semibold text-slate-700">1. Type de pari</div>
                  <div className="grid grid-cols-2 gap-1.5">
                    {TYPES_DEFI.map((t) => (
                      <button key={t.type} type="button" onClick={() => choisirType(t.type)}
                        aria-pressed={type === t.type}
                        className={cn("min-h-[44px] rounded-xl px-3 py-2 text-left text-[12.5px] font-semibold ring-1 ring-inset transition-colors",
                          type === t.type ? "bg-amber-50 text-amber-900 ring-amber-300" : "bg-white text-slate-700 ring-stone-200 hover:bg-stone-50")}>
                        {t.type}
                      </button>
                    ))}
                  </div>
                  <p className="mt-1.5 text-[11px] text-slate-500">{TYPES_DEFI.find((t) => t.type === type)?.aide}</p>
                </div>

                {/* Chevaux */}
                <div>
                  <div className="mb-1.5 flex items-baseline justify-between text-[11.5px] font-semibold text-slate-700">
                    <span>2. {nbRequis === 1 ? "Votre cheval" : "Vos 2 chevaux"}</span>
                    <span className="font-medium text-slate-500 tabular-nums">{chevaux.length}/{nbRequis}</span>
                  </div>
                  <div className="grid grid-cols-2 gap-1.5 sm:grid-cols-3">
                    {jouables.map((p) => {
                      const actif = chevaux.includes(p.numero);
                      return (
                        <button key={p.numero} type="button" onClick={() => basculer(p.numero)} aria-pressed={actif}
                          className={cn("flex min-h-[44px] items-center gap-2 rounded-xl px-2.5 py-1.5 text-left ring-1 ring-inset transition-colors",
                            actif ? "bg-amber-50 ring-amber-400" : "bg-white ring-stone-200 hover:bg-stone-50")}>
                          <CasaqueNumero numero={p.numero} />
                          <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-slate-800">{p.nom_cheval}</span>
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Points */}
                <div>
                  <div className="mb-1.5 flex items-baseline justify-between text-[11.5px] font-semibold text-slate-700">
                    <span>3. Points misés</span>
                    <span className="font-display text-[15px] font-bold tabular-nums text-slate-900">{points} pts</span>
                  </div>
                  <div className="flex gap-1.5">
                    {PALIERS.filter((v) => v >= regles.points_min && v <= pointsMax).map((v) => (
                      <button key={v} type="button" onClick={() => setPoints(v)} aria-pressed={points === v}
                        className={cn("min-h-[40px] flex-1 rounded-lg text-[12.5px] font-semibold tabular-nums ring-1 ring-inset",
                          points === v ? "bg-slate-900 text-white ring-slate-900" : "bg-white text-slate-700 ring-stone-200 hover:bg-stone-50")}>
                        {v}
                      </button>
                    ))}
                  </div>
                  <input type="range" min={regles.points_min} max={pointsMax} step={5}
                    value={Math.min(points, pointsMax)} onChange={(e) => setPoints(Number(e.target.value))}
                    aria-label="Points misés" className="mt-2 w-full accent-amber-700" />
                </div>

                {/* Récap */}
                <div className="rounded-xl bg-stone-50 px-3 py-2.5 text-[11.5px] leading-relaxed text-slate-600 ring-1 ring-inset ring-stone-200">
                  Si gagnant : <b className="text-slate-800">{points} pts × rapport PMU officiel</b>
                  {coteIndicative != null && <> (≈ {formatPts(points * coteIndicative)} à la cote actuelle de {coteIndicative.toLocaleString("fr-FR")}, le rapport final fait foi)</>}.
                  {" "}Un pari validé est <b className="text-slate-800">définitif</b> : ni modifiable, ni annulable.
                </div>

                <button type="button" onClick={valider} disabled={chevaux.length !== nbRequis || envoi || points > pointsMax}
                  className="inline-flex min-h-[48px] items-center justify-center gap-2 rounded-xl bg-amber-800 px-4 text-[13px] font-bold text-white shadow-[0_5px_14px_-9px_rgba(146,64,14,.65)] transition-opacity disabled:cursor-not-allowed disabled:opacity-50">
                  {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Medal className="h-4 w-4" />}
                  {chevaux.length !== nbRequis
                    ? `Choisissez ${nbRequis - chevaux.length} cheva${nbRequis - chevaux.length > 1 ? "ux" : "l"}`
                    : `Valider mon pari · ${points} pts`}
                </button>
                <p className="-mt-2 text-center text-[11px] text-slate-500">
                  Clôture à {new Date(data.limite).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit" })}
                  {" · "}{restants} pari{restants > 1 ? "s" : ""} restant{restants > 1 ? "s" : ""} sur cette course
                </p>
              </div>
            ) : (
              <div className="flex items-center gap-2.5 rounded-xl bg-stone-50 px-3 py-3 text-[12px] text-slate-600 ring-1 ring-inset ring-stone-200">
                <Lock className="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
                {!data.ouvert ? "Paris fermés : le départ est donné ou imminent."
                  : restants <= 0 ? `Vous avez joué vos ${regles.max_paris_par_course} paris sur cette course.`
                  : "Solde de points insuffisant ce mois-ci. Rendez-vous le 1er du mois prochain !"}
              </div>
            )}

            {mesParis.length > 0 && (
              <div>
                <div className="mb-1.5 text-[11.5px] font-semibold text-slate-700">Mes paris sur cette course</div>
                <ul className="flex flex-col divide-y divide-stone-100 rounded-xl ring-1 ring-inset ring-stone-200">
                  {mesParis.map((p) => (
                    <li key={p.pari_id} className="flex flex-wrap items-center justify-between gap-2 px-3 py-2.5">
                      <div className="min-w-0">
                        <div className="flex flex-wrap items-center gap-1.5 text-[12.5px] font-semibold text-slate-800">
                          {p.type_pari}
                          <span className="inline-flex items-center gap-1">{p.chevaux.map((n, i) => <span key={n} className="inline-flex items-center gap-1">{i > 0 && "+"}<CasaqueNumero numero={n} /></span>)}</span>
                        </div>
                        <div className="mt-1 flex flex-wrap gap-1.5"><StatutPari statut={p.statut} /><OriginePari origine={p.origine} /></div>
                      </div>
                      <ResultatPari p={p} />
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div className="flex flex-wrap items-center justify-between gap-2 text-[11.5px] text-slate-600">
              <span className="inline-flex items-center gap-1.5">
                <Users className="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
                {data.tendance.nb_joueurs === 0 ? "Soyez le premier joueur du défi sur cette course"
                  : `${data.tendance.nb_joueurs} joueur${data.tendance.nb_joueurs > 1 ? "s" : ""} sur cette course`}
                {data.tendance.cheval_plus_joue != null && <> · n°{data.tendance.cheval_plus_joue} le plus joué</>}
              </span>
              <Link href="/defi" className="inline-flex items-center gap-0.5 font-semibold text-amber-800 hover:underline">
                Classement <ChevronRight className="h-3.5 w-3.5" aria-hidden="true" />
              </Link>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
