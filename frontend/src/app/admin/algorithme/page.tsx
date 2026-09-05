"use client";

/**
 * Supervision IA — poste de pilotage admin.
 *
 * Six vues sur la même vérité : ce que le système a conseillé, ce que ça a
 * rapporté, comment le modèle évolue, ce qu'il corrige tout seul.
 *
 * Deux principes tenus sur toute la page :
 *   1. Aucune valeur n'est estimée, extrapolée ou remplie par défaut. Une
 *      mesure absente s'affiche « — », un échantillon trop petit porte un badge
 *      et son chiffre n'est jamais promu en verdict.
 *   2. Tout se rafraîchit seul. Chaque bloc a sa cadence — 15 s pour le
 *      battement de cœur, 60 s pour les agrégats lourds — et l'horodatage
 *      affiché vient du serveur, donc un flux mort vieillit à l'écran.
 *
 * Refonte : la page portait son propre fond, sa propre largeur, sa propre
 * barre d'onglets et sa propre garde d'accès. Tout ça vient maintenant de la
 * coquille commune (`components/admin/shell`), et la barre de six onglets — qui
 * débordait sans le dire à 390 px — utilise le composant `Segments`, à
 * défilement accroché et cibles de 40 px.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import useSWR from "swr";
import { Brain, Pause, Play, RefreshCw } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { adminApi, statsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { EnTetePage, Segments, Vide } from "@/components/admin/ui";
import LiveBar from "@/components/admin/supervision/LiveBar";
import OverviewTab from "@/components/admin/supervision/OverviewTab";
import ParisTab from "@/components/admin/supervision/ParisTab";
import RentabiliteTab from "@/components/admin/supervision/RentabiliteTab";
import ModeleTab from "@/components/admin/supervision/ModeleTab";
import ApprentissageTab from "@/components/admin/supervision/ApprentissageTab";
import OutilsApprentissage, {
  type OutilsApprentissagePayload,
} from "@/components/admin/supervision/OutilsApprentissage";
import type {
  AlgoEvolutionPayload, ParisPayload, PulsePayload, RentabilitePayload,
} from "@/components/admin/supervision/types";

const TABS = [
  { key: "overview", label: "Vue d'ensemble" },
  { key: "paris", label: "Types de paris" },
  { key: "rentabilite", label: "Rentabilité" },
  { key: "modele", label: "Modèle" },
  { key: "apprentissage", label: "Apprentissage" },
  { key: "outils", label: "Outils" },
] as const;
type TabKey = (typeof TABS)[number]["key"];

const FENETRES = [
  { days: 7, label: "7 j" },
  { days: 30, label: "30 j" },
  { days: 90, label: "90 j" },
  { days: 0, label: "Tout" },
] as const;

export default function SupervisionIAPage() {
  const { user } = useAuth();
  const isAdmin = !!user?.is_admin;

  const [tab, setTab] = useState<TabKey>("overview");
  const [days, setDays] = useState<number>(90);
  const [live, setLive] = useState(true);
  const [histLimit, setHistLimit] = useState(30);
  const [lastSync, setLastSync] = useState<number>(() => Date.now());
  const [now, setNow] = useState<number>(() => Date.now());
  // Horodatage du dernier règlement effectivement intégré aux agrégats : sert
  // à afficher « à jour jusqu'à la course de HH:MM », pas juste « en direct ».
  const [derniereCourseIntegree, setDerniereCourseIntegree] = useState<string | null>(null);

  // Horloge locale : c'est elle qui fait vieillir l'ancienneté affichée quand
  // un rafraîchissement cesse d'aboutir, au lieu de figer un « à l'instant ».
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(id);
  }, []);

  const onSync = useCallback(() => setLastSync(Date.now()), []);
  const every = (ms: number) => (live ? ms : 0);

  // ── Battement de cœur (15 s) ────────────────────────────────
  const { data: pulse, mutate: refreshPulse } = useSWR<PulsePayload>(
    isAdmin ? "sup-pulse" : null,
    () => adminApi.supervisionPulse().then((r) => r.data),
    { refreshInterval: every(15_000), onSuccess: onSync, keepPreviousData: true }
  );

  // ── Agrégats lourds ─────────────────────────────────────────
  // Le sondage lent (60 s) n'est qu'un filet de sécurité : le vrai déclencheur
  // est le règlement d'une course, détecté par le battement de cœur ci-dessus.
  const { data: paris, isLoading: loadingParis, mutate: mutParis } = useSWR<ParisPayload>(
    isAdmin ? ["sup-paris", days] : null,
    () => adminApi.supervisionParis(days).then((r) => r.data),
    { refreshInterval: every(60_000), keepPreviousData: true }
  );
  const { data: renta, mutate: mutRenta } = useSWR<RentabilitePayload>(
    isAdmin ? ["sup-renta", days] : null,
    () => adminApi.supervisionRentabilite(days).then((r) => r.data),
    { refreshInterval: every(60_000), keepPreviousData: true }
  );
  const { data: algo } = useSWR<AlgoEvolutionPayload>(
    isAdmin ? "sup-algo" : null,
    () => adminApi.supervisionAlgoEvolution(60).then((r) => r.data),
    { refreshInterval: every(120_000), keepPreviousData: true }
  );

  // ── Moteur d'apprentissage ──────────────────────────────────
  const { data: alState, mutate: mutAlState } = useSWR(
    isAdmin ? "sup-al-state" : null,
    () => adminApi.alState().then((r) => r.data),
    { refreshInterval: every(30_000), keepPreviousData: true }
  );
  const { data: mlStatus } = useSWR(
    isAdmin ? "sup-ml-status" : null,
    () => statsApi.mlStatus().then((r) => r.data),
    { refreshInterval: every(60_000), keepPreviousData: true }
  );
  const { data: learning, mutate: mutLearning } = useSWR(
    isAdmin ? "sup-learning" : null,
    () => adminApi.learningSignals().then((r) => r.data),
    { refreshInterval: every(60_000), keepPreviousData: true }
  );
  const { data: converge, mutate: mutConverge } = useSWR(
    isAdmin ? "sup-converge" : null,
    () => adminApi.learningConvergence().then((r) => r.data),
    { refreshInterval: every(120_000), keepPreviousData: true }
  );
  const { data: calib } = useSWR(
    isAdmin ? "sup-calib" : null,
    () => adminApi.calibrationQuality().then((r) => r.data),
    { refreshInterval: every(300_000), keepPreviousData: true }
  );
  const { data: history, isLoading: loadingHistory, mutate: mutHistory } = useSWR(
    isAdmin ? ["sup-history", histLimit] : null,
    () => adminApi.alHistory(histLimit).then((r) => r.data),
    { refreshInterval: every(60_000), keepPreviousData: true }
  );
  const { data: biasMatrix } = useSWR(
    isAdmin ? "sup-bias" : null,
    () => adminApi.biasMatrix().then((r) => r.data),
    { refreshInterval: every(300_000), keepPreviousData: true }
  );
  // Outils d'apprentissage : quelles étapes ont réellement tourné, et quels
  // correcteurs ont PROUVÉ qu'ils amélioraient quelque chose. Rafraîchi lentement
  // — ces états ne bougent qu'une fois par nuit — mais rafraîchi quand même : une
  // étape qui cesse de tourner ne se signale que par le vieillissement de sa date.
  const { data: outils } = useSWR<OutilsApprentissagePayload>(
    isAdmin ? "sup-outils" : null,
    () => adminApi.supervisionOutilsApprentissage().then((r) => r.data),
    { refreshInterval: every(300_000), keepPreviousData: true }
  );

  // ── Recalcul déclenché par le règlement d'une course ────────
  // Sans ça, un ROI pouvait rester 60 s en retard sur la dernière course
  // arrivée. Le battement de cœur porte l'horodatage du dernier règlement :
  // dès qu'il change, tout ce qui en dépend est refetché immédiatement.
  const dernierReglement = pulse?.conseils_du_jour?.dernier_reglement ?? null;
  const derniereAnalyse = pulse?.apprentissage?.derniere_analyse ?? null;
  const vuReglement = useRef<string | null>(null);
  const vuAnalyse = useRef<string | null>(null);

  useEffect(() => {
    if (!dernierReglement) return;
    if (vuReglement.current === null) { vuReglement.current = dernierReglement; return; }
    if (vuReglement.current === dernierReglement) return;
    vuReglement.current = dernierReglement;
    setDerniereCourseIntegree(dernierReglement);
    void Promise.all([mutParis(), mutRenta(), mutLearning(), mutConverge()]);
  }, [dernierReglement, mutParis, mutRenta, mutLearning, mutConverge]);

  useEffect(() => {
    if (!derniereAnalyse) return;
    if (vuAnalyse.current === null) { vuAnalyse.current = derniereAnalyse; return; }
    if (vuAnalyse.current === derniereAnalyse) return;
    vuAnalyse.current = derniereAnalyse;
    void Promise.all([mutAlState(), mutHistory()]);
  }, [derniereAnalyse, mutAlState, mutHistory]);

  // La garde d'accès vit dans la coquille ; ici on se contente de ne rien
  // demander au serveur tant qu'on ne sait pas si l'on est admin.
  const secondsSince = Math.max(0, Math.floor((now - lastSync) / 1000));

  return (
    <div className="space-y-4 sm:space-y-5">
      <EnTetePage
        titre="Supervision IA"
        icone={<Brain className="h-4 w-4" />}
        desc="Ce que l'algorithme a conseillé, ce que ça a rapporté, et comment il apprend — mesuré sur les rapports PMU réels, jamais reconstitué après coup."
        actions={
          <>
            {/* Fenêtre d'analyse. Elle change TOUT ce qui est affiché en
                dessous : elle reste donc dans l'en-tête, jamais enfouie dans un
                onglet. */}
            <div
              role="group"
              aria-label="Fenêtre d'analyse"
              className="flex overflow-hidden rounded-xl border border-border bg-card"
            >
              {FENETRES.map((f) => (
                <button
                  key={f.days}
                  onClick={() => setDays(f.days)}
                  aria-pressed={days === f.days}
                  className={cn(
                    "min-h-[2.5rem] px-3 text-xs font-semibold transition-colors",
                    days === f.days
                      ? "bg-foreground text-background"
                      : "text-muted-foreground hover:bg-muted hover:text-foreground",
                  )}
                >
                  {f.label}
                </button>
              ))}
            </div>
            <button
              onClick={() => setLive((v) => !v)}
              title={live ? "Mettre le rafraîchissement en pause" : "Reprendre le rafraîchissement"}
              className="inline-flex min-h-[2.5rem] items-center gap-1.5 rounded-xl border border-border bg-card px-3 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground"
            >
              {live ? <Pause className="h-3.5 w-3.5" /> : <Play className="h-3.5 w-3.5" />}
              {live ? "Pause" : "Reprendre"}
            </button>
            <button
              onClick={() => refreshPulse()}
              className="inline-flex min-h-[2.5rem] items-center gap-1.5 rounded-xl border border-border bg-card px-3 text-xs font-semibold text-muted-foreground transition-colors hover:text-foreground"
            >
              <RefreshCw className="h-3.5 w-3.5" />
              <span className="hidden sm:inline">Actualiser</span>
            </button>
          </>
        }
      />

      <LiveBar
        pulse={pulse}
        live={live}
        secondsSince={secondsSince}
        derniereCourseIntegree={derniereCourseIntegree}
      />

      {/* Onglets collants : sur une page de 4 000 px, revenir en haut pour
          changer de vue est une corvée qu'aucun tableau de bord n'impose. */}
      <div className="sticky top-14 z-20 -mx-3 bg-muted/25 px-3 py-2 backdrop-blur sm:-mx-5 sm:px-5 lg:top-0">
        <Segments items={TABS} actif={tab} onChange={setTab} />
      </div>

      {tab === "overview" && (
        <OverviewTab
          paris={paris}
          renta={renta}
          algo={algo}
          victoires={converge?.victoires}
          onGoTo={(k) => setTab(k as TabKey)}
        />
      )}
      {tab === "paris" && (
        loadingParis && !paris
          ? <Vide>Chargement des chiffres par type de pari…</Vide>
          : <ParisTab data={paris} />
      )}
      {tab === "rentabilite" && <RentabiliteTab data={renta} />}
      {tab === "modele" && <ModeleTab algo={algo} calib={calib} converge={converge} />}
      {tab === "apprentissage" && (
        <ApprentissageTab
          alState={alState}
          mlStatus={mlStatus}
          learning={learning}
          history={history}
          biasMatrix={biasMatrix}
          histLimit={histLimit}
          setHistLimit={setHistLimit}
          loadingHistory={loadingHistory}
        />
      )}
      {tab === "outils" && <OutilsApprentissage data={outils} />}

      <p className="pb-2 text-center text-xs leading-relaxed text-muted-foreground">
        Source : conseils de mise réellement émis avant le départ, réglés sur les rapports PMU
        publiés. Runs reconstruits a posteriori exclus. Les ROI qui servent de VERDICT sont
        calculés gains plafonnés à 50× la mise ; les courbes de capital et les résultats par
        jour montrent les gains réellement encaissés, la version plafonnée en pointillés.
      </p>
    </div>
  );
}
