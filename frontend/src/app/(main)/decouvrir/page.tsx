import type { Metadata } from "next";
import Link from "next/link";
import {
  ArrowRight,
  BarChart3,
  Check,
  Crown,
  ListOrdered,
  Search,
  ShieldCheck,
  Trophy,
  Wallet,
} from "lucide-react";
import { fetchTrackRecord } from "@/lib/seo";
import { SeoHero, Container, Section, Chip } from "@/components/seo/kit";

/**
 * Page d'arrivée des réseaux sociaux (lien de la bio TikTok, Instagram, Facebook).
 *
 * Le visiteur arrive d'une vidéo qui parlait de courses, pas du site : il ne sait pas ce
 * qu'est BlackTurf. L'accueil lui parle comme à un habitué ; ici, on explique en trois
 * écrans ce que fait le site, on montre les chiffres mesurés, puis on déroule l'échelle
 * gratuit → Pass Jour → Expert. Les vidéos elles-mêmes ne peuvent pas vendre (TikTok
 * interdit la promotion des services de paris) : c'est cette page qui convertit.
 *
 * Hors index : page de campagne, son contenu double l'accueil et /tarifs.
 * Chiffres lus dans l'API, jamais écrits en dur.
 */
export const revalidate = 900;

const TITLE = "Découvrir BlackTurf : l'analyse de chaque course PMU";
const DESCRIPTION =
  "Ce que fait BlackTurf, en 2 minutes : probabilité par cheval, classement de l'algorithme, plan de mise adapté à ton budget et résultats publiés.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/decouvrir" },
  robots: { index: false, follow: true },
};

