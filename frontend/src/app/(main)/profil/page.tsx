"use client";

import { useState, useEffect } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { toast } from "sonner";
import {
  Loader2, CreditCard, Bell, User, Shield, Check, X,
  TrendingUp, Zap, Brain, Star, ChevronRight, Lock,
} from "lucide-react";
import Link from "next/link";
import { useRequireAuth } from "@/hooks/useAuth";
import { authApi, api } from "@/lib/api";
import { planLabel, formatDate, cn } from "@/lib/utils";

/* ─── Schema ─────────────────────────────────────────────── */
const profileSchema = z.object({
  prenom: z.string().min(1, "Requis"),
  nom: z.string().optional(),
  bankroll_initiale: z.number().min(0).optional(),
  profil_risque: z.enum(["conservateur", "equilibre", "agressif"]),
});
type ProfileForm = z.infer<typeof profileSchema>;

/* ─── Plan features config ───────────────────────────────── */
const PLAN_FEATURES: Record<string, { label: string; included: boolean }[]> = {
  free: [
    { label: "Programme complet", included: true },
    { label: "Paris de valeur (3/jour)", included: true },
    { label: "Suivi de capital", included: true },
    { label: "Paris de valeur illimités", included: false },
    { label: "Analyse IA détaillée", included: false },
    { label: "Assistant IA", included: false },
    { label: "Notifications", included: false },
  ],
  decouverte: [
    { label: "Programme complet", included: true },
    { label: "Paris de valeur (3/jour)", included: true },
    { label: "Suivi de capital", included: true },
    { label: "Paris de valeur illimités", included: false },
    { label: "Analyse IA détaillée", included: false },
    { label: "Assistant IA", included: false },
    { label: "Notifications", included: false },
  ],
  standard: [
    { label: "Programme complet", included: true },
    { label: "Paris de valeur illimités", included: true },
    { label: "Suivi de capital", included: true },
    { label: "Analyse IA détaillée", included: true },
    { label: "Notifications", included: true },
    { label: "Assistant IA", included: false },
    { label: "Stratégies avancées", included: false },
  ],
  starter: [
    { label: "Programme complet", included: true },
    { label: "Paris de valeur illimités", included: true },
    { label: "Suivi de capital", included: true },
    { label: "Analyse IA détaillée", included: true },
    { label: "Notifications", included: true },
    { label: "Assistant IA", included: false },
    { label: "Stratégies avancées", included: false },
  ],
  pro: [
    { label: "Programme complet", included: true },
    { label: "Paris de valeur illimités", included: true },
    { label: "Suivi de capital avancé", included: true },
    { label: "Analyse IA détaillée", included: true },
    { label: "Assistant IA", included: true },
    { label: "Notifications", included: true },
    { label: "Stratégies avancées", included: true },
  ],
  expert: [
    { label: "Programme complet", included: true },
    { label: "Paris de valeur illimités", included: true },
    { label: "Suivi de capital avancé", included: true },
    { label: "Analyse IA détaillée", included: true },
    { label: "Assistant IA", included: true },
    { label: "Notifications", included: true },
    { label: "Stratégies avancées", included: true },
  ],
};

/* ─── Risk profile options ───────────────────────────────── */
const RISK_OPTIONS = [
  {
    value: "conservateur" as const,
    icon: "🛡️",
    label: "Prudent",
    desc: "Mises faibles, capital protégé",
    color: "text-blue-700",
    activeBorder: "border-blue-400 bg-blue-50",
    dot: "bg-blue-500",
  },
  {
    value: "equilibre" as const,
    icon: "⚖️",
    label: "Modéré",
    desc: "Risque / rendement équilibré",
    color: "text-amber-700",
    activeBorder: "border-amber-400 bg-amber-50",
    dot: "bg-amber-500",
  },
  {
    value: "agressif" as const,
    icon: "🚀",
    label: "Risqué",
    desc: "Mises max, rendement visé",
    color: "text-red-700",
    activeBorder: "border-red-400 bg-red-50",
    dot: "bg-red-500",
  },
];

/* ─── Input component ────────────────────────────────────── */
function Field({
  label,
  error,
  children,
}: {
  label: string;
  error?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide">{label}</label>
      {children}
      {error && <p className="text-xs text-red-700">{error}</p>}
    </div>
  );
}

const inputCls =
  "w-full rounded-xl border border-gray-200 bg-white px-3.5 py-2.5 text-sm text-gray-800 outline-none transition-all focus:border-amber-400 focus:ring-2 focus:ring-amber-100 placeholder:text-gray-600 disabled:bg-gray-50 disabled:text-gray-600";

