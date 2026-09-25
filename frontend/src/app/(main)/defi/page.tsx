"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  CalendarDays, ChevronDown, ChevronLeft, ChevronRight, Crown, Loader2, Medal, ScrollText,
  Sparkles, Target, Trophy, User,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { defiApi, type DefiLigne, type DefiMoi, type DefiPalmares, type DefiRegles, type DefiStats } from "@/lib/api";
import { CompteGratuitCta } from "@/components/billing/CompteGratuitCta";
import {
  DEFI_REGLES_DEFAUT, OriginePari, ResultatPari, StatutPari, formatPts, moisLabel, planLabel,
} from "@/components/defi/kit";
import { cn } from "@/lib/utils";

const CARTE = "rounded-2xl bg-white ring-1 ring-inset ring-[#ECE7DC] shadow-[0_1px_2px_rgba(17,24,39,.05),0_12px_28px_-22px_rgba(17,24,39,.45)]";

function moisCourantParis(): string {
  const p = new Intl.DateTimeFormat("fr-CA", { timeZone: "Europe/Paris", year: "numeric", month: "2-digit" })
    .formatToParts(new Date());
  return `${p.find((x) => x.type === "year")?.value}-${p.find((x) => x.type === "month")?.value}`;
}

function decalerMois(mois: string, delta: number): string {
  const [a, m] = mois.split("-").map(Number);
  const d = new Date(Date.UTC(a, m - 1 + delta, 1));
  return `${d.getUTCFullYear()}-${String(d.getUTCMonth() + 1).padStart(2, "0")}`;
}

function joursRestants(mois: string): number {
  const [a, m] = mois.split("-").map(Number);
  const fin = new Date(Date.UTC(a, m, 1)).getTime();
  return Math.max(0, Math.ceil((fin - Date.now()) / 86_400_000));
}

function Roi({ v }: { v: number | null }) {
  if (v == null) return <span className="text-slate-400">—</span>;
  return <span className={cn(v > 0 ? "text-emerald-700" : v < 0 ? "text-rose-700" : "text-slate-600")}>{v > 0 ? "+" : ""}{v.toLocaleString("fr-FR")} %</span>;
}

function DuelOrigine({ titre, icone: Icone, s, accent }: { titre: string; icone: typeof User; s: DefiStats; accent: string }) {
  return (
    <div className="rounded-xl bg-stone-50 p-3 ring-1 ring-inset ring-stone-200">
      <div className={cn("flex items-center gap-1.5 text-[11.5px] font-semibold", accent)}>
        <Icone className="h-3.5 w-3.5" aria-hidden="true" /> {titre}
      </div>
      <div className="mt-1.5 font-display text-[18px] font-bold tabular-nums text-slate-900">{formatPts(s.points_nets, true)}</div>
      <div className="mt-0.5 text-[11px] leading-snug text-slate-500 tabular-nums">
        <div>{s.nb_paris} pari{s.nb_paris > 1 ? "s" : ""}</div>
        <div>rendement <Roi v={s.roi} /></div>
      </div>
    </div>
  );
}

