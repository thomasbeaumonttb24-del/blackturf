"use client";
import { createContext, useContext, useState, type ReactNode } from "react";
import useSWR from "swr";
import { coursesApi } from "@/lib/api";
type PartantIdentite = { numero: number; nom_cheval: string; casaque_image_url?: string | null };
const CasaquesContext = createContext<PartantIdentite[]>([]);
export function CasaquesProvider({ partants, children }: { partants: PartantIdentite[]; children: ReactNode }) {
  return <CasaquesContext.Provider value={partants}>{children}</CasaquesContext.Provider>;
}
// Le numéro reste lisible indépendamment du chargement de la casaque.
export function CasaqueNumero({ numero, imgUrl, courseId, nom, vertical = false }: {
  numero?: number | null; imgUrl?: string | null; courseId?: string; nom?: string; vertical?: boolean;
}) {
  const partants = useContext(CasaquesContext);
  const { data } = useSWR(courseId && !partants.length ? ["casaques", courseId] : null,
    async ([, id]: [string, string]) => (await coursesApi.course(id)).data as { partants: PartantIdentite[] },
    { revalidateOnFocus: false, shouldRetryOnError: false, dedupingInterval: 300000 });
  const partant = (partants.length ? partants : data?.partants ?? []).find(p => numero != null ? p.numero === numero : p.nom_cheval === nom);
  const number = numero ?? partant?.numero;
  const url = imgUrl ?? partant?.casaque_image_url;
  const [failedUrl, setFailedUrl] = useState<string | null>(null);
  return <span style={{ display: "inline-flex", flexDirection: vertical ? "column" : "row", alignItems: "center", gap: 4, flexShrink: 0, verticalAlign: "middle" }}>
    {number != null && <span aria-label={"Numéro de partant " + number} style={{ display: "inline-flex", alignItems: "center", justifyContent: "center", minWidth: 30, height: 26, padding: "0 4px", borderRadius: 6, background: "#172033", color: "#fff", fontSize: 13, fontWeight: 800, lineHeight: 1, fontVariantNumeric: "tabular-nums", whiteSpace: "nowrap" }}>{number}</span>}
    {url && failedUrl !== url && <img src={url} alt={"Casaque" + (number != null ? " du n°" + number : "")} width={30} height={30} loading="lazy" onError={() => setFailedUrl(url)} style={{ width: 30, height: 30, minWidth: 30, maxWidth: "none", objectFit: "contain", background: "#fff", borderRadius: 4, flexShrink: 0 }} />}
  </span>;
}
export function IdentiteCheval({ numero, nom, courseId, imgUrl }: { numero?: number | null; nom: string; courseId?: string; imgUrl?: string | null }) {
  return <span style={{ display: "inline-flex", alignItems: "center", gap: 6, minWidth: 0, maxWidth: "100%", verticalAlign: "middle" }}>
    <CasaqueNumero numero={numero} nom={nom} courseId={courseId} imgUrl={imgUrl} />
    <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={nom}>{nom}</span>
  </span>;
}
