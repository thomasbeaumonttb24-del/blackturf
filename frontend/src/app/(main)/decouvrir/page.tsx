import type { Metadata } from "next";
import type { ReactNode } from "react";
import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";
import { fetchPalmaresPublic, fetchTrackRecord } from "@/lib/seo";

/**
 * Page d'arrivée des réseaux sociaux (lien de la bio TikTok, Instagram, Facebook).
 *
 * Le visiteur arrive d'une vidéo qui parlait de courses, pas du site. Les vidéos ne
 * peuvent pas vendre (TikTok interdit la promotion des services de paris) : c'est cette
 * page qui convertit. Parti pris : une page produit sobre, des écrans réels lisibles et
 * annotés, des chiffres mesurés, puis gratuit → Pass Jour → Expert.
 *
 * Écrans : captures iPhone 15 Pro (393×852 @3x) du site en ligne, barre d'état comprise,
 * pour que la maquette garde les proportions exactes du téléphone.
 *
 * Hors index : page de campagne, son contenu double l'accueil et /tarifs.
 * Chiffres lus dans l'API ; le bandeau disparaît plutôt que d'afficher un zéro.
 */
export const revalidate = 900;

const TITLE = "Découvrir BlackTurf : chaque course PMU en chiffres";
const DESCRIPTION =
  "Les chances de chaque cheval, la cote juste et un plan de mise à ton budget, sur toutes les courses PMU du jour.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/decouvrir" },
  robots: { index: false, follow: true },
};

const nb = (v: number) => v.toLocaleString("fr-FR");
const pct = (v: number) => `${v.toLocaleString("fr-FR", { maximumFractionDigits: 0 })} %`;

type PariPublic = {
  course_id: string;
  hippodrome: string;
  date: string;
  type_pari: string;
  chevaux: number[];
  mise: number;
  gain: number;
  rapport: number;
  fige_avant_course: boolean;
};

type Palmares = {
  top_gains?: PariPublic[];
  gagnants?: PariPublic[];
  nb_paris_gagnes?: number;
  nb_courses_gagnantes?: number;
  nb_courses_reglees?: number;
  quinte?: { disponible?: boolean; nb_tickets_gagnants?: number; nb_courses?: number; depuis?: string | null };
};

const euros = (v: number) =>
  `${v.toLocaleString("fr-FR", { minimumFractionDigits: 0, maximumFractionDigits: v % 1 === 0 ? 0 : 2 })} €`;

