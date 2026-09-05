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
 */

import { useState } from "react";
import Link from "next/link";
import { toast } from "sonner";
import {
  AlertTriangle, ArrowRight, Brain, CheckCircle2, Clock, Instagram, Loader2,
  Radio, RefreshCw, Server, ShieldAlert, XCircle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { adminApi } from "@/lib/api";
import { cn, formatDateTime } from "@/lib/utils";
import {
  Carte, CartesOuTableau, Champ, DefilementX, EnTetePage, Encart, GrilleTuiles, Note,
  Panneau, Puce, Segments, Squelette, TD, TH, Tuile, VoirPlus, Vide,
  depuis, num, pct, signedPct,
} from "@/components/admin/ui";
import { useDashboard, useErreurs, useModeles, useScrapers } from "@/components/admin/data";
import { scraperSain, type ModelVersion } from "@/components/admin/types";

const ONGLETS = [
  { key: "modeles", label: "Modèles" },
  { key: "sources", label: "Sources" },
  { key: "erreurs", label: "Erreurs" },
  { key: "integrations", label: "Intégrations" },
] as const;
type Onglet = (typeof ONGLETS)[number]["key"];

/* ───────────────────────────── modèles ─────────────────────────────────── */

function etatModele(m: ModelVersion) {
  if (m.est_actif) return <Badge variant="success" className="text-[11px]">Actif</Badge>;
  if (m.est_rollback) return <Badge variant="warning" className="text-[11px]">Rollback</Badge>;
  return <Badge variant="secondary" className="text-[11px]">Archivé</Badge>;
}

function OngletModeles() {
  const { data: dashboard } = useDashboard();
  const { data: modeles, mutate } = useModeles();
  const [tout, setTout] = useState(false);
  const [deploiement, setDeploiement] = useState<number | null>(null);

  async function deployer(version: number) {
    if (!window.confirm(`Déployer le modèle v${version} ? Il servira les pronostics dès la prochaine course.`)) return;
    setDeploiement(version);
    try {
      await adminApi.deployModel(version);
      toast.success(`Modèle v${version} déployé`);
      mutate();
    } catch {
      toast.error("Le déploiement a échoué");
    } finally {
      setDeploiement(null);
    }
  }

  const actif = modeles?.find((m) => m.est_actif);
  const visibles = modeles ? (tout ? modeles : modeles.slice(0, 6)) : [];

  return (
    <div className="space-y-4">
      <Panneau
        titre="Modèle en service"
        desc="La version qui calcule les probabilités servies en ce moment."
        icone={<Brain className="h-3.5 w-3.5" />}
        ton={dashboard && !dashboard.modele.version ? "alerte" : "neutre"}
      >
        {!dashboard ? (
          <Squelette lignes={2} />
        ) : !dashboard.modele.version ? (
          <Encart ton="alerte" icone={<AlertTriangle className="h-4 w-4" />}>
            Aucun modèle déployé — les pronostics ne s&apos;appuient sur aucune version active.
          </Encart>
        ) : (
          <GrilleTuiles colonnes={4}>
            <Tuile label="Version" valeur={`v${dashboard.modele.version}`} ton="ok" />
            <Tuile
              label="AUC-ROC"
              valeur={dashboard.modele.auc_roc?.toFixed(4) ?? "—"}
              aide="Capacité à classer un gagnant devant un perdant. 0,5 = hasard, 1 = parfait."
            />
            <Tuile
              label="Précision top-3"
              valeur={pct((dashboard.modele.precision_top3 ?? 0) * 100)}
              aide="Part des courses où le gagnant réel figurait dans les 3 premiers du classement prédit."
            />
            <Tuile
              label="Entraîné"
              valeur={<span className="text-base">{depuis(dashboard.modele.trained_at)}</span>}
              sub={dashboard.modele.trained_at ? formatDateTime(dashboard.modele.trained_at) : undefined}
            />
          </GrilleTuiles>
        )}
      </Panneau>

      <Panneau
        titre="Historique des versions"
        desc="Chaque nuit produit une version. La question utile n'est pas la métrique du jour mais son sens de variation."
        actions={
          <>
            <Puce>{num(modeles?.length)} version(s)</Puce>
            {actif && <Puce ton="ok">actif v{actif.version_num}</Puce>}
          </>
        }
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
                    <div className="flex items-center gap-2">
                      {etatModele(m)}
                      {!m.est_actif && (
                        <button
                          onClick={() => deployer(m.version_num)}
                          disabled={deploiement === m.version_num}
                          className="inline-flex min-h-[2.25rem] items-center gap-1.5 rounded-lg border border-border px-3 text-xs font-semibold transition-colors hover:border-brand-gold/50 hover:text-brand-gold-dark disabled:opacity-50"
                        >
                          {deploiement === m.version_num
                            ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            : "Déployer"}
                        </button>
                      )}
                    </div>
                  </div>
                  <div className="mt-2 space-y-1 border-t border-border/60 pt-2">
                    <Champ label="AUC-ROC">{m.auc_roc.toFixed(4)}</Champ>
                    <Champ label="AUC walk-forward">{m.walk_forward_auc?.toFixed(4) ?? "—"}</Champ>
                    <Champ label="Brier">
                      <span className={m.brier_score < 0.18 ? "text-emerald-700" : "text-red-700"}>
                        {m.brier_score.toFixed(4)}
                      </span>
                    </Champ>
                    <Champ label="Top-3">
                      {m.precision_top3 != null ? pct(m.precision_top3 * 100) : "—"}
                    </Champ>
                    <Champ label="ROI simulé">
                      <span className={(m.roi_simule ?? 0) >= 0 ? "text-emerald-700" : "text-red-700"}>
                        {m.roi_simule != null ? signedPct(m.roi_simule * 100) : "—"}
                      </span>
                    </Champ>
                    <Champ label="Partants d'entraînement">{num(m.nb_courses_train)}</Champ>
                  </div>
                </Carte>
              ))}
              tableau={
                <DefilementX label="Historique des versions du modèle">
                  <table className="w-full min-w-[820px] border-collapse">
                    <thead>
                      <tr className="border-b border-border">
                        <th className={TH}>Version</th>
                        <th className={cn(TH, "text-right")}>AUC-ROC</th>
                        <th className={cn(TH, "text-right")}>Brier</th>
                        <th className={cn(TH, "text-right")}>Walk-forward</th>
                        <th className={cn(TH, "text-right")}>Top-3</th>
                        <th className={cn(TH, "text-right")}>ROI simulé</th>
                        <th className={cn(TH, "text-right")} title="Partants d'entraînement (≈ 9,3 par course)">Partants</th>
                        <th className={cn(TH, "text-center")}>État</th>
                        <th className={cn(TH, "text-right")}>Action</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibles.map((m) => (
                        <tr
                          key={m.version_num}
                          className={cn("border-b border-border/40 last:border-0", m.est_actif && "bg-brand-gold-light/60")}
                        >
                          <td className={cn(TD, "font-mono font-bold")}>v{m.version_num}</td>
                          <td className={cn(TD, "text-right tabular-nums")}>{m.auc_roc.toFixed(4)}</td>
                          <td className={cn(TD, "text-right tabular-nums", m.brier_score < 0.18 ? "text-emerald-700" : "text-red-700")}>
                            {m.brier_score.toFixed(4)}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>
                            {m.walk_forward_auc?.toFixed(4) ?? "—"}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums")}>
                            {m.precision_top3 != null ? pct(m.precision_top3 * 100) : "—"}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums", (m.roi_simule ?? 0) >= 0 ? "text-emerald-700" : "text-red-700")}>
                            {m.roi_simule != null ? signedPct(m.roi_simule * 100) : "—"}
                          </td>
                          <td className={cn(TD, "text-right tabular-nums text-muted-foreground")}>{num(m.nb_courses_train)}</td>
                          <td className={cn(TD, "text-center")}>{etatModele(m)}</td>
                          <td className={cn(TD, "text-right")}>
                            {!m.est_actif && (
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => deployer(m.version_num)}
                                disabled={deploiement === m.version_num}
                              >
                                {deploiement === m.version_num
                                  ? <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                  : "Déployer"}
                              </Button>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </DefilementX>
              }
            />
            <VoirPlus total={modeles.length} montres={6} tout={tout} onToggle={() => setTout((v) => !v)} />
            <Note>
              « Partants » compte les lignes d&apos;entraînement, pas les courses : il y en a
              environ 9,3 par course. La colonne porte ce nom depuis la migration 0001.
            </Note>
          </>
        )}
      </Panneau>
    </div>
  );
}

