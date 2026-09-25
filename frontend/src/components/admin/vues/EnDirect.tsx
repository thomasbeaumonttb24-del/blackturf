"use client";

/**
 * « En ce moment sur le site » — personnes ayant un onglet visible dans les
 * 5 dernières minutes (signal envoyé par `components/SignalPresence`).
 *
 * Les comptes connectés sont nommés ; les anonymes sont comptés. La console
 * d'administration n'émet pas de signal : l'exploitant ne se compte pas.
 */

import { Radio } from "lucide-react";
import { BadgeFormule, Initiales, Panneau, PointLive, Squelette, T, Vide, num } from "../ui";
import { useEnLigne } from "../data";
import { Compteur } from "../relief";

function ilYa(s: number | null): string {
  if (s == null) return "";
  if (s < 60) return "à l'instant";
  return `il y a ${Math.round(s / 60)} min`;
}

const pluriel = (n: number | null, mot: string) => `${mot}${(n ?? 0) > 1 ? "s" : ""}`;

export default function EnDirect({ className }: { className?: string }) {
  const { data } = useEnLigne();

  return (
    <Panneau
      titre="En ce moment sur le site"
      icone={<Radio className="h-3.5 w-3.5" />}
      className={className}
      actions={data?.disponible ? (
        <span className="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
          <PointLive /> Direct
        </span>
      ) : undefined}
    >
      {!data ? (
        <Squelette lignes={3} />
      ) : !data.disponible ? (
        <Vide>Mesure indisponible pour l&apos;instant.</Vide>
      ) : (
        <>
          <div className="flex items-end gap-4">
            <div className="bt-or-texte text-6xl font-black leading-none tracking-tight tabular-nums">
              <Compteur valeur={data.total} format={(v) => num(Math.round(v))} />
            </div>
            <div className="pb-0.5 text-[13px] leading-snug text-muted-foreground">
              <div><b className="font-semibold text-foreground">{num(data.connectes)}</b> {pluriel(data.connectes, "connecté")}</div>
              <div><b className="font-semibold text-foreground">{num(data.anonymes)}</b> {pluriel(data.anonymes, "visiteur")} sans compte</div>
            </div>
          </div>

          {data.comptes.length > 0 && (
            <ul className="mt-4 divide-y divide-white/[0.05] border-t border-white/[0.06]">
              {data.comptes.slice(0, 8).map((c) => (
                <li key={c.user_id} className="flex items-center gap-3 py-2.5">
                  <Initiales email={c.email} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-[13px] font-medium" title={c.email}>{c.email}</div>
                    <div className="truncate text-xs text-muted-foreground">
                      {c.chemin ?? "—"} · {ilYa(c.vu_il_y_a_s)}
                    </div>
                  </div>
                  <BadgeFormule plan={c.is_admin ? "admin" : c.plan} />
                </li>
              ))}
            </ul>
          )}

          {data.pages.length > 0 && (
            <div className="mt-4">
              <div className={T.etiquette}>Pages ouvertes</div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {data.pages.map((p) => (
                  <span key={p.chemin} className="inline-flex items-center gap-1.5 rounded-full border border-white/10 bg-white/[0.04] px-2.5 py-1 text-xs shadow-[inset_0_1px_0_rgba(255,255,255,0.06)]">
                    <span className="max-w-[180px] truncate">{p.chemin}</span>
                    <b className="tabular-nums">{p.n}</b>
                  </span>
                ))}
              </div>
            </div>
          )}

          {data.total === 0 && (
            <p className="mt-3 text-xs text-muted-foreground">Personne sur le site depuis {data.fenetre_min} min.</p>
          )}
        </>
      )}
    </Panneau>
  );
}
