import { titleCase, type SeoApercuCourse } from "@/lib/seo";

/**
 * Classement de l'IA rendu CÔTÉ SERVEUR, présent dès le premier octet du HTML.
 *
 * Le masquage est fait par l'API (`/courses/{id}/apercu`) : une ligne non révélée
 * n'a ni numéro ni nom dans la réponse. Seuls le rang, les probabilités et la cote
 * juste (1/proba) sortent. Partagé par la fiche course et le Quinté du jour.
 */
export function AnalyseIA({ apercu, titre }: { apercu: SeoApercuCourse | null; titre?: string }) {
  if (!apercu || apercu.classement.length === 0) return null;
  return (
    <>
      <h3 className="mt-6 font-display text-[15px] font-bold text-slate-900">
        {titre ?? "Analyse IA de la course"} ({apercu.nb_analyses} chevaux notés)
      </h3>
      <p className="mt-1.5 text-[13px] leading-relaxed text-stone-600">
        {apercu.proba_top1 != null && (
          <>
            Le premier du classement est donné gagnant à{" "}
            {(apercu.proba_top1 * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %
            {apercu.confiance != null ? `, avec une confiance de ${apercu.confiance}/100` : ""}.{" "}
          </>
        )}
        {apercu.accord_marche === true && "Il est aussi le favori des cotes. "}
        {apercu.accord_marche === false && "Le marché, lui, en désigne un autre. "}
        {/* L'accord était figé au pluriel : « 1 chevaux sont crédités » s'affichait tel
            quel sur toutes les fiches à un seul écarté. */}
        {apercu.nb_ecartes > 0 &&
          (apercu.nb_ecartes === 1
            ? `1 cheval est crédité de moins de 3 % de chances. `
            : `${apercu.nb_ecartes} chevaux sont crédités de moins de 3 % de chances. `)}
        La cote juste est l&apos;inverse de la probabilité : au-dessus, le cheval est
        payé plus qu&apos;il ne vaut ; en dessous, moins.{" "}
        <a
          href="/pronostics-ia"
          className="font-medium text-brand-gold-dark underline-offset-2 hover:underline"
        >
          Comment l&apos;IA calcule ces probabilités
        </a>
        .
      </p>
      <div className="mt-3 overflow-x-auto rounded-xl border border-stone-200">
        <table className="w-full border-collapse text-[12.5px] sm:min-w-[460px] sm:text-[13px]">
          <caption className="sr-only">
            Classement prédit par BlackTurf, probabilité de victoire et cote juste
          </caption>
          <thead>
            <tr className="bg-stone-50 text-left text-[10.5px] uppercase text-stone-600 sm:text-[11px] sm:tracking-[0.08em]">
              <th scope="col" className="px-2 py-2 sm:px-3 font-semibold">
                <span className="sm:hidden" title="Rang">#</span><span className="hidden sm:inline">Rang</span>
              </th>
              <th scope="col" className="px-2 py-2 sm:px-3 font-semibold">Cheval</th>
              <th scope="col" className="px-2 py-2 sm:px-3 text-right font-semibold">
                <span className="sm:hidden">Proba.</span><span className="hidden sm:inline">Proba. victoire</span>
              </th>
              <th scope="col" className="px-2 py-2 sm:px-3 text-right font-semibold">
                <span className="sm:hidden">C. juste</span><span className="hidden sm:inline">Cote juste</span>
              </th>
            </tr>
          </thead>
          <tbody>
            {apercu.classement.map((l) => (
              <tr key={l.rang} className="border-t border-stone-100 text-stone-600">
                <td className="px-2 py-2 sm:px-3 font-display font-bold tabular-nums text-slate-900">
                  {l.rang}
                </td>
                <td className="px-2 py-2 sm:px-3 font-medium text-slate-900">
                  {l.revele && l.nom ? (
                    <>
                      {l.numero != null && (
                        <span className="mr-1.5 tabular-nums text-stone-600">{l.numero}</span>
                      )}
                      {titleCase(l.nom)}
                    </>
                  ) : (
                    // Masqué PAR LE SERVEUR : le nom n'existe pas dans la
                    // réponse. Pas un flou CSS, qui se retire en deux clics.
                    <span className="text-stone-500">Réservé aux abonnés</span>
                  )}
                </td>
                <td className="px-2 py-2 sm:px-3 text-right tabular-nums">
                  {l.proba_top1 != null
                    ? `${(l.proba_top1 * 100).toLocaleString("fr-FR", { maximumFractionDigits: 1 })} %`
                    : "—"}
                </td>
                <td className="px-2 py-2 sm:px-3 text-right tabular-nums">
                  {l.cote_juste != null
                    ? l.cote_juste.toLocaleString("fr-FR", { maximumFractionDigits: 1 })
                    : "—"}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
