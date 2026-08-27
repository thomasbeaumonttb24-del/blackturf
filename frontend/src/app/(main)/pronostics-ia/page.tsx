import type { Metadata } from "next";
import Link from "next/link";
import { Brain, Database, RefreshCw, Target, Scale, AlertTriangle } from "lucide-react";
import { fetchTrackRecord, ogBase, twitterBase, filAriane, jourCourtAnnee } from "@/lib/seo";
import { SeoHero, Container, Section, Callout, Chip, DefCard } from "@/components/seo/kit";

/**
 * Page pilier du champ « pronostic par intelligence artificielle ».
 *
 * Ce que le site n'avait pas : une page qui EXPLIQUE la méthode. Le sujet était pourtant
 * partout en filigrane — 35 occurrences du champ lexical sur l'accueil, 31 sur les tarifs
 * — sans qu'aucune page ne le porte dans son titre ni ne le traite de bout en bout. Un
 * internaute qui cherche « pronostic hippique intelligence artificielle » ou « algorithme
 * pronostic PMU » veut savoir ce qu'il y a sous le capot ; il ne trouvait qu'une promesse.
 *
 * Le partage des rôles avec /track-record est net, pour ne pas se concurrencer soi-même :
 * ici la MÉTHODE, là-bas les RÉSULTATS mesurés. Chaque page renvoie vers l'autre.
 *
 * Les chiffres viennent tous de l'API : rien n'est écrit en dur, rien n'est arrondi à
 * l'avantage du site, et le rendement négatif est publié au même titre que le reste.
 */
export const revalidate = 900;

const TITLE = "Pronostics hippiques par IA : comment fonctionne l'algorithme";
const DESCRIPTION =
  "L'intelligence artificielle appliquée aux courses PMU : sur quelles données le modèle apprend, comment il calcule une probabilité par cheval, et comment sa justesse est mesurée.";

export const metadata: Metadata = {
  title: TITLE,
  description: DESCRIPTION,
  alternates: { canonical: "/pronostics-ia" },
  openGraph: ogBase({ title: TITLE, description: DESCRIPTION, url: "/pronostics-ia" }),
  twitter: twitterBase({ title: TITLE, description: DESCRIPTION }),
};

const pct = (v: number | null | undefined) =>
  v === null || v === undefined ? "—" : `${v.toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`;
const nb = (v: number) => v.toLocaleString("fr-FR");