const nb = (v: number | null | undefined) => (v == null ? "—" : v.toLocaleString("fr-FR"));
const pct = (v: number | null | undefined) =>
  v == null ? "—" : `${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;

const INSCRIPTION = `/inscription?suite=${encodeURIComponent("/programme")}`;

const OUTILS = [
  {
    icon: BarChart3,
    t: "Une probabilité par cheval",
    d: "Chaque partant reçoit ses chances de victoire en %, et la cote juste qui en découle, à comparer avec la cote du PMU.",
  },
  {
    icon: ListOrdered,
    t: "Le classement de l'algorithme",
    d: "La course rangée du plus probable au moins probable, avec la forme, le terrain, le jockey et l'entraîneur qui pèsent.",
  },
  {
    icon: Wallet,
    t: "Un plan de mise à ton budget",
    d: "Tu donnes ton montant, le site le répartit selon ton profil : Prudent, Modéré ou Risqué. Le plan est figé avant le départ.",
  },
  {
    icon: Search,
    t: "Toutes les fiches",
    d: "Chevaux, jockeys, entraîneurs, hippodromes : l'historique et les statistiques derrière chaque course.",
  },
];

const ETAPES = [
  { n: "1", t: "Ouvre le programme du jour", d: "Toutes les réunions PMU, trot et galop, mises à jour en continu." },
  { n: "2", t: "Lis le classement et les chances", d: "En un coup d'œil : qui l'algorithme voit devant, et à quel point." },
  { n: "3", t: "Applique le plan, ou pas", d: "Tu restes maître de ta décision. Le site te donne les chiffres pour la prendre." },
];

const FORMULES = [
  {
    nom: "Gratuit",
    prix: "0 €",
    sous: "pour toujours",
    pour: "Pour découvrir",
    points: [
      "Programme et cotes en direct",
      "Classement complet : 1 course par jour",
      "Plan de mise sur cette course",
      "Défi du mois : 30 jours Expert à gagner",
    ],
    cta: "Créer mon compte gratuit",
    href: INSCRIPTION,
    fort: false,
  },
  {
    nom: "Pass Jour",
    prix: "5 €",
    sous: "24 h, sans abonnement",
    pour: "Pour tout tester une journée",
    points: [
      "Accès Expert complet pendant 24 h",
      "Payé une fois, rien ne se renouvelle",
      "Idéal un jour de Quinté+",
    ],
    cta: "Prendre le Pass Jour",
    href: "/tarifs#passes",
    fort: false,
  },
  {
    nom: "Expert",
    prix: "19 €",
    sous: "par mois, sans engagement",
    pour: "Pour suivre toutes les courses",
    points: [
      "Classement et plan de mise illimités",
      "Paris de valeur en temps réel",
      "Argent pro détecté sur le marché",
      "Assistant IA et créateur de stratégies",
      "Alertes e-mail et notifications",
    ],
    cta: "Passer Expert",
    href: "/tarifs",
    fort: true,
  },
];

export default async function DecouvrirPage() {
  const tr = await fetchTrackRecord();
  const g = tr?.global;

  return (
    <>
      <SeoHero
        eyebrow="Tu viens de nos vidéos ?"
        title="Chaque course PMU,"
        accent="décortiquée en chiffres"
        lead="BlackTurf fait pour chaque course ce que nos vidéos font pour un sujet : il lit les données, calcule les chances de chaque cheval et te montre le résultat en clair. Voici le site en 2 minutes."
        chips={
          <>
            {g && g.nb_courses_analysees > 0 && <Chip tone="gold">{nb(g.nb_courses_analysees)} courses analysées</Chip>}
            <Chip>Modèle réentraîné chaque nuit</Chip>
            <Chip>Résultats publiés, pertes comprises</Chip>
          </>
        }
      >
        <div className="mt-7 flex flex-col gap-3 sm:flex-row">
          <Link
            href={INSCRIPTION}
            className="btn-shimmer inline-flex items-center justify-center gap-1.5 rounded-xl bg-gradient-gold px-5 py-3 text-sm font-semibold text-brand-dark shadow-sm transition-transform hover:scale-[1.02]"
          >
            Créer mon compte gratuit <ArrowRight className="h-4 w-4" />
          </Link>
          <Link
            href="/tarifs"
            className="inline-flex items-center justify-center gap-1.5 rounded-xl border border-amber-200 bg-white px-5 py-3 text-sm font-semibold text-brand-dark transition-colors hover:bg-amber-50"
          >
            Voir les formules
          </Link>
        </div>
        <p className="mt-3 text-xs text-brand-charcoal">Gratuit, sans carte bancaire. 18 ans et plus.</p>
      </SeoHero>

      <Container>
        <Section title="Ce que tu trouves sur le site">
          <div className="grid gap-3 sm:grid-cols-2">
            {OUTILS.map((o) => (
              <div key={o.t} className="rounded-xl border border-gray-200 bg-white p-4">
                <o.icon className="h-5 w-5 text-brand-gold-dark" aria-hidden />
                <h3 className="mt-2 font-display text-[15px] font-semibold text-brand-dark">{o.t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-brand-charcoal">{o.d}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Comment ça marche">
          <ol className="grid gap-3 sm:grid-cols-3">
            {ETAPES.map((e) => (
              <li key={e.n} className="rounded-xl border border-gray-200 bg-white p-4">
                <span className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-gold font-display text-sm font-bold text-brand-dark">
                  {e.n}
                </span>
                <h3 className="mt-3 font-display text-[15px] font-semibold text-brand-dark">{e.t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-brand-charcoal">{e.d}</p>
              </li>
            ))}
          </ol>
        </Section>

        {g && g.nb_courses_analysees > 0 && g.accuracy_top3 != null && (
          <Section title="Les chiffres, sans maquillage">
            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-amber-200 bg-amber-50/60 p-4">
                <div className="font-display text-3xl font-bold text-brand-dark">{pct(g.accuracy_top3)}</div>
                <p className="mt-1 text-sm text-brand-charcoal">
                  des courses : le n°1 de l&apos;algorithme finit dans les 3 premiers (hasard : {pct(g.hasard_top3)}).
                </p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="font-display text-3xl font-bold text-brand-dark">{nb(g.nb_courses_analysees)}</div>
                <p className="mt-1 text-sm text-brand-charcoal">courses mesurées, chacune comparée à l&apos;arrivée officielle.</p>
              </div>
              <div className="rounded-xl border border-gray-200 bg-white p-4">
                <div className="font-display text-3xl font-bold text-brand-dark">{g.nb_partants_moyen == null ? "—" : nb(Math.round(g.nb_partants_moyen * 10) / 10)}</div>
                <p className="mt-1 text-sm text-brand-charcoal">partants en moyenne par course : trouver le bon trio n&apos;a rien d&apos;évident.</p>
              </div>
            </div>
            <p className="mt-4 text-sm leading-relaxed text-brand-charcoal">
              Tout est publié, les bons jours comme les mauvais, sur la page{" "}
              <Link href="/track-record" className="font-medium text-brand-gold-dark underline">
                Performances
              </Link>
              . Aucun résultat n&apos;est garanti : une probabilité de 30 % veut aussi dire 70 % de
              chances que ça ne passe pas.
            </p>
          </Section>
        )}

        <Section title="Gratuit ou payant : à toi de voir">
          <div className="grid gap-4 md:grid-cols-3">
            {FORMULES.map((f) => (
              <div
                key={f.nom}
                className={
                  f.fort
                    ? "relative rounded-2xl bg-gradient-to-br from-stone-900 via-stone-900 to-emerald-950 p-5 text-white ring-2 ring-amber-400/70"
                    : "rounded-2xl border border-gray-200 bg-white p-5"
                }
              >
                {f.fort && (
                  <span className="absolute -top-3 left-5 inline-flex items-center gap-1 rounded-full bg-gradient-to-b from-amber-300 to-amber-500 px-3 py-1 text-xs font-bold text-stone-900">
                    <Crown className="h-3 w-3" /> Le plus complet
                  </span>
                )}
                <h3 className={`font-display text-lg font-bold ${f.fort ? "text-white" : "text-brand-dark"}`}>{f.nom}</h3>
                <p className={`text-xs ${f.fort ? "text-stone-300" : "text-brand-charcoal"}`}>{f.pour}</p>
                <div className="mt-3 flex items-baseline gap-1.5">
                  <span className="text-3xl font-extrabold">{f.prix}</span>
                  <span className={`text-xs ${f.fort ? "text-stone-300" : "text-brand-charcoal"}`}>{f.sous}</span>
                </div>
                <ul className="mt-4 space-y-2">
                  {f.points.map((p) => (
                    <li key={p} className="flex items-start gap-2 text-sm">
                      <Check className={`mt-0.5 h-4 w-4 shrink-0 ${f.fort ? "text-amber-300" : "text-brand-gold-dark"}`} />
                      <span className={f.fort ? "text-stone-100" : "text-brand-charcoal"}>{p}</span>
                    </li>
                  ))}
                </ul>
                <Link
                  href={f.href}
                  className={
                    f.fort
                      ? "mt-5 inline-flex w-full items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-4 py-2.5 text-sm font-bold text-stone-900"
                      : "mt-5 inline-flex w-full items-center justify-center gap-1.5 rounded-xl border border-amber-200 px-4 py-2.5 text-sm font-semibold text-brand-dark hover:bg-amber-50"
                  }
                >
                  {f.cta} <ArrowRight className="h-4 w-4" />
                </Link>
              </div>
            ))}
          </div>
          <p className="mt-3 text-xs text-brand-charcoal">
            Aussi : Standard à 12 €/mois (5 courses par jour), Pass Semaine 12 € et Pass Mois 24 €.{" "}
            <Link href="/tarifs" className="underline">Toutes les formules</Link>
          </p>
        </Section>

        <Section title="Envie de voir avant de t'inscrire ?">
          <div className="grid gap-3 sm:grid-cols-2">
            <Link href="/quinte-du-jour" className="glass-card group flex items-start gap-3 rounded-2xl p-5">
              <Trophy className="mt-0.5 h-5 w-5 shrink-0 text-brand-gold-dark" aria-hidden />
              <span>
                <span className="block font-display font-semibold text-brand-dark group-hover:text-brand-gold-dark">
                  Le Quinté+ du jour
                </span>
                <span className="mt-1 block text-sm text-brand-charcoal">La course phare du jour : partants, terrain et analyse.</span>
              </span>
            </Link>
            <Link href="/pronostics-ia" className="glass-card group flex items-start gap-3 rounded-2xl p-5">
              <ShieldCheck className="mt-0.5 h-5 w-5 shrink-0 text-brand-gold-dark" aria-hidden />
              <span>
                <span className="block font-display font-semibold text-brand-dark group-hover:text-brand-gold-dark">
                  La méthode en détail
                </span>
                <span className="mt-1 block text-sm text-brand-charcoal">Les données, le modèle et la façon dont on le vérifie.</span>
              </span>
            </Link>
          </div>
        </Section>

        <p className="mt-12 rounded-xl bg-gray-50 p-4 text-xs leading-relaxed text-brand-charcoal">
          Jouer comporte des risques : endettement, dépendance… Appelez le 09 74 75 13 13 (appel non
          surtaxé). Réservé aux personnes majeures. BlackTurf est un outil d&apos;analyse : il ne prend
          aucun pari et ne garantit aucun gain.
        </p>
      </Container>
    </>
  );
}
