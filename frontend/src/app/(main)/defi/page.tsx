"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import useSWR from "swr";
import {
  ArrowRight, ChevronDown, ChevronLeft, ChevronRight, Crown, Loader2, ScrollText, Sparkles,
  Target, Timer, Trophy, User, Users,
} from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { defiApi, type DefiClassement, type DefiMoi, type DefiPalmares, type DefiRegles, type DefiStats } from "@/lib/api";
import { CompteGratuitCta } from "@/components/billing/CompteGratuitCta";
import { DefiConcept } from "@/components/defi/DefiConcept";
import { DecorRayons, TropheeSvg } from "@/components/defi/illustrations";
import {
  Avatar, CompteRebours, DEFI_CARTE, DEFI_FOND, DEFI_REGLES_DEFAUT, DefiEntete, LigneClassement,
  BandeauEssai, dateLancement, OriginePari, PastilleDirect, Podium, ResultatPari, StatutPari, formatPts, joursRestants, moisLabel, planLabel, formatNombre, chevauxLisibles } from "@/components/defi/kit";
import { cn } from "@/lib/utils";

const CARTE = DEFI_CARTE;

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

function Roi({ v }: { v: number | null }) {
  if (v == null) return <span className="text-slate-400">—</span>;
  return <span className={cn("font-semibold", v > 0 ? "text-emerald-700" : v < 0 ? "text-rose-700" : "text-slate-600")}>{v > 0 ? "+" : ""}{formatNombre(v, 2)} %</span>;
}

/** Titre de section de la page : surtitre or + titre. */
function TitreSection({ id, surtitre, titre, droite }: { id?: string; surtitre: string; titre: string; droite?: React.ReactNode }) {
  return (
    <div className="mb-3 flex items-end justify-between gap-3">
      <div>
        <div className="text-[10.5px] font-bold uppercase tracking-[0.16em] text-amber-700">{surtitre}</div>
        <h2 id={id} className="font-display text-[19px] font-bold text-slate-900">{titre}</h2>
      </div>
      {droite}
    </div>
  );
}

// ─── En-tête ───────────────────────────────────────────────────────────────
const MEDAILLES_PRIX = [
  "from-[#FCD66B] via-[#F2B53A] to-[#C9861A] text-[#7A4A06]",
  "from-[#F1F4F8] via-[#D5DBE3] to-[#A9B3C1] text-slate-700",
  "from-[#F7D2B0] via-[#E1A06C] to-[#B8733E] text-[#6B3B14]",
];

