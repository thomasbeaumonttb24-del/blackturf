"use client";

/**
 * Système — modèles, sources de données, erreurs, intégrations.
 *
 * Ces quatre sujets étaient dispersés dans l'empilement de `/admin`, chacun
 * derrière un dépliage, sans lien entre eux. Ils sont pourtant lus ensemble :
 * quand un pronostic sort faux, on regarde le modèle actif, puis la fraîcheur
 * des cotes, puis les exceptions.
 *
 * Ils partagent maintenant une page et une sous-navigation. Un onglet plutôt
 * qu'un empilement, parce qu'aucun de ces quatre blocs n'a besoin des trois
 * autres à l'écran en même temps — et que quatre tableaux empilés sur un
 * téléphone, ça fait dix écrans de défilement.
 *
 * Règle de la page (04/10) : chaque chiffre dit d'où il vient. Le hold-out
 * d'entraînement et le terrain ne se mélangent pas, une source coupée exprès
 * n'est pas « en service », et une erreur non résolue ne sort pas de l'écran
 * parce qu'elle a vieilli.
 */

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowRight, Brain, CheckCircle2, Clock, Instagram, Loader2,
  MinusCircle, Moon, Radio, RefreshCw, Server, ShieldAlert, TrendingDown, TrendingUp, XCircle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { adminApi } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import {
  Carte, CartesOuTableau, Champ, DefilementX, EnTetePage, Encart, Etat, GrilleTuiles, Note,
  Panneau, Puce, Repliable, Segments, Squelette, TD, TH, Tuile, VoirPlus, Vide,
  depuis, num, pct, tone,
} from "@/components/admin/ui";
import { useDashboard, useErreurs, useModeles, useScrapers } from "@/components/admin/data";
import {
  STATUT_SOURCE_LABELS, scraperSain,
  type ModelVersion, type SourceDonnees, type SystemError,
} from "@/components/admin/types";

const ONGLETS = [
  { key: "modeles", label: "Modèles" },
  { key: "sources", label: "Sources" },
  { key: "erreurs", label: "Erreurs" },
  { key: "integrations", label: "Intégrations" },
] as const;
type Onglet = (typeof ONGLETS)[number]["key"];

const fr3 = (v: number | null | undefined) =>
  v == null || !isFinite(v)
    ? "—"
    : v.toLocaleString("fr-FR", { minimumFractionDigits: 3, maximumFractionDigits: 3 });
const ecart = (v: number | null | undefined) =>
  v == null || !isFinite(v) ? "—" : `${v > 0 ? "+" : v < 0 ? "−" : ""}${fr3(Math.abs(v))}`;
const jour = (iso: string | null | undefined) =>
  iso
    ? new Date(iso).toLocaleDateString("fr-FR", { day: "2-digit", month: "2-digit", timeZone: "Europe/Paris" })
    : "—";

function ChargementImpossible({ quoi, error, retry }: { quoi: string; error: unknown; retry: () => void }) {
  const msg = error instanceof Error ? error.message : String(error ?? "");
  return (
    <Encart ton="alerte" icone={<AlertTriangle className="h-4 w-4" />}>
      Impossible de charger {quoi}{msg ? ` (${msg})` : ""}.{" "}
      <button className="font-semibold underline" onClick={retry}>Réessayer</button>
    </Encart>
  );
}

/* ───────────────────────────── modèles ─────────────────────────────────── */

/** En dessous, le taux de réussite top-3 d'une version bouge de ±10 points par
 *  pur hasard : on l'affiche en gris, sans en tirer de couleur. */
const ECHANTILLON_MIN = 40;
/** Seuil d'alerte du Brier, le même qu'à l'entraînement (`ml/models.py`). */
const BRIER_SEUIL = 0.18;

function etatModele(m: ModelVersion) {
  if (m.est_actif) return <Etat ton="ok">En service</Etat>;
  if (m.est_rollback)
    return <Etat ton="alerte" titre="Retirée par un retour arrière : ne sert plus de référence.">Retirée</Etat>;
  return <Etat ton="neutre">Archivée</Etat>;
}

