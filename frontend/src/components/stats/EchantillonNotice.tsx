import { Info } from "lucide-react";

/**
 * Taille d'échantillon en dessous de laquelle un taux affiché ne veut rien dire.
 *
 * À 200 courses, un taux de 66 % porte un intervalle de confiance à 95 % d'environ
 * ±6,5 points ; à 9 courses, il est de ±31 points — autrement dit le chiffre est
 * du bruit. Le read-model ne retenant que la cohorte rejouable (snapshots
 * pré-course, démarrés le 2026-08-18), le compteur est reparti de zéro : tant
 * qu'il n'a pas rattrapé, on le DIT au lieu d'afficher un pourcentage nu.
 */
export const SEUIL_ECHANTILLON = 200;

function formatDateFr(iso: string | null | undefined): string | null {
  if (!iso) return null;
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? null
    : d.toLocaleDateString("fr-FR", { day: "2-digit", month: "long", year: "numeric" });
}

/**
 * Mention affichée tant que l'échantillon est trop petit pour que les taux
 * publiés soient tenus pour acquis. Ne rend rien au-delà du seuil.
 */
export function EchantillonNotice({
  nbCourses,
  mesureDepuis,
  variante = "clair",
}: {
  nbCourses: number | null | undefined;
  mesureDepuis?: string | null;
  variante?: "clair" | "sombre";
}) {
  if (nbCourses == null || nbCourses >= SEUIL_ECHANTILLON) return null;

  const depuis = formatDateFr(mesureDepuis);
  const sombre = variante === "sombre";

  return (
    <p
      className={[
        "mt-4 flex items-start gap-2 rounded-xl px-3 py-2 text-[11px] leading-5",
        sombre
          ? "bg-white/5 text-slate-300 ring-1 ring-white/10"
          : "bg-amber-50 text-amber-900 ring-1 ring-amber-200",
      ].join(" ")}
    >
      <Info className="mt-[1px] h-3.5 w-3.5 shrink-0" aria-hidden="true" />
      <span>
        Échantillon en cours de constitution :{" "}
        <strong className="font-semibold">
          {nbCourses.toLocaleString("fr-FR")} course{nbCourses > 1 ? "s" : ""}
        </strong>{" "}
        réglée{nbCourses > 1 ? "s" : ""}
        {depuis ? ` depuis le ${depuis}` : ""}. Ces taux vont encore bouger
        sensiblement — nous les publions quand même plutôt que d&apos;attendre d&apos;avoir
        de beaux chiffres.
      </span>
    </p>
  );
}