/* ───────────────────────────── sources ─────────────────────────────────── */

function OngletSources() {
  const { data: scrapers } = useScrapers();
  const sources = Object.entries(scrapers ?? {});
  const ok = sources.filter(([, s]) => scraperSain(s.statut)).length;

  return (
    <Panneau
      titre="Sources de données"
      desc="Statut et fraîcheur par scraper. Une source qui répond mais ne ramène rien reste en échec — c'est le cas trompeur du projet."
      icone={<Radio className="h-3.5 w-3.5" />}
      ton={sources.length > 0 && ok < sources.length ? "alerte" : "neutre"}
      actions={
        sources.length > 0 ? (
          <>
            <Puce ton={ok === sources.length ? "ok" : "alerte"}>{ok}/{sources.length} en service</Puce>
            {ok < sources.length && <Puce ton="alerte">{sources.length - ok} en échec</Puce>}
          </>
        ) : undefined
      }
    >
      {!scrapers ? (
        <Squelette lignes={4} />
      ) : sources.length === 0 ? (
        <Vide>Aucune source déclarée.</Vide>
      ) : (
        <div className="grid gap-2.5 sm:grid-cols-2 xl:grid-cols-3">
          {sources.map(([source, s]) => {
            const sain = scraperSain(s.statut);
            return (
              <div
                key={source}
                className={cn(
                  "rounded-xl border p-3",
                  sain ? "border-border bg-card" : "border-red-200 bg-red-50/40",
                )}
              >
                <div className="flex items-center gap-2">
                  {sain ? (
                    <CheckCircle2 className={cn("h-4 w-4 shrink-0", s.statut === "ok" ? "text-emerald-600" : "text-amber-600")} aria-hidden />
                  ) : (
                    <XCircle className="h-4 w-4 shrink-0 text-destructive" aria-hidden />
                  )}
                  <span className="truncate text-[13px] font-semibold capitalize">{source}</span>
                  {s.duree_ms != null && (
                    <span className="ml-auto shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground">
                      {s.duree_ms} ms
                    </span>
                  )}
                </div>
                <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1" title={s.derniere_maj ? formatDateTime(s.derniere_maj) : undefined}>
                    <Clock className="h-3 w-3" aria-hidden />
                    {s.derniere_maj ? depuis(s.derniere_maj) : "jamais"}
                  </span>
                  {!sain && <span className="font-semibold text-destructive">{s.statut}</span>}
                  {sain && s.statut !== "ok" && (
                    <span className="rounded bg-amber-100 px-1.5 py-0.5 text-[11px] font-semibold text-amber-800">
                      {s.statut}
                    </span>
                  )}
                </div>
                {s.erreur && (
                  <p className="mt-2 break-words rounded-lg bg-destructive/5 p-2 text-xs text-destructive">{s.erreur}</p>
                )}
              </div>
            );
          })}
        </div>
      )}
      <Note>
        « ok_avec_échecs » reste sain : des échecs comptés sous le seuil d&apos;anomalie. En
        revanche « ok_but_empty » — que des succès, aucune donnée — est traité comme une panne.
      </Note>
    </Panneau>
  );
}

