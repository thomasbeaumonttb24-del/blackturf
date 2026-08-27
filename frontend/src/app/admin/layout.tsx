import type { Metadata } from "next";

/**
 * Console d'administration : `noindex`, et un titre à elle.
 *
 * Les trois pages `/admin`, `/admin/algorithme` et `/admin/instagram` s'annonçaient
 * « index, follow » sous le titre de la page d'accueil — elles héritaient du réglage du
 * layout racine, faute d'en déclarer un. Le même oubli que sur les autres espaces privés,
 * corrigés le 2026-08-27 ; celui-ci était passé au travers.
 *
 * Comme pour eux, la directive ne sera pas lue tant que robots.txt interdira l'exploration
 * de `/admin/` : un `noindex` posé sur une page qu'un robot n'a pas le droit de charger
 * reste lettre morte. Elle est là pour que la page soit correcte si elle venait à être
 * explorée — par un robot qui ignore robots.txt, ou si l'exclusion était levée un jour.
 *
 * Le titre, lui, sert immédiatement : c'est celui de l'onglet du navigateur, et il évite
 * un quatrième doublon du titre de l'accueil.
 */
export const metadata: Metadata = {
  title: "Administration",
  robots: { index: false, follow: false },
};

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  return <>{children}</>;
}
