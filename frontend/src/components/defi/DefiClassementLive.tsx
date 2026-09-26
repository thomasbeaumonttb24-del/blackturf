"use client";

/**
 * Classement du Défi du mois EN DIRECT : podium des trois premiers sur l'en-tête
 * sombre du défi, puis la suite du classement et la place du joueur connecté,
 * même s'il est loin. Posé là où l'on veut donner envie de jouer : accueil,
 * résultats du jour, pages course, tableau de bord.
 */

import Link from "next/link";
import useSWR from "swr";
import { ArrowRight, Crown, Loader2 } from "lucide-react";
import { useAuth } from "@/hooks/useAuth";
import { defiApi, type DefiClassement } from "@/lib/api";
import {
  BOUTON_OR, CompteRebours, DEFI_CARTE, DefiEntete, LigneClassement, PastilleDirect, Podium, dateLancement, moisLabel, planLabel, formatNombre } from "@/components/defi/kit";
import { cn } from "@/lib/utils";

export function DefiClassementLive({ top = 5, className, titre = "Défi du mois", ctaCourse }: {
  /** 3 = podium seul ; au-delà, la suite du classement s'affiche sous le podium. */
  top?: number;
  className?: string;
  titre?: string;
  /** Sur une page course : le bouton ouvre l'onglet Défi au lieu de /defi. */
  ctaCourse?: () => void;
}) {
  const { user } = useAuth();
  const { data } = useSWR<DefiClassement>(
    ["/defi/classement/top", top, user?.user_id ?? ""],
    () => defiApi.classement(undefined, top).then((r) => r.data),
    { refreshInterval: 60_000 },
  );
  const { data: regles } = useSWR("/defi/regles", () => defiApi.regles().then((r) => r.data),
    { revalidateOnFocus: false });

  const prix = regles?.recompenses?.[0];
  const minParis = regles?.min_paris_classement ?? 10;
  const lignes = data?.lignes ?? [];
  const suite = lignes.slice(3);
  const ma = data?.ma_ligne;
  const maVisible = !!ma && lignes.some((l) => l.moi);
  const max = lignes[0]?.solde ?? 0;

  return (
    <section aria-label="Classement du Défi du mois en direct"
      className={cn(DEFI_CARTE, className)}>
      <DefiEntete
        surtitre={data ? `${moisLabel(data.mois)} · ${data.nb_joueurs} joueur${data.nb_joueurs > 1 ? "s" : ""}` : "Classement"}
        titre={titre}
        sousTitre={data?.essai ? <>Mois d&apos;essai · récompenses dès le {dateLancement(regles?.premier_mois)}</>
          : prix && <>1<sup>er</sup> du mois : {prix.jours} jours {planLabel(prix.plan)} offerts</>}
        droite={<>
          <PastilleDirect />
          {data && <CompteRebours mois={data.mois} />}
        </>}
      >
        {!data ? (
          <div className="flex h-40 items-center justify-center"><Loader2 className="h-5 w-5 animate-spin text-amber-600/70" /></div>
        ) : (
          <>
            <Podium compact={top <= 3} lignes={[0, 1, 2].map((i) => lignes[i] && ({ nom: lignes[i].nom, solde: lignes[i].solde, moi: lignes[i].moi }))} />
            {lignes.length === 0 && (
              <p className="mt-4 flex items-start gap-2 rounded-xl bg-white/80 px-3 py-2.5 text-[12px] leading-snug text-slate-700 ring-1 ring-inset ring-amber-200">
                <Crown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden="true" />
                Personne n&apos;est encore classé : il faut {minParis} paris dans le mois. Les trois marches sont à prendre.
              </p>
            )}
          </>
        )}
      </DefiEntete>

      {(suite.length > 0 || (ma && !maVisible)) && (
        <ol className="divide-y divide-stone-100 border-b border-stone-100 py-1" start={4}>
          {suite.map((l) => (
            <LigneClassement key={`${l.rang}-${l.nom}`} rang={l.rang} nom={l.nom} solde={l.solde}
              nbParis={l.nb_paris} moi={l.moi} max={max} />
          ))}
          {ma && !maVisible && (
            <>
              {suite.length > 0 && <li aria-hidden="true" className="py-1 text-center text-[11px] leading-none tracking-[0.3em] text-slate-300">•••</li>}
              <LigneClassement rang={ma.rang} nom={ma.nom} solde={ma.solde} nbParis={ma.nb_paris} moi max={max}
                detail={ma.rang == null ? `${ma.nb_paris}/${minParis} paris pour être classé` : undefined} />
            </>
          )}
        </ol>
      )}

      <div className="flex flex-wrap items-center justify-between gap-2 bg-stone-50/70 px-4 py-3">
        <span className="text-[11.5px] text-slate-600">
          {user ? "Chaque arrivée met le classement à jour."
            : `Gratuit, sans argent réel : ${formatNombre((regles?.capital_mensuel ?? 1000), 2)} points offerts chaque mois.`}
        </span>
        {ctaCourse ? (
          <button type="button" onClick={ctaCourse}
            className={BOUTON_OR}>
            Parier sur cette course <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </button>
        ) : (
          <Link href="/defi"
            className={BOUTON_OR}>
            {user ? "Classement complet" : "Participer gratuitement"} <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
          </Link>
        )}
      </div>
    </section>
  );
}
