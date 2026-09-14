"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import useSWR, { useSWRConfig } from "swr";
import { toast } from "sonner";
import { format, isToday, isYesterday, parseISO } from "date-fns";
import { fr } from "date-fns/locale";
import {
  MessagesSquare, SendHorizontal, Flag, Trash2, Ban, ShieldCheck, Loader2, RefreshCw,
  ArrowDown, Check, X, Sparkles, Pencil, UserPlus,
} from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/hooks/useAuth";
import { useWebSocket } from "@/hooks/useWebSocket";
import { chatApi, marquerChatLuAuDepart, type ChatMessage, type ChatMoi } from "@/lib/api";
import { cn } from "@/lib/utils";

const LONGUEUR_MAX = 500;

type ChatEvent =
  | { type: "message"; message: ChatMessage }
  | { type: "suppression"; message_ids: string[] }
  | { type: "presents"; n: number }
  | { type: "banni" };

/** Message d'erreur lisible renvoyé par l'API (`detail`), sinon un repli générique. */
function detailErreur(err: unknown, repli: string): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } })?.response?.data?.detail;
  return typeof detail === "string" ? detail : repli;
}

function statut(err: unknown): number | undefined {
  return (err as { response?: { status?: number } })?.response?.status;
}

// ─── Petits éléments ─────────────────────────────────────────
const AVATAR_TEINTES = [
  "from-amber-400 to-orange-500",
  "from-emerald-400 to-teal-600",
  "from-sky-400 to-blue-600",
  "from-rose-400 to-pink-600",
  "from-violet-400 to-purple-600",
  "from-lime-500 to-green-600",
  "from-slate-500 to-slate-700",
];

function Avatar({ pseudo, userId, taille = "md" }: { pseudo: string; userId: string; taille?: "md" | "lg" }) {
  let h = 0;
  for (let i = 0; i < userId.length; i++) h = (h * 31 + userId.charCodeAt(i)) >>> 0;
  return (
    <div
      aria-hidden
      className={cn(
        "shrink-0 rounded-full bg-gradient-to-br text-white font-semibold uppercase flex items-center justify-center shadow-sm ring-2 ring-white",
        taille === "lg" ? "h-12 w-12 text-lg" : "h-9 w-9 text-sm",
        AVATAR_TEINTES[h % AVATAR_TEINTES.length],
      )}
    >
      {pseudo.slice(0, 1) || "?"}
    </div>
  );
}

function BadgeRole({ role }: { role: ChatMessage["auteur"]["role"] }) {
  if (role === "admin") {
    return (
      <span className="inline-flex items-center gap-0.5 rounded-full bg-gray-900 px-1.5 py-px text-[10px] font-semibold leading-4 text-white">
        <ShieldCheck className="h-2.5 w-2.5" /> Équipe
      </span>
    );
  }
  if (role === "abonne") {
    return (
      <span className="rounded-full bg-gradient-gold-soft px-1.5 py-px text-[10px] font-semibold leading-4 text-amber-900">
        Abonné
      </span>
    );
  }
  return null;
}

function libelleJour(iso: string): string {
  const d = parseISO(iso);
  if (isToday(d)) return "Aujourd'hui";
  if (isYesterday(d)) return "Hier";
  const s = format(d, "EEEE d MMMM", { locale: fr });
  return s.charAt(0).toUpperCase() + s.slice(1);
}

function Carte({ children, className }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={cn("rounded-3xl border border-gray-200/80 bg-white shadow-[0_8px_30px_rgba(17,24,39,0.06)]", className)}>
      {children}
    </div>
  );
}

function TuileIcone({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-2xl bg-gradient-gold text-white shadow-md shadow-amber-600/20">
      {children}
    </div>
  );
}

// ─── Choix du pseudo ─────────────────────────────────────────
const REGLES = [
  "Partagez vos gains, vos tuyaux et vos analyses",
  "Entraide et respect entre turfistes",
  "Pas de publicité ni de pronostics payants — les messages signalés sont relus par l'équipe",
];

/** Raccourcis d'amorce : donnent le ton du salon (entraide) et le rendent lisible. */
const SUJETS = [
  { label: "Mon gain", prefixe: "🏆 Gain : " },
  { label: "Un tuyau", prefixe: "💡 Tuyau : " },
  { label: "Une question", prefixe: "❓ Question : " },
];