function MaCarte({ moi, regles }: { moi: DefiMoi; regles: DefiRegles }) {
  const manque = Math.max(0, regles.min_paris_classement - moi.nb_paris);
  const verdict = moi.plan.nb_paris && moi.perso.nb_paris && moi.plan.roi != null && moi.perso.roi != null
    ? moi.perso.roi > moi.plan.roi ? "Vos choix perso battent le plan de mise ce mois-ci 🔥"
      : moi.perso.roi < moi.plan.roi ? "Le plan de mise fait mieux que vos choix perso ce mois-ci."
      : "Égalité parfaite entre vos choix et le plan de mise."
    : null;
  return (
    <section className={cn(CARTE, "p-5")} aria-label="Mon défi">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <div className="text-[11.5px] font-semibold text-slate-500">Mon solde · {moi.nom}</div>
          <div className="mt-1 font-display text-[32px] font-bold leading-none tabular-nums text-slate-900">{formatPts(moi.solde)}</div>
          <div className="mt-1.5 text-[12px] text-slate-600 tabular-nums">
            {moi.nb_paris} pari{moi.nb_paris > 1 ? "s" : ""} · {moi.nb_gagnes} gagné{moi.nb_gagnes > 1 ? "s" : ""}
            {moi.nb_en_attente > 0 && <> · {moi.nb_en_attente} en attente</>} · rendement <Roi v={moi.roi} />
          </div>
        </div>
        <div className="text-right">
          <div className="text-[11.5px] font-semibold text-slate-500">Mon rang</div>
          {moi.rang != null ? (
            <div className="mt-1 font-display text-[32px] font-bold leading-none tabular-nums text-amber-800">
              {moi.rang}<span className="text-[15px] text-slate-500">{moi.rang === 1 ? "er" : "e"} / {moi.nb_classes}</span>
            </div>
          ) : (
            <div className="mt-1 max-w-[180px] text-[12px] font-medium leading-snug text-slate-600">
              Encore <b className="text-slate-900">{manque} pari{manque > 1 ? "s" : ""}</b> pour entrer au classement
            </div>
          )}
        </div>
      </div>
      {moi.nb_paris > 0 && (
        <div className="mt-4">
          <div className="grid grid-cols-2 gap-2">
            <DuelOrigine titre="Plan BlackTurf" icone={Sparkles} s={moi.plan} accent="text-amber-800" />
            <DuelOrigine titre="Mes choix perso" icone={User} s={moi.perso} accent="text-slate-700" />
          </div>
          {verdict && <p className="mt-2 text-[12px] font-medium text-slate-700">{verdict}</p>}
        </div>
      )}
      <Link href="/programme"
        className="mt-4 inline-flex min-h-[44px] w-full items-center justify-center gap-2 rounded-xl bg-amber-800 px-4 text-[13px] font-bold text-white">
        <Target className="h-4 w-4" aria-hidden="true" /> Choisir une course et parier
      </Link>
    </section>
  );
}

function LigneClassement({ l }: { l: DefiLigne }) {
  return (
    <li className={cn("grid grid-cols-[40px_minmax(0,1fr)_auto] items-center gap-3 px-4 py-2.5", l.moi && "bg-amber-50/70")}>
      <span className={cn("inline-flex h-7 w-7 items-center justify-center rounded-full text-[12px] font-bold tabular-nums",
        l.rang === 1 ? "bg-amber-400 text-white" : l.rang === 2 ? "bg-slate-300 text-slate-800" : l.rang === 3 ? "bg-orange-300 text-orange-950" : "bg-stone-100 text-slate-600")}>
        {l.rang ?? "–"}
      </span>
      <div className="min-w-0">
        <div className="truncate text-[13px] font-semibold text-slate-800">
          {l.nom}{l.moi && <span className="ml-1.5 text-[11px] font-semibold text-amber-800">(vous)</span>}
          {l.hors_concours && <span className="ml-1.5 text-[11px] font-medium text-slate-500">hors concours</span>}
        </div>
        <div className="text-[11px] text-slate-500 tabular-nums">
          {l.nb_paris} paris · {l.nb_gagnes} gagnés · <Roi v={l.roi} />
        </div>
      </div>
      <span className="font-display text-[15px] font-bold tabular-nums text-slate-900">{formatPts(l.solde)}</span>
    </li>
  );
}

