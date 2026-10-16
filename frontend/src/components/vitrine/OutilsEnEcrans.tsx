import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Check } from "lucide-react";

/**
 * Les outils de BlackTurf montrés en VRAIS écrans du site, chacun avec la formule
 * minimale qui l'ouvre (grille de /tarifs). Partagé par l'accueil et /decouvrir :
 * mieux vaut une vraie capture annotée qu'une maquette « Exemple ».
 */

/** `acces` = formule minimale (grille de /tarifs). */
export const FONCTIONS = [
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
    src: "/img/decouvrir/f-comparaison-v2.webp", w: 1180, h: 1308, large: false,
    acces: "Compte gratuit", t: "Cotes de 5 sites comparées",
    d: "PMU, Geny, Unibet, Bet365 et Ladbrokes côte à côte, avec le mouvement de chaque cote. La meilleure ressort en vert.",
    alt: "Tableau de comparaison des cotes PMU, Geny, Unibet, Bet365 et Ladbrokes pour les 12 partants, meilleure cote en vert et mouvement de cote",
  },
  {
    src: "/img/decouvrir/f-duel-v2.webp", w: 1180, h: 1262, large: false,
    acces: "Compte gratuit", t: "Duel de deux chevaux",
    d: "Cote, ELO, forme, victoires, repos : deux partants face à face, critère par critère. Plus les confrontations déjà courues.",
    alt: "Comparateur : That's It contre Jonquillete Crepin, cote, ELO, forme, victoires, nombre de courses, repos et musique",
  },
  {
    src: "/img/decouvrir/f-argent.webp", w: 1365, h: 714, large: true,
    acces: "Standard", t: "L'argent misé, cheval par cheval",
    d: "Où va l'argent des parieurs, et les grosses mises qui arrivent juste avant le départ.",
    alt: "Argent misé en Simple gagnant cheval par cheval : grosse mise de 9 613 € sur North Rim, +5 035 € entrés en 26 minutes",
  },
];

const aussi = (tu: boolean) => [
  { t: "Assistant IA", d: tu ? "Pose tes questions sur n'importe quelle course." : "Posez vos questions sur n'importe quelle course." },
  { t: "Créateur de stratégies", d: tu ? "Teste tes propres règles sur 12 mois de courses." : "Testez vos propres règles sur 12 mois de courses." },
  { t: "Argent pro détecté", d: "Les mouvements de cote suspects signalés en direct." },
  { t: "Alertes", d: tu ? "E-mail et notifications avant les courses qui t'intéressent." : "E-mail et notifications avant les courses qui vous intéressent." },
  { t: "Module Quinté+", d: "Le Quinté du jour analysé, tickets réglés aux vrais rapports." },
  { t: "Pronostics presse", d: "L'avis des journaux comparé à celui de l'algorithme." },
];

export function OutilsEnEcrans({ tutoiement = false, id }: { tutoiement?: boolean; id?: string }) {
  return (
    <section id={id} className="scroll-mt-20 border-b border-stone-200 bg-[#faf8f4]">
      <div className="mx-auto max-w-6xl px-4 py-16 sm:py-24">
        <div className="max-w-2xl">
          <p className="text-sm font-medium text-brand-gold-dark">{tutoiement ? "Tout ce que tu débloques" : "Tout ce que vous débloquez"}</p>
          <h2 className="mt-3 font-display text-3xl font-semibold tracking-[-0.025em] text-stone-950 sm:text-4xl">
            Les outils des pros, sur chaque course.
          </h2>
          <p className="mt-4 text-lg text-stone-600">Écrans réels du site, sans retouche.</p>
        </div>
        <div className="mt-12 grid gap-6 md:grid-cols-2">
          {FONCTIONS.map((f) => (
            <article
              key={f.src}
              className={`flex flex-col overflow-hidden rounded-3xl bg-white ring-1 ring-stone-200/80 shadow-[0_24px_60px_-40px_rgba(17,24,39,.35)] ${f.large ? "md:col-span-2" : ""}`}
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
              {/* Zone d'écran de hauteur fixe, image calée en haut et fondue en bas :
                  des cartes voisines gardent la même hauteur, sans vide au-dessus. */}
              <div className={`relative mt-auto overflow-hidden bg-[#f5f0e6] px-4 pt-6 sm:px-8 sm:pt-8 ${f.large ? "" : "h-[360px] sm:h-[440px]"}`}>
                <Image
                  src={f.src}
                  alt={f.alt}
                  width={f.w}
                  height={f.h}
                  sizes={f.large ? "(min-width: 1024px) 1000px, 94vw" : "(min-width: 768px) 460px, 90vw"}
                  className={`mx-auto h-auto w-full rounded-t-2xl shadow-[0_-8px_40px_-20px_rgba(17,24,39,0.35)] ${f.large ? "max-w-[1000px]" : "max-w-[440px]"}`}
                />
                {!f.large && <div aria-hidden className="pointer-events-none absolute inset-x-0 bottom-0 h-20 bg-gradient-to-t from-[#f5f0e6] to-transparent" />}
              </div>
            </article>
          ))}
        </div>

        <h3 className="mt-16 text-sm font-semibold uppercase tracking-wider text-stone-500">Et aussi</h3>
        <ul className="mt-5 grid gap-x-8 gap-y-6 sm:grid-cols-2 lg:grid-cols-3">
          {aussi(tutoiement).map((a) => (
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
  );
}
