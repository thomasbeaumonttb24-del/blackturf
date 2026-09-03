import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { BottomNav } from "@/components/layout/BottomNav";
import { EmailVerificationBanner } from "@/components/layout/EmailVerificationBanner";
import { EssaiSansCarteBanner } from "@/components/layout/EssaiSansCarteBanner";
import { PaiementEchoueBanner } from "@/components/layout/PaiementEchoueBanner";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen">
      {/* Lien d'évitement : premier élément focusable de la page, invisible tant qu'il n'a
          pas le focus. Sans lui, atteindre le contenu au clavier impose de traverser toute
          la navigation à chaque page — et un agent qui suit l'ordre du DOM n'a aucun
          raccourci déclaré vers le corps du document. */}
      <a
        href="#contenu"
        className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-4 focus:z-[100] focus:rounded-lg focus:bg-brand-dark focus:px-4 focus:py-2 focus:text-sm focus:font-semibold focus:text-white"
      >
        Aller au contenu principal
      </a>
      <Navbar />
      <EmailVerificationBanner />
      <EssaiSansCarteBanner />
      <PaiementEchoueBanner />
      {/* pb mobile = hauteur réelle BottomNav (item 52px + marge) + safe-area iPhone,
          sinon le bas du contenu passe sous la barre sur écran à encoche. */}
      <main id="contenu" className="flex-1 pb-[calc(68px+env(safe-area-inset-bottom))] md:pb-0">{children}</main>
      <Footer />
      <BottomNav />
    </div>
  );
}