export default async function PronosticsIaPage() {
  const tr = await fetchTrackRecord();
  const g = tr?.global;
  const clv = tr?.clv;
  const parDiscipline = tr?.by_discipline ?? [];

  const breadcrumb = filAriane([
    { nom: "Accueil", url: "/" },
    { nom: "Pronostics par IA" },
  ]);

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: JSON.stringify(breadcrumb) }}
      />

      <SeoHero
        eyebrow="La méthode"
        breadcrumbs={[{ label: "Accueil", href: "/" }, { label: "Pronostics par IA" }]}
        title="Pronostics hippiques par"
        accent="intelligence artificielle"
        lead="Un modèle statistique lit chaque course du programme PMU, en tire une probabilité de victoire pour chaque partant, et la confronte à ce que dit le marché. Voici comment il travaille — et comment on vérifie qu'il a raison."
        chips={
          <>
            {g && <Chip tone="gold"><Brain className="h-3 w-3" /> {nb(g.nb_courses_analysees)} courses mesurées</Chip>}
            <Chip>Réentraîné chaque nuit</Chip>
            <Chip>Résultats publiés, pertes comprises</Chip>
          </>
        }
      />

      <Container>
        <Section title="Ce que calcule l'algorithme">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Pour chaque cheval engagé, le modèle produit une <strong>probabilité de victoire</strong> —
            un nombre entre 0 et 100 %, pas un classement d&apos;opinion. La somme des probabilités
            d&apos;une course fait 100 % : si un cheval monte, un autre descend. De cette probabilité
            découle une <strong>cote juste</strong>, celle qui rendrait le pari équitable, comparée
            ensuite à la cote réellement proposée par le PMU.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
            C&apos;est l&apos;écart entre les deux qui fait un{" "}
            <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-dark underline">
              pari de valeur
            </Link>{" "}
            : un cheval que le modèle estime à 20 % de chances mais que le marché paie comme s&apos;il
            en avait 12 %. L&apos;algorithme ne cherche donc pas « le gagnant » — il cherche les
            écarts entre la réalité mesurée et l&apos;opinion du marché.
          </p>

          <div className="mt-5 grid gap-3 sm:grid-cols-2">
            <DefCard term="Probabilité, pas pronostic">
              Un pronostic dit « je joue le 7 ». Une probabilité dit « le 7 gagne 22 fois sur 100 ».
              La seconde se vérifie, la première non.
            </DefCard>
            <DefCard term="Cote juste">
              L&apos;inverse de la probabilité. Une chance sur cinq, c&apos;est une cote juste de 5,0.
              Au-dessus, le pari est favorable ; en dessous, il est perdant à long terme.
            </DefCard>
          </div>
        </Section>

        <Section title="Sur quelles données il apprend">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Le modèle est entraîné sur l&apos;historique réel des courses françaises et
            internationales reprises par le PMU : performances passées de chaque cheval, discipline,
            distance, état du terrain, poids et handicaps, driver ou jockey, entraîneur, numéro de
            corde, allocation, taille du peloton — et l&apos;évolution des cotes elles-mêmes, qui
            portent l&apos;information du marché.
          </p>
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            {[
              { icon: Database, t: "Données de course", d: "Discipline, distance, terrain, allocation, partants, corde et handicap." },
              { icon: Target, t: "Historique des partants", d: "La musique, les temps, les réductions kilométriques, les confrontations passées." },
              { icon: Scale, t: "Signal du marché", d: "Les cotes et leur mouvement jusqu'au départ, qui agrègent l'avis de tous les parieurs." },
            ].map((c) => (
              <div key={c.t} className="rounded-xl border border-gray-200 bg-white p-4">
                <c.icon className="h-5 w-5 text-brand-gold-dark" aria-hidden />
                <h3 className="mt-2 font-display text-[15px] font-semibold text-brand-dark">{c.t}</h3>
                <p className="mt-1 text-sm leading-relaxed text-brand-charcoal">{c.d}</p>
              </div>
            ))}
          </div>
        </Section>

        <Section title="Comment il se corrige">
          <p className="text-sm leading-relaxed text-brand-charcoal">
            Un modèle figé se périme : les chevaux progressent, les écuries changent de forme, les
            pistes évoluent. Celui de BlackTurf est <strong>réentraîné chaque nuit</strong> sur les
            courses de la veille, arrivées et rapports compris. Chaque prédiction est ensuite
            confrontée au résultat réel, et cet écart nourrit l&apos;entraînement suivant.
          </p>
          <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
            Le pronostic est <strong>figé dix minutes avant le départ</strong> et conservé tel quel.
            C&apos;est ce qui rend la mesure honnête : impossible de réécrire après coup ce qui avait
            été annoncé.
          </p>
          <div className="mt-4 flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50/70 p-4">
            <RefreshCw className="mt-0.5 h-5 w-5 shrink-0 text-brand-gold-dark" aria-hidden />
            <p className="text-sm leading-relaxed text-brand-charcoal">
              Un pronostic qui n&apos;est pas horodaté avant la course ne prouve rien. Tous les
              chiffres publiés ici portent sur des prédictions enregistrées{" "}
              <strong>avant le départ</strong>, jamais reconstituées ensuite.
            </p>
          </div>
        </Section>

        {g && (
          <Section title="Comment on vérifie qu'il a raison">
            <p className="text-sm leading-relaxed text-brand-charcoal">
              Trois mesures, sur {nb(g.nb_courses_analysees)} courses analysées
              {g.mesure_depuis ? ` depuis le ${jourCourtAnnee(g.mesure_depuis)}` : ""}, avec{" "}
              {g.nb_partants_moyen.toLocaleString("fr-FR")} partants en moyenne.
            </p>

            <dl className="mt-4 grid grid-cols-1 gap-px overflow-hidden rounded-xl border border-gray-200 bg-gray-200 sm:grid-cols-3">
              {[
                { k: "Gagnant désigné", v: pct(g.accuracy_top1), s: `le hasard ferait ${pct(g.hasard_top1)}` },
                { k: "Gagnant dans le trio prédit", v: pct(g.accuracy_top3), s: `le hasard ferait ${pct(g.hasard_top3)}` },
                {
                  k: "Score de Brier",
                  v: g.brier_moyen !== null && g.brier_moyen !== undefined
                    ? g.brier_moyen.toLocaleString("fr-FR", { maximumFractionDigits: 4 })
                    : "—",
                  s: "plus il est bas, plus les probabilités sont justes",
                },
              ].map((c) => (
                <div key={c.k} className="bg-white px-4 py-3.5">
                  <dt className="text-[11px] leading-snug text-brand-charcoal">{c.k}</dt>
                  <dd className="mt-1 font-display text-[22px] font-bold tabular-nums text-brand-dark">{c.v}</dd>
                  <div className="mt-0.5 text-[11px] text-brand-charcoal">{c.s}</div>
                </div>
              ))}
            </dl>

            <p className="mt-4 text-sm leading-relaxed text-brand-charcoal">
              Le <strong>score de Brier</strong> est la mesure qui compte vraiment. Il ne juge pas le
              classement mais la justesse des probabilités : annoncer 80 % puis se tromper coûte plus
              cher qu&apos;annoncer 55 %. Un modèle qui dirait « 50 % » à tout le monde obtiendrait un
              score médiocre même en devinant souvent le vainqueur.
            </p>

            {clv && (
              <p className="mt-3 text-sm leading-relaxed text-brand-charcoal">
                Quatrième mesure, la plus exigeante : sur {nb(clv.n)} paris,{" "}
                <strong>{pct(clv.pct_beat_line)} ont été pris à une cote meilleure que la cote de
                clôture</strong>. Autrement dit, le modèle a repéré avant le marché que ces chevaux
                étaient sous-évalués — c&apos;est le signe le plus difficile à obtenir par chance.
              </p>
            )}

            {parDiscipline.length > 0 && (
              <>
                <h3 className="mt-6 font-display text-[15px] font-bold text-brand-dark">
                  Résultats par discipline
                </h3>
                <div className="mt-3 overflow-x-auto rounded-xl border border-gray-200">
                  <table className="w-full min-w-[420px] border-collapse text-[13px]">
                    <thead>
                      <tr className="bg-gray-50 text-left text-[11px] uppercase tracking-[0.08em] text-brand-charcoal">
                        <th scope="col" className="px-3 py-2 font-semibold">Discipline</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Courses</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Gagnant trouvé</th>
                        <th scope="col" className="px-3 py-2 text-right font-semibold">Dans le trio</th>
                      </tr>
                    </thead>
                    <tbody>
                      {parDiscipline.map((d) => (
                        <tr key={d.discipline} className="border-t border-gray-100 text-brand-charcoal">
                          <td className="px-3 py-2 font-medium capitalize text-brand-dark">{d.discipline}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{nb(d.nb_courses)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{pct(d.accuracy_top1)}</td>
                          <td className="px-3 py-2 text-right tabular-nums">{pct(d.accuracy_top3)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
          </Section>
        )}

        <Section title="Ce que l'intelligence artificielle ne fait pas">
          <div className="flex items-start gap-3 rounded-xl border border-amber-200 bg-amber-50/70 p-4">
            <AlertTriangle className="mt-0.5 h-5 w-5 shrink-0 text-brand-gold-dark" aria-hidden />
            <div className="text-sm leading-relaxed text-brand-charcoal">
              <p>
                <strong className="text-brand-dark">Elle ne rend pas le pari hippique gagnant.</strong>{" "}
                Le PMU prélève environ 20 % des enjeux avant toute redistribution : un joueur doit
                donc être meilleur que le marché de plus de vingt points pour espérer un rendement
                positif. Mieux classer les chevaux ne suffit pas à renverser cette table.
              </p>
              {g && g.favori_roi !== null && g.favori_roi !== undefined && (
                <p className="mt-2">
                  Chiffre à l&apos;appui : miser 1 € Gagnant sur le favori de l&apos;algorithme, sur{" "}
                  {nb(g.nb_favoris_evalues)} courses, aurait rendu <strong>{pct(g.favori_roi)}</strong>.
                  Une perte. Nous le publions parce que c&apos;est vrai, et parce qu&apos;un site qui
                  promettrait l&apos;inverse mentirait.
                </p>
              )}
              <p className="mt-2">
                Ce que le modèle apporte, c&apos;est un classement mieux informé que le marché et une
                mesure honnête de sa propre justesse — pas une martingale. Aucun algorithme ne prédit
                une chute, un cheval malade ou une tactique de course.
              </p>
            </div>
          </div>
        </Section>

        <Section title="Les questions qu'on nous pose">
          <div className="grid gap-3 sm:grid-cols-2">
            <DefCard term="Est-ce vraiment de l'IA ?">
              C&apos;est un modèle d&apos;apprentissage statistique entraîné sur des données réelles,
              pas un moteur de règles écrites à la main ni un agent conversationnel. Il apprend de
              ses erreurs à chaque réentraînement.
            </DefCard>
            <DefCard term="Faut-il jouer tous ses pronostics ?">
              Non. L&apos;algorithme signale des écarts de valeur ; c&apos;est le plan de mise, adossé
              à votre budget et à votre profil de risque, qui décide de quoi jouer et pour combien.
            </DefCard>
            <DefCard term="Pourquoi publier les pertes ?">
              Parce qu&apos;un palmarès qui ne montre que ses réussites ne mesure rien. Le{" "}
              <Link href="/track-record" className="font-medium text-brand-gold-dark underline">
                palmarès complet
              </Link>{" "}
              porte toutes les courses analysées, sans sélection.
            </DefCard>
            <DefCard term="Le modèle voit-il les cotes ?">
              Oui, et c&apos;est voulu : la cote agrège l&apos;opinion de milliers de parieurs. Le but
              n&apos;est pas de l&apos;ignorer mais de repérer où elle se trompe.
            </DefCard>
          </div>
        </Section>

        <Section title="Pour aller plus loin">
          <ul className="space-y-2 text-sm text-brand-charcoal">
            <li>
              <Link href="/track-record" className="font-medium text-brand-gold-dark hover:underline">
                Le palmarès mesuré
              </Link>{" "}
              — ce que l&apos;algorithme a produit course après course, pertes comprises.
            </li>
            <li>
              <Link
                href="/blog/ia-pronostics-hippiques"
                className="font-medium text-brand-gold-dark hover:underline"
              >
                L&apos;intelligence artificielle peut-elle battre les courses ?
              </Link>{" "}
              — ce que le machine learning sait faire, et où il bute.
            </li>
            <li>
              <Link href="/guides/pari-de-valeur" className="font-medium text-brand-gold-dark hover:underline">
                Le pari de valeur expliqué
              </Link>{" "}
              — pourquoi l&apos;écart à la cote compte plus que le nom du favori.
            </li>
          </ul>
        </Section>

        <Callout href="/programme" cta="Voir les analyses du jour">
          Chaque course du programme PMU est analysée avant le départ : probabilité par cheval, cote
          juste, écart avec le marché. Les résultats sont ensuite notés aux rapports officiels.
        </Callout>
      </Container>
    </>
  );
}