function ChoixPseudo({ userId, onChoisi }: { userId: string; onChoisi: () => void }) {
  const [pseudo, setPseudo] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);
  const apercu = pseudo.trim() || "Votre pseudo";

  const valider = async (e: React.FormEvent) => {
    e.preventDefault();
    setEnvoi(true);
    setErreur(null);
    try {
      await chatApi.choisirPseudo(pseudo.trim());
      onChoisi();
    } catch (err) {
      setErreur(detailErreur(err, "Impossible d'enregistrer ce pseudo."));
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <div className="mx-auto max-w-lg px-4 py-10 sm:py-16">
      <Carte className="overflow-hidden">
        <div className="bg-gradient-to-br from-amber-50 via-white to-white px-6 pb-5 pt-6 sm:px-8">
          <TuileIcone><MessagesSquare className="h-5 w-5" /></TuileIcone>
          <h1 className="mt-4 text-2xl font-bold tracking-tight text-gray-900">Rejoindre la communauté</h1>
          <p className="mt-1.5 text-sm leading-relaxed text-gray-600">
            Le salon d&apos;entraide des turfistes BlackTurf : gains, tuyaux, courses à suivre, questions
            sur le site. Choisissez le pseudo sous lequel vous apparaîtrez — votre nom et votre e-mail
            ne sont jamais affichés.
          </p>
        </div>

        <form onSubmit={valider} className="space-y-4 px-6 pb-6 sm:px-8">
          <div>
            <label htmlFor="pseudo" className="mb-1.5 block text-sm font-medium text-gray-900">Pseudo</label>
            <input
              id="pseudo"
              value={pseudo}
              onChange={(e) => { setPseudo(e.target.value); setErreur(null); }}
              maxLength={20}
              autoComplete="off"
              autoFocus
              placeholder="ex. Turfiste_75"
              aria-invalid={!!erreur}
              aria-describedby="pseudo-aide"
              className={cn(
                "w-full rounded-xl border bg-white px-3.5 py-2.5 text-sm text-gray-900 outline-none transition placeholder:text-gray-400",
                "focus:border-brand-gold focus:ring-4 focus:ring-brand-gold/15",
                erreur ? "border-red-300" : "border-gray-300",
              )}
            />
            <p id="pseudo-aide" className="mt-1.5 text-xs text-gray-600">
              3 à 20 caractères : lettres, chiffres, point, tiret ou soulignement.
            </p>
            {erreur && <p role="alert" className="mt-1.5 text-sm font-medium text-red-700">{erreur}</p>}
          </div>

          {/* Aperçu : ce que les autres verront */}
          <div className="flex items-center gap-3 rounded-2xl border border-dashed border-gray-200 bg-gray-50/70 p-3">
            <Avatar pseudo={apercu} userId={userId} />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-gray-900">{apercu}</div>
              <div className="text-xs text-gray-600">Aperçu de votre profil dans le salon</div>
            </div>
          </div>

          <ul className="space-y-1.5">
            {REGLES.map((r) => (
              <li key={r} className="flex items-center gap-2 text-sm text-gray-700">
                <span className="flex h-4 w-4 items-center justify-center rounded-full bg-emerald-100">
                  <Check className="h-3 w-3 text-emerald-700" />
                </span>
                {r}
              </li>
            ))}
          </ul>

          <button
            type="submit"
            disabled={envoi || pseudo.trim().length < 3}
            className="btn-shimmer inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-gold px-4 py-2.5 text-sm font-semibold text-brand-dark shadow-sm shadow-brand-gold/25 ring-1 ring-brand-gold/30 transition hover:bg-brand-gold-deep active:scale-[0.99] disabled:cursor-not-allowed disabled:opacity-50"
          >
            {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <Sparkles className="h-4 w-4" />}
            {envoi ? "Enregistrement…" : "Entrer dans le salon"}
          </button>
        </form>
      </Carte>
    </div>
  );
}

