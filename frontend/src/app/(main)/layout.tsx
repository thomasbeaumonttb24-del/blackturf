import { Navbar } from "@/components/layout/Navbar";
import { Footer } from "@/components/layout/Footer";
import { BottomNav } from "@/components/layout/BottomNav";
import { EmailVerificationBanner } from "@/components/layout/EmailVerificationBanner";

export default function MainLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-screen">
      <Navbar />
      <EmailVerificationBanner />
      {/* pb mobile = hauteur réelle BottomNav (item 52px + marge) + safe-area iPhone,
          sinon le bas du contenu passe sous la barre sur écran à encoche. */}
      <main className="flex-1 pb-[calc(68px+env(safe-area-inset-bottom))] md:pb-0">{children}</main>
      <Footer />
      <BottomNav />
    </div>
  );
}
