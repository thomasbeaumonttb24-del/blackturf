import Link from "next/link";
import Image from "next/image";
import { Mail } from "lucide-react";
import { AVIS, INSTAGRAM, TIKTOK } from "@/lib/social";
import { RUBRIQUES as R } from "@/lib/navigation";
import { TrustpilotAvis } from "./TrustpilotAvis";

/**
 * `rel="nofollow"` sur les liens vers des espaces privés.
 *
 * `/assistant` est interdit d'exploration par robots.txt, mais étaient
 * liés depuis le pied de page de CHAQUE page du site. Un lien massivement répété vers une
 * adresse qu'un robot n'a pas le droit de charger produit exactement le cas que Search
 * Console signale comme « indexée malgré le blocage par robots.txt » : Google connaît
 * l'URL par le lien, ne peut pas la lire, et l'indexe sans contenu. Le `nofollow` retire
 * ces adresses du graphe de liens sans rien changer pour le visiteur, qui les utilise.
 */
const COLUMNS: Array<{
  title: string;
  links: Array<{ href: string; label: string; prive?: boolean }>;
}> = [
  {
    title: "Produit",
    links: [
      R.coursesDuJour,
      R.quinte,
      R.outsiders,
      R.resultats,
      { ...R.parisDeValeur, prive: true },
      R.performances,
      R.defi,
      R.methode,
      { ...R.assistant, prive: true },
    ],
  },
  {
    title: "Tarifs",
    links: [
      { href: "/tarifs", label: "Gratuit" },
      { href: "/tarifs", label: "Standard — 12€/mois" },
      { href: "/tarifs", label: "Expert — 19€/mois" },
      { href: "/tarifs#passes", label: "Pass sans abonnement — dès 5€" },
    ],
  },
  {
    title: "Ressources",
    links: [
      { href: "/newsletter", label: "La lettre du lundi" },
      // Ces deux entrées manquaient. Le pied de page est ce qui donne à une rubrique un
      // lien depuis CHAQUE page du site : sans elle, « lire la musique » n'était atteint
      // que depuis deux pages sur quinze, et les archives depuis trois.
      { href: "/resultats/archives", label: "Archives des arrivées" },
      { href: "/blog", label: "Blog" },
      { href: "/hippodromes", label: "Hippodromes" },
      { href: "/disciplines", label: "Disciplines" },
      { href: "/guides", label: "Guides paris PMU" },
      { href: "/guides/types-de-paris-pmu", label: "Types de paris" },
      { href: "/guides/pari-de-valeur", label: "Pari de valeur" },
      { href: "/guides/comment-lire-la-musique", label: "Lire la musique" },
    ],
  },
];

const LEGAL = [
  { href: "/mentions-legales", label: "Mentions légales" },
  { href: "/confidentialite", label: "Confidentialité" },
  { href: "/cgu", label: "CGU" },
  { href: "/cgv", label: "CGV" },
];

/** Bouton blanc à logo, commun à Google, Instagram, TikTok et au contact. */
const BOUTON_LOGO =
  "inline-flex items-center gap-2.5 rounded-lg border bg-white px-4 text-sm text-[#191919] transition-shadow hover:shadow-md";