// ─── Modération (admin) ──────────────────────────────────────
function PanneauModeration({
  onSupprimer, onBannir, onFermer,
}: {
  onSupprimer: (id: string) => Promise<void>;
  onBannir: (userId: string, pseudo: string) => Promise<void>;
  onFermer: () => void;
}) {
  const { data: sig, mutate: mutateSig } = useSWR("chat-signalements", () =>
    chatApi.signalements().then((r) => r.data.signalements), { refreshInterval: 30_000 });
  const { data: bannis, mutate: mutateBannis } = useSWR("chat-bannis", () =>
    chatApi.bannis().then((r) => r.data.bannis));

  const classer = async (id: string) => {
    try {
      await chatApi.classerSignalement(id);
      mutateSig();
    } catch (err) {
      toast.error(detailErreur(err, "Impossible de classer ce signalement."));
    }
  };

  const lever = async (userId: string) => {
    try {
      await chatApi.bannir(userId, false);
      mutateBannis();
      toast.success("Bannissement levé");
    } catch (err) {
      toast.error(detailErreur(err, "Impossible de lever le bannissement."));
    }
  };

  const bouton = "inline-flex h-8 items-center gap-1.5 rounded-lg border px-2.5 text-xs font-medium transition";

  return (
    <div className="max-h-[45vh] overflow-y-auto border-b border-gray-200 bg-gray-50/80 px-4 py-4 sm:px-5">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
          <ShieldCheck className="h-4 w-4 text-brand-gold-dark" /> Modération
        </h2>
        <button onClick={onFermer} aria-label="Fermer la modération" className="rounded-lg p-1 text-gray-600 hover:bg-gray-200/60">
          <X className="h-4 w-4" />
        </button>
      </div>

      <section>
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-600">
          Signalements en attente · {sig?.length ?? "…"}
        </h3>
        {sig?.length === 0 && (
          <p className="mt-2 rounded-xl border border-dashed border-gray-200 bg-white px-3 py-3 text-sm text-gray-600">
            Rien à relire, le salon est serein.
          </p>
        )}
        <ul className="mt-2 space-y-2">
          {sig?.map((s) => (
            <li key={s.signalement_id} className="rounded-2xl border border-gray-200 bg-white p-3.5 shadow-sm">
              <div className="flex items-center gap-2">
                <Avatar pseudo={s.message.auteur.pseudo} userId={s.message.auteur.user_id} />
                <div className="min-w-0 text-xs text-gray-600">
                  <div className="font-semibold text-gray-900">{s.message.auteur.pseudo}</div>
                  Signalé par {s.signale_par}{s.motif ? ` · « ${s.motif} »` : ""}
                </div>
              </div>
              <p className="mt-2 whitespace-pre-wrap break-words rounded-xl bg-gray-50 px-3 py-2 text-sm text-gray-900">
                {s.message.contenu}
              </p>
              <div className="mt-2.5 flex flex-wrap gap-2">
                <button className={cn(bouton, "border-gray-200 bg-white text-gray-700 hover:bg-gray-50")}
                  onClick={async () => { await onSupprimer(s.message.message_id); mutateSig(); }}>
                  <Trash2 className="h-3.5 w-3.5" /> Supprimer le message
                </button>
                {!s.auteur_banni && (
                  <button className={cn(bouton, "border-red-200 bg-red-50 text-red-700 hover:bg-red-100")}
                    onClick={async () => {
                      await onBannir(s.message.auteur.user_id, s.message.auteur.pseudo);
                      mutateSig(); mutateBannis();
                    }}>
                    <Ban className="h-3.5 w-3.5" /> Bannir l&apos;auteur
                  </button>
                )}
                <button className={cn(bouton, "border-transparent text-gray-600 hover:bg-gray-100")}
                  onClick={() => classer(s.signalement_id)}>
                  Classer sans suite
                </button>
              </div>
            </li>
          ))}
        </ul>
      </section>

      <section className="mt-5">
        <h3 className="text-[11px] font-semibold uppercase tracking-wider text-gray-600">
          Membres bannis · {bannis?.length ?? "…"}
        </h3>
        {bannis?.length === 0 && <p className="mt-2 text-sm text-gray-600">Aucun.</p>}
        <ul className="mt-2 divide-y divide-gray-100 rounded-2xl border border-gray-200 bg-white">
          {bannis?.map((b) => (
            <li key={b.user_id} className="flex items-center justify-between gap-3 px-3 py-2 text-sm">
              <span className="min-w-0 truncate">
                <strong className="text-gray-900">{b.pseudo ?? "—"}</strong>{" "}
                <span className="text-gray-600">{b.email}</span>
              </span>
              <button className={cn(bouton, "shrink-0 border-gray-200 text-gray-700 hover:bg-gray-50")}
                onClick={() => lever(b.user_id)}>
                Lever
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}

// ─── Modifier son pseudo ─────────────────────────────────────
function ModalPseudo({
  actuel, userId, onFermer, onEnregistre,
}: {
  actuel: string;
  userId: string;
  onFermer: () => void;
  onEnregistre: (pseudo: string) => void;
}) {
  const [pseudo, setPseudo] = useState(actuel);
  const [envoi, setEnvoi] = useState(false);
  const [erreur, setErreur] = useState<string | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onFermer(); };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onFermer]);

  const valider = async (e: React.FormEvent) => {
    e.preventDefault();
    const nouveau = pseudo.trim();
    if (nouveau === actuel) return onFermer();
    setEnvoi(true);
    setErreur(null);
    try {
      const r = await chatApi.choisirPseudo(nouveau);
      toast.success(`Vous apparaissez désormais sous le nom ${r.data.pseudo}`);
      onEnregistre(r.data.pseudo);
    } catch (err) {
      setErreur(detailErreur(err, "Impossible d'enregistrer ce pseudo."));
    } finally {
      setEnvoi(false);
    }
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-gray-900/40 p-4 backdrop-blur-sm" onClick={onFermer}>
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby="titre-pseudo"
        onClick={(e) => e.stopPropagation()}
        className="w-full max-w-sm rounded-3xl border border-gray-200 bg-white p-6 shadow-2xl"
      >
        <div className="flex items-start justify-between gap-3">
          <h2 id="titre-pseudo" className="text-lg font-bold text-gray-900">Modifier mon pseudo</h2>
          <button onClick={onFermer} aria-label="Fermer" className="rounded-lg p-1 text-gray-600 hover:bg-gray-100">
            <X className="h-4 w-4" />
          </button>
        </div>
        <form onSubmit={valider} className="mt-4 space-y-3">
          <div className="flex items-center gap-3 rounded-2xl bg-gray-50 p-3">
            <Avatar pseudo={pseudo.trim() || "?"} userId={userId} />
            <div className="min-w-0">
              <div className="truncate text-sm font-semibold text-gray-900">{pseudo.trim() || "Votre pseudo"}</div>
              <div className="text-xs text-gray-600">Visible par tous les membres</div>
            </div>
          </div>
          <label htmlFor="nouveau-pseudo" className="sr-only">Nouveau pseudo</label>
          <input
            id="nouveau-pseudo"
            value={pseudo}
            onChange={(e) => { setPseudo(e.target.value); setErreur(null); }}
            maxLength={20}
            autoComplete="off"
            autoFocus
            aria-invalid={!!erreur}
            className={cn(
              "w-full rounded-xl border bg-white px-3.5 py-2.5 text-sm text-gray-900 outline-none transition",
              "focus:border-brand-gold focus:ring-4 focus:ring-brand-gold/15",
              erreur ? "border-red-300" : "border-gray-300",
            )}
          />
          <p className="text-xs text-gray-600">3 à 20 caractères : lettres, chiffres, point, tiret ou soulignement.</p>
          {erreur && <p role="alert" className="text-sm font-medium text-red-700">{erreur}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onFermer}
              className="rounded-xl px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-100">
              Annuler
            </button>
            <button type="submit" disabled={envoi || pseudo.trim().length < 3}
              className="inline-flex items-center gap-1.5 rounded-xl bg-brand-gold px-4 py-2 text-sm font-semibold text-brand-dark shadow-sm ring-1 ring-brand-gold/30 transition hover:bg-brand-gold-deep disabled:cursor-not-allowed disabled:opacity-50">
              {envoi && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Enregistrer
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ─── Salon ───────────────────────────────────────────────────
function Squelette() {
  return (
    <div className="space-y-5 py-2" aria-hidden>
      {[60, 40, 72, 50].map((w, i) => (
        <div key={i} className={cn("flex gap-2.5", i % 3 === 2 && "flex-row-reverse")}>
          <div className="h-9 w-9 animate-pulse rounded-full bg-gray-200" />
          <div className="space-y-1.5" style={{ width: `${w}%` }}>
            <div className="h-3 w-24 animate-pulse rounded bg-gray-200" />
            <div className="h-10 animate-pulse rounded-2xl bg-gray-200/80" />
          </div>
        </div>
      ))}
    </div>
  );
}

function Salon({ moi, onBanni, onPseudoModifie }: {
  moi: ChatMoi;
  onBanni: () => void;
  onPseudoModifie: (pseudo: string) => void;
}) {
  const [editionPseudo, setEditionPseudo] = useState(false);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [plusAnciens, setPlusAnciens] = useState(false);
  const [chargement, setChargement] = useState(true);
  const [chargementAnciens, setChargementAnciens] = useState(false);
  const [erreur, setErreur] = useState(false);
  const [presents, setPresents] = useState<number | null>(null);
  const [texte, setTexte] = useState("");
  const [envoi, setEnvoi] = useState(false);
  const [moderation, setModeration] = useState(false);
  const [nonLus, setNonLus] = useState(0);
  const [actif, setActif] = useState<string | null>(null);

  const listeRef = useRef<HTMLDivElement>(null);
  const saisieRef = useRef<HTMLTextAreaElement>(null);
  const collerEnBas = useRef(true);
  const hauteurAvant = useRef<number | null>(null);
  const premierChargement = useRef(true);

  const { data: signalements } = useSWR(moi.is_admin ? "chat-signalements" : null, () =>
    chatApi.signalements().then((r) => r.data.signalements), { refreshInterval: 30_000 });
  const nbSignalements = signalements?.length ?? 0;

  // Identifiants déjà reçus : un même message peut arriver deux fois (réponse du
  // POST + diffusion, rechargement après reconnexion). Il ne doit compter qu'une fois.
  const connus = useRef(new Set<string>());

  const fusionner = useCallback((nouveaux: ChatMessage[]) => {
    for (const m of nouveaux) connus.current.add(m.message_id);
    setMessages((prev) => {
      const parId = new Map(prev.map((m) => [m.message_id, m]));
      for (const m of nouveaux) parId.set(m.message_id, m);
      return [...parId.values()].sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at));
    });
  }, []);

  // Historique récent. Rappelé à chaque (re)connexion du flux : ce qui a été écrit
  // pendant une coupure réseau n'est jamais arrivé par la socket.
  const chargerRecents = useCallback(async () => {
    try {
      const r = await chatApi.messages();
      fusionner(r.data.messages);
      if (premierChargement.current) {
        setPlusAnciens(r.data.plus_anciens);
        premierChargement.current = false;
      }
      setErreur(false);
    } catch (err) {
      if (statut(err) === 403) onBanni();
      else setErreur(true);
    } finally {
      setChargement(false);
    }
  }, [fusionner, onBanni]);

  useEffect(() => { chargerRecents(); }, [chargerRecents]);

  // Lecture du salon → la bulle « non lus » de la barre de navigation retombe à zéro.
  // Regroupé (1 s) pour qu'une rafale de messages ne produise qu'un appel, et
  // seulement onglet visible : un salon ouvert en arrière-plan n'a rien été lu.
  const { mutate: mutateGlobal } = useSWRConfig();
  const minuterieLu = useRef<ReturnType<typeof setTimeout> | null>(null);
  const envoyerLu = useCallback(() => {
    chatApi.marquerLu()
      .then(() => mutateGlobal("chat-non-lus", { non_lus: 0 }, { revalidate: false }))
      .catch(() => {});
  }, [mutateGlobal]);
  const marquerLu = useCallback(() => {
    if (minuterieLu.current) clearTimeout(minuterieLu.current);
    minuterieLu.current = setTimeout(() => {
      minuterieLu.current = null;
      if (document.visibilityState === "visible") envoyerLu();
    }, 1000);
  }, [envoyerLu]);
  useEffect(() => {
    // Ouvrir le salon, c'est l'avoir lu : marquage immédiat. Une temporisation ici se
    // perdait si l'on repartait vite (constaté en recette : bulle restée à 4).
    if (document.visibilityState === "visible") envoyerLu();
    const onVisible = () => { if (document.visibilityState === "visible") marquerLu(); };
    const onPageHide = () => {
      if (!minuterieLu.current) return;
      clearTimeout(minuterieLu.current);
      minuterieLu.current = null;
      marquerChatLuAuDepart();
    };
    document.addEventListener("visibilitychange", onVisible);
    window.addEventListener("pagehide", onPageHide);
    return () => {
      document.removeEventListener("visibilitychange", onVisible);
      window.removeEventListener("pagehide", onPageHide);
      // Quitter le salon avec un marquage en attente : l'envoyer tout de suite, sinon
      // le dernier message lu réapparaîtrait comme non lu.
      if (minuterieLu.current) {
        clearTimeout(minuterieLu.current);
        minuterieLu.current = null;
        if (document.visibilityState === "visible") envoyerLu();
      }
    };
  }, [marquerLu, envoyerLu]);

  const onEvent = useCallback((data: unknown) => {
    const e = data as ChatEvent;
    if (e.type === "message") {
      const inedit = !connus.current.has(e.message.message_id);
      fusionner([e.message]);
      if (inedit && e.message.auteur.user_id !== moi.user_id && !collerEnBas.current) setNonLus((n) => n + 1);
      if (inedit) marquerLu();
    } else if (e.type === "suppression") {
      setMessages((prev) => prev.filter((m) => !e.message_ids.includes(m.message_id)));
    } else if (e.type === "presents") {
      setPresents(e.n);
    } else if (e.type === "banni") {
      onBanni();
    }
  }, [fusionner, onBanni, moi.user_id, marquerLu]);

  const dejaOuvert = useRef(false);
  const onOpen = useCallback(() => {
    // La première ouverture coïncide avec le chargement initial : inutile de doubler.
    if (dejaOuvert.current) chargerRecents();
    dejaOuvert.current = true;
  }, [chargerRecents]);

  const { connected, closeCode, reconnect } = useWebSocket("/chat", true, { onMessage: onEvent, onOpen });
  useEffect(() => { if (closeCode === 4403) onBanni(); }, [closeCode, onBanni]);

  // Défilement : on reste collé en bas tant que le membre y est ; charger des
  // messages plus anciens conserve la position de lecture.
  useLayoutEffect(() => {
    const el = listeRef.current;
    if (!el) return;
    if (hauteurAvant.current !== null) {
      el.scrollTop += el.scrollHeight - hauteurAvant.current;
      hauteurAvant.current = null;
    } else if (collerEnBas.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages, chargement]);

  // Zone de saisie qui grandit avec le texte (4 lignes environ, puis défilement).
  useLayoutEffect(() => {
    const ta = saisieRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 132)}px`;
  }, [texte]);

  const onScroll = () => {
    const el = listeRef.current;
    if (!el) return;
    collerEnBas.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    if (collerEnBas.current) setNonLus(0);
  };

  const allerEnBas = () => {
    const el = listeRef.current;
    if (el) el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    setNonLus(0);
  };

  const chargerAnciens = async () => {
    if (!messages.length) return;
    setChargementAnciens(true);
    try {
      const r = await chatApi.messages(messages[0].created_at);
      hauteurAvant.current = listeRef.current?.scrollHeight ?? null;
      fusionner(r.data.messages);
      setPlusAnciens(r.data.plus_anciens);
    } catch (err) {
      toast.error(detailErreur(err, "Impossible de charger les messages précédents."));
    } finally {
      setChargementAnciens(false);
    }
  };

  const envoyer = async () => {
    const contenu = texte.trim();
    if (!contenu || envoi || contenu.length > LONGUEUR_MAX) return;
    setEnvoi(true);
    try {
      const r = await chatApi.envoyer(contenu);
      collerEnBas.current = true;
      fusionner([r.data]);
      setTexte("");
    } catch (err) {
      if (statut(err) === 403 && moi.email_confirme) onBanni();
      else toast.error(detailErreur(err, "Message non envoyé, réessayez."));
    } finally {
      setEnvoi(false);
      saisieRef.current?.focus();
    }
  };

  const supprimer = useCallback(async (id: string) => {
    try {
      await chatApi.supprimer(id);
      setMessages((prev) => prev.filter((m) => m.message_id !== id));
    } catch (err) {
      toast.error(detailErreur(err, "Suppression impossible."));
    }
  }, []);

  const signaler = async (m: ChatMessage) => {
    if (!window.confirm(`Signaler ce message de ${m.auteur.pseudo} à l'équipe ?`)) return;
    try {
      await chatApi.signaler(m.message_id);
      toast.success("Merci, le message sera relu par l'équipe.");
    } catch (err) {
      toast.error(detailErreur(err, "Signalement impossible."));
    }
  };

  const bannir = useCallback(async (userId: string, pseudo: string) => {
    if (!window.confirm(`Bannir ${pseudo} du salon ? Son compte et son abonnement ne sont pas touchés.`)) return;
    const effacer = window.confirm(`Effacer aussi tous les messages de ${pseudo} ?`);
    try {
      await chatApi.bannir(userId, true, effacer);
      toast.success(`${pseudo} est banni du salon`);
    } catch (err) {
      toast.error(detailErreur(err, "Bannissement impossible."));
    }
  }, []);

  const trop = texte.length > LONGUEUR_MAX;
  const actionIcone = "flex h-7 w-7 items-center justify-center rounded-full text-gray-600 transition hover:bg-gray-100";

  return (
    <div className="mx-auto flex h-[calc(100dvh-4rem-56px)] max-w-4xl flex-col md:h-[calc(100dvh-4rem)] md:px-6 md:py-6">
      <Carte className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-none border-x-0 border-t-0 shadow-none md:rounded-3xl md:border md:shadow-[0_8px_30px_rgba(17,24,39,0.06)]">

        {/* En-tête */}
        <div className="flex items-center justify-between gap-3 border-b border-gray-100 bg-gradient-to-r from-amber-50/70 via-white to-white px-4 py-3.5 sm:px-5">
          <div className="flex min-w-0 items-center gap-3">
            <TuileIcone><MessagesSquare className="h-5 w-5" /></TuileIcone>
            <div className="min-w-0">
              <h1 className="text-base font-bold leading-tight tracking-tight text-gray-900 sm:text-lg">Communauté</h1>
              <p className="flex min-w-0 items-center gap-1 text-xs text-gray-600">
                <span className="hidden truncate sm:inline">L&apos;entraide des turfistes ·</span>
                <span className="shrink-0">vous êtes</span>
                <button
                  onClick={() => setEditionPseudo(true)}
                  title="Modifier mon pseudo"
                  aria-label={`Modifier mon pseudo (${moi.pseudo})`}
                  className="group/pseudo inline-flex min-w-0 items-center gap-1 rounded-md px-1 font-semibold text-gray-900 hover:bg-amber-100/70"
                >
                  <span className="truncate">{moi.pseudo}</span>
                  <Pencil className="h-3 w-3 shrink-0 text-gray-500 group-hover/pseudo:text-brand-gold-dark" />
                </button>
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {connected ? (
              <span className="inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800">
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-60" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-emerald-500" />
                </span>
                {presents === null ? "En direct" : <>{presents}<span className="hidden sm:inline">&nbsp;en ligne</span></>}
              </span>
            ) : (
              <button onClick={reconnect}
                className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-gray-50 px-2.5 py-1 text-xs font-medium text-gray-700 hover:bg-gray-100">
                <RefreshCw className="h-3 w-3" /> Reconnecter
              </button>
            )}
            {moi.is_admin && (
              <button
                onClick={() => setModeration((v) => !v)}
                aria-pressed={moderation}
                aria-label="Modération"
                className={cn(
                  "relative inline-flex h-8 items-center gap-1.5 rounded-full border px-2.5 text-xs font-medium transition",
                  moderation ? "border-gray-900 bg-gray-900 text-white" : "border-gray-200 bg-white text-gray-700 hover:bg-gray-50",
                )}
              >
                <ShieldCheck className="h-3.5 w-3.5" />
                <span className="hidden sm:inline">Modération</span>
                {nbSignalements > 0 && (
                  <span className="flex h-4 min-w-4 items-center justify-center rounded-full bg-red-600 px-1 text-[10px] font-bold text-white">
                    {nbSignalements}
                  </span>
                )}
              </button>
            )}
          </div>
        </div>

        {editionPseudo && moi.pseudo && (
          <ModalPseudo
            actuel={moi.pseudo}
            userId={moi.user_id}
            onFermer={() => setEditionPseudo(false)}
            onEnregistre={(p) => {
              // Les messages déjà affichés prennent le nouveau nom tout de suite ; les
              // autres membres le verront à leur prochain chargement.
              setMessages((prev) => prev.map((m) =>
                m.auteur.user_id === moi.user_id ? { ...m, auteur: { ...m.auteur, pseudo: p } } : m));
              onPseudoModifie(p);
              setEditionPseudo(false);
            }}
          />
        )}

        {moi.is_admin && moderation && (
          <PanneauModeration onSupprimer={supprimer} onBannir={bannir} onFermer={() => setModeration(false)} />
        )}

        {/* Messages */}
        <div className="relative min-h-0 flex-1">
          <div
            ref={listeRef}
            onScroll={onScroll}
            onClick={(e) => { if (e.target === e.currentTarget) setActif(null); }}
            className="h-full overflow-y-auto overflow-x-hidden bg-[linear-gradient(180deg,#FAFAF9_0%,#FFFFFF_60%)] px-3 pb-4 pt-3 sm:px-5"
            role="log"
            aria-live="polite"
            aria-label="Messages du salon"
          >
            {chargement && <Squelette />}

            {!chargement && !plusAnciens && (
              <div className="mx-auto mb-2 mt-1 max-w-md rounded-2xl border border-amber-100 bg-amber-50/60 px-4 py-3 text-center">
                <p className="text-sm font-semibold text-gray-900">Bienvenue dans la communauté turf 🏇</p>
                <p className="mt-0.5 text-xs leading-relaxed text-gray-600">
                  Fêtez vos gains, partagez vos tuyaux et vos analyses, posez vos questions sur le site :
                  ce qui vous aide peut aider les autres. Respect de rigueur, pas de publicité ni de
                  pronostics payants.
                </p>
              </div>
            )}

            {plusAnciens && (
              <div className="mb-2 text-center">
                <button onClick={chargerAnciens} disabled={chargementAnciens}
                  className="inline-flex items-center gap-1.5 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700 shadow-sm hover:bg-gray-50 disabled:opacity-60">
                  {chargementAnciens && <Loader2 className="h-3 w-3 animate-spin" />}
                  Voir les messages précédents
                </button>
              </div>
            )}

            {!chargement && erreur && messages.length === 0 && (
              <div className="py-12 text-center text-sm text-gray-600">
                Impossible de charger les messages.{" "}
                <button className="font-medium text-brand-gold-dark underline" onClick={chargerRecents}>Réessayer</button>
              </div>
            )}
            {!chargement && !erreur && messages.length === 0 && (
              <div className="flex flex-col items-center py-14 text-center">
                <div className="flex h-14 w-14 items-center justify-center rounded-full bg-gray-100">
                  <MessagesSquare className="h-6 w-6 text-gray-600" />
                </div>
                <p className="mt-3 text-sm font-semibold text-gray-900">Le salon est calme pour l&apos;instant</p>
                <p className="mt-1 text-xs text-gray-600">Lancez la discussion : un gain à fêter, un tuyau pour la réunion du jour…</p>
              </div>
            )}

            <ul>
              {messages.map((m, i) => {
                const prec = messages[i - 1];
                const nouveauJour = !prec || libelleJour(prec.created_at) !== libelleJour(m.created_at);
                const suite = !nouveauJour && prec?.auteur.user_id === m.auteur.user_id
                  && Date.parse(m.created_at) - Date.parse(prec.created_at) < 5 * 60_000;
                const estMoi = m.auteur.user_id === moi.user_id;
                const peutSupprimer = estMoi || moi.is_admin;
                const peutBannir = moi.is_admin && !estMoi && m.auteur.role !== "admin";
                const heure = format(parseISO(m.created_at), "HH:mm");
                return (
                  <li key={m.message_id} className={cn(suite ? "mt-1" : "mt-4")}>
                    {nouveauJour && (
                      <div className="my-4 flex items-center gap-3" role="separator">
                        <span className="h-px flex-1 bg-gradient-to-r from-transparent to-gray-200" />
                        <span className="rounded-full border border-gray-200 bg-white px-3 py-0.5 text-[11px] font-medium text-gray-600 shadow-sm">
                          {libelleJour(m.created_at)}
                        </span>
                        <span className="h-px flex-1 bg-gradient-to-l from-transparent to-gray-200" />
                      </div>
                    )}
                    <div className={cn("group flex items-end gap-2.5", estMoi && "flex-row-reverse")}>
                      {suite ? <div className="w-9 shrink-0" /> : <Avatar pseudo={m.auteur.pseudo} userId={m.auteur.user_id} />}
                      <div className={cn("flex min-w-0 max-w-[82%] flex-col sm:max-w-[70%]", estMoi && "items-end")}>
                        {!suite && (
                          <div className={cn("mb-1 flex items-center gap-1.5 px-1 text-xs", estMoi && "flex-row-reverse")}>
                            <span className="font-semibold text-gray-900">{estMoi ? "Vous" : m.auteur.pseudo}</span>
                            <BadgeRole role={m.auteur.role} />
                            <time dateTime={m.created_at} className="text-[11px] text-gray-500">{heure}</time>
                          </div>
                        )}
                        <div className="relative">
                          <div
                            onClick={() => setActif((a) => (a === m.message_id ? null : m.message_id))}
                            title={format(parseISO(m.created_at), "d MMMM à HH:mm", { locale: fr })}
                            className={cn(
                              "whitespace-pre-wrap break-words px-3.5 py-2 text-[14px] leading-relaxed text-gray-900 transition-shadow",
                              estMoi
                                ? "rounded-2xl bg-gradient-to-br from-amber-100 to-amber-50 ring-1 ring-inset ring-amber-200/80"
                                : "rounded-2xl border border-gray-200/90 bg-white shadow-[0_1px_2px_rgba(17,24,39,0.05)]",
                              !suite && (estMoi ? "rounded-tr-md" : "rounded-tl-md"),
                              m.auteur.role === "admin" && !estMoi && "border-gray-300",
                            )}
                          >
                            {m.contenu}
                          </div>
                          {/* Actions : flottantes au survol (ou au toucher sur mobile). */}
                          <div
                            className={cn(
                              "absolute -top-4 z-10 flex items-center gap-0.5 rounded-full border border-gray-200 bg-white p-0.5 shadow-md transition",
                              estMoi ? "left-0 -translate-x-1/3" : "right-0 translate-x-1/3",
                              actif === m.message_id
                                ? "opacity-100"
                                : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100 focus-within:pointer-events-auto focus-within:opacity-100",
                            )}
                          >
                            {!estMoi && (
                              <button onClick={() => signaler(m)} className={actionIcone}
                                aria-label={`Signaler le message de ${m.auteur.pseudo}`} title="Signaler">
                                <Flag className="h-3.5 w-3.5" />
                              </button>
                            )}
                            {peutSupprimer && (
                              <button
                                onClick={() => { if (window.confirm("Supprimer ce message ?")) supprimer(m.message_id); }}
                                className={cn(actionIcone, "hover:bg-red-50 hover:text-red-700")}
                                aria-label="Supprimer le message" title="Supprimer">
                                <Trash2 className="h-3.5 w-3.5" />
                              </button>
                            )}
                            {peutBannir && (
                              <button onClick={() => bannir(m.auteur.user_id, m.auteur.pseudo)}
                                className={cn(actionIcone, "hover:bg-red-50 hover:text-red-700")}
                                aria-label={`Bannir ${m.auteur.pseudo}`} title="Bannir du salon">
                                <Ban className="h-3.5 w-3.5" />
                              </button>
                            )}
                          </div>
                        </div>
                      </div>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>

          {nonLus > 0 && (
            <button onClick={allerEnBas}
              className="absolute bottom-3 left-1/2 inline-flex -translate-x-1/2 items-center gap-1.5 rounded-full bg-gray-900 px-3.5 py-1.5 text-xs font-medium text-white shadow-lg transition hover:bg-gray-800">
              <ArrowDown className="h-3.5 w-3.5" />
              {nonLus} nouveau{nonLus > 1 ? "x" : ""} message{nonLus > 1 ? "s" : ""}
            </button>
          )}
        </div>

        {/* Saisie */}
        <div className="border-t border-gray-100 bg-white px-3 pb-3 pt-2.5 sm:px-5">
          {!moi.email_confirme ? (
            <p className="rounded-xl bg-amber-50 px-3 py-2.5 text-sm text-amber-900">
              Confirmez votre adresse e-mail pour écrire — le lien peut être renvoyé depuis votre profil.
            </p>
          ) : (
            <>
            {!texte && (
              <div className="mb-2 flex gap-1.5 overflow-x-auto" aria-label="Amorcer un message">
                {SUJETS.map((s) => (
                  <button
                    key={s.label}
                    type="button"
                    onClick={() => { setTexte(s.prefixe); requestAnimationFrame(() => saisieRef.current?.focus()); }}
                    className="shrink-0 rounded-full border border-gray-200 bg-white px-3 py-1 text-xs font-medium text-gray-700 transition hover:border-brand-gold/50 hover:bg-amber-50"
                  >
                    {s.prefixe.split(" ")[0]} {s.label}
                  </button>
                ))}
              </div>
            )}
            <form
              onSubmit={(e) => { e.preventDefault(); envoyer(); }}
              className={cn(
                "flex items-end gap-2 rounded-2xl border bg-gray-50 p-1.5 pl-3.5 transition",
                "focus-within:border-brand-gold focus-within:bg-white focus-within:ring-4 focus-within:ring-brand-gold/15",
                trop ? "border-red-300" : "border-gray-200",
              )}
            >
              <label htmlFor="message" className="sr-only">Votre message</label>
              <textarea
                id="message"
                ref={saisieRef}
                value={texte}
                onChange={(e) => setTexte(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                    e.preventDefault();
                    envoyer();
                  }
                }}
                rows={1}
                placeholder="Un gain, un tuyau, une question ?"
                className="max-h-[132px] min-h-[36px] flex-1 resize-none border-0 bg-transparent py-2 text-sm leading-5 text-gray-900 outline-none placeholder:text-gray-400 focus:ring-0"
              />
              <button
                type="submit"
                aria-label="Envoyer"
                disabled={envoi || !texte.trim() || trop}
                className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-gold text-white shadow-sm shadow-amber-600/30 transition hover:brightness-110 active:scale-95 disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
              >
                {envoi ? <Loader2 className="h-4 w-4 animate-spin" /> : <SendHorizontal className="h-4 w-4" />}
              </button>
            </form>
            </>
          )}
          <div className="mt-1.5 flex items-center justify-between gap-3 px-1 text-[11px] text-gray-500">
            <span className="truncate">
              <kbd className="font-sans">Entrée</kbd> pour envoyer · <kbd className="font-sans">Maj+Entrée</kbd> pour aller à la ligne
              <span className="hidden sm:inline"> · Jouer comporte des risques : 09 74 75 13 13</span>
            </span>
            {texte.length > LONGUEUR_MAX - 100 && (
              <span className={cn("shrink-0 tabular-nums", trop && "font-semibold text-red-700")}>
                {texte.length}/{LONGUEUR_MAX}
              </span>
            )}
          </div>
        </div>
      </Carte>
    </div>
  );
}

// ─── Invitation (visiteur sans compte) ───────────────────────
const APERCU_BULLES = [
  { largeur: "58%", moi: false }, { largeur: "40%", moi: false }, { largeur: "50%", moi: true },
  { largeur: "66%", moi: false }, { largeur: "36%", moi: true }, { largeur: "54%", moi: false },
  { largeur: "46%", moi: false }, { largeur: "60%", moi: true },
];

const ATOUTS = [
  "Partagez vos gains, vos tuyaux et vos analyses",
  "Échangez en direct avec d'autres passionnés de turf",
  "Gratuit : un compte suffit",
];

function Invitation() {
  return (
    <div className="mx-auto max-w-4xl px-4 py-8 md:px-6 md:py-10">
      <Carte className="relative overflow-hidden">
        {/* Aperçu flouté du salon : de simples formes, aucun vrai message n'est exposé. */}
        <div aria-hidden className="pointer-events-none absolute inset-0 select-none px-5 py-4 opacity-80 blur-[3px]">
          {APERCU_BULLES.map((b, i) => (
            <div key={i} className={cn("mt-4 flex items-end gap-2.5", b.moi && "flex-row-reverse")}>
              <div className={cn("h-9 w-9 shrink-0 rounded-full bg-gradient-to-br", AVATAR_TEINTES[i % AVATAR_TEINTES.length])} />
              <div className="space-y-1.5" style={{ width: b.largeur }}>
                <div className={cn("h-2.5 w-20 rounded bg-gray-300", b.moi && "ml-auto")} />
                <div className={cn("h-11 rounded-2xl", b.moi ? "bg-amber-100 ring-1 ring-amber-200" : "border border-gray-200 bg-white")} />
              </div>
            </div>
          ))}
        </div>
        <div aria-hidden className="absolute inset-0 bg-gradient-to-b from-white/40 via-white/75 to-white/95" />

        <div className="relative flex justify-center px-4 py-12 sm:py-16">
          <div className="w-full max-w-md rounded-3xl border border-gray-200 bg-white/95 p-6 text-center shadow-xl shadow-gray-900/5 sm:p-8">
            <div className="mx-auto w-fit"><TuileIcone><MessagesSquare className="h-5 w-5" /></TuileIcone></div>
            <h1 className="mt-4 text-2xl font-bold tracking-tight text-gray-900">Rejoignez la communauté des turfistes</h1>
            <p className="mt-2 text-sm leading-relaxed text-gray-600">
              Gains, tuyaux, analyses, courses du jour : les membres BlackTurf échangent en direct.
              Créez votre compte gratuit pour lire les messages et participer.
            </p>
            <ul className="mx-auto mt-5 w-fit space-y-2 text-left">
              {ATOUTS.map((a) => (
                <li key={a} className="flex items-center gap-2 text-sm text-gray-700">
                  <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-emerald-100">
                    <Check className="h-3 w-3 text-emerald-700" />
                  </span>
                  {a}
                </li>
              ))}
            </ul>
            <Link
              href="/inscription"
              className="btn-shimmer mt-6 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-brand-gold px-4 py-3 text-sm font-semibold text-brand-dark shadow-sm shadow-brand-gold/25 ring-1 ring-brand-gold/30 transition hover:bg-brand-gold-deep active:scale-[0.99]"
            >
              <UserPlus className="h-4 w-4" /> Créer mon compte gratuit
            </Link>
            <p className="mt-4 text-sm text-gray-600">
              Déjà membre ?{" "}
              <Link href="/login?redirect=/chat" className="font-semibold text-brand-gold-dark hover:underline">
                Se connecter
              </Link>
            </p>
          </div>
        </div>
      </Carte>
    </div>
  );
}

// ─── Page ────────────────────────────────────────────────────
export default function ChatPage() {
  // Pas de redirection vers la connexion : un visiteur sans compte voit l'invitation,
  // c'est elle qui donne envie de s'inscrire.
  const { user, loading } = useAuth();
  const { data: moi, error, mutate } = useSWR(user ? "chat-moi" : null, () => chatApi.moi().then((r) => r.data));

  const onBanni = useCallback(() => {
    mutate((m) => (m ? { ...m, banni: true } : m), { revalidate: false });
  }, [mutate]);

  if (!loading && !user) return <Invitation />;
  if (loading || (!moi && !error)) {
    return (
      <div className="flex justify-center py-28 text-gray-600">
        <Loader2 className="h-6 w-6 animate-spin" aria-label="Chargement" />
      </div>
    );
  }
  if (error || !moi) {
    return (
      <div className="py-28 text-center text-sm text-gray-600">
        Impossible d&apos;ouvrir la communauté.{" "}
        <button className="font-medium text-brand-gold-dark underline" onClick={() => mutate()}>Réessayer</button>
      </div>
    );
  }
  if (moi.banni) {
    return (
      <div className="mx-auto max-w-md px-4 py-20">
        <Carte className="p-8 text-center">
          <div className="mx-auto flex h-12 w-12 items-center justify-center rounded-full bg-gray-100">
            <Ban className="h-6 w-6 text-gray-600" />
          </div>
          <p className="mt-4 font-semibold text-gray-900">Votre accès à la communauté est suspendu</p>
          <p className="mt-1.5 text-sm leading-relaxed text-gray-600">
            Cette décision de modération ne concerne que le salon : le reste du site et votre
            abonnement restent accessibles normalement.
          </p>
        </Carte>
      </div>
    );
  }
  if (!moi.pseudo) return <ChoixPseudo userId={moi.user_id} onChoisi={() => mutate()} />;
  return (
    <Salon
      moi={moi}
      onBanni={onBanni}
      onPseudoModifie={(p) => mutate((m) => (m ? { ...m, pseudo: p } : m), { revalidate: false })}
    />
  );
}