/** Écart modèle − cote, et son sens par rapport à la version précédente. */
function EcartCote({ m, prec }: { m: ModelVersion; prec?: ModelVersion }) {
  const d = m.rank_delta_market;
  const variation = d != null && prec?.rank_delta_market != null ? d - prec.rank_delta_market : null;
  return (
    <span className="inline-flex items-center justify-end gap-1">
      <span className={cn("font-semibold", tone(d))}>{ecart(d)}</span>
      {variation != null && Math.abs(variation) >= 0.0005 && (
        variation > 0
          ? <TrendingUp className="h-3.5 w-3.5 text-emerald-600" aria-label="en hausse sur la version précédente" />
          : <TrendingDown className="h-3.5 w-3.5 text-red-600" aria-label="en baisse sur la version précédente" />
      )}
    </span>
  );
}

function EnCourse({ m, champ }: { m: ModelVersion; champ: "top3" | "brier" }) {
  const e = m.en_course;
  if (!e || e.n_courses === 0) return <span className="text-muted-foreground">—</span>;
  const faible = e.n_courses < ECHANTILLON_MIN;
  if (champ === "top3") {
    return (
      <span className={cn(faible && "text-muted-foreground")} title={`${e.n_courses} courses`}>
        {pct((e.top3 ?? 0) * 100, 0)}
      </span>
    );
  }
  return (
    <span className={cn(faible ? "text-muted-foreground" : (e.brier ?? 0) > BRIER_SEUIL && "text-red-700")}>
      {fr3(e.brier)}
    </span>
  );
}

