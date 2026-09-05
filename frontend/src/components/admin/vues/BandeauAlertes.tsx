"use client";

/**
 * « Ce qui demande une action » — le premier bloc de la console.
 *
 * L'ancienne page ouvrait sur quatre tuiles de comptage puis empilait sept
 * sections dépliables. Rien ne disait ce qui n'allait pas : il fallait ouvrir
 * chaque section pour le découvrir, et un paiement échoué se lisait à la même
 * taille qu'un compteur d'utilisateurs.
 *
 * Ici chaque ligne est un problème NOMMÉ, avec sa gravité, son ancienneté et le
 * lien qui mène à l'endroit où on le traite. Quand il n'y a rien, le bloc le dit
 * en une phrase au lieu de disparaître — un silence ne se distingue pas d'une
 * panne d'affichage.
 */

import Link from "next/link";
import {
  AlertTriangle, ArrowRight, CheckCircle2, CreditCard, Radio, Brain, ShieldAlert,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Panneau, depuis } from "../ui";
import { incidentsPaiement, useAbonnements, useDashboard, useErreurs, useScrapers } from "../data";
import { MOUVEMENT_LABELS, scraperSain } from "../types";

/** Au-delà, un modèle « actif » décrit un état du monde qui n'existe plus :
 *  le ré-entraînement tourne chaque nuit, deux nuits muettes sont une panne. */
const MODELE_PERIME_H = 48;

type Gravite = "alerte" | "attention";

interface Ligne {
  cle: string;
  gravite: Gravite;
  icone: React.ElementType;
  titre: string;
  detail: string;
  href: string;
  lienLabel: string;
}