/* ───────────────────────────── erreurs ─────────────────────────────────── */

function OngletErreurs() {
  const { data, mutate } = useErreurs();
  const [tout, setTout] = useState(false);
  const erreurs = data?.errors ?? [];
  const ouvertes = erreurs.filter((e) => !e.resolved).length;
  const visibles = tout ? erreurs : erreurs.slice(0, 10);

  return (
    <Panneau
      titre="Erreurs récentes"
      desc="Exceptions de l'API et scrapers échoués sur 72 h. Une anomalie qui dure est UNE ligne qui se répète, pas N lignes."
      icone={<ShieldAlert className="h-3.5 w-3.5" />}
      ton={ouvertes > 0 ? "alerte" : "ok"}
      actions={
        <>
          <Puce ton={ouvertes > 0 ? "alerte" : "ok"}>{ouvertes} ouverte(s)</Puce>
          <Puce>{erreurs.length} sur 72 h</Puce>
        </>
      }
      bodyClassName="p-0 sm:p-0"
    >
      {!data ? (
        <div className="p-4 sm:p-5"><Squelette lignes={4} /></div>
      ) : erreurs.length === 0 ? (
        <div className="p-4 sm:p-5">
          <Vide>Aucune erreur sur les 72 dernières heures.</Vide>
        </div>
      ) : (
        <>
          <ul className="divide-y divide-border/60">
            {visibles.map((e, i) => (
              <li key={e.id ?? `s${i}`}>
                <details className="group px-4 py-3 sm:px-5">
                  <summary className="flex cursor-pointer list-none flex-col gap-1.5">
                    <span className="flex flex-wrap items-center gap-1.5">
                      <span
                        className={cn(
                          "shrink-0 rounded px-1.5 py-0.5 font-mono text-[11px] font-semibold",
                          e.kind === "scraper" ? "bg-amber-500/15 text-amber-800" : "bg-red-500/15 text-red-700",
                        )}
                      >
                        {e.source}
                      </span>
                      {(e.occurrences ?? 1) > 1 && (
                        <span className="shrink-0 rounded bg-orange-500/15 px-1.5 py-0.5 font-mono text-[11px] font-semibold text-orange-800">
                          ×{e.occurrences}
                        </span>
                      )}
                      {e.resolved && (
                        <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-700">
                          <CheckCircle2 className="h-3 w-3" /> résolu
                        </span>
                      )}
                      {/* L'horodatage de tête est le RÉCENT : c'est lui qui dit
                          si le problème est encore actif. */}
                      <span className="ml-auto shrink-0 font-mono text-[11px] text-muted-foreground">
                        {(e.derniere_occurrence ?? e.created_at)
                          ? depuis((e.derniere_occurrence ?? e.created_at)!)
                          : "—"}
                      </span>
                    </span>
                    <span className="block break-words text-[13px] font-medium leading-snug">{e.message}</span>
                    {e.endpoint && (
                      <span className="block truncate font-mono text-[11px] text-muted-foreground">{e.endpoint}</span>
                    )}
                  </summary>
                  {e.created_at && (
                    <p className="mt-2 font-mono text-[11px] text-muted-foreground">
                      {(e.occurrences ?? 1) > 1
                        ? `première occurrence le ${formatDateTime(e.created_at)}`
                        : formatDateTime(e.created_at)}
                    </p>
                  )}
                  {e.detail && (
                    <pre className="mt-2 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded-lg bg-muted/50 p-2.5 text-[11px] leading-relaxed">
                      {e.detail}
                    </pre>
                  )}
                  {e.kind === "api" && e.id != null && !e.resolved && (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-2.5"
                      onClick={async () => { await adminApi.resolveError(e.id!); mutate(); }}
                    >
                      Marquer résolu
                    </Button>
                  )}
                </details>
              </li>
            ))}
          </ul>
          <div className="px-4 pb-4 sm:px-5 sm:pb-5">
            <VoirPlus total={erreurs.length} montres={10} tout={tout} onToggle={() => setTout((v) => !v)} />
          </div>
        </>
      )}
    </Panneau>
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
          <Button variant="brand" onClick={lancerRetrain} disabled={retraining} className="min-h-[2.75rem]">
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