function OngletModeles() {
  const { data: dashboard } = useDashboard();
  const { data: modeles, error, mutate } = useModeles();
  const [tout, setTout] = useState(false);
  const [deploiement, setDeploiement] = useState<number | null>(null);

  async function deployer(m: ModelVersion) {
    const avert = m.est_rollback
      ? `\n\nATTENTION : v${m.version_num} a été RETIRÉE par un retour arrière. Ne la remettez en service que si vous savez pourquoi.`
      : "";
    if (!window.confirm(`Mettre v${m.version_num} en service ? Elle calculera les pronostics dès la prochaine course.${avert}`)) return;
    setDeploiement(m.version_num);
    try {
      await adminApi.deployModel(m.version_num);
      toast.success(`v${m.version_num} en service`);
      mutate();
    } catch {
      toast.error("Le déploiement a échoué");
    } finally {
      setDeploiement(null);
    }
  }

  if (error && !modeles) {
    return <ChargementImpossible quoi="les modèles" error={error} retry={() => mutate()} />;
  }

  const actif = modeles?.find((m) => m.est_actif);
  const visibles = modeles ? (tout ? modeles : modeles.slice(0, 8)) : [];
  const precedente = (m: ModelVersion) => (modeles ? modeles[modeles.indexOf(m) + 1] : undefined);
  const ec = actif?.en_course;
  const holdoutTop3 = actif?.precision_top3 != null ? pct(actif.precision_top3 * 100, 0) : "—";

  const boutonDeployer = (m: ModelVersion) =>
    m.est_actif ? null : m.fichier_disponible ? (
      <Button size="sm" variant="outline" onClick={() => deployer(m)} disabled={deploiement !== null}>
        {deploiement === m.version_num ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Déployer"}
      </Button>
    ) : (
      <span
        className="text-[11px] text-muted-foreground"
        title="Le fichier du modèle a été purgé du serveur : cette version ne peut plus être remise en service."
      >
        fichier purgé
      </span>
    );

  return (
    <div className="space-y-4">
      <Panneau
        titre="Modèle en service"
        desc="La version qui calcule les probabilités servies en ce moment, et ce qu'elle a réellement donné depuis."
        icone={<Brain className="h-3.5 w-3.5" />}
        ton={modeles && !actif ? "alerte" : "neutre"}
      >
        {!modeles ? (
          <Squelette lignes={2} />
        ) : !actif ? (
          <Encart ton="alerte" icone={<AlertTriangle className="h-4 w-4" />}>
            Aucune version marquée en service — les pronostics ne s&apos;appuient sur aucun modèle identifié.
          </Encart>
        ) : (
          <>
            <GrilleTuiles colonnes={4}>
              <Tuile
                label="Version"
                valeur={`v${actif.version_num}`}
                ton="ok"
                sub={
                  <span title={formatDateTime(actif.created_at)}>
                    entraînée {depuis(actif.created_at)}
                    {actif.train_fin && <> · courses apprises jusqu&apos;au {jour(actif.train_fin)}</>}
                  </span>
                }
              />
              <Tuile
                label="Classement vs cote"
                valeur={ecart(actif.rank_delta_market)}
                ton={actif.rank_delta_market == null ? "neutre" : actif.rank_delta_market > 0 ? "ok" : "alerte"}
                sub={<>modèle {fr3(actif.rank_auc)} · cote seule {fr3(actif.market_rank_auc)}</>}
                aide="AUC intra-course sur les courses tenues à l'écart de l'entraînement : chance qu'un partant mieux classé finisse devant un moins bien classé. Comparée au classement par la cote sur les mêmes courses. Positif = le modèle ordonne mieux que le marché."
              />
              <Tuile
                label="Top-3 en course"
                valeur={ec && ec.n_courses > 0 ? pct((ec.top3 ?? 0) * 100, 0) : "—"}
                ton={ec && ec.n_courses > 0 && ec.n_courses < ECHANTILLON_MIN ? "attention" : "neutre"}
                sub={
                  ec && ec.n_courses > 0 ? (
                    <>
                      {num(ec.n_courses)} courses depuis le {jour(ec.debut)}
                      {ec.n_courses < ECHANTILLON_MIN && " — trop peu pour conclure"} · hold-out {holdoutTop3}
                    </>
                  ) : (
                    <>aucune course analysée depuis sa mise en service · hold-out {holdoutTop3}</>
                  )
                }
                aide="Part des courses réellement courues où le gagnant figurait dans les 3 premiers du classement publié AVANT le départ. Le hold-out est la même mesure à l'entraînement."
              />
              <Tuile
                label="Brier en course"
                valeur={ec && ec.n_courses > 0 ? fr3(ec.brier) : "—"}
                ton={ec && ec.n_courses >= ECHANTILLON_MIN && (ec.brier ?? 0) > BRIER_SEUIL ? "alerte" : "neutre"}
                sub={<>hold-out {fr3(actif.brier_score)} · alerte au-delà de {fr3(BRIER_SEUIL)}</>}
                aide="Erreur quadratique des probabilités « dans les 3 premiers », par partant : plus bas = mieux calibré."
              />
            </GrilleTuiles>
            {dashboard?.modele.precision_top3 != null && dashboard.modele.nb_courses_evaluees ? (
              <Note>
                Toutes versions confondues, le gagnant était dans le top-3 publié avant le départ
                sur {pct(dashboard.modele.precision_top3 * 100, 1)} des{" "}
                {num(dashboard.modele.nb_courses_evaluees)} courses analysées.
              </Note>
            ) : null}
          </>
        )}
      </Panneau>

      <Panneau
        titre="Historique des versions"
        desc="Une version par nuit. À lire dans le sens de variation : l'écart à la cote progresse-t-il, et le terrain confirme-t-il l'entraînement ?"
        actions={modeles ? <Puce>{num(modeles.length)} dernières</Puce> : undefined}
      >
        {!modeles ? (
          <Squelette lignes={5} />
        ) : modeles.length === 0 ? (
          <Vide>Aucune version enregistrée.</Vide>
        ) : (
          <>
            <CartesOuTableau
              cartes={visibles.map((m) => (
                <Carte key={m.version_num} ton={m.est_actif ? "ok" : "neutre"}>
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-mono text-sm font-bold">v{m.version_num}</span>
                    <span className="text-xs text-muted-foreground">{jour(m.created_at)}</span>
                    {etatModele(m)}
                  </div>
                  <div className="mt-2 space-y-1 border-t border-border/60 pt-2">
                    <Champ label="Écart à la cote"><EcartCote m={m} prec={precedente(m)} /></Champ>
                    <Champ label="Modèle / cote">{fr3(m.rank_auc)} / {fr3(m.market_rank_auc)}</Champ>
                    <Champ label="Brier hold-out">{fr3(m.brier_score)}</Champ>
                    <Champ label="Courses en service">{num(m.en_course?.n_courses ?? 0)}</Champ>
                    <Champ label="Top-3 en course"><EnCourse m={m} champ="top3" /></Champ>
                    <Champ label="Brier en course"><EnCourse m={m} champ="brier" /></Champ>
                  </div>
                  {!m.est_actif && <div className="mt-2 flex justify-end">{boutonDeployer(m)}</div>}
                </Carte>
              ))}
              tableau={
                <DefilementX label="Historique des versions du modèle">
                  <table className="w-full min-w-[880px] border-collapse">
                    <thead>
                      <tr>
                        <th className={TH} rowSpan={2}>Version</th>
                        <th className={TH} rowSpan={2}>Entraînée</th>
                        <th className={cn(TH, "border-b border-border/60 text-center")} colSpan={4}>
                          Hold-out d&apos;entraînement
                        </th>
                        <th className={cn(TH, "border-b border-border/60 text-center")} colSpan={3}>
                          En service, courses réelles
                        </th>
                        <th className={cn(TH, "text-center")} rowSpan={2}>État</th>
                        <th className={cn(TH, "text-right")} rowSpan={2}>Action</th>
                      </tr>
                      <tr className="border-b border-border">
                        <th className={cn(TH, "text-right")} title="AUC intra-course du modèle">Modèle</th>
                        <th className={cn(TH, "text-right")} title="Même mesure, partants classés par la cote">Cote</th>
                        <th className={cn(TH, "text-right")} title="Modèle − cote. Flèche : sens par rapport à la version précédente">Écart</th>
                        <th className={cn(TH, "text-right")}>Brier</th>
                        <th className={cn(TH, "text-right")}>Courses</th>
                        <th className={cn(TH, "text-right")} title="Gagnant dans le top-3 publié avant le départ">Top-3</th>
                        <th className={cn(TH, "text-right")}>Brier</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibles.map((m) => (
                        <tr
                          key={m.version_num}
                          className={cn(
                            "border-b border-border/40 last:border-0",
                            m.est_actif && "bg-brand-gold-light/60",
                            m.est_rollback && "opacity-70",
                          )}
                        >
                          <td className={cn(TD, "font-mono font-bold")}>v{m.version_num}</td>
                          <td className={cn(TD, "whitespace-nowrap text-muted-foreground")} title={formatDateTime(m.created_at)}>
                            {jour(m.created_at)}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums")}>{fr3(m.rank_auc)}</td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>{fr3(m.market_rank_auc)}</td>
                          <td className={cn(TD, "text-right tabular-nums")}><EcartCote m={m} prec={precedente(m)} /></td>
                          <td className={cn(TD, "text-right tabular-nums", (m.brier_score ?? 0) > BRIER_SEUIL && "text-red-700")}>
                            {fr3(m.brier_score)}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>{num(m.en_course?.n_courses ?? 0)}</td>
                          <td className={cn(TD, "text-right tabular-nums")}><EnCourse m={m} champ="top3" /></td>
                          <td className={cn(TD, "text-right tabular-nums")}><EnCourse m={m} champ="brier" /></td>
                          <td className={cn(TD, "text-center")}>{etatModele(m)}</td>
                          <td className={cn(TD, "text-right")}>{boutonDeployer(m)}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </DefilementX>
              }
            />
            <VoirPlus total={modeles.length} montres={8} tout={tout} onToggle={() => setTout((v) => !v)} />
            <Note>
              Le <strong>hold-out</strong> est mesuré à l&apos;entraînement, sur des courses tenues à
              l&apos;écart. <strong>En service</strong> compte les courses courues pendant que la version
              servait, avec le classement publié avant le départ — rien de recalculé après coup. Sous{" "}
              {ECHANTILLON_MIN} courses, les chiffres en gris ne permettent pas de conclure. Le ROI réel
              des plans de mise est sur la page Algorithme.
            </Note>
          </>
        )}
      </Panneau>
    </div>
  );
}

/* ───────────────────────────── sources ─────────────────────────────────── */

const EN_DEFAUT = ["en_retard", "vide", "erreur", "inconnue"];

function dureeLisible(ms: number | null | undefined): string | null {
  if (ms == null) return null;
  if (ms < 1000) return `${ms} ms`;
  const s = Math.round(ms / 1000);
  if (s < 60) return `${s} s`;
  return `${Math.floor(s / 60)} min ${String(s % 60).padStart(2, "0")} s`;
}

function cadenceLisible(min: number | null): string {
  if (min == null) return "irrégulière";
  return min < 60 ? `attendue toutes les ${min} min au plus` : `attendue toutes les ${min / 60} h au plus`;
}

function IconeStatut({ statut }: { statut: string }) {
  if (statut === "ok") return <CheckCircle2 className="h-4 w-4 shrink-0 text-emerald-600" aria-hidden />;
  if (statut === "au_repos") return <Moon className="h-4 w-4 shrink-0 text-slate-500" aria-hidden />;
  if (statut === "desactivee") return <MinusCircle className="h-4 w-4 shrink-0 text-slate-400" aria-hidden />;
  if (statut === "en_retard" || statut === "vide")
    return <AlertTriangle className="h-4 w-4 shrink-0 text-amber-600" aria-hidden />;
  return <XCircle className="h-4 w-4 shrink-0 text-destructive" aria-hidden />;
}

function CarteSource({ s }: { s: SourceDonnees }) {
  const defaut = EN_DEFAUT.includes(s.statut);
  const duree = dureeLisible(s.duree_ms);
  return (
    <div
      className={cn(
        "rounded-xl border p-3",
        s.statut === "erreur" ? "border-red-200 bg-red-50/40"
          : defaut ? "border-amber-200 bg-amber-50/40"
          : "border-border bg-card",
      )}
    >
      <div className="flex items-start gap-2">
        <span className="mt-0.5"><IconeStatut statut={s.statut} /></span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span className="text-[13px] font-semibold">{s.libelle}</span>
            <span
              className={cn(
                "rounded px-1.5 py-0.5 text-[11px] font-semibold",
                s.statut === "ok" ? "bg-emerald-100 text-emerald-800"
                  : s.statut === "erreur" ? "bg-red-100 text-red-800"
                  : defaut ? "bg-amber-100 text-amber-800"
                  : "bg-muted text-muted-foreground",
              )}
            >
              {STATUT_SOURCE_LABELS[s.statut] ?? s.statut}
            </span>
          </div>
          {s.role && <p className="mt-0.5 text-xs leading-snug text-muted-foreground">{s.role}</p>}
        </div>
      </div>
      <div className="mt-2.5 space-y-1 border-t border-border/60 pt-2 text-xs">
        <div className="flex items-center justify-between gap-2">
          <span className="inline-flex items-center gap-1 text-muted-foreground">
            <Clock className="h-3 w-3" aria-hidden /> {s.type === "cotes" ? "Dernière cote" : "Dernière exécution"}
          </span>
          <span
            className={cn("font-medium tabular-nums", defaut && "text-amber-800")}
            title={s.derniere_maj ? formatDateTime(s.derniere_maj) : undefined}
          >
            {s.derniere_maj ? depuis(s.derniere_maj) : "jamais"}
          </span>
        </div>
        <div className="flex items-center justify-between gap-2">
          <span className="text-muted-foreground">Cadence</span>
          <span className="text-right">{cadenceLisible(s.retard_max_min)}</span>
        </div>
        {s.type === "scraper" ? (
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Sur 24 h</span>
            <span className="text-right tabular-nums">
              {num(s.n_24h)} exécution{s.n_24h > 1 ? "s" : ""}
              {s.n_24h > 0 && <> · {num(s.n_avec_donnees_24h)} avec données</>}
            </span>
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Sur 24 h</span>
            <span className="text-right tabular-nums">
              {num(s.n_24h)} cotes · {num(s.partants_cotes_24h)} partants
            </span>
          </div>
        )}
        {duree && (
          <div className="flex items-center justify-between gap-2">
            <span className="text-muted-foreground">Durée du dernier passage</span>
            <span className="tabular-nums">{duree}</span>
          </div>
        )}
      </div>
      {s.erreur && (
        <p className="mt-2 break-words rounded-lg bg-destructive/5 p-2 text-xs text-destructive">{s.erreur}</p>
      )}
    </div>
  );
}

function OngletSources() {
  const { data: scrapers, error, mutate } = useScrapers();

  if (error && !scrapers) {
    return <ChargementImpossible quoi="l'état des sources" error={error} retry={() => mutate()} />;
  }

  const toutes = Object.values(scrapers ?? {});
  const actives = toutes.filter((s) => s.statut !== "desactivee");
  const coupees = toutes.filter((s) => s.statut === "desactivee");
  const collecte = actives.filter((s) => s.type === "scraper");
  const cotes = actives.filter((s) => s.type === "cotes");
  const enDefaut = actives.filter((s) => EN_DEFAUT.includes(s.statut));
  const auRepos = actives.filter((s) => s.statut === "au_repos").length;
  const ordre = (a: SourceDonnees, b: SourceDonnees) =>
    Number(EN_DEFAUT.includes(b.statut)) - Number(EN_DEFAUT.includes(a.statut));

  return (
    <div className="space-y-4">
      <Panneau
        titre="Sources de données"
        desc="Chaque source est jugée sur sa fraîcheur par rapport à sa cadence attendue, et sur ce qu'elle a réellement ramené en 24 h — pas sur le statut de sa dernière ligne."
        icone={<Radio className="h-3.5 w-3.5" />}
        ton={enDefaut.length > 0 ? "alerte" : "neutre"}
        actions={
          scrapers ? (
            <>
              <Puce ton={enDefaut.length ? "alerte" : "ok"}>
                {actives.length - enDefaut.length - auRepos}/{actives.length} en service
              </Puce>
              {enDefaut.length > 0 && <Puce ton="alerte">{enDefaut.length} en défaut</Puce>}
              {auRepos > 0 && <Puce titre="Aucune course entre H−1 et H+3 : silence normal">{auRepos} au repos</Puce>}
            </>
          ) : undefined
        }
      >
        {!scrapers ? (
          <Squelette lignes={4} />
        ) : actives.length === 0 ? (
          <Vide>Aucune source active.</Vide>
        ) : (
          <div className="space-y-5">
            <section>
              <h3 className="mb-2 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                Collecte (scraper du site)
              </h3>
              <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                {[...collecte].sort(ordre).map((s) => <CarteSource key={s.libelle} s={s} />)}
              </div>
            </section>
            {cotes.length > 0 && (
              <section>
                <h3 className="mb-1 text-xs font-semibold uppercase tracking-[0.06em] text-muted-foreground">
                  Cotes des bookmakers (démons du serveur)
                </h3>
                <p className="mb-2 text-xs text-muted-foreground">
                  Ces collecteurs tournent hors du scraper et ne tiennent pas de journal : leur témoin est
                  la dernière cote qu&apos;ils ont posée en base.
                </p>
                <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
                  {[...cotes].sort(ordre).map((s) => <CarteSource key={s.libelle} s={s} />)}
                </div>
              </section>
            )}
          </div>
        )}
        <Note>
          « Au repos » : aucune course entre H−1 et H+3, le silence est normal. « Tourne à vide » :
          des exécutions réussies qui n&apos;ont rien ramené — traité comme une panne.
        </Note>
      </Panneau>

      {coupees.length > 0 && (
        <Repliable
          id="systeme-sources-coupees"
          titre="Sources désactivées"
          sousTitre="Coupées exprès : leur silence n'est pas une panne."
          resume={<Puce>{coupees.length}</Puce>}
          defaut={false}
        >
          <ul className="divide-y divide-border/60">
            {coupees.map((s) => (
              <li key={s.libelle} className="flex flex-col gap-0.5 py-2.5 sm:flex-row sm:items-baseline sm:gap-3">
                <span className="w-40 shrink-0 text-[13px] font-semibold capitalize">{s.libelle.replace(/_/g, " ")}</span>
                <span className="flex-1 text-xs text-muted-foreground">{s.raison_arret}</span>
                <span
                  className="shrink-0 text-xs text-muted-foreground"
                  title={s.derniere_maj ? formatDateTime(s.derniere_maj) : undefined}
                >
                  dernière trace {s.derniere_maj ? `le ${jour(s.derniere_maj)}` : "—"}
                </span>
              </li>
            ))}
          </ul>
        </Repliable>
      )}
    </div>
  );
}

/* ───────────────────────────── erreurs ─────────────────────────────────── */

/** Une anomalie dont le dernier écho date de moins de deux heures est en cours. */
const ACTIVE_MS = 2 * 3600 * 1000;

function categorie(e: SystemError): { label: string; classe: string } {
  if (e.kind === "scraper" || e.source.startsWith("scraper:"))
    return { label: `Scraper ${e.source.replace(/^scraper:/, "")}`, classe: "bg-amber-500/15 text-amber-800" };
  if (e.source === "data_quality") return { label: "Qualité des données", classe: "bg-sky-500/15 text-sky-800" };
  if (e.source === "api") return { label: "API", classe: "bg-red-500/15 text-red-700" };
  return { label: e.source, classe: "bg-muted text-muted-foreground" };
}

function gravite(level: string): { label: string; classe: string } {
  if (level === "critical") return { label: "critique", classe: "text-red-700" };
  if (level === "warning") return { label: "avertissement", classe: "text-amber-700" };
  return { label: "erreur", classe: "text-red-700" };
}

function LigneErreur({ e, onResolu }: { e: SystemError; onResolu: () => void }) {
  const [enCours, setEnCours] = useState(false);
  const derniere = e.derniere_occurrence ?? e.created_at;
  const active = !e.resolved && derniere != null && Date.now() - new Date(derniere).getTime() < ACTIVE_MS;
  const cat = categorie(e);
  const g = gravite(e.level);
  const n = e.occurrences ?? 1;

  async function resoudre() {
    setEnCours(true);
    try {
      await adminApi.resolveError(e.id!);
      onResolu();
    } catch {
      toast.error("Impossible de marquer l'erreur comme résolue");
    } finally {
      setEnCours(false);
    }
  }

  return (
    <li>
      <details className="group px-4 py-3 sm:px-5">
        <summary className="flex cursor-pointer list-none flex-col gap-1.5">
          <span className="flex flex-wrap items-center gap-1.5">
            <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[11px] font-semibold", cat.classe)}>{cat.label}</span>
            <span className={cn("text-[11px] font-semibold", g.classe)}>{g.label}</span>
            {active && (
              <span className="inline-flex items-center gap-1 rounded bg-red-500/10 px-1.5 py-0.5 text-[11px] font-semibold text-red-700">
                <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-red-500" aria-hidden /> en cours
              </span>
            )}
            {e.resolved && (
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700">
                <CheckCircle2 className="h-3 w-3" /> résolue
              </span>
            )}
            <span
              className="ml-auto shrink-0 text-[11px] text-muted-foreground"
              title={derniere ? formatDateTime(derniere) : undefined}
            >
              {n > 1 ? `${num(n)} fois · dernière ${derniere ? depuis(derniere) : "—"}` : derniere ? depuis(derniere) : "—"}
            </span>
          </span>
          <span className="line-clamp-2 break-words text-[13px] font-medium leading-snug">{e.message}</span>
          {e.endpoint && <span className="block truncate font-mono text-[11px] text-muted-foreground">{e.endpoint}</span>}
        </summary>
        <p className="mt-2 text-[11px] text-muted-foreground">
          {n > 1 && e.created_at
            ? `Apparue le ${formatDateTime(e.created_at)}, revue ${num(n)} fois, dernière le ${formatDateTime(derniere)}.`
            : e.created_at ? `Le ${formatDateTime(e.created_at)}.` : null}
        </p>
        {/* Le résumé coupe à deux lignes : le texte entier se lit ici. */}
        {(e.detail || e.message.length > 160) && (
          <pre className="mt-2 max-h-72 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-2.5 text-[11px] leading-relaxed">
            {e.detail && e.detail !== e.message ? e.detail : e.message}
          </pre>
        )}
        {e.id != null && !e.resolved && (
          <div className="mt-2.5 flex flex-wrap items-center gap-2">
            <Button size="sm" variant="outline" onClick={resoudre} disabled={enCours}>
              {enCours ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : "Marquer résolue"}
            </Button>
            {e.source === "data_quality" && (
              <span className="text-[11px] text-muted-foreground">
                Contrôle horaire : si le problème persiste, il réapparaît à la prochaine vérification.
              </span>
            )}
          </div>
        )}
      </details>
    </li>
  );
}

function OngletErreurs() {
  const { data, error, mutate } = useErreurs();
  const [tout, setTout] = useState(false);

  if (error && !data) {
    return <ChargementImpossible quoi="les erreurs" error={error} retry={() => mutate()} />;
  }

  const erreurs = data?.errors ?? [];
  const ouvertes = erreurs.filter((e) => !e.resolved);
  const resolues = erreurs.filter((e) => e.resolved);
  const visibles = tout ? ouvertes : ouvertes.slice(0, 10);
  const enCours = ouvertes.filter((e) => {
    const d = e.derniere_occurrence ?? e.created_at;
    return d != null && Date.now() - new Date(d).getTime() < ACTIVE_MS;
  }).length;

  return (
    <div className="space-y-4">
      <Panneau
        titre="Erreurs ouvertes"
        desc="Exceptions de l'API, contrôles de qualité des données et scrapers en échec. Une erreur reste ici tant qu'elle n'est pas marquée résolue, quel que soit son âge."
        icone={<ShieldAlert className="h-3.5 w-3.5" />}
        ton={ouvertes.length > 0 ? "alerte" : "ok"}
        actions={
          data ? (
            <>
              <Puce ton={ouvertes.length > 0 ? "alerte" : "ok"}>{ouvertes.length} ouverte{ouvertes.length > 1 ? "s" : ""}</Puce>
              {enCours > 0 && <Puce ton="alerte" titre="Dernière occurrence il y a moins de 2 h">{enCours} en cours</Puce>}
            </>
          ) : undefined
        }
        bodyClassName="p-0 sm:p-0"
      >
        {!data ? (
          <div className="p-4 sm:p-5"><Squelette lignes={4} /></div>
        ) : ouvertes.length === 0 ? (
          <div className="p-4 sm:p-5"><Vide>Aucune erreur ouverte.</Vide></div>
        ) : (
          <>
            <ul className="divide-y divide-border/60">
              {visibles.map((e, i) => <LigneErreur key={e.id ?? `s${i}`} e={e} onResolu={() => mutate()} />)}
            </ul>
            <div className="px-4 pb-4 sm:px-5 sm:pb-5">
              <VoirPlus total={ouvertes.length} montres={10} tout={tout} onToggle={() => setTout((v) => !v)} />
            </div>
          </>
        )}
      </Panneau>

      {resolues.length > 0 && (
        <Repliable
          id="systeme-erreurs-resolues"
          titre="Résolues récemment"
          sousTitre="Marquées résolues, avec une occurrence sur les 72 dernières heures."
          resume={<Puce>{resolues.length}</Puce>}
          defaut={false}
          bodyClassName="p-0 sm:p-0"
        >
          <ul className="divide-y divide-border/60">
            {resolues.map((e, i) => <LigneErreur key={e.id ?? `r${i}`} e={e} onResolu={() => mutate()} />)}
          </ul>
        </Repliable>
      )}
    </div>
  );
}

/* ─────────────────────────── intégrations ──────────────────────────────── */

function OngletIntegrations() {
  return (
    <Panneau
      titre="Intégrations"
      desc="Les services extérieurs dont dépend la plateforme."
    >
      <Link
        href="/admin/instagram"
        className="group flex min-h-[4.5rem] items-start gap-3 rounded-xl border border-border p-3 transition-colors hover:border-brand-gold/40 hover:bg-brand-gold-light/40"
      >
        <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-muted text-muted-foreground transition-colors group-hover:bg-brand-gold/10 group-hover:text-brand-gold-dark">
          <Instagram className="h-4 w-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1 text-[13px] font-semibold">
            Publication Instagram
            <ArrowRight className="h-3.5 w-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5" aria-hidden />
          </span>
          <span className="mt-0.5 block text-xs leading-relaxed text-muted-foreground">
            Dépôt et renouvellement du jeton d&apos;accès Meta. Le jeton expire au bout de
            60 jours et se renouvelle tout seul — cet écran sert à le déposer et à vérifier
            qu&apos;il tient.
          </span>
        </span>
      </Link>
    </Panneau>
  );
}

/* ─────────────────────────────── page ──────────────────────────────────── */

export default function SystemePage() {
  const [onglet, setOnglet] = useState<Onglet>("modeles");
  const { data: erreurs } = useErreurs();
  const { data: scrapers } = useScrapers();
  const [retraining, setRetraining] = useState(false);

  const erreursOuvertes = (erreurs?.errors ?? []).filter((e) => !e.resolved).length;
  const sourcesKo = Object.values(scrapers ?? {}).filter((s) => !scraperSain(s.statut)).length;

  async function lancerRetrain() {
    if (!window.confirm("Lancer un ré-entraînement maintenant ? Il tourne en arrière-plan, comme celui de la nuit, et prend plusieurs dizaines de minutes.")) return;
    setRetraining(true);
    try {
      await adminApi.retrain();
      toast.success("Ré-entraînement lancé en arrière-plan");
    } catch {
      toast.error("Le déclenchement a échoué");
    } finally {
      setRetraining(false);
    }
  }

  return (
    <div className="space-y-4 sm:space-y-5">
      <EnTetePage
        titre="Système"
        icone={<Server className="h-4 w-4" />}
        desc="Modèles entraînés, sources de données, exceptions et services extérieurs."
        actions={
          <Button onClick={lancerRetrain} disabled={retraining} className="h-9 rounded-lg bg-[#1b2230] px-3.5 text-[13px] font-medium text-white hover:bg-[#2c3547]">
            {retraining ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
            Ré-entraîner
          </Button>
        }
      />

      <Segments
        items={ONGLETS.map((o) => ({
          ...o,
          badge: o.key === "erreurs" ? erreursOuvertes : o.key === "sources" ? sourcesKo : undefined,
        }))}
        actif={onglet}
        onChange={setOnglet}
      />

      {onglet === "modeles" && <OngletModeles />}
      {onglet === "sources" && <OngletSources />}
      {onglet === "erreurs" && <OngletErreurs />}
      {onglet === "integrations" && <OngletIntegrations />}
    </div>
  );
}