function Reglement({ regles }: { regles: DefiRegles }) {
  const lots = regles.recompenses.map((r) => `${r.rang}${r.rang === 1 ? "er" : "e"} : ${r.jours} jours ${planLabel(r.plan)} offerts`).join(" · ");
  return (
    <details className={cn(CARTE, "group")}>
      <summary className="flex min-h-[52px] cursor-pointer list-none items-center justify-between gap-3 px-5 text-[13px] font-semibold text-slate-800">
        <span className="inline-flex items-center gap-2"><ScrollText className="h-4 w-4 text-amber-700" aria-hidden="true" /> Règlement du défi</span>
        <ChevronDown className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <ol className="list-decimal space-y-2 pb-5 pl-10 pr-5 text-[12.5px] leading-relaxed text-slate-700">
        <li><b>Participation gratuite</b>, réservée aux personnes majeures ayant un compte BlackTurf à l&apos;adresse e-mail confirmée, quel que soit l&apos;abonnement. Aucun achat ni aucun pari en argent réel n&apos;est demandé : les points n&apos;ont aucune valeur monétaire et ne s&apos;échangent pas.</li>
        <li>Chaque mois (calendrier de Paris), chaque joueur reçoit <b>{regles.capital_mensuel} points</b>. Le solde repart à {regles.capital_mensuel} le 1er du mois suivant.</li>
        <li>Paris proposés : Simple Gagnant, Simple Placé, Couplé Gagnant et Couplé Placé, sur les courses où le PMU les ouvre. Mise de <b>{regles.points_min} à {regles.points_max} points</b> par pari, au plus <b>{regles.max_paris_par_course} paris par course</b>.</li>
        <li>Les paris ferment <b>{regles.verrou_minutes} minutes avant le départ prévu</b>, à l&apos;heure du serveur. Un pari validé est définitif : ni modifiable, ni annulable.</li>
        <li>Un pari gagnant rapporte <b>points misés × rapport PMU officiel</b> publié à l&apos;arrivée, le même pour tous les joueurs, quel que soit l&apos;opérateur où chacun joue en vrai. Un cheval non-partant ou une course annulée rembourse la mise.</li>
        <li>Le pari porte l&apos;étiquette « Plan BlackTurf » quand il reprend un pari du plan de mise que vous avez consulté sur la course, « Perso » sinon. L&apos;étiquette n&apos;a pas d&apos;effet sur le classement.</li>
        <li>Sont classés les joueurs ayant engagé au moins <b>{regles.min_paris_classement} paris</b> dans le mois, par solde décroissant ; à égalité, le plus grand nombre de paris gagnants puis le premier pari le plus ancien l&apos;emportent.</li>
        <li>Récompenses : {lots}. Elles sont remises après la clôture du mois, une fois tous les paris réglés et les comptes vérifiés. Un abonné payant reçoit l&apos;équivalent en déduction de son abonnement. Les récompenses sont nominatives et ne s&apos;échangent pas contre de l&apos;argent.</li>
        <li><b>Un seul compte par personne.</b> BlackTurf peut vérifier l&apos;identité des gagnants et exclure du défi, sans récompense, tout compte multiple, automatisé ou ayant contourné les règles.</li>
        <li>Les comptes de l&apos;équipe BlackTurf jouent hors concours. BlackTurf peut modifier ou arrêter le défi ; un mois commencé se termine avec les règles en vigueur à son début.</li>
      </ol>
      <p className="px-5 pb-5 text-[11.5px] leading-relaxed text-slate-500">
        Jouer comporte des risques : endettement, isolement, dépendance. Pour être aidé, appelez le 09 74 75 13 13 (appel non surtaxé).
      </p>
    </details>
  );
}