function Hero({ mois, enCours, setMois, regles, classement }: {
  mois: string; enCours: boolean; setMois: (m: string) => void; regles: DefiRegles; classement?: DefiClassement;
}) {
  const jours = joursRestants(mois);
  const leader = classement?.lignes.find((l) => l.rang === 1);
  return (
    <header className={cn(DEFI_FOND, "relative isolate overflow-hidden rounded-[28px] px-5 pb-6 pt-6 ring-1 ring-amber-900/10 shadow-[inset_0_1px_0_#fff,0_30px_60px_-44px_rgba(120,53,15,.7)] sm:px-8 sm:pb-8 sm:pt-8")}>
      <DecorRayons className="-z-10" />
      <TropheeSvg className="pointer-events-none absolute -right-6 top-4 -z-10 w-44 opacity-95 sm:right-6 sm:top-6 sm:w-56" />

      <div className="flex flex-wrap items-center justify-between gap-3">
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/80 px-2.5 py-1 text-[10.5px] font-bold uppercase tracking-[0.14em] text-amber-800 shadow-sm ring-1 ring-inset ring-amber-200">
          <Sparkles className="h-3 w-3" aria-hidden="true" /> Concours gratuit · sans argent réel
        </span>
        <div className="flex items-center gap-1 rounded-2xl bg-white/85 p-1 shadow-sm ring-1 ring-inset ring-amber-200 backdrop-blur">
          <button type="button" aria-label="Mois précédent" onClick={() => setMois(decalerMois(mois, -1))}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-slate-500 hover:bg-amber-50 hover:text-slate-900">
            <ChevronLeft className="h-4 w-4" />
          </button>
          <span className="min-w-[128px] text-center text-[13px] font-bold text-slate-900">{moisLabel(mois)}</span>
          <button type="button" aria-label="Mois suivant" disabled={enCours} onClick={() => setMois(decalerMois(mois, 1))}
            className="inline-flex h-9 w-9 items-center justify-center rounded-xl text-slate-500 hover:bg-amber-50 hover:text-slate-900 disabled:opacity-25">
            <ChevronRight className="h-4 w-4" />
          </button>
        </div>
      </div>

      <div className="mt-5 max-w-[26rem] sm:max-w-md">
        <h1 className="font-display text-[32px] font-bold leading-[1.05] tracking-tight text-slate-900 sm:text-[42px]">
          Défi du <span className="bg-gradient-to-b from-amber-500 to-amber-800 bg-clip-text text-transparent">mois</span>
        </h1>
        <p className="mt-2.5 text-[14px] leading-relaxed text-slate-700">
          {formatNombre(regles.capital_mensuel, 2)} points offerts chaque mois, vos pronostics sur les vraies courses,
          réglés au rapport PMU officiel. Le meilleur solde remporte un abonnement.
        </p>
      </div>

      <div className="mt-5 flex flex-wrap items-center gap-2 text-[12px]">
        {enCours && <PastilleDirect />}
        {enCours && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-amber-200">
            <Timer className="h-3.5 w-3.5 text-amber-600" aria-hidden="true" />
            {jours <= 1 ? "Dernier jour du défi" : `Encore ${jours} jours`}
          </span>
        )}
        <span className="inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-amber-200">
          <Users className="h-3.5 w-3.5 text-amber-600" aria-hidden="true" /> {classement?.nb_joueurs ?? 0} joueur{(classement?.nb_joueurs ?? 0) > 1 ? "s" : ""} · {classement?.nb_classes ?? 0} classé{(classement?.nb_classes ?? 0) > 1 ? "s" : ""}
        </span>
        {leader && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/90 px-2.5 py-1 font-semibold text-slate-700 shadow-sm ring-1 ring-inset ring-amber-200">
            <Crown className="h-3.5 w-3.5 fill-amber-400 text-amber-600" aria-hidden="true" /> En tête : {leader.nom}
          </span>
        )}
      </div>

      <ul className="mt-6 grid grid-cols-1 gap-2.5 sm:grid-cols-3">
        {regles.recompenses.map((r, i) => (
          <li key={r.rang} className={cn("relative flex items-center gap-3 overflow-hidden rounded-2xl bg-white/90 px-3.5 py-3 shadow-[0_10px_24px_-18px_rgba(120,53,15,.7)] ring-1 ring-inset backdrop-blur",
            r.rang === 1 ? "ring-amber-300" : "ring-amber-900/10")}>
            <span className={cn("relative inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-gradient-to-b font-display text-[15px] font-bold shadow-[inset_0_1px_0_rgba(255,255,255,.7),0_4px_10px_-4px_rgba(120,53,15,.6)] ring-2 ring-white", MEDAILLES_PRIX[i] ?? MEDAILLES_PRIX[2])}>
              {r.rang === 1 ? <Crown className="h-5 w-5" /> : r.rang}
            </span>
            <div className="min-w-0">
              <div className="text-[11px] font-semibold uppercase tracking-[0.1em] text-slate-500">{r.rang}{r.rang === 1 ? "er" : "e"} du mois</div>
              <div className="text-[15px] font-bold text-slate-900">{r.jours} jours {planLabel(r.plan)}</div>
              <div className="text-[11px] text-slate-500">offerts au gagnant</div>
            </div>
          </li>
        ))}
      </ul>
    </header>
  );
}

// ─── Ma saison ─────────────────────────────────────────────────────────────
function Duel({ plan, perso }: { plan: DefiStats; perso: DefiStats }) {
  const max = Math.max(1, Math.abs(plan.points_nets), Math.abs(perso.points_nets));
  const lignes = [
    { libelle: "Plan BlackTurf", icone: Sparkles, s: plan, teinte: "bg-amber-500" },
    { libelle: "Mes choix perso", icone: User, s: perso, teinte: "bg-slate-700" },
  ];
  return (
    <div className="space-y-3">
      {lignes.map(({ libelle, icone: Icone, s, teinte }) => (
        <div key={libelle}>
          <div className="flex items-baseline justify-between gap-2 text-[12.5px]">
            <span className="inline-flex items-center gap-1.5 font-semibold text-slate-800"><Icone className="h-3.5 w-3.5 text-slate-500" aria-hidden="true" /> {libelle}</span>
            <span className="tabular-nums text-slate-500">{s.nb_paris} pari{s.nb_paris > 1 ? "s" : ""} · <Roi v={s.roi} /></span>
          </div>
          <div className="mt-1.5 flex items-center gap-2">
            <span className="h-2.5 flex-1 overflow-hidden rounded-full bg-stone-100">
              <span className={cn("block h-full rounded-full", s.points_nets >= 0 ? teinte : "bg-rose-400")}
                style={{ width: `${Math.max(s.nb_paris ? 4 : 0, (Math.abs(s.points_nets) / max) * 100)}%` }} />
            </span>
            <span className={cn("w-20 text-right font-display text-[13px] font-bold tabular-nums", s.points_nets >= 0 ? "text-emerald-700" : "text-rose-700")}>
              {formatPts(s.points_nets, true)}
            </span>
          </div>
        </div>
      ))}
    </div>
  );
}

