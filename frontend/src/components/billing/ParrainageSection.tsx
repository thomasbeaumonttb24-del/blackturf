"use client";

import { useEffect, useState, type CSSProperties } from "react";
import { Check, Copy, Gift, Loader2, Share2, UserPlus, CreditCard, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { parrainageApi, type ResumeParrainage } from "@/lib/api";
import { euros } from "@/lib/parrainage";
import { cn } from "@/lib/utils";
import { Reveal, Tilt } from "@/components/track-record/effets";
import { Anneau, Compteur } from "@/components/espace/kit";

/**
 * Onglet « Parrainage » du profil.
 *
 * Tout y est automatique : le lien existe dès le premier affichage, le crédit
 * arrive seul quand le filleul a payé, et Stripe le déduit seul de la
 * prochaine mensualité. Cet écran ne fait qu'expliquer et montrer où l'on en est.
 *
 * Relief repris du palmarès et de « Mon espace » (`Tilt`, `tr-shine`,
 * `tr-medal`, `Reveal`, `Compteur`) : tout se met à plat avec « réduire les
 * animations », sans rien perdre du contenu.
 */
type Etape = ResumeParrainage["filleuls"][number]["etape"];

// Suivi en trois temps, le même pour chaque filleul : on voit d'un coup d'œil
// où il en est et ce qui manque pour que les 5 € tombent. Le libellé exact vient
// du serveur (`etape_libelle`), seul à connaître l'état réel.
const ETAPES_SUIVI = ["Inscrit", "1er paiement", "5 € crédités"] as const;
const AVANCEMENT: Record<Etape, number> = {
  email_a_confirmer: 1, attente_paiement: 1, paiement_en_cours: 1, verification: 2,
  credite: 3, reporte: 3, refuse: 1, parrain_inactif: 1, annule: 2,
};
const ECHEC: Etape[] = ["refuse", "parrain_inactif", "annule"];
const COULEUR: Record<Etape, string> = {
  email_a_confirmer: "text-stone-600", attente_paiement: "text-amber-700", paiement_en_cours: "text-amber-700",
  verification: "text-emerald-700", credite: "text-emerald-700", reporte: "text-amber-700",
  refuse: "text-stone-500", parrain_inactif: "text-stone-500", annule: "text-stone-500",
};

export function ParrainageSection() {
  const [data, setData] = useState<ResumeParrainage | null>(null);
  const [erreur, setErreur] = useState<string | null>(null);
  const [copie, setCopie] = useState(false);

  useEffect(() => {
    parrainageApi.moi()
      .then(({ data }) => setData(data))
      .catch((e: { response?: { status?: number } }) =>
        setErreur(e?.response?.status === 403
          ? "Confirmez d'abord votre adresse e-mail (lien reçu à l'inscription) pour obtenir votre lien de parrainage."
          : "Le parrainage est momentanément indisponible. Réessayez dans quelques minutes."));
  }, []);

  async function copier() {
    if (!data) return;
    try {
      await navigator.clipboard.writeText(data.lien);
      setCopie(true);
      toast.success("Lien copié : il ne reste qu'à l'envoyer");
      setTimeout(() => setCopie(false), 2000);
    } catch {
      toast.error("Copie impossible : sélectionnez le lien à la main.");
    }
  }

  async function partager() {
    if (!data) return;
    const texte = `Je t'invite sur BlackTurf, les pronostics PMU par IA : ${euros(data.remise_cents)} offerts sur ton premier abonnement avec mon lien.`;
    if (typeof navigator !== "undefined" && navigator.share) {
      try {
        await navigator.share({ title: "BlackTurf", text: texte, url: data.lien });
      } catch {
        /* partage annulé */
      }
      return;
    }
    window.open(`https://wa.me/?text=${encodeURIComponent(`${texte} ${data.lien}`)}`, "_blank", "noopener");
  }

  if (erreur) {
    return <p className="px-4 sm:px-6 py-8 text-sm text-stone-600">{erreur}</p>;
  }
  if (!data) {
    return (
      <div className="flex justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-stone-400" />
      </div>
    );
  }

  const remise = euros(data.remise_cents);
  const credit = data.credit_disponible_cents;

  return (
    <div className="px-4 sm:px-6 py-5 space-y-7">
      {/* ── Carte d'invitation en relief ── */}
      <Tilt max={5} className="rounded-3xl">
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-br from-stone-900 via-stone-900 to-stone-800 p-5 sm:p-7 text-white shadow-[0_30px_60px_-30px_rgba(28,25,23,.65)] ring-1 ring-white/10">
          <span className="tr-shine" aria-hidden />
          <div className="absolute -right-16 -top-16 h-56 w-56 rounded-full bg-amber-400/25 blur-3xl" aria-hidden />
          <div className="absolute -left-16 -bottom-20 h-56 w-56 rounded-full bg-emerald-400/15 blur-3xl" aria-hidden />

          <div className="relative grid gap-6 sm:grid-cols-[1fr_auto] sm:items-center">
            <div className="tr-pop">
              <p className="inline-flex items-center gap-1.5 rounded-full bg-white/10 px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-amber-300 ring-1 ring-white/10">
                <Gift className="h-3.5 w-3.5" /> Parrainage
              </p>
              <h3 className="mt-3 font-display text-2xl sm:text-[1.9rem] font-semibold leading-tight tracking-tight">
                <span className="whitespace-nowrap">{remise} pour votre ami,</span>
                <br />
                <span className="whitespace-nowrap bg-gradient-to-r from-amber-200 via-amber-300 to-amber-500 bg-clip-text text-transparent">
                  {remise} pour vous.
                </span>
              </h3>
              <p className="mt-2.5 max-w-md text-sm leading-relaxed text-stone-300">
                Votre ami paie {remise} de moins sur son premier abonnement. Dès que son paiement est
                encaissé, {remise} de crédit s&apos;ajoutent à votre compte, déduits automatiquement de
                vos factures. Sans limite d&apos;amis.
              </p>
            </div>

            {/* Deux bons « −5 € » en lévitation */}
            <div className="relative mx-auto h-36 w-60 sm:h-40 sm:w-64 [perspective:900px]" aria-hidden>
              <Bon position="left-0 top-12 -rotate-[9deg]" teinte="from-emerald-300 to-emerald-500" legende="Votre ami" montant={remise} delai="0s" />
              <Bon position="right-0 top-0 rotate-[7deg]" teinte="from-amber-200 to-amber-500" legende="Vous" montant={remise} delai="-2.2s" />
            </div>
          </div>

          {/* Lien + actions */}
          <div className="relative mt-6 rounded-2xl bg-white/[0.06] p-2 ring-1 ring-white/15 backdrop-blur-sm">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
              <div className="min-w-0 flex-1 px-2.5 py-1.5">
                <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-stone-400">Votre lien personnel</p>
                <p className="truncate font-mono text-sm text-stone-100" title={data.lien}>{data.lien}</p>
              </div>
              <div className="flex gap-2">
                <button
                  onClick={copier}
                  className="inline-flex flex-1 sm:flex-none items-center justify-center gap-1.5 rounded-xl bg-gradient-to-b from-amber-300 to-amber-500 px-4 py-2.5 text-sm font-semibold text-stone-900 shadow-[0_8px_20px_-8px_rgba(245,158,11,.8),inset_0_1px_0_rgba(255,255,255,.5)] transition-transform hover:-translate-y-0.5 active:translate-y-0"
                >
                  {copie ? <Check className="h-4 w-4" /> : <Copy className="h-4 w-4" />}
                  {copie ? "Copié" : "Copier"}
                </button>
                <button
                  onClick={partager}
                  className="inline-flex flex-1 sm:flex-none items-center justify-center gap-1.5 rounded-xl bg-white/10 px-4 py-2.5 text-sm font-semibold text-white ring-1 ring-white/20 transition-all hover:-translate-y-0.5 hover:bg-white/15"
                >
                  <Share2 className="h-4 w-4" /> Partager
                </button>
              </div>
            </div>
          </div>
          <p className="relative mt-2.5 text-xs text-stone-400">
            Ou donnez votre code :{" "}
            <span className="rounded-md bg-white/10 px-1.5 py-0.5 font-mono font-semibold tracking-[0.2em] text-stone-100">{data.code}</span>
          </p>
        </div>
      </Tilt>

      {/* ── Compteurs ── */}
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Tuile delai={0} label="Amis inscrits"><Compteur valeur={data.filleuls.length} /></Tuile>
        <Tuile delai={80} label="Amis abonnés"><Compteur valeur={data.valides} /></Tuile>
        <Tuile delai={160} label="Gagnés au total" accent="emerald">
          <Compteur valeur={data.gagne_cents / 100} suffixe=" €" />
        </Tuile>
        <Tuile delai={240} label="Crédit disponible" accent="amber">
          {credit === null ? "—" : <Compteur valeur={credit / 100} decimales={credit % 100 ? 2 : 0} suffixe=" €" />}
        </Tuile>
      </div>

      <PlafondDuMois mois={data.mois} remise={data.remise_cents} situation={data.deduction.situation} />

      <OuVaLeCredit deduction={data.deduction} credit={credit} remise={remise} />

      {/* ── Comment ça marche ── */}
      <div>
        <Titre sur="En 3 étapes" titre="Comment ça marche" />
        <ol className="grid gap-3 sm:grid-cols-3">
          <Etape n={1} delai={0} icone={UserPlus} titre="Votre ami s'inscrit"
                 texte="Avec votre lien ou votre code. La remise s'applique toute seule, rien à saisir." />
          <Etape n={2} delai={100} icone={CreditCard} titre={`Il paie ${remise} de moins`}
                 texte="Sur son premier abonnement, Standard ou Expert, au mois ou à l'année." />
          <Etape n={3} delai={200} icone={Sparkles} titre={`Vous gagnez ${remise}`}
                 texte="Dès que son paiement est encaissé, déduits de votre prochaine mensualité ou de l'abonnement que vous prendrez." />
        </ol>
      </div>

      {/* ── Suivi des filleuls ── */}
      <div>
        <Titre sur="Suivi" titre="Vos filleuls" />
        {data.filleuls.length === 0 ? (
          <Reveal className="rounded-2xl border border-dashed border-stone-300 bg-stone-50/60 px-4 py-8 text-center">
            <Gift className="mx-auto h-8 w-8 text-amber-500 tr-medal" aria-hidden />
            <p className="mt-3 text-sm font-medium text-stone-800">Aucun filleul pour l&apos;instant</p>
            <p className="mt-1 text-xs text-stone-500">Envoyez votre lien : chaque ami abonné vous rapporte {remise}.</p>
          </Reveal>
        ) : (
          <ul className="space-y-2.5">
            {data.filleuls.map((f, i) => (
              <li
                key={i}
                className="esp-ligne esp-panneau rounded-2xl p-4"
                style={{ animationDelay: `${Math.min(i, 8) * 60}ms` } as CSSProperties}
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="flex min-w-0 items-center gap-3">
                    <span className={cn(
                      "flex h-9 w-9 flex-shrink-0 items-center justify-center rounded-full text-sm font-bold shadow-inner",
                      f.statut === "valide" ? "bg-gradient-to-br from-emerald-300 to-emerald-500 text-white"
                        : "bg-gradient-to-br from-stone-100 to-stone-200 text-stone-700",
                    )}>
                      {f.prenom[0]?.toUpperCase()}
                    </span>
                    <div className="min-w-0">
                      <p className="truncate text-sm font-semibold text-stone-900">{f.prenom}</p>
                      <p className="text-xs text-stone-500">Inscrit le {new Date(f.depuis).toLocaleDateString("fr-FR")}</p>
                    </div>
                  </div>
                  {f.statut === "valide" && (
                    <span className="flex-shrink-0 rounded-full bg-emerald-50 px-2.5 py-1 text-xs font-bold text-emerald-700 ring-1 ring-emerald-200">
                      +{remise}
                    </span>
                  )}
                </div>
                <Suivi etape={f.etape} />
                <p className={cn("mt-2 text-xs font-medium", COULEUR[f.etape])}>
                  {f.etape_libelle}
                  {f.credite_le && ` · le ${new Date(f.credite_le).toLocaleDateString("fr-FR")}`}
                </p>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* ── Règles ── */}
      <details className="group esp-panneau rounded-2xl px-4 py-3 text-xs text-stone-600">
        <summary className="flex cursor-pointer list-none items-center justify-between text-sm font-semibold text-stone-800">
          Les règles, en clair
          <span className="text-lg leading-none text-stone-400 transition-transform group-open:rotate-45">+</span>
        </summary>
        <ul className="mt-3 space-y-2">
          {[
            "Les 5 € ne sont accordés qu'une fois le premier paiement de votre ami réellement encaissé. Une inscription seule ne rapporte rien.",
            "C'est une réduction sur votre abonnement BlackTurf, jamais un versement d'argent.",
            "Vos crédits se cumulent jusqu'à rendre votre mensualité gratuite : 4 parrainages par mois en Expert (19 €), 3 en Standard (12 €). Au-delà, ils sont reportés au mois suivant, rien n'est perdu.",
            "Quand vos crédits couvrent toute la facture, vous n'êtes pas prélevé ce mois-là ; le petit reste éventuel (1 € en Expert, 3 € en Standard) est déduit du mois suivant.",
            "Votre ami doit être un nouveau client, avec son propre compte et sa propre carte bancaire. Sa remise remplace l'essai gratuit.",
            "Si le paiement de votre ami est remboursé ou contesté, le crédit correspondant est annulé.",
          ].map((r) => (
            <li key={r} className="flex gap-2">
              <Check className="mt-0.5 h-3.5 w-3.5 flex-shrink-0 text-amber-600" aria-hidden />
              <span>{r}</span>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

/**
 * Jauge du mois : crédits posés sur la période en cours, sur le plafond de la
 * formule (celui qui rend la mensualité gratuite), et ce qui attend le mois
 * suivant. Le calcul est écrit en toutes lettres : 19 € − 3 × 5 € = 4 €.
 */
function PlafondDuMois({ mois, remise, situation }: {
  mois: ResumeParrainage["mois"];
  remise: number;
  situation: ResumeParrainage["deduction"]["situation"];
}) {
  const { plafond, poses, reportes, prix_cents: prix } = mois;
  const reste = Math.max(0, plafond - poses);
  const apres = Math.max(0, prix - poses * remise);
  const formule = mois.formule === "standard" ? "Standard" : mois.formule === "expert" ? "Expert" : null;
  const gratuit = poses >= plafond;
  // Pas de mensualité à payer (offert, résilié) : les crédits du mois vont en réserve.
  const reserve = situation === "offert" || situation === "resilie";
  const phrase = reserve
    ? `${poses} crédit${poses > 1 ? "s" : ""} gagné${poses > 1 ? "s" : ""} ce mois-ci, mis en réserve : vous n'avez pas de mensualité à payer pour l'instant.`
    : gratuit
      ? situation === "sans_abonnement"
        ? "De quoi rendre gratuit le premier mois de votre futur abonnement."
        : "Mensualité entièrement couverte : vous ne serez pas prélevé."
      : situation === "sans_abonnement"
        ? `Encore ${reste} ami${reste > 1 ? "s" : ""} abonné${reste > 1 ? "s" : ""} et votre premier mois d'abonnement sera gratuit.`
        : `Encore ${reste} ami${reste > 1 ? "s" : ""} abonné${reste > 1 ? "s" : ""} et votre prochain mois est gratuit.`;
  return (
    <Reveal className="relative overflow-hidden rounded-2xl bg-gradient-to-br from-stone-900 to-stone-800 p-4 sm:p-5 text-white shadow-[0_24px_48px_-28px_rgba(28,25,23,.8)]">
      <span className="tr-shine" aria-hidden />
      <div className="relative flex items-center gap-4 sm:gap-5">
        <Anneau pct={(poses / plafond) * 100} taille={92} epaisseur={9} couleur={["#FCD34D", "#10B981"]}>
          <span className="font-display text-2xl font-semibold leading-none">{poses}<span className="text-sm text-stone-400">/{plafond}</span></span>
          <span className="mt-0.5 text-[9px] uppercase tracking-[0.15em] text-stone-400">ce mois</span>
        </Anneau>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-amber-300">Votre mois en cours</p>
          <p className="mt-1 text-sm font-semibold leading-snug">{phrase}</p>
          <p className={cn("mt-1.5 font-mono text-xs text-stone-300 tabular-nums", reserve && "hidden")}>
            {euros(prix)} − {poses} × {euros(remise)} = <span className="font-semibold text-white">{euros(apres)}</span>
            {formule && <span className="font-sans text-stone-400"> · formule {formule}</span>}
          </p>
        </div>
      </div>
      <p className="relative mt-3 border-t border-white/10 pt-3 text-[11px] leading-relaxed text-stone-400">
        Plafond : {plafond} crédits par mois{formule ? ` en ${formule}` : ""}, de quoi rendre la mensualité gratuite.
        {reportes > 0
          ? ` ${reportes} crédit${reportes > 1 ? "s" : ""} de ${euros(remise)} ${reportes > 1 ? "attendent" : "attend"} le mois suivant : rien n'est perdu.`
          : " Au-delà, vos crédits sont reportés au mois suivant : rien n'est perdu."}
      </p>
    </Reveal>
  );
}

const jour = (iso: string | null | undefined) =>
  iso ? new Date(iso).toLocaleDateString("fr-FR", { day: "numeric", month: "long" }) : null;

/**
 * Où tombera le crédit, dit précisément : la prochaine facture réelle calculée
 * par Stripe quand il y en a une, sinon pourquoi le crédit attend en réserve.
 */
function OuVaLeCredit({ deduction, credit, remise }: {
  deduction: ResumeParrainage["deduction"];
  credit: number | null;
  remise: string;
}) {
  const aDuCredit = (credit ?? 0) > 0;
  let titre: string;
  let texte: string;
  let ticket: { avant: number; apres: number; date: string | null } | null = null;

  switch (deduction.situation) {
    case "facture":
      titre = aDuCredit ? "Votre prochaine facture, crédit déduit" : "Votre prochaine facture";
      texte = aDuCredit
        ? `Stripe déduit automatiquement votre crédit le ${jour(deduction.date) ?? "jour du prélèvement"}. Au plus le montant de la facture : le reste passe à la suivante.`
        : `Chaque ami abonné vous fait gagner ${remise}, déduits automatiquement de cette facture.`;
      ticket = { avant: deduction.total_cents, apres: deduction.a_payer_cents, date: jour(deduction.date) };
      break;
    case "abonne":
      titre = "Déduit de votre prochaine facture";
      texte = `Votre crédit sera déduit automatiquement${jour(deduction.date) ? ` le ${jour(deduction.date)}` : ""}, sans rien faire.`;
      break;
    case "offert":
      titre = "Votre abonnement vous est offert";
      texte = "Vous n'avez aucune facture à régler : vos crédits restent en réserve sur votre compte et seront déduits automatiquement dès que vous aurez un abonnement payant.";
      break;
    case "resilie":
      titre = "Crédit mis en réserve";
      texte = `Votre abonnement s'arrête${jour(deduction.date) ? ` le ${jour(deduction.date)}` : " à l'échéance"} : vos crédits restent sur votre compte et seront déduits de votre prochain abonnement.`;
      break;
    default:
      titre = "Déduit de votre futur abonnement";
      texte = "Vous n'êtes pas encore abonné : vos crédits vous attendent et seront déduits automatiquement de l'abonnement que vous prendrez.";
  }

  return (
    <Reveal className="esp-panneau flex flex-col gap-4 rounded-2xl p-4 sm:flex-row sm:items-center">
      <div className="min-w-0 flex-1">
        <p className="text-[11px] font-medium uppercase tracking-[0.18em] text-stone-500">Où vont vos crédits</p>
        <p className="mt-1 text-sm font-semibold text-stone-900">{titre}</p>
        <p className="mt-1 text-xs leading-relaxed text-stone-600">{texte}</p>
      </div>
      {ticket && (
        <div className="relative shrink-0 rounded-xl bg-gradient-to-br from-stone-50 to-white px-4 py-3 text-right ring-1 ring-stone-200 shadow-[0_10px_20px_-14px_rgba(28,25,23,.5)]">
          {ticket.date && <p className="text-[10px] uppercase tracking-[0.15em] text-stone-500">Le {ticket.date}</p>}
          {ticket.avant !== ticket.apres && (
            <p className="text-xs text-stone-400 line-through tabular-nums">{euros(ticket.avant)}</p>
          )}
          <p className="font-display text-xl font-semibold tabular-nums text-stone-900">{euros(ticket.apres)}</p>
          {ticket.avant !== ticket.apres && (
            <p className="text-[11px] font-semibold text-emerald-700">−{euros(ticket.avant - ticket.apres)} de crédit</p>
          )}
        </div>
      )}
    </Reveal>
  );
}

/** Bon cadeau flottant (décor de la carte d'invitation). */
function Bon({ position, teinte, legende, montant, delai }: { position: string; teinte: string; legende: string; montant: string; delai: string }) {
  return (
    <div className={cn("absolute", position)}>
      <div className="tr-medal" style={{ animationDelay: delai }}>
        <div className={cn(
          "relative h-20 w-28 sm:h-24 sm:w-32 overflow-hidden rounded-2xl bg-gradient-to-br p-3 text-stone-900",
          "shadow-[0_18px_30px_-12px_rgba(0,0,0,.6),inset_0_1px_0_rgba(255,255,255,.6),inset_0_-3px_0_rgba(0,0,0,.12)]",
          teinte,
        )}>
          <span className="tr-shine" />
          <p className="text-[10px] font-bold uppercase tracking-[0.15em] opacity-70">{legende}</p>
          <p className="mt-1 font-display text-2xl sm:text-3xl font-extrabold leading-none">−{montant}</p>
          <span className="absolute -right-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-stone-900" />
          <span className="absolute -left-2 top-1/2 h-4 w-4 -translate-y-1/2 rounded-full bg-stone-900" />
        </div>
      </div>
    </div>
  );
}

/** Barre de suivi en trois temps : inscrit → 1er paiement → 5 € crédités. */
function Suivi({ etape }: { etape: Etape }) {
  const fait = AVANCEMENT[etape];
  const barre = ECHEC.includes(etape);
  return (
    <div className="mt-3.5 flex items-center" aria-label={`Étape ${fait} sur 3`}>
      {ETAPES_SUIVI.map((etape, i) => {
        const ok = i < fait;
        return (
          <div key={etape} className={cn("flex items-center", i < ETAPES_SUIVI.length - 1 && "flex-1")}>
            <div className="flex flex-col items-center">
              <span className={cn(
                "flex h-6 w-6 items-center justify-center rounded-full text-[10px] font-bold transition-colors",
                ok && !barre ? "bg-gradient-to-br from-emerald-400 to-emerald-600 text-white shadow-[0_4px_10px_-3px_rgba(16,185,129,.7)]"
                  : ok ? "bg-stone-300 text-white"
                  : i === fait && !barre ? "bg-amber-100 text-amber-700 ring-2 ring-amber-300"
                  : "bg-stone-100 text-stone-400",
              )}>
                {barre && i === fait ? <X className="h-3 w-3" /> : ok ? <Check className="h-3 w-3" /> : i + 1}
              </span>
              <span className="mt-1 whitespace-nowrap text-[10px] text-stone-500">{etape}</span>
            </div>
            {i < ETAPES_SUIVI.length - 1 && (
              <span className={cn("mx-1.5 mb-4 h-0.5 flex-1 rounded-full", i + 1 < fait && !barre ? "bg-emerald-400" : "bg-stone-200")} />
            )}
          </div>
        );
      })}
    </div>
  );
}

function Titre({ sur, titre }: { sur: string; titre: string }) {
  return (
    <Reveal className="mb-3">
      <span className="flex items-center gap-2 text-[11px] font-medium uppercase tracking-[0.2em] text-stone-500">
        <span className="h-px w-5 bg-amber-600/70" aria-hidden /> {sur}
      </span>
      <h3 className="mt-1.5 font-display text-lg font-medium tracking-tight text-stone-900">{titre}</h3>
    </Reveal>
  );
}

function Tuile({ children, label, accent, delai }: { children: React.ReactNode; label: string; accent?: "emerald" | "amber"; delai: number }) {
  return (
    <Reveal delay={delai}>
      <Tilt max={8} className="h-full rounded-2xl">
        <div className={cn(
          "h-full rounded-2xl p-3.5",
          accent === "emerald" ? "bg-gradient-to-br from-emerald-50 to-white ring-1 ring-emerald-200 shadow-[0_14px_28px_-18px_rgba(16,185,129,.6)]"
            : accent === "amber" ? "bg-gradient-to-br from-amber-50 to-white ring-1 ring-amber-200 shadow-[0_14px_28px_-18px_rgba(245,158,11,.6)]"
            : "esp-panneau",
        )}>
          <p className={cn("tr-pop font-display text-2xl font-semibold",
            accent === "emerald" ? "text-emerald-700" : accent === "amber" ? "text-amber-700" : "text-stone-900")}>
            {children}
          </p>
          <p className="mt-1 text-[11px] leading-tight text-stone-600">{label}</p>
        </div>
      </Tilt>
    </Reveal>
  );
}

function Etape({ n, icone: Icone, titre, texte, delai }: { n: number; icone: typeof Gift; titre: string; texte: string; delai: number }) {
  return (
    <Reveal as="li" delay={delai}>
      <Tilt max={6} className="h-full rounded-2xl">
        <div className="esp-panneau relative h-full overflow-hidden rounded-2xl p-4">
          <span className="absolute -right-3 -top-5 font-display text-7xl font-bold text-stone-100 select-none" aria-hidden>{n}</span>
          <span className="tr-pop relative flex h-10 w-10 items-center justify-center rounded-xl bg-gradient-to-br from-stone-800 to-stone-950 text-amber-300 shadow-[0_10px_20px_-8px_rgba(28,25,23,.7),inset_0_1px_0_rgba(255,255,255,.15)]">
            <Icone className="h-5 w-5" aria-hidden />
          </span>
          <p className="relative mt-3 text-sm font-semibold text-stone-900">{titre}</p>
          <p className="relative mt-1 text-xs leading-relaxed text-stone-600">{texte}</p>
        </div>
      </Tilt>
    </Reveal>
  );
}