export default function DefiPage() {
  const { user } = useAuth();
  const moisCourant = useMemo(() => moisCourantParis(), []);
  const [mois, setMois] = useState(moisCourant);
  const [voirNonClasses, setVoirNonClasses] = useState(false);
  const enCours = mois === moisCourant;

  const { data: regles = DEFI_REGLES_DEFAUT as unknown as DefiRegles } = useSWR(
    "/defi/regles", () => defiApi.regles().then((r) => r.data), { revalidateOnFocus: false });
  const { data: classement, isLoading } = useSWR(
    ["/defi/classement", mois, user?.user_id ?? ""], () => defiApi.classement(mois).then((r) => r.data),
    { refreshInterval: enCours ? 60_000 : 0 });
  const { data: moi } = useSWR<DefiMoi>(
    user ? ["/defi/moi", mois, user.user_id] : null, () => defiApi.moi(mois).then((r) => r.data),
    { refreshInterval: enCours ? 60_000 : 0 });
  const { data: palmares } = useSWR<DefiPalmares>("/defi/palmares", () => defiApi.palmares().then((r) => r.data));

  const classes = classement?.lignes.filter((l) => l.classe) ?? [];
  const autres = classement?.lignes.filter((l) => !l.classe) ?? [];
  const jours = joursRestants(mois);

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-5 px-4 py-6 sm:px-5">
      {/* En-tête */}
      <header className="rounded-[20px] bg-[#F3EDE0] px-5 py-5 ring-1 ring-inset ring-[#E6DCC6]">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="inline-flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-b from-amber-50 to-amber-100 text-amber-700 ring-1 ring-inset ring-amber-200">
              <Medal className="h-5 w-5" aria-hidden="true" />
            </span>
            <div>
              <h1 className="font-display text-[22px] font-bold text-slate-900">Défi du mois</h1>
              <p className="text-[12.5px] text-slate-600">{regles.capital_mensuel} points, vos pronostics, le rapport officiel.</p>
            </div>
          </div>
          <div className="flex items-center gap-1 rounded-xl bg-white/80 p-1 ring-1 ring-inset ring-[#E6DCC6]">
            <button type="button" aria-label="Mois précédent" onClick={() => setMois(decalerMois(mois, -1))}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-white">
              <ChevronLeft className="h-4 w-4" />
            </button>
            <span className="min-w-[120px] text-center text-[13px] font-semibold text-slate-800">{moisLabel(mois)}</span>
            <button type="button" aria-label="Mois suivant" disabled={enCours} onClick={() => setMois(decalerMois(mois, 1))}
              className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-slate-600 hover:bg-white disabled:opacity-30">
              <ChevronRight className="h-4 w-4" />
            </button>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-1 gap-2 sm:grid-cols-3">
          {regles.recompenses.map((r) => (
            <div key={r.rang} className={cn("rounded-xl px-3 py-2.5 ring-1 ring-inset",
              r.rang === 1 ? "bg-amber-50 ring-amber-300" : "bg-white/80 ring-[#E6DCC6]")}>
              <div className="flex items-center gap-1.5 text-[11.5px] font-semibold text-slate-600">
                {r.rang === 1 ? <Crown className="h-3.5 w-3.5 text-amber-600" /> : <Trophy className="h-3.5 w-3.5 text-slate-500" />}
                {r.rang}{r.rang === 1 ? "er" : "e"} du mois
              </div>
              <div className="mt-0.5 text-[13.5px] font-bold text-slate-900">{r.jours} jours {planLabel(r.plan)} offerts</div>
            </div>
          ))}
        </div>
        {enCours && (
          <p className="mt-3 inline-flex items-center gap-1.5 text-[12px] font-medium text-slate-600">
            <CalendarDays className="h-3.5 w-3.5" aria-hidden="true" />
            {jours <= 1 ? "Dernier jour du défi !" : `Encore ${jours} jours pour grimper au classement`}
          </p>
        )}
      </header>

      {/* Ma carte */}
      {user ? (
        moi ? <MaCarte moi={moi} regles={regles} /> : (
          <div className={cn(CARTE, "flex justify-center p-8")}><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        )
      ) : (
        <div className={cn(CARTE, "p-5")}>
          <CompteGratuitCta
            icone={Medal}
            titre="Entrez dans le défi"
            texte={`Un compte gratuit suffit : ${regles.capital_mensuel} points chaque mois pour parier sur les courses, et un abonnement à gagner.`}
            avantages={[
              "Participation gratuite, sans argent réel",
              "Vos propres chevaux, ou ceux du plan de mise",
              "Paris réglés au rapport PMU officiel",
              `${regles.recompenses[0]?.jours ?? 30} jours ${planLabel(regles.recompenses[0]?.plan ?? "expert")} pour le 1er du mois`,
            ]}
            suite="/defi"
          />
        </div>
      )}

      {/* Classement */}
      <section className={CARTE} aria-label="Classement">
        <div className="flex items-center justify-between gap-3 px-5 pb-3 pt-5">
          <h2 className="inline-flex items-center gap-2 font-display text-[16px] font-bold text-slate-900">
            <Trophy className="h-4 w-4 text-amber-700" aria-hidden="true" /> Classement
          </h2>
          <span className="text-[11.5px] text-slate-500">{classement?.nb_joueurs ?? 0} joueur{(classement?.nb_joueurs ?? 0) > 1 ? "s" : ""}</span>
        </div>
        {isLoading ? (
          <div className="flex justify-center pb-8"><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        ) : classes.length === 0 ? (
          <p className="px-5 pb-5 text-[12.5px] text-slate-600">
            Personne n&apos;est encore classé : il faut {regles.min_paris_classement} paris dans le mois. La première place est à prendre.
          </p>
        ) : (
          <ol className="divide-y divide-stone-100 border-t border-stone-100">
            {classes.map((l) => <LigneClassement key={`${l.rang}-${l.nom}`} l={l} />)}
          </ol>
        )}
        {autres.length > 0 && (
          <div className="border-t border-stone-100">
            <button type="button" onClick={() => setVoirNonClasses((v) => !v)}
              className="flex min-h-[44px] w-full items-center justify-between px-5 text-[12px] font-semibold text-slate-600">
              Pas encore classés, moins de {regles.min_paris_classement} paris ({autres.length})
              <ChevronDown className={cn("h-4 w-4 transition-transform", voirNonClasses && "rotate-180")} />
            </button>
            {voirNonClasses && (
              <ul className="divide-y divide-stone-100 border-t border-stone-100">
                {autres.map((l, i) => <LigneClassement key={`${i}-${l.nom}`} l={l} />)}
              </ul>
            )}
          </div>
        )}
      </section>

      {/* Mes paris */}
      {moi && moi.paris.length > 0 && (
        <section className={CARTE} aria-label="Mes paris du mois">
          <h2 className="px-5 pb-3 pt-5 font-display text-[16px] font-bold text-slate-900">Mes paris de {moisLabel(mois).toLowerCase()}</h2>
          <ul className="divide-y divide-stone-100 border-t border-stone-100">
            {moi.paris.map((p) => (
              <li key={p.pari_id} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
                <div className="min-w-0">
                  <Link href={`/courses/${p.course_id}#defi`} className="text-[12.5px] font-semibold text-slate-800 hover:underline">
                    {p.type_pari} {p.chevaux.map((n) => `n°${n}`).join(" + ")}
                  </Link>
                  <div className="text-[11px] text-slate-500">
                    {p.course_label}{p.date_heure && <> · {new Date(p.date_heure).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</>}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-1.5"><StatutPari statut={p.statut} /><OriginePari origine={p.origine} /></div>
                </div>
                <ResultatPari p={p} />
              </li>
            ))}
          </ul>
        </section>
      )}

      {/* Palmarès */}
      {palmares && palmares.length > 0 && (
        <section className={cn(CARTE, "p-5")} aria-label="Palmarès">
          <h2 className="mb-3 inline-flex items-center gap-2 font-display text-[16px] font-bold text-slate-900">
            <Crown className="h-4 w-4 text-amber-600" aria-hidden="true" /> Palmarès
          </h2>
          <ul className="flex flex-col gap-1.5">
            {palmares.map((p) => (
              <li key={`${p.mois}-${p.rang}`} className="flex items-center justify-between gap-3 text-[12.5px]">
                <span className="text-slate-600">{moisLabel(p.mois)} · {p.rang}{p.rang === 1 ? "er" : "e"}</span>
                <span className="font-semibold text-slate-800">{p.nom} <span className="font-normal text-slate-500 tabular-nums">· {formatPts(p.solde)}</span></span>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Reglement regles={regles} />
    </div>
  );
}