function MaSaison({ moi, regles, enCours }: { moi: DefiMoi; regles: DefiRegles; enCours: boolean }) {
  const pct = Math.min(100, (moi.nb_paris / regles.min_paris_classement) * 100);
  const verdict = moi.plan.nb_paris && moi.perso.nb_paris && moi.plan.roi != null && moi.perso.roi != null
    ? moi.perso.roi > moi.plan.roi ? "Vos choix perso battent le plan de mise ce mois-ci 🔥"
      : moi.perso.roi < moi.plan.roi ? "Le plan de mise fait mieux que vos choix perso ce mois-ci."
      : "Égalité parfaite entre vos choix et le plan de mise."
    : null;
  return (
    <section className={CARTE} aria-label="Ma saison">
      <div className="grid sm:grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)]">
        <div className="border-b border-stone-100 p-5 sm:border-b-0 sm:border-r">
          <div className="flex items-center gap-2.5">
            <Avatar nom={moi.nom} taille={36} className="ring-stone-100" />
            <div>
              <div className="text-[10.5px] font-bold uppercase tracking-[0.14em] text-slate-500">Ma saison</div>
              <div className="text-[13.5px] font-bold text-slate-900">{moi.nom}</div>
            </div>
          </div>
          <div className="mt-4 font-display text-[36px] font-bold leading-none tabular-nums text-slate-900">{formatPts(moi.solde)}</div>
          <div className="mt-1.5 text-[12.5px] text-slate-600">
            {moi.rang != null
              ? <><b className="text-amber-700">{moi.rang}{moi.rang === 1 ? "er" : "e"}</b> sur {moi.nb_classes} classés</>
              : "Pas encore classé"}
            {" "}· rendement <Roi v={moi.roi} />
          </div>
          {moi.rang == null && (
            <div className="mt-4">
              <div className="flex justify-between text-[11.5px] text-slate-600">
                <span>Qualification</span><span className="font-semibold tabular-nums">{moi.nb_paris}/{regles.min_paris_classement} paris</span>
              </div>
              <span className="mt-1.5 block h-2 overflow-hidden rounded-full bg-stone-100">
                <span className="block h-full rounded-full bg-gradient-to-r from-amber-400 to-amber-600" style={{ width: `${pct}%` }} />
              </span>
            </div>
          )}
          <dl className="mt-4 grid grid-cols-3 gap-2 text-center">
            {([["Paris", moi.nb_paris], ["Gagnés", moi.nb_gagnes], ["En attente", moi.nb_en_attente]] as const).map(([l, v]) => (
              <div key={l} className="flex flex-col-reverse rounded-xl bg-stone-50 py-2 ring-1 ring-inset ring-stone-100">
                <dt className="text-[10.5px] text-slate-500">{l}</dt>
                <dd className="font-display text-[16px] font-bold tabular-nums text-slate-900">{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        <div className="flex flex-col p-5">
          <div className="text-[10.5px] font-bold uppercase tracking-[0.14em] text-slate-500">Le duel du mois</div>
          <p className="mb-3 mt-0.5 text-[12px] text-slate-600">Vos paris repris du plan de mise contre vos propres choix.</p>
          {moi.nb_paris > 0 ? <Duel plan={moi.plan} perso={moi.perso} /> : (
            <p className="rounded-xl bg-stone-50 px-3 py-3 text-[12.5px] text-slate-600 ring-1 ring-inset ring-stone-100">
              Aucun pari ce mois-ci. Ouvrez une course, onglet « Défi du mois ».
            </p>
          )}
          {verdict && <p className="mt-3 text-[12.5px] font-semibold text-slate-800">{verdict}</p>}
          {enCours && (
            <Link href="/programme"
              className="mt-5 inline-flex min-h-[46px] items-center justify-center gap-2 rounded-xl bg-gradient-to-b from-amber-600 to-amber-800 px-4 text-[13px] font-bold text-white shadow-[inset_0_1px_0_rgba(255,255,255,.25)] sm:mt-auto">
              <Target className="h-4 w-4" aria-hidden="true" /> Choisir une course et parier
            </Link>
          )}
        </div>
      </div>
    </section>
  );
}

// ─── Règlement ─────────────────────────────────────────────────────────────
function Reglement({ regles }: { regles: DefiRegles }) {
  const lots = regles.recompenses.map((r) => `${r.rang}${r.rang === 1 ? "er" : "e"} : ${r.jours} jours ${planLabel(r.plan)} offerts`).join(" · ");
  return (
    <details className={cn(CARTE, "group")}>
      <summary className="flex min-h-[56px] cursor-pointer list-none items-center justify-between gap-3 px-5 text-[13.5px] font-bold text-slate-900">
        <span className="inline-flex items-center gap-2"><ScrollText className="h-4 w-4 text-amber-700" aria-hidden="true" /> Règlement complet du défi</span>
        <ChevronDown className="h-4 w-4 text-slate-400 transition-transform group-open:rotate-180" aria-hidden="true" />
      </summary>
      <ol className="list-decimal space-y-2 border-t border-stone-100 pb-5 pl-10 pr-5 pt-4 text-[12.5px] leading-relaxed text-slate-700">
        <li><b>Participation gratuite</b>, réservée aux personnes majeures ayant un compte BlackTurf à l&apos;adresse e-mail confirmée et un pseudo, quel que soit l&apos;abonnement. Aucun achat ni aucun pari en argent réel n&apos;est demandé : les points n&apos;ont aucune valeur monétaire et ne s&apos;échangent pas.</li>
        <li>Chaque mois (calendrier de Paris), chaque joueur reçoit <b>{formatNombre(regles.capital_mensuel, 2)} points</b>. Le solde repart à {formatNombre(regles.capital_mensuel, 2)} le 1<sup>er</sup> du mois suivant.</li>
        <li>Tous les paris que le PMU ouvre sur la course sont proposés : Simple Gagnant et Placé, Couplé Gagnant, Placé et Ordre, Trio et Trio Ordre, Tiercé, 2sur4, Multi (ou Mini Multi), Super 4, Quarté+, Quinté+ et Pick5. Mise de <b>{regles.points_min} à {regles.points_max} points</b> par pari, au plus <b>{regles.max_paris_par_course} paris par course</b>. Pour les paris à l&apos;ordre, l&apos;ordre de sélection des chevaux est l&apos;ordre d&apos;arrivée joué.</li>
        <li>Les paris ferment <b>{regles.verrou_minutes} minutes avant le départ prévu</b>, à l&apos;heure du serveur. Un pari validé est définitif : ni modifiable, ni annulable.</li>
        <li>Un pari gagnant rapporte <b>points misés × rapport PMU officiel</b> (pour 1 € misé) publié à l&apos;arrivée, le même pour tous les joueurs, quel que soit l&apos;opérateur où chacun joue en vrai. Tiercé, Quarté+ et Quinté+ sont réglés comme un ticket PMU : rapport Ordre si l&apos;ordre joué est exact, sinon Désordre, sinon Bonus. Une formule à plusieurs chevaux (2sur4 ou Pick5 au-delà du minimum) répartit la mise sur ses combinaisons ; le Multi est réglé au rapport de la formule jouée (en 4, 5, 6 ou 7). Un cheval non-partant, une course annulée ou un rapport jamais publié dans les 72 heures remboursent la mise.</li>
        <li>Le pari porte l&apos;étiquette « Plan BlackTurf » quand il reprend un pari du plan de mise que vous avez consulté sur la course, « Perso » sinon. L&apos;étiquette n&apos;a pas d&apos;effet sur le classement.</li>
        <li>Sont classés les joueurs ayant engagé au moins <b>{regles.min_paris_classement} paris</b> dans le mois, par solde décroissant ; à égalité, le plus grand nombre de paris gagnants puis le premier pari le plus ancien l&apos;emportent.</li>
        <li>Récompenses : {lots}. Elles sont remises après la clôture du mois, une fois tous les paris réglés et les comptes vérifiés. Un abonné payant reçoit l&apos;équivalent en déduction de son abonnement. Les récompenses sont nominatives et ne s&apos;échangent pas contre de l&apos;argent.</li>
        <li>Lancement officiel le <b>{dateLancement(regles.premier_mois)}</b>. Les mois précédents sont des mois d&apos;essai : on y joue avec les mêmes règles, sans récompense.</li>
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
  const { data: classement, isLoading } = useSWR<DefiClassement>(
    ["/defi/classement", mois, user?.user_id ?? ""], () => defiApi.classement(mois).then((r) => r.data),
    { refreshInterval: enCours ? 60_000 : 0 });
  const { data: moi } = useSWR<DefiMoi>(
    user ? ["/defi/moi", mois, user.user_id] : null, () => defiApi.moi(mois).then((r) => r.data),
    { refreshInterval: enCours ? 60_000 : 0 });
  const { data: palmares } = useSWR<DefiPalmares>("/defi/palmares", () => defiApi.palmares().then((r) => r.data));

  const classes = classement?.lignes.filter((l) => l.classe) ?? [];
  const autres = classement?.lignes.filter((l) => !l.classe) ?? [];
  const max = classes[0]?.solde ?? 0;
  const palmaresParMois = (palmares ?? []).reduce<Record<string, DefiPalmares>>((acc, p) => {
    (acc[p.mois] ??= []).push(p);
    return acc;
  }, {});

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 px-4 py-6 sm:px-6 sm:py-8">
      {classement?.essai && <BandeauEssai premierMois={regles.premier_mois} />}
      <Hero mois={mois} enCours={enCours} setMois={setMois} regles={regles} classement={classement} />

      {user ? (
        moi ? <MaSaison moi={moi} regles={regles} enCours={enCours} /> : (
          <div className={cn(CARTE, "flex justify-center p-10")}><Loader2 className="h-5 w-5 animate-spin text-slate-400" /></div>
        )
      ) : (
        <div className={cn(CARTE, "p-5")}>
          <CompteGratuitCta
            titre="Entrez dans le défi"
            texte={`Un compte gratuit suffit : ${formatNombre(regles.capital_mensuel, 2)} points chaque mois pour parier sur les courses, et un abonnement à gagner.`}
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

      <section aria-labelledby="defi-concept">
        <TitreSection id="defi-concept" surtitre="En 4 étapes" titre="Comment ça marche" />
        <DefiConcept
          capital={regles.capital_mensuel}
          pointsMin={regles.points_min}
          pointsMax={regles.points_max}
          prix={regles.recompenses[0]}
        />
        <div className="mt-3 flex items-start gap-3 rounded-2xl bg-amber-50/70 px-4 py-3 text-[12.5px] leading-relaxed text-slate-700 ring-1 ring-inset ring-amber-200">
          <span className="font-display text-[15px] font-bold text-amber-700">Ex.</span>
          <p>
            50 points sur un cheval gagnant rapporté 4,20 € au PMU : 50 × 4,20 = <b className="text-slate-900">210 points</b> reviennent
            dans votre solde, soit +160 points. Un pari perdu retire sa mise. Il faut {regles.min_paris_classement} paris dans le mois
            pour entrer au classement.
          </p>
        </div>
      </section>

      <section aria-labelledby="defi-classement">
        <TitreSection id="defi-classement" surtitre={enCours ? "En direct" : moisLabel(mois)} titre="Classement du mois" />
        <div className={CARTE}>
          <DefiEntete
            compact
            surtitre={moisLabel(mois)}
            titre="Le podium"
            sousTitre={`${classement?.nb_classes ?? 0} joueur${(classement?.nb_classes ?? 0) > 1 ? "s" : ""} classé${(classement?.nb_classes ?? 0) > 1 ? "s" : ""} · minimum ${regles.min_paris_classement} paris`}
            droite={enCours ? <><PastilleDirect /><CompteRebours mois={mois} /></> : undefined}
          >
            {isLoading ? (
              <div className="flex h-40 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-amber-600/70" /></div>
            ) : (
              <Podium lignes={[0, 1, 2].map((i) => classes[i] && ({ nom: classes[i].nom, solde: classes[i].solde, moi: classes[i].moi }))} />
            )}
          </DefiEntete>
          {classes.length > 3 && (
            <ol className="divide-y divide-stone-100 py-1">
              {classes.slice(3).map((l) => (
                <LigneClassement key={`${l.rang}-${l.nom}`} rang={l.rang} nom={l.nom} solde={l.solde}
                  nbParis={l.nb_paris} moi={l.moi} max={max}
                  detail={<>{l.nb_paris} paris · {l.nb_gagnes} gagnés</>} />
              ))}
            </ol>
          )}
          {classes.length === 0 && !isLoading && (
            <p className="px-5 py-4 text-[12.5px] text-slate-600">
              Personne n&apos;est encore classé : il faut {regles.min_paris_classement} paris dans le mois. La première place est à prendre.
            </p>
          )}
          {autres.length > 0 && (
            <div className="border-t border-stone-100">
              <button type="button" onClick={() => setVoirNonClasses((v) => !v)} aria-expanded={voirNonClasses}
                className="flex min-h-[48px] w-full items-center justify-between px-5 text-[12.5px] font-semibold text-slate-700 hover:bg-stone-50">
                En course pour la qualification ({autres.length})
                <ChevronDown className={cn("h-4 w-4 text-slate-400 transition-transform", voirNonClasses && "rotate-180")} />
              </button>
              {voirNonClasses && (
                <ul className="divide-y divide-stone-100 border-t border-stone-100 py-1">
                  {autres.map((l, i) => (
                    <LigneClassement key={`${i}-${l.nom}`} rang={null} nom={l.nom} solde={l.solde} nbParis={l.nb_paris}
                      moi={l.moi} max={max || l.solde}
                      detail={l.hors_concours ? "hors concours" : `${l.nb_paris}/${regles.min_paris_classement} paris`} />
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </section>

      {moi && moi.paris.length > 0 && (
        <section aria-labelledby="defi-mes-paris">
          <TitreSection id="defi-mes-paris" surtitre={moisLabel(mois)} titre="Mes paris"
            droite={<span className="text-[12px] tabular-nums text-slate-500">{moi.paris.length} pari{moi.paris.length > 1 ? "s" : ""}</span>} />
          <ul className="grid gap-2 sm:grid-cols-2">
            {moi.paris.map((p) => (
              <li key={p.pari_id} className="flex flex-col justify-between gap-2 rounded-2xl bg-white p-4 ring-1 ring-inset ring-[#ECE7DC]">
                <div className="flex items-start justify-between gap-2">
                  <Link href={`/courses/${p.course_id}#defi`} className="min-w-0 hover:underline">
                    <div className="text-[13px] font-bold text-slate-900">{p.type_pari} {chevauxLisibles(p.type_pari, p.chevaux)}</div>
                    <div className="truncate text-[11.5px] text-slate-500">
                      {p.course_label}{p.date_heure && <> · {new Date(p.date_heure).toLocaleString("fr-FR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</>}
                    </div>
                  </Link>
                  <ResultatPari p={p} />
                </div>
                <div className="flex flex-wrap gap-1.5"><StatutPari statut={p.statut} /><OriginePari origine={p.origine} /></div>
              </li>
            ))}
          </ul>
        </section>
      )}

      {palmares && palmares.length > 0 && (
        <section aria-labelledby="defi-palmares">
          <TitreSection id="defi-palmares" surtitre="Les mois passés" titre="Palmarès" />
          <ul className="grid gap-3 sm:grid-cols-2">
            {Object.entries(palmaresParMois).map(([m, gagnants]) => (
              <li key={m} className={cn(CARTE, "p-4")}>
                <div className="flex items-center gap-2 text-[12.5px] font-bold text-slate-900">
                  <Trophy className="h-4 w-4 text-amber-600" aria-hidden="true" /> {moisLabel(m)}
                </div>
                <ol className="mt-2.5 space-y-2">
                  {[...gagnants].sort((a, b) => a.rang - b.rang).map((g) => (
                    <li key={g.rang} className="flex items-center gap-2.5 text-[12.5px]">
                      <span className="w-6 text-center font-display font-bold text-slate-500">{g.rang}</span>
                      <Avatar nom={g.nom} taille={26} className="ring-stone-100" />
                      <span className="min-w-0 flex-1 truncate font-semibold text-slate-800">{g.nom}</span>
                      <span className="tabular-nums text-slate-500">{formatPts(g.solde)}</span>
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        </section>
      )}

      <Reglement regles={regles} />

      <Link href="/programme" className="inline-flex items-center justify-center gap-1.5 self-center text-[13px] font-semibold text-amber-800 hover:underline">
        Voir les courses du jour <ArrowRight className="h-4 w-4" aria-hidden="true" />
      </Link>
    </div>
  );
}