/** « HIPPODROME DE VITTEL » → « Vittel » ; « HIPPODROME DE NEWMARKET GB » → « Newmarket (GB) ». */
function lieu(nom: string): string {
  const s = nom.replace(/^HIPPODROME (DE |D'|DU |DES )?/i, "").trim();
  const etr = s.match(/^(.*) ([A-Z]{2,3})$/);
  const t = (x: string) => x.toLowerCase().replace(/(^|[\s'-])\p{L}/gu, (m) => m.toUpperCase());
  return etr ? `${t(etr[1])} (${etr[2]})` : t(s);
}

const jourCourt = (iso: string) =>
  new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "short", timeZone: "Europe/Paris" });
const heure = (iso: string) =>
  new Date(iso).toLocaleTimeString("fr-FR", { hour: "2-digit", minute: "2-digit", timeZone: "Europe/Paris" });

const INSCRIPTION = `/inscription?suite=${encodeURIComponent("/programme")}`;

/**
 * Les écrans entiers rendent tout illisible : chaque étape montre le BLOC utile, découpé
 * dans une capture réelle et affiché à taille de lecture.
 */
const ETAPES = [
  {
    src: "/img/decouvrir/bloc-course.webp",
    w: 840,
    h: 797,
    alt: "Prochaine course : Prix de Loucelles à Caen, départ dans 4 min 58, attelé, 2 450 m, 16 partants",
    t: "Choisis ta course",
    d: "Tout le programme PMU du jour, avec le compte à rebours du prochain départ.",
    points: ["Trot et galop, toutes les réunions", "Distance, discipline, nombre de partants"],
  },
  {
    src: "/img/decouvrir/bloc-chevaux.webp",
    w: 840,
    h: 1126,
    alt: "Deux fiches partants : PHINEAS 50 % de victoire, cote 2,0 pour une cote juste de 1,98 ; WIMBLEDON HAWKEYE 20 %, cote 3,9 pour une cote juste de 4,96",
    t: "Vois les chances de chaque cheval",
    d: "Un pourcentage de victoire par cheval, et la cote qu'il devrait avoir.",
    points: ["Cote PMU face à la cote juste", "Forme, aptitude et niveau notés sur 100", "Dernières places et changement de jockey"],
  },
  {
    src: "/img/decouvrir/bloc-plan.webp",
    w: 840,
    h: 1051,
    alt: "Plan de mise de 10 € figé avant le départ, profil Risqué : Couplé Ordre 3-7 pour 4 € et 3-1 pour 6 €",
    t: "Suis un plan à ton budget",
    d: "Tu donnes ton montant, le site le répartit selon ton profil.",
    points: ["Prudent, Modéré ou Risqué", "Figé avant le départ, réglé aux rapports PMU réels"],
  },
];

/** Fonctions montrées en vrais écrans. `acces` = formule minimale (grille de /tarifs). */
const FONCTIONS = [
  {
    src: "/img/decouvrir/f-valeur.webp", w: 505, h: 616, large: false,
    acces: "Standard", t: "Paris de valeur",
    d: "Les chevaux mieux cotés que leur vraie chance. Ici : 29 % calculés contre 22 % selon la cote, et la meilleure cote du marché à 9,5.",
    alt: "Pari de valeur : Kamaran Madrik, chance calculée 29 % contre 22 % selon la cote, cote juste 3,5, meilleure cote 9,5 chez Bet365, afflux d'argent",
  },
  {
    src: "/img/decouvrir/f-outsider.webp", w: 760, h: 758, large: false,
    acces: "Standard", t: "Outsiders détectés",
    d: "Les grosses cotes capables d'accrocher une place, avec leurs raisons sur 30 critères. Ici : repéré à 26, arrivé 3e.",
    alt: "Outsider fort : Bismillah Face, cote 42, repéré à 26, 31 % de chance top 3, 8 critères favorables, arrivé 3e placé ×4,8",
  },
  {
    src: "/img/decouvrir/f-cotes-live.webp", w: 1365, h: 470, large: true,
    acces: "Compte gratuit", t: "Cotes en direct",
    d: "Chaque cote suivie jusqu'au départ, rafraîchie toutes les 5 secondes : qui est joué, qui est délaissé.",
    alt: "Marché des cotes en direct : courbe et variation de chaque cheval depuis l'ouverture",
  },
  {
    src: "/img/decouvrir/f-comparaison.webp", w: 760, h: 1046, large: false,
    acces: "Compte gratuit", t: "Cotes de 5 sites comparées",
    d: "PMU, Geny, Unibet, Bet365, Ladbrokes côte à côte. La meilleure cote ressort en vert.",
    alt: "Tableau de comparaison des cotes PMU, Geny, Unibet et Bet365 pour chaque cheval, meilleure cote en vert",
  },
  {
    src: "/img/decouvrir/f-duel.webp", w: 760, h: 918, large: false,
    acces: "Compte gratuit", t: "Duel de deux chevaux",
    d: "Cote, ELO, forme, victoires, repos : deux partants face à face, critère par critère. Plus les confrontations déjà courues.",
    alt: "Comparateur : Horus de Val contre Kassya, cote, ELO, forme, victoires, nombre de courses",
  },
  {
    src: "/img/decouvrir/f-argent.webp", w: 1365, h: 714, large: true,
    acces: "Standard", t: "L'argent misé, cheval par cheval",
    d: "Où va l'argent des parieurs, et les grosses mises qui arrivent juste avant le départ.",
    alt: "Argent misé en Simple gagnant cheval par cheval : grosse mise de 9 613 € sur North Rim, +5 035 € entrés en 26 minutes",
  },
];

const AUSSI = [
  { t: "Assistant IA", d: "Pose tes questions sur n'importe quelle course." },
  { t: "Créateur de stratégies", d: "Teste tes propres règles sur 12 mois de courses." },
  { t: "Argent pro détecté", d: "Les mouvements de cote suspects signalés en direct." },
  { t: "Alertes", d: "E-mail et notifications avant les courses qui t'intéressent." },
  { t: "Module Quinté+", d: "Le Quinté du jour analysé, tickets réglés aux vrais rapports." },
  { t: "Pronostics presse", d: "L'avis des journaux comparé à celui de l'algorithme." },
];

const FORMULES = [
  { nom: "Gratuit", prix: "0 €", sous: "pour toujours", points: ["Programme et cotes en direct", "1 course analysée par jour", "Défi du mois"], cta: "Créer un compte", href: INSCRIPTION, fort: false },
  { nom: "Pass Jour", prix: "5 €", sous: "24 h, sans abonnement", points: ["Tout débloqué pendant 24 h", "Aucun renouvellement", "Idéal un jour de Quinté+"], cta: "Tester 24 h", href: "/tarifs#passes", fort: false },
  { nom: "Expert", prix: "19 €", sous: "par mois, sans engagement", points: ["Toutes les courses, sans limite", "Paris de valeur en direct", "Assistant IA et alertes"], cta: "Passer Expert", href: "/tarifs", fort: true },
];

function Telephone({
  src,
  alt,
  priority = false,
  className = "",
  children,
}: {
  src: string;
  alt: string;
  priority?: boolean;
  className?: string;
  children?: ReactNode;
}) {
  return (
    <div className={`rounded-[2.9rem] bg-stone-950 p-[9px] shadow-[0_40px_80px_-32px_rgba(17,24,39,0.45)] ring-1 ring-stone-800 ${className}`}>
      <div className="relative aspect-[393/852] overflow-hidden rounded-[2.35rem] bg-white">
        {/* Barre d'état iOS */}
        <div className="absolute inset-x-0 top-0 z-10 flex h-[6.34%] items-center justify-between bg-white px-[9%] text-[11px] font-semibold text-stone-900">
          <span>9:41</span>
          <span className="flex items-center gap-1" aria-hidden>
            <svg width="16" height="10" viewBox="0 0 16 10" fill="currentColor"><rect x="0" y="6" width="3" height="4" rx="0.8" /><rect x="4.3" y="4" width="3" height="6" rx="0.8" /><rect x="8.6" y="2" width="3" height="8" rx="0.8" /><rect x="12.9" y="0" width="3" height="10" rx="0.8" /></svg>
            <svg width="22" height="11" viewBox="0 0 22 11"><rect x="0.5" y="0.5" width="19" height="10" rx="3" fill="none" stroke="currentColor" opacity="0.4" /><rect x="2" y="2" width="14" height="7" rx="1.6" fill="currentColor" /><rect x="20.4" y="3.5" width="1.4" height="4" rx="0.7" fill="currentColor" opacity="0.4" /></svg>
          </span>
        </div>
        <div className="absolute left-1/2 top-[1.3%] z-20 h-[3.6%] w-[31%] -translate-x-1/2 rounded-full bg-black" aria-hidden />
        <Image
          src={src}
          alt={alt}
          width={780}
          height={1584}
          priority={priority}
          sizes="(min-width: 768px) 300px, 260px"
          className="absolute inset-x-0 top-[6.34%] h-auto w-full"
        />
        {children}
      </div>
    </div>
  );
}

export default async function DecouvrirPage() {
  const [tr, palmaresBrut] = await Promise.all([fetchTrackRecord(), fetchPalmaresPublic()]);
  const p = (palmaresBrut ?? {}) as Palmares;
  const top = (p.top_gains ?? []).filter((t) => t.fige_avant_course).slice(0, 3);
  const derniers = (p.gagnants ?? []).filter((t) => t.fige_avant_course).slice(0, 3);
  const aDesResultats = !!p.nb_paris_gagnes && p.nb_paris_gagnes > 0;
  const g = tr?.global;
  const mesure = !!g && g.nb_courses_analysees > 0 && g.accuracy_top3 != null && g.hasard_top3 != null;

  return (
    <div className="bg-white text-stone-900">
      {/* Accroche */}
      <section className="border-b border-stone-200 bg-[#faf8f4]">
        <div className="mx-auto grid max-w-6xl items-center gap-12 px-4 py-14 sm:py-20 md:grid-cols-[1fr_auto] md:gap-16">
          <div className="max-w-xl">
            <p className="text-sm font-medium text-brand-gold-dark">BlackTurf · analyse des courses PMU</p>
            <h1 className="mt-4 font-display text-[2.05rem] font-semibold leading-[1.05] tracking-[-0.035em] text-stone-950 sm:text-6xl">
              Chaque course PMU,
              <br />
              lue en chiffres.
            </h1>
            <p className="mt-5 text-lg leading-relaxed text-stone-600">
              Les chances de chaque cheval, la cote juste et un plan de mise à ton budget. Sur toutes les courses du jour.
            </p>
            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link
                href={INSCRIPTION}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-stone-950 px-6 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-stone-800"
              >
                Créer un compte gratuit <ArrowRight className="h-4 w-4" />
              </Link>
              <Link
                href="/tarifs"
                className="inline-flex items-center justify-center gap-1.5 rounded-full px-5 py-3.5 text-[15px] font-semibold text-stone-900 ring-1 ring-stone-300 transition-colors hover:bg-white"
              >
                Voir les prix
              </Link>
            </div>
            <p className="mt-3 text-sm text-stone-500">Sans carte bancaire. Réservé aux 18 ans et plus.</p>
          </div>

          <div className="relative mx-auto w-full max-w-[460px] md:w-[460px]">
            <Telephone
              src="/img/decouvrir/partants.webp"
              alt="Écran Partants d'une course sur mobile"
              priority
              className="ml-auto w-[230px] sm:w-[270px]"
            />
            {/* Le bloc qui compte, agrandi, posé devant le téléphone */}
            <figure className="absolute bottom-[12%] left-0 w-[78%] max-w-[360px] overflow-hidden rounded-2xl bg-white shadow-[0_24px_60px_-20px_rgba(17,24,39,0.35)] ring-1 ring-stone-200">
              <Image
                src="/img/decouvrir/bloc-cheval.webp"
                alt="Fiche PHINEAS : 50 % de chances de victoire, 78 % dans le top 3, cote 2,0 pour une cote juste de 1,98, forme 100, aptitude 92, niveau 100"
                width={840}
                height={559}
                priority
                sizes="360px"
                className="h-auto w-full"
              />
            </figure>
          </div>
        </div>
      </section>

      {/* Chiffres clés */}
      {mesure && (
        <section className="border-b border-stone-200">
          <dl className="mx-auto grid max-w-6xl grid-cols-2 px-4 md:grid-cols-4">
            {[
              { v: nb(g.nb_courses_analysees), l: "courses analysées et vérifiées" },
              { v: pct(g.accuracy_top3), l: `n°1 de l'algorithme dans le top 3 (hasard : ${pct(g.hasard_top3)})` },
              { v: "7j/7", l: "modèle réentraîné chaque nuit sur les arrivées" },
              { v: "100 %", l: "des résultats publiés, pertes comprises" },
            ].map((c, i) => (
              <div
                key={c.l}
                className={["py-8 px-4 md:px-8 border-stone-200", i % 2 === 1 && "border-l", i >= 2 && "border-t md:border-t-0", i === 2 && "md:border-l", (i === 0 || i === 2) && "pl-0", i === 2 && "md:pl-8"].filter(Boolean).join(" ")}
              >
                <dt className="font-display text-3xl font-semibold tracking-tight text-stone-950 tabular-nums sm:text-4xl">{c.v}</dt>
                <dd className="mt-1.5 text-sm leading-snug text-stone-500">{c.l}</dd>
              </div>
            ))}
          </dl>
        </section>
      )}

      {/* Résultats réels */}
      {aDesResultats && (
        <section className="border-b border-stone-200 bg-stone-950 text-white">
          <div className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
            <p className="text-sm font-medium text-amber-400">Résultats réels</p>
            <h2 className="mt-3 max-w-2xl font-display text-3xl font-semibold tracking-[-0.025em] sm:text-4xl">
              Chaque pari figé avant le départ, réglé aux rapports PMU.
            </h2>

            <dl className="mt-12 grid grid-cols-2 gap-x-6 gap-y-10 md:grid-cols-4">
              {[
                p.nb_paris_gagnes ? { v: nb(p.nb_paris_gagnes), l: "paris gagnants" } : null,
                p.nb_courses_gagnantes && p.nb_courses_reglees
                  ? { v: nb(p.nb_courses_gagnantes), l: `courses gagnées sur ${nb(p.nb_courses_reglees)} jouées` }
                  : null,
                top[0] ? { v: euros(top[0].gain), l: `plus gros gain, pour ${euros(top[0].mise)} misés` } : null,
                p.quinte?.disponible && p.quinte.nb_tickets_gagnants
                  ? { v: nb(p.quinte.nb_tickets_gagnants), l: `tickets Quinté+ gagnants${p.quinte.depuis ? ` depuis le ${jourCourt(p.quinte.depuis)}` : ""}` }
                  : null,
              ]
                .filter((c): c is { v: string; l: string } => c !== null)
                .map((c) => (
                  <div key={c.l} className="border-l border-stone-700 pl-5">
                    <dt className="font-display text-3xl font-semibold tracking-tight tabular-nums sm:text-4xl">{c.v}</dt>
                    <dd className="mt-1.5 text-sm leading-snug text-stone-400">{c.l}</dd>
                  </div>
                ))}
            </dl>

            <div className="mt-16 grid gap-10 lg:grid-cols-2">
              {top.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-stone-400">Les plus gros coups</h3>
                  <ul className="mt-4 divide-y divide-stone-800 rounded-2xl bg-stone-900 ring-1 ring-stone-800">
                    {top.map((t) => (
                      <li key={t.course_id + t.type_pari + t.chevaux.join("-")} className="flex items-center justify-between gap-4 px-5 py-4">
                        <div className="min-w-0">
                          <div className="font-semibold">{t.type_pari} · {t.chevaux.join("-")}</div>
                          <div className="mt-0.5 truncate text-sm text-stone-400">
                            {lieu(t.hippodrome)} · {jourCourt(t.date)} · rapport {t.rapport.toLocaleString("fr-FR")}
                          </div>
                        </div>
                        <div className="shrink-0 text-right tabular-nums">
                          <div className="text-xs text-stone-500">{euros(t.mise)} →</div>
                          <div className="font-display text-xl font-semibold text-amber-400">{euros(t.gain)}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
              {derniers.length > 0 && (
                <div>
                  <h3 className="text-sm font-semibold uppercase tracking-wider text-stone-400">Derniers paris gagnants</h3>
                  <ul className="mt-4 divide-y divide-stone-800 rounded-2xl bg-stone-900 ring-1 ring-stone-800">
                    {derniers.map((t) => (
                      <li key={t.course_id + t.type_pari + t.chevaux.join("-")} className="flex items-center justify-between gap-4 px-5 py-4">
                        <div className="min-w-0">
                          <div className="font-semibold">{t.type_pari} · {t.chevaux.join("-")}</div>
                          <div className="mt-0.5 truncate text-sm text-stone-400">
                            {lieu(t.hippodrome)} · {jourCourt(t.date)} à {heure(t.date)}
                          </div>
                        </div>
                        <div className="shrink-0 text-right tabular-nums">
                          <div className="text-xs text-stone-500">{euros(t.mise)} →</div>
                          <div className="font-display text-xl font-semibold text-emerald-400">{euros(t.gain)}</div>
                        </div>
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
            <p className="mt-8 max-w-3xl text-sm leading-relaxed text-stone-400">
              Les gros coups sont rares et la plupart des paris ne gagnent pas. Le bilan complet, pertes comprises, est public sur la page{" "}
              <Link href="/track-record" className="font-medium text-white underline underline-offset-4">Performances</Link>.
            </p>
            <div className="mt-10 flex flex-col gap-3 sm:flex-row sm:items-center">
              <Link
                href={INSCRIPTION}
                className="inline-flex items-center justify-center gap-2 rounded-full bg-white px-6 py-3.5 text-[15px] font-semibold text-stone-950 transition-colors hover:bg-stone-200"
              >
                Voir les plans du jour <ArrowRight className="h-4 w-4" />
              </Link>
              <span className="text-sm text-stone-400">Compte gratuit : 1 course analysée chaque jour.</span>
            </div>
          </div>
        </section>
      )}

      {/* Fonctions */}
      <section className="border-b border-stone-200 bg-[#faf8f4]">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
          <div className="max-w-2xl">
            <p className="text-sm font-medium text-brand-gold-dark">Tout ce que tu débloques</p>
            <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.025em] text-stone-950 sm:text-4xl">
              Les outils des pros, sur chaque course.
            </h2>
            <p className="mt-4 text-lg text-stone-600">Écrans réels du site, pris aujourd&apos;hui.</p>
          </div>
          <div className="mt-12 grid gap-6 md:grid-cols-2">
            {FONCTIONS.map((f) => (
              <article
                key={f.src}
                className={`flex flex-col overflow-hidden rounded-3xl bg-white ring-1 ring-stone-200 ${f.large ? "md:col-span-2" : ""}`}
              >
                <div className="p-6 sm:p-8">
                  <span
                    className={`inline-flex rounded-full px-2.5 py-1 text-xs font-semibold ${
                      f.acces === "Compte gratuit" ? "bg-stone-100 text-stone-700" : "bg-stone-950 text-white"
                    }`}
                  >
                    {f.acces === "Compte gratuit" ? "Compte gratuit" : `Dès ${f.acces}`}
                  </span>
                  <h3 className="mt-4 font-display text-2xl font-semibold tracking-[-0.02em] text-stone-950">{f.t}</h3>
                  <p className="mt-2 max-w-xl text-[15px] leading-relaxed text-stone-600">{f.d}</p>
                </div>
                <div className="mt-auto bg-[#f5f0e6] px-4 pt-6 sm:px-8 sm:pt-8">
                  <Image
                    src={f.src}
                    alt={f.alt}
                    width={f.w}
                    height={f.h}
                    sizes={f.large ? "(min-width: 1024px) 1000px, 94vw" : "(min-width: 768px) 460px, 90vw"}
                    className={`mx-auto h-auto w-full rounded-t-2xl shadow-[0_-8px_40px_-20px_rgba(17,24,39,0.35)] ${f.large ? "max-w-[1000px]" : "max-w-[440px]"}`}
                  />
                </div>
              </article>
            ))}
          </div>

          <h3 className="mt-16 text-sm font-semibold uppercase tracking-wider text-stone-500">Et aussi</h3>
          <ul className="mt-5 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
            {AUSSI.map((a) => (
              <li key={a.t} className="flex gap-3">
                <Check className="mt-1 h-4 w-4 shrink-0 text-brand-gold-dark" />
                <span>
                  <span className="block font-semibold text-stone-900">{a.t}</span>
                  <span className="block text-[15px] text-stone-500">{a.d}</span>
                </span>
              </li>
            ))}
          </ul>
          <div className="mt-12">
            <Link
              href="/tarifs"
              className="inline-flex items-center justify-center gap-2 rounded-full bg-stone-950 px-6 py-3.5 text-[15px] font-semibold text-white transition-colors hover:bg-stone-800"
            >
              Débloquer tous les outils <ArrowRight className="h-4 w-4" />
            </Link>
          </div>
        </div>
      </section>

      {/* Comment ça marche */}
      <section className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
        <div className="max-w-2xl">
          <p className="text-sm font-medium text-brand-gold-dark">Comment ça marche</p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.025em] text-stone-950 sm:text-4xl">De la course au plan, en trois écrans.</h2>
        </div>
        <div className="mt-14 space-y-20 sm:space-y-28">
          {ETAPES.map((e, i) => (
            <div key={e.src} className="grid items-center gap-8 md:grid-cols-2 md:gap-16">
              <div className={i % 2 === 1 ? "md:order-2" : ""}>
                <span className="font-mono text-sm font-semibold text-brand-gold-dark">0{i + 1}</span>
                <h3 className="mt-2 font-display text-2xl font-semibold tracking-[-0.02em] text-stone-950 sm:text-3xl">{e.t}</h3>
                <p className="mt-3 text-lg leading-relaxed text-stone-600">{e.d}</p>
                <ul className="mt-6 space-y-2.5">
                  {e.points.map((p) => (
                    <li key={p} className="flex items-start gap-2.5 text-[15px] text-stone-700">
                      <Check className="mt-0.5 h-4 w-4 shrink-0 text-brand-gold-dark" />
                      {p}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-3xl bg-[#f5f0e6] p-5 sm:p-10">
                <Image
                  src={e.src}
                  alt={e.alt}
                  width={e.w}
                  height={e.h}
                  sizes="(min-width: 768px) 420px, 92vw"
                  className="mx-auto h-auto w-full max-w-[420px] rounded-2xl shadow-[0_20px_50px_-24px_rgba(17,24,39,0.35)]"
                />
              </div>
            </div>
          ))}
        </div>
        <p className="mt-16 text-center text-xs text-stone-400">Captures réelles du site. Fiches et plan : Qatar Prix Dollar, ParisLongchamp, 3 octobre 2026.</p>
      </section>

      {/* Formules */}
      <section className="border-t border-stone-200 bg-[#faf8f4]">
        <div className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
          <div className="max-w-2xl">
            <p className="text-sm font-medium text-brand-gold-dark">Formules</p>
            <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.025em] text-stone-950 sm:text-4xl">Commence gratuitement. Débloque tout quand tu veux.</h2>
          </div>
          <div className="mt-12 grid gap-5 md:grid-cols-3">
            {FORMULES.map((f) => (
              <div
                key={f.nom}
                className={`flex flex-col rounded-2xl p-7 ${f.fort ? "bg-stone-950 text-white" : "bg-white ring-1 ring-stone-200"}`}
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-[15px] font-semibold">{f.nom}</h3>
                  {f.fort && <span className="text-xs font-medium text-amber-400">Recommandé</span>}
                </div>
                <div className="mt-5 flex items-baseline gap-2">
                  <span className="font-display text-5xl font-semibold tracking-tight tabular-nums">{f.prix}</span>
                  <span className={`text-sm ${f.fort ? "text-stone-400" : "text-stone-500"}`}>{f.sous}</span>
                </div>
                <ul className={`mt-7 space-y-3 border-t pt-6 ${f.fort ? "border-stone-800" : "border-stone-200"}`}>
                  {f.points.map((p) => (
                    <li key={p} className="flex items-start gap-2.5 text-[15px]">
                      <Check className={`mt-0.5 h-4 w-4 shrink-0 ${f.fort ? "text-amber-400" : "text-stone-900"}`} />
                      <span className={f.fort ? "text-stone-200" : "text-stone-600"}>{p}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href={f.href}
                  className={`mt-8 inline-flex items-center justify-center gap-2 rounded-full px-5 py-3 text-[15px] font-semibold transition-colors ${
                    f.fort ? "bg-white text-stone-950 hover:bg-stone-200" : "bg-stone-950 text-white hover:bg-stone-800"
                  }`}
                >
                  {f.cta} <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            ))}
          </div>
          <p className="mt-6 text-sm text-stone-500">
            Aussi : Standard 12 €/mois, Pass Semaine 12 €, Pass Mois 24 €.{" "}
            <Link href="/tarifs" className="font-medium text-stone-900 underline underline-offset-4">Tous les prix</Link>
          </p>
        </div>
      </section>

      <p className="mx-auto max-w-3xl px-4 py-10 text-center text-xs leading-relaxed text-stone-400">
        Jouer comporte des risques : endettement, dépendance… Appelez le 09 74 75 13 13 (appel non surtaxé). Réservé aux
        majeurs. BlackTurf est un outil d&apos;analyse : aucun gain n&apos;est garanti.
      </p>
    </div>
  );
}