export default function BandeauAlertes() {
  const { data: dashboard } = useDashboard();
  const { data: erreurs } = useErreurs();
  const { data: scrapers } = useScrapers();
  const { data: abos } = useAbonnements();

  const lignes: Ligne[] = [];

  // ── Paiements : ce qui coupe l'accès d'un client payant passe en premier.
  const paiements = incidentsPaiement(abos);
  if (paiements.uniques.length > 0) {
    const d = paiements.dernier;
    lignes.push({
      cle: "paiements",
      gravite: "alerte",
      icone: CreditCard,
      titre: `${paiements.uniques.length} incident${paiements.uniques.length > 1 ? "s" : ""} de paiement sur 7 jours`,
      detail: d
        ? `Dernier : ${MOUVEMENT_LABELS[d.type] ?? d.type} — ${d.email ?? "compte supprimé"}, ${depuis(d.created_at)}`
        : "",
      href: "/admin/abonnements",
      lienLabel: "Voir les abonnements",
    });
  }

  const sansCarte = abos?.resume.en_essai_sans_carte ?? 0;
  if (sansCarte > 0) {
    lignes.push({
      cle: "sans-carte",
      gravite: "attention",
      icone: CreditCard,
      titre: `${sansCarte} essai${sansCarte > 1 ? "s" : ""} sans moyen de paiement`,
      detail: "Accès bloqué tant qu'aucune carte n'est rattachée — ces essais ne convertiront pas seuls.",
      href: "/admin/abonnements",
      lienLabel: "Voir les essais",
    });
  }

  const finEssai = abos?.resume.fin_essai_sous_3j ?? 0;
  if (finEssai > 0) {
    lignes.push({
      cle: "fin-essai",
      gravite: "attention",
      icone: CreditCard,
      titre: `${finEssai} essai${finEssai > 1 ? "s" : ""} se termine${finEssai > 1 ? "nt" : ""} sous 3 jours`,
      detail: "Fenêtre courte : c'est là que se joue la conversion.",
      href: "/admin/abonnements",
      lienLabel: "Voir les essais",
    });
  }

  // ── Scrapers muets. « ok_but_empty » compte comme une panne : quatre sources
  // sont restées « ok » à zéro donnée pendant des semaines.
  const ko = Object.entries(scrapers ?? {}).filter(([, s]) => !scraperSain(s.statut));
  if (ko.length > 0) {
    lignes.push({
      cle: "scrapers",
      gravite: "alerte",
      icone: Radio,
      titre: `${ko.length} scraper${ko.length > 1 ? "s" : ""} en échec`,
      detail: ko.map(([nom, s]) => `${nom} (${s.statut})`).join(" · "),
      href: "/admin/systeme",
      lienLabel: "Voir les scrapers",
    });
  }

  // ── Erreurs runtime ouvertes.
  const ouvertes = (erreurs?.errors ?? []).filter((e) => !e.resolved);
  if (ouvertes.length > 0) {
    const derniere = ouvertes[0];
    lignes.push({
      cle: "erreurs",
      gravite: ouvertes.length >= 5 ? "alerte" : "attention",
      icone: ShieldAlert,
      titre: `${ouvertes.length} erreur${ouvertes.length > 1 ? "s" : ""} non résolue${ouvertes.length > 1 ? "s" : ""}`,
      detail: derniere
        ? `Dernière : ${derniere.source} — ${derniere.message.slice(0, 90)}`
        : "Exceptions API et scrapers échoués sur 72 h.",
      href: "/admin/systeme",
      lienLabel: "Voir les erreurs",
    });
  }

  // ── Modèle gelé. Le cas vécu : un gate cassé a figé le modèle pendant des
  // semaines sans qu'aucun écran ne le dise.
  const entraine = dashboard?.modele.trained_at;
  const ageH = entraine ? (Date.now() - new Date(entraine).getTime()) / 3_600_000 : null;
  if (dashboard && (!dashboard.modele.version || (ageH != null && ageH > MODELE_PERIME_H))) {
    lignes.push({
      cle: "modele",
      gravite: "alerte",
      icone: Brain,
      titre: dashboard.modele.version
        ? `Modèle figé depuis ${Math.round((ageH ?? 0) / 24)} j`
        : "Aucun modèle déployé",
      detail: dashboard.modele.version
        ? `Le ré-entraînement tourne chaque nuit : v${dashboard.modele.version} entraînée ${depuis(entraine)}.`
        : "Les pronostics ne s'appuient sur aucune version active.",
      href: "/admin/systeme",
      lienLabel: "Voir les modèles",
    });
  }

  const chargement = !dashboard && !erreurs && !scrapers && !abos;

  return (
    <Panneau
      titre="Ce qui demande une action"
      desc="Incidents ouverts, classés du plus coûteux au moins urgent. Chaque ligne mène à l'écran où on le traite."
      icone={lignes.length > 0 ? <AlertTriangle className="h-3.5 w-3.5" /> : <CheckCircle2 className="h-3.5 w-3.5" />}
      ton={lignes.some((l) => l.gravite === "alerte") ? "alerte" : lignes.length > 0 ? "attention" : "ok"}
      bodyClassName="p-0 sm:p-0"
    >
      {chargement ? (
        <p className="px-4 py-5 text-[13px] text-muted-foreground sm:px-5">Relevé en cours…</p>
      ) : lignes.length === 0 ? (
        <p className="flex items-start gap-2 px-4 py-4 text-[13px] leading-relaxed text-emerald-800 sm:px-5">
          <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-emerald-600" aria-hidden />
          <span>
            Rien à traiter : aucune erreur ouverte, toutes les sources répondent, aucun
            paiement en échec et le modèle a été ré-entraîné dans les {MODELE_PERIME_H} h.
          </span>
        </p>
      ) : (
        <ul className="divide-y divide-border/60">
          {lignes.map((l) => {
            const Icone = l.icone;
            return (
              <li key={l.cle}>
                <Link
                  href={l.href}
                  className="flex min-h-[3.5rem] items-start gap-3 px-4 py-3 transition-colors hover:bg-muted/40 sm:px-5"
                >
                  <span
                    className={cn(
                      "mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-xl border",
                      l.gravite === "alerte"
                        ? "border-red-200 bg-red-50 text-red-700"
                        : "border-amber-200 bg-amber-50 text-amber-700",
                    )}
                  >
                    <Icone className="h-4 w-4" aria-hidden />
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block text-[13px] font-semibold leading-snug">{l.titre}</span>
                    {l.detail && (
                      <span className="mt-0.5 block break-words text-xs leading-relaxed text-muted-foreground">
                        {l.detail}
                      </span>
                    )}
                    <span className="mt-1 inline-flex items-center gap-1 text-xs font-semibold text-brand-gold-dark">
                      {l.lienLabel} <ArrowRight className="h-3 w-3" aria-hidden />
                    </span>
                  </span>
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </Panneau>
  );
}