export function Footer() {
  return (
    <footer className="relative border-t border-gray-200 bg-brand-warm mt-auto">
      {/* Accent doré en haut */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-400/40 to-transparent" />

      {/* Avis : Trustpilot (widget officiel) et Google (lien « Demander des avis » de la fiche). */}
      <div className="border-b border-gray-200 bg-white/70">
        <div className="mx-auto flex max-w-7xl flex-col items-center justify-between gap-4 px-4 py-6 sm:px-6 md:flex-row lg:px-8">
          <div className="text-center md:text-left">
            <p className="font-display text-base font-bold text-gray-900">Vous utilisez BlackTurf ?</p>
            <p className="text-sm text-gray-600">Votre avis aide d&apos;autres turfistes à nous trouver.</p>
          </div>
          <div className="flex flex-wrap items-center justify-center gap-3">
            <TrustpilotAvis />
            <a
              href={AVIS.google.ecrire}
              target="_blank"
              rel="noopener noreferrer"
              className={`${BOUTON_LOGO} h-10 border-[#DADCE0]`}
            >
              <Image src="/img/logos/google-g.svg" alt="" width={20} height={20} />
              <span>
                Laisser un avis <strong>Google</strong>
              </span>
            </a>
          </div>
        </div>
      </div>

      <div className="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 gap-8 md:grid-cols-5">

          {/* Marque */}
          <div className="col-span-2">
            <div className="flex items-center gap-2.5 mb-3">
              {/* `alt` vide, volontairement : le nom est écrit juste à côté, et un
                  alt qui le répète fait lire « BlackTurf BlackTurf » à un lecteur
                  d'écran (règle axe « image-redundant-alt »). L'image est décorative. */}
              <Image
                src="/logo-transparent.png"
                alt=""
                width={30}
                height={30}
                className="object-contain"
              />
              <span className="font-display text-lg font-bold text-gray-900">
                Black<span className="text-gradient">Turf</span>
              </span>
            </div>
            <p className="text-sm text-gray-600 leading-relaxed max-w-xs">
              Pronostics PMU par IA, notés aux rapports réels. Données PMU officielles,
              chiffres vérifiables.
            </p>

            <div className="mt-5 flex flex-wrap gap-2.5">
              {/*
                Instagram et TikTok n'étaient liés depuis AUCUNE page du site : le pied de
                page est le seul endroit qui donne un lien depuis chaque page.

                `rel="me"` déclare que ce profil appartient à la même entité que le site.
                C'est le pendant du `sameAs` du balisage : les deux se répondent, et un
                robot qui ne lit pas le JSON-LD lit celui-là.
              */}
              <a
                href={INSTAGRAM.url}
                target="_blank"
                rel="me noopener noreferrer"
                className={`${BOUTON_LOGO} h-11 border-gray-200`}
              >
                <Image src="/img/email/instagram-glyph.png" alt="" width={22} height={22} className="rounded-md" />
                <span>
                  Suivre <strong>{INSTAGRAM.pseudo}</strong>
                </span>
              </a>
              <a
                href={TIKTOK.url}
                target="_blank"
                rel="me noopener noreferrer"
                className={`${BOUTON_LOGO} h-11 border-gray-200`}
              >
                <Image src="/img/logos/tiktok.svg" alt="" width={22} height={22} className="rounded-md" />
                <span>
                  Suivre <strong>{TIKTOK.pseudo}</strong>
                </span>
              </a>
              <a href="mailto:contact@blackturf.fr" className={`${BOUTON_LOGO} h-11 border-gray-200`}>
                <span className="flex h-[22px] w-[22px] items-center justify-center rounded-md bg-brand-gold-dark text-white">
                  <Mail className="h-3.5 w-3.5" />
                </span>
                contact@blackturf.fr
              </a>
            </div>
          </div>

          {/* Colonnes */}
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-900 mb-3">{col.title}</h3>
              <ul className="space-y-2 text-sm text-gray-600">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <Link
                      href={l.href}
                      rel={l.prive ? "nofollow" : undefined}
                      className="transition-colors hover:text-brand-gold-dark"
                    >
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 pt-6 border-t border-gray-200 flex flex-col gap-3 text-xs text-gray-600 lg:flex-row lg:items-center lg:justify-between">
          <p className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 lg:justify-start">
            <span>© 2026 BlackTurf</span>
            {LEGAL.map((l) => (
              <Link key={l.href} href={l.href} className="transition-colors hover:text-brand-gold-dark">
                {l.label}
              </Link>
            ))}
          </p>
          <p className="text-center lg:text-right">
            <span className="mr-1.5 inline-flex rounded border border-red-300 px-1 font-bold text-red-700">18+</span>
            Jouer comporte des risques : endettement, dépendance.{" "}
            <a
              href="https://www.joueurs-info-service.fr"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-gray-900 transition-colors"
            >
              joueurs-info-service.fr — 09 74 75 13 13
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