/* ─── Page ───────────────────────────────────────────────── */
export default function ProfilPage() {
  const { user, loading, refreshUser } = useRequireAuth();
  const [savingProfile, setSavingProfile] = useState(false);
  const [loadingPortal, setLoadingPortal] = useState(false);
  const [loadingCancel, setLoadingCancel] = useState(false);
  const [pushEnabled, setPushEnabled] = useState(false);
  const [activeSection, setActiveSection] = useState<"profile" | "plan" | "notifs" | "security">("profile");

  const { register, handleSubmit, watch, setValue, reset, formState: { errors } } = useForm<ProfileForm>({
    resolver: zodResolver(profileSchema),
    defaultValues: {
      prenom: "", nom: "", bankroll_initiale: undefined, profil_risque: "equilibre",
    },
  });

  // useRequireAuth charge `user` de façon asynchrone : sans ce reset, le formulaire
  // resterait sur les valeurs vides du 1er rendu (bug d'affichage : champs vides).
  useEffect(() => {
    if (user) {
      reset({
        prenom: user.prenom || "",
        nom: user.nom || "",
        bankroll_initiale: user.bankroll_initiale ?? undefined,
        profil_risque: (user.profil_risque as "conservateur" | "equilibre" | "agressif") || "equilibre",
      });
    }
  }, [user, reset]);

  const profilRisque = watch("profil_risque");
  const isFree = user && ["free", "decouverte"].includes(user.plan);
  const planKey = user?.plan ?? "free";
  const features = PLAN_FEATURES[planKey] ?? PLAN_FEATURES.free;

  async function onSave(data: ProfileForm) {
    setSavingProfile(true);
    try {
      await authApi.updateMe(data);
      await refreshUser();
      toast.success("Profil mis à jour");
    } catch {
      toast.error("Erreur lors de la sauvegarde");
    } finally {
      setSavingProfile(false);
    }
  }

  async function handlePortal() {
    setLoadingPortal(true);
    try {
      const res = await api.post("/stripe/portal");
      window.location.href = res.data.url;
    } catch {
      toast.error("Erreur d'accès au portail Stripe");
      setLoadingPortal(false);
    }
  }

  async function handleCancel() {
    if (!window.confirm("Résilier votre abonnement ? Vous conservez l'accès jusqu'à la fin de la période en cours.")) return;
    setLoadingCancel(true);
    try {
      const res = await api.post("/stripe/cancel");
      toast.success(res.data?.message || "Demande de résiliation enregistrée.");
    } catch {
      toast.error("Erreur lors de la résiliation. Contactez contact@blackturf.fr");
    } finally {
      setLoadingCancel(false);
    }
  }

  async function handlePushSubscription() {
    if (!("Notification" in window) || !("serviceWorker" in navigator)) {
      toast.error("Notifications non supportées");
      return;
    }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") { toast.error("Permission refusée"); return; }
    try {
      const reg = await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: process.env.NEXT_PUBLIC_VAPID_PUBLIC_KEY,
      });
      await authApi.savePushSub(sub.toJSON());
      setPushEnabled(true);
      toast.success("Notifications activées !");
    } catch {
      toast.error("Erreur lors de l'activation");
    }
  }

  if (loading)
    return (
      <div className="flex items-center justify-center py-24">
        <Loader2 className="h-8 w-8 animate-spin text-gray-300" />
      </div>
    );
  if (!user) return null;

  const initials = `${user.prenom?.[0] ?? ""}${user.nom?.[0] ?? user.email[0]}`.toUpperCase();

  const SECTIONS = [
    { id: "profile" as const, label: "Profil", icon: User },
    { id: "plan" as const, label: "Abonnement", icon: CreditCard },
    { id: "notifs" as const, label: "Notifications", icon: Bell },
    { id: "security" as const, label: "Sécurité", icon: Shield },
  ];

  return (
    <div className="mx-auto max-w-4xl px-4 sm:px-6 lg:px-8 py-6 sm:py-8 space-y-5 sm:space-y-6">

      {/* ── User header card ── */}
      <div className="rounded-2xl border border-gray-200 bg-gradient-to-br from-white to-amber-50/40 px-4 sm:px-6 py-4 sm:py-5 flex flex-col sm:flex-row sm:items-center gap-4 shadow-sm">
        <div className="h-14 w-14 rounded-2xl bg-gradient-to-br from-amber-400 to-orange-400 flex items-center justify-center text-white text-xl font-bold shadow-sm flex-shrink-0">
          {initials}
        </div>
        <div className="flex-1 min-w-0">
          <h1 className="text-lg font-bold text-gray-900 truncate">
            {user.prenom ? `${user.prenom}${user.nom ? ` ${user.nom}` : ""}` : user.email}
          </h1>
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <span className="text-sm text-gray-600">{user.email}</span>
            <span className="text-gray-200">·</span>
            <span
              className={cn(
                "text-xs font-semibold px-2 py-0.5 rounded-full",
                planKey === "expert"
                  ? "bg-emerald-100 text-emerald-700"
                  : ["starter", "standard"].includes(planKey)
                  ? "bg-amber-100 text-amber-700"
                  : "bg-gray-100 text-gray-600",
              )}
            >
              {planLabel(planKey)}
            </span>
            {user.email_verified && (
              <span className="text-xs text-emerald-700 flex items-center gap-0.5">
                <Check className="h-3 w-3" /> Vérifié
              </span>
            )}
          </div>
        </div>
        {isFree && (
          <Link
            href="/tarifs"
            className="flex-shrink-0 self-start inline-flex items-center gap-1.5 rounded-xl bg-amber-500 hover:bg-amber-600 text-brand-dark text-sm font-semibold px-4 py-2 transition-colors shadow-sm shadow-amber-200"
          >
            <Zap className="h-4 w-4" /> Passer Standard
          </Link>
        )}
      </div>

      {/* ── Sidebar nav + content ── */}
      <div className="grid grid-cols-1 sm:grid-cols-[200px_1fr] gap-4">

        {/* Sidebar — 2×2 sur mobile (pas de scroll), colonne sur desktop */}
        <div className="grid grid-cols-2 sm:flex sm:flex-col gap-1.5 sm:gap-1">
          {SECTIONS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveSection(id)}
              className={cn(
                "flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-sm font-medium transition-all",
                activeSection === id
                  ? "bg-gray-900 text-white shadow-sm"
                  : "text-gray-600 bg-gray-50 sm:bg-transparent hover:bg-gray-100 hover:text-gray-900",
              )}
            >
              <Icon className="h-4 w-4 flex-shrink-0" />
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="rounded-2xl border border-gray-200 bg-white shadow-sm overflow-hidden">

          {/* ── Profile ── */}
          {activeSection === "profile" && (
            <form onSubmit={handleSubmit(onSave)}>
              <div className="px-4 sm:px-6 py-4 border-b border-gray-100">
                <h2 className="font-bold text-gray-900">Informations personnelles</h2>
                <p className="text-xs text-gray-600 mt-0.5">Vos données de compte et préférences IA</p>
              </div>
              <div className="px-4 sm:px-6 py-5 space-y-5">
                <div className="grid grid-cols-2 gap-4">
                  <Field label="Prénom" error={errors.prenom?.message}>
                    <input {...register("prenom")} className={inputCls} placeholder="Jean" />
                  </Field>
                  <Field label="Nom">
                    <input {...register("nom")} className={inputCls} placeholder="Dupont" />
                  </Field>
                </div>

                <Field label="E-mail">
                  <input value={user.email} disabled className={inputCls} />
                </Field>

                <Field label="Capital initial (€)">
                  <input
                    {...register("bankroll_initiale", { valueAsNumber: true })}
                    type="number"
                    min="0"
                    step="1"
                    className={inputCls}
                    placeholder="500"
                  />
                </Field>

                {/* Risk profile */}
                <div className="space-y-2.5">
                  <label className="block text-xs font-semibold text-gray-600 uppercase tracking-wide">
                    Profil de risque
                  </label>
                  <div className="grid grid-cols-3 gap-2 sm:gap-3">
                    {RISK_OPTIONS.map((opt) => (
                      <button
                        key={opt.value}
                        type="button"
                        onClick={() => setValue("profil_risque", opt.value)}
                        className={cn(
                          "relative rounded-xl border-2 p-2.5 sm:p-3 text-left transition-all",
                          profilRisque === opt.value
                            ? opt.activeBorder
                            : "border-gray-200 hover:border-gray-300 bg-white",
                        )}
                      >
                        <input
                          {...register("profil_risque")}
                          type="radio"
                          value={opt.value}
                          className="sr-only"
                        />
                        <div className="text-xl mb-1.5">{opt.icon}</div>
                        <div className={cn("text-xs font-bold", profilRisque === opt.value ? opt.color : "text-gray-700")}>
                          {opt.label}
                        </div>
                        <div className="text-[10px] text-gray-600 mt-0.5 leading-tight">{opt.desc}</div>
                        {profilRisque === opt.value && (
                          <span className={cn("absolute top-2 right-2 h-4 w-4 rounded-full flex items-center justify-center", opt.dot)}>
                            <Check className="h-2.5 w-2.5 text-white" />
                          </span>
                        )}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div className="px-4 sm:px-6 py-4 border-t border-gray-100 bg-gray-50/50 flex justify-end">
                <button
                  type="submit"
                  disabled={savingProfile}
                  className="inline-flex items-center gap-2 rounded-xl bg-gray-900 hover:bg-gray-800 text-white text-sm font-semibold px-5 py-2.5 transition-colors disabled:opacity-50"
                >
                  {savingProfile && <Loader2 className="h-4 w-4 animate-spin" />}
                  Sauvegarder
                </button>
              </div>
            </form>
          )}

          {/* ── Plan ── */}
          {activeSection === "plan" && (
            <div>
              <div className="px-4 sm:px-6 py-4 border-b border-gray-100">
                <h2 className="font-bold text-gray-900">Abonnement</h2>
                <p className="text-xs text-gray-600 mt-0.5">Gérez votre plan et votre facturation</p>
              </div>
              <div className="px-4 sm:px-6 py-5 space-y-5">

                {/* Current plan badge */}
                <div
                  className={cn(
                    "rounded-2xl p-4 sm:p-5 border-2",
                    planKey === "expert"
                      ? "border-emerald-200 bg-gradient-to-br from-emerald-50 to-white"
                      : ["starter", "standard"].includes(planKey)
                      ? "border-amber-200 bg-gradient-to-br from-amber-50 to-white"
                      : "border-gray-200 bg-gray-50",
                  )}
                >
                  <div className="flex items-center justify-between mb-3">
                    <div>
                      <p className="text-xs font-semibold text-gray-600 uppercase tracking-wide mb-1">Plan actuel</p>
                      <p
                        className={cn(
                          "text-2xl font-bold",
                          planKey === "expert"
                            ? "text-emerald-700"
                            : ["starter", "standard"].includes(planKey)
                            ? "text-amber-700"
                            : "text-gray-700",
                        )}
                      >
                        {planLabel(planKey)}
                      </p>
                    </div>
                    {planKey === "expert" && <Star className="h-8 w-8 text-emerald-400" />}
                    {["starter", "standard"].includes(planKey) && <TrendingUp className="h-8 w-8 text-amber-700" />}
                    {isFree && <Brain className="h-8 w-8 text-gray-300" />}
                  </div>

                  {/* Features */}
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-1.5">
                    {features.map((f) => (
                      <div key={f.label} className="flex items-center gap-2 text-sm">
                        {f.included ? (
                          <Check className="h-3.5 w-3.5 text-emerald-700 flex-shrink-0" />
                        ) : (
                          <Lock className="h-3.5 w-3.5 text-gray-300 flex-shrink-0" />
                        )}
                        <span className={f.included ? "text-gray-700" : "text-gray-600"}>{f.label}</span>
                      </div>
                    ))}
                  </div>
                </div>

                {/* CTA */}
                {isFree ? (
                  <div className="rounded-2xl border border-amber-200 bg-amber-50 p-4 sm:p-5 space-y-3">
                    <div className="flex items-center gap-2">
                      <Zap className="h-5 w-5 text-amber-700" />
                      <p className="font-semibold text-amber-800">Débloquez tout</p>
                    </div>
                    <p className="text-sm text-amber-700">
                      Paris de valeur illimités, assistant IA et notifications en temps réel.
                    </p>
                    <Link
                      href="/tarifs"
                      className="inline-flex items-center gap-2 rounded-xl bg-amber-500 hover:bg-amber-600 text-brand-dark text-sm font-semibold px-5 py-2.5 transition-colors"
                    >
                      Voir les offres <ChevronRight className="h-4 w-4" />
                    </Link>
                  </div>
                ) : (
                  <div className="flex flex-col gap-3">
                    <button
                      onClick={handlePortal}
                      disabled={loadingPortal}
                      className="flex items-center gap-2 text-sm text-gray-600 hover:text-gray-900 font-medium transition-colors disabled:opacity-50"
                    >
                      {loadingPortal ? <Loader2 className="h-4 w-4 animate-spin" /> : <CreditCard className="h-4 w-4" />}
                      Gérer l&apos;abonnement via Stripe
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                    <button
                      onClick={handleCancel}
                      disabled={loadingCancel}
                      className="flex items-center gap-2 text-sm text-red-700 hover:text-red-700 font-medium transition-colors disabled:opacity-50"
                    >
                      {loadingCancel ? <Loader2 className="h-4 w-4 animate-spin" /> : null}
                      Résilier mon abonnement
                    </button>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ── Notifications ── */}
          {activeSection === "notifs" && (
            <div>
              <div className="px-4 sm:px-6 py-4 border-b border-gray-100">
                <h2 className="font-bold text-gray-900">Notifications</h2>
                <p className="text-xs text-gray-600 mt-0.5">Alertes paris de valeur en temps réel</p>
              </div>
              <div className="px-4 sm:px-6 py-5 space-y-4">
                <div className="flex items-center justify-between gap-3 rounded-2xl border border-gray-200 p-4">
                  <div>
                    <p className="text-sm font-semibold text-gray-800">Notifications</p>
                    <p className="text-xs text-gray-600 mt-0.5">Alertes de valeur instantanées sur votre appareil</p>
                  </div>
                  {isFree ? (
                    <span className="flex items-center gap-1 text-xs text-gray-600 bg-gray-100 rounded-full px-3 py-1.5">
                      <Lock className="h-3 w-3" /> Standard requis
                    </span>
                  ) : (
                    <button
                      onClick={handlePushSubscription}
                      disabled={pushEnabled}
                      className={cn(
                        "rounded-xl text-sm font-semibold px-4 py-2 transition-all",
                        pushEnabled
                          ? "bg-emerald-100 text-emerald-700"
                          : "bg-gray-900 hover:bg-gray-800 text-white",
                      )}
                    >
                      {pushEnabled ? "✓ Activé" : "Activer"}
                    </button>
                  )}
                </div>
                {isFree && (
                  <p className="text-xs text-gray-600">
                    Les notifications sont disponibles à partir du plan Standard.{" "}
                    <Link href="/tarifs" className="text-amber-700 font-medium hover:underline">
                      Voir les offres →
                    </Link>
                  </p>
                )}
              </div>
            </div>
          )}

          {/* ── Security ── */}
          {activeSection === "security" && (
            <div>
              <div className="px-4 sm:px-6 py-4 border-b border-gray-100">
                <h2 className="font-bold text-gray-900">Sécurité</h2>
                <p className="text-xs text-gray-600 mt-0.5">Statut de votre compte</p>
              </div>
              <div className="px-4 sm:px-6 py-5 space-y-3">

                {/* Email verified row */}
                <div className="flex items-center justify-between gap-3 rounded-2xl border border-gray-200 p-4">
                  <div className="min-w-0">
                    <p className="text-sm font-semibold text-gray-800">E-mail vérifié</p>
                    <p className="text-xs text-gray-600 mt-0.5 truncate">{user.email}</p>
                  </div>
                  <div className="flex items-center gap-2">
                    {user.email_verified ? (
                      <span className="flex items-center gap-1 text-xs font-semibold text-emerald-700 bg-emerald-50 rounded-full px-2.5 py-1">
                        <Check className="h-3 w-3" /> Vérifié
                      </span>
                    ) : (
                      <>
                        <span className="flex items-center gap-1 text-xs font-semibold text-amber-700 bg-amber-50 rounded-full px-2.5 py-1">
                          <X className="h-3 w-3" /> Non vérifié
                        </span>
                        <button
                          onClick={async () => {
                            try {
                              await api.post("/auth/resend-verification");
                              toast.success("E-mail renvoyé");
                            } catch {
                              toast.error("Erreur");
                            }
                          }}
                          className="text-xs text-gray-600 hover:text-gray-900 font-medium underline underline-offset-2"
                        >
                          Renvoyer
                        </button>
                      </>
                    )}
                  </div>
                </div>

                {/* Account creation */}
                <div className="flex items-center justify-between rounded-2xl border border-gray-200 p-4">
                  <p className="text-sm font-semibold text-gray-800">Compte créé le</p>
                  <span className="text-sm text-gray-600">{formatDate(user.created_at)}</span>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Responsible gambling ── */}
      <div className="rounded-2xl border border-orange-100 bg-orange-50/50 px-4 sm:px-5 py-4 text-xs text-orange-700">
        <p className="font-semibold mb-1">⚠️ Jeu responsable</p>
        <p>
          Si vous avez des difficultés à contrôler votre jeu, appelez le{" "}
          <strong>09 74 75 13 13</strong> (Joueurs Info Service, gratuit, 7j/7, 8h–2h) ou visitez{" "}
          <a
            href="https://www.joueurs-info-service.fr"
            target="_blank"
            rel="noopener noreferrer"
            className="underline font-medium"
          >
            joueurs-info-service.fr
          </a>.
        </p>
      </div>
    </div>
  );
}
