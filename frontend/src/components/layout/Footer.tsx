import Link from "next/link";
import Image from "next/image";

export function Footer() {
  return (
    <footer className="border-t border-gray-200 bg-gray-50 py-12 mt-auto">
      <div className="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
        <div className="grid grid-cols-1 md:grid-cols-4 gap-8">

          {/* Brand */}
          <div className="col-span-1 md:col-span-1">
            <div className="flex items-center gap-2.5 mb-3">
              <Image
                src="/logo.png"
                alt="BlackTurf"
                width={28}
                height={28}
                className="rounded-md object-contain"
              />
              <span className="font-bold text-gray-900">
                Black<span className="text-brand-gold-deep">Turf</span>
              </span>
            </div>
            <p className="text-xs text-gray-500 leading-relaxed">
              Le Terminal IA des Parieurs Gagnants.<br />
              Analyses propulsées par XGBoost + LightGBM + CatBoost.
            </p>
          </div>

          {/* Produit */}
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3">Produit</h4>
            <ul className="space-y-2 text-sm text-gray-500">
              <li><Link href="/programme" className="hover:text-gray-900 transition-colors">Programme du jour</Link></li>
              <li><Link href="/value-bets" className="hover:text-gray-900 transition-colors">Value Bets</Link></li>
              <li><Link href="/bankroll" className="hover:text-gray-900 transition-colors">Bankroll tracker</Link></li>
              <li><Link href="/assistant" className="hover:text-gray-900 transition-colors">Assistant IA</Link></li>
            </ul>
          </div>

          {/* Plans */}
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3">Plans</h4>
            <ul className="space-y-2 text-sm text-gray-500">
              <li><Link href="/tarifs" className="hover:text-gray-900 transition-colors">Gratuit</Link></li>
              <li><Link href="/tarifs" className="hover:text-gray-900 transition-colors">Standard — 19€/mois</Link></li>
              <li><Link href="/tarifs" className="hover:text-gray-900 transition-colors">Expert — 39€/mois</Link></li>
            </ul>
          </div>

          {/* Légal */}
          <div>
            <h4 className="text-sm font-semibold text-gray-900 mb-3">Légal</h4>
            <ul className="space-y-2 text-sm text-gray-500">
              <li><Link href="/mentions-legales" className="hover:text-gray-900 transition-colors">Mentions légales</Link></li>
              <li><Link href="/confidentialite" className="hover:text-gray-900 transition-colors">Confidentialité</Link></li>
              <li><Link href="/cgu" className="hover:text-gray-900 transition-colors">CGU</Link></li>
            </ul>
          </div>
        </div>

        <div className="mt-8 pt-8 border-t border-gray-200 flex flex-col sm:flex-row items-center justify-between gap-4">
          <p className="text-xs text-gray-400">
            © 2026 BlackTurf. Tous droits réservés.
          </p>
          <p className="text-xs text-gray-400 text-center">
            ⚠️ Le jeu peut être dangereux. Jouez de façon responsable. Interdit aux mineurs.{" "}
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
