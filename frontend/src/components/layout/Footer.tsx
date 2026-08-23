import Link from "next/link";
import Image from "next/image";
import { ShieldCheck, Database, Mail } from "lucide-react";

const COLUMNS: Array<{ title: string; links: Array<{ href: string; label: string }> }> = [
  {
    title: "Produit",
    links: [
      { href: "/programme", label: "Programme du jour" },
      { href: "/value-bets", label: "Paris de valeur" },
      { href: "/bankroll", label: "Suivi du capital" },
      { href: "/assistant", label: "Assistant IA" },
    ],
  },
  {
    title: "Plans",
    links: [
      { href: "/tarifs", label: "Gratuit" },
      { href: "/tarifs", label: "Standard — 12€/mois" },
      { href: "/tarifs", label: "Expert — 19€/mois" },
    ],
  },
  {
    title: "Ressources",
    links: [
      { href: "/quinte-du-jour", label: "Quinté+ du jour" },
      { href: "/resultats", label: "Résultats et rapports" },
      { href: "/blog", label: "Blog" },
      { href: "/hippodromes", label: "Hippodromes" },
      { href: "/disciplines", label: "Disciplines" },
      { href: "/guides", label: "Guides paris PMU" },
      { href: "/guides/types-de-paris-pmu", label: "Types de paris" },
      { href: "/guides/pari-de-valeur", label: "Pari de valeur" },
    ],
  },
  {
    title: "Légal",
    links: [
      { href: "/mentions-legales", label: "Mentions légales" },
      { href: "/confidentialite", label: "Confidentialité" },
      { href: "/cgu", label: "CGU" },
      { href: "/cgv", label: "CGV" },
    ],
  },
];

export function Footer() {
  return (
    <footer className="relative border-t border-gray-200 bg-brand-warm py-14 mt-auto">
      {/* Accent doré en haut */}
      <div className="absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-amber-400/40 to-transparent" />

      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-2 md:grid-cols-6 gap-8">

          {/* Brand */}
          <div className="col-span-2">
            <div className="flex items-center gap-2.5 mb-3">
              <Image
                src="/logo.png"
                alt="BlackTurf"
                width={30}
                height={30}
                className="rounded-md object-contain ring-1 ring-amber-200/60"
              />
              <span className="font-display text-lg font-bold text-gray-900">
                Black<span className="text-gradient">Turf</span>
              </span>
            </div>
            <p className="text-xs text-gray-500 leading-relaxed max-w-xs">
              Le terminal algorithmique des parieurs gagnants.<br />
              Analyses propulsées par XGBoost + LightGBM + CatBoost.
            </p>

            {/* Trust chips */}
            <div className="mt-4 flex flex-wrap gap-2">
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-medium text-emerald-700">
                <Database className="h-3 w-3" /> Données PMU officielles
              </span>
              <span className="inline-flex items-center gap-1.5 rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-medium text-amber-700">
                <ShieldCheck className="h-3 w-3" /> Chiffres vérifiables
              </span>
            </div>

            {/* Contact */}
            <a
              href="mailto:contact@blackturf.fr"
              className="mt-4 inline-flex items-center gap-1.5 text-xs font-medium text-gray-500 transition-colors hover:text-brand-gold-deep"
            >
              <Mail className="h-3.5 w-3.5" /> contact@blackturf.fr
            </a>
          </div>

          {/* Columns */}
          {COLUMNS.map((col) => (
            <div key={col.title}>
              <h3 className="text-xs font-semibold uppercase tracking-wider text-gray-900 mb-3">{col.title}</h3>
              <ul className="space-y-2 text-sm text-gray-500">
                {col.links.map((l) => (
                  <li key={l.label}>
                    <Link href={l.href} className="transition-colors hover:text-brand-gold-deep">
                      {l.label}
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <div className="mt-10 pt-8 border-t border-gray-200 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-xs text-gray-500">
            © 2026 BlackTurf. Tous droits réservés.
          </p>
          <p className="text-xs text-gray-500 text-center">
            Le jeu peut être dangereux. Jouez de façon responsable. Interdit aux mineurs.{" "}
            <a
              href="https://www.joueurs-info-service.fr"
              target="_blank"
              rel="noopener noreferrer"
              className="underline hover:text-gray-600 transition-colors"
            >
              joueurs-info-service.fr — 09 74 75 13 13
            </a>
          </p>
        </div>
      </div>
    </footer>
  );
}
