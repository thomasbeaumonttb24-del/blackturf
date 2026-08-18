import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
  timeout: 15000, // sans timeout, une requête peut pendre indéfiniment (spinner infini)
});

// Refresh partagé (single-flight) : si N requêtes tombent en 401 en même temps,
// on ne déclenche qu'UN seul POST /auth/refresh, sinon cascade de refresh concurrents
// qui invalident le refresh token et déconnectent l'utilisateur.
let refreshPromise: Promise<string> | null = null;

// Attach JWT from localStorage (client-side only)
if (typeof window !== "undefined") {
  api.interceptors.request.use((config) => {
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // Auto-refresh on 401 (single-flight + flag _retry anti-boucle)
  api.interceptors.response.use(
    (r) => r,
    async (error) => {
      const original = error.config as (typeof error.config & { _retry?: boolean }) | undefined;
      if (error.response?.status === 401 && original && !original._retry) {
        const refresh = localStorage.getItem("refresh_token");
        if (refresh) {
          original._retry = true; // ne ré-essaie qu'une fois (évite la boucle si re-401)
          try {
            if (!refreshPromise) {
              refreshPromise = axios
                .post(`${API_URL}/api/v1/auth/refresh`, { refresh_token: refresh })
                .then((res) => {
                  const { access_token } = res.data;
                  localStorage.setItem("access_token", access_token);
                  return access_token as string;
                })
                .finally(() => {
                  refreshPromise = null;
                });
            }
            const access_token = await refreshPromise;
            original.headers.Authorization = `Bearer ${access_token}`;
            return api(original);
          } catch {
            localStorage.removeItem("access_token");
            localStorage.removeItem("refresh_token");
            window.location.href = "/login";
          }
        }
      }
      return Promise.reject(error);
    }
  );
}

// API helpers
export const authApi = {
  register: (data: { email: string; password: string; nom?: string; prenom?: string }) =>
    api.post("/auth/register", data),
  login: (email: string, password: string) =>
    api.post("/auth/login", new URLSearchParams({ username: email, password }), {
      headers: { "Content-Type": "application/x-www-form-urlencoded" },
    }),
  me: () => api.get("/auth/me"),
  updateMe: (data: Record<string, unknown>) => api.patch("/auth/me", data),
  savePushSub: (sub: object) => api.put("/auth/push-subscription", sub),
};

export const coursesApi = {
  programme: (jour?: string) => api.get("/programme", { params: jour ? { jour } : {} }),
  course: (id: string) => api.get(`/courses/${id}`),
  resultats: (id: string) => api.get(`/courses/${id}/resultats`),
  // Types de paris réellement proposés par le PMU pour la course (2sur4 inclus seulement
  // s'il est offert). Évite de proposer/sélectionner un pari injouable.
  parisDisponibles: (id: string) => api.get(`/courses/${id}/paris-disponibles`),
  confrontations: (id: string) => api.get(`/courses/${id}/confrontations`),
  cheval: (id: string) => api.get(`/chevaux/${id}`),
  jockey: (id: string) => api.get(`/jockeys/${id}`),
  entraineur: (id: string) => api.get(`/entraineurs/${id}`),
};

export const predictionsApi = {
  get: (courseId: string, bankroll?: number) =>
    api.get(`/courses/${courseId}/predictions`, { params: { bankroll } }),
  trigger: (courseId: string, bankroll?: number) =>
    api.post(`/courses/${courseId}/predict`, null, { params: { bankroll } }),
  valueBets: (niveauMin?: number) =>
    api.get("/value-bets", { params: { niveau_min: niveauMin } }),
  valueBetsHistory: (limit = 50, offset = 0) =>
    api.get("/value-bets/historique", { params: { limit, offset } }),
  // Compteur agrégé public (bandeau Free) — jamais de détail individuel, juste un total.
  valueBetsCompteur: (niveauMin = 3) =>
    api.get("/value-bets/compteur", { params: { niveau_min: niveauMin } }),
  pariDuJour: () => api.get("/pari-du-jour"),
  pariDuJourProfils: () => api.get("/pari-du-jour-profils"),
  modelVersion: () => api.get("/model/version"),
};

export const bankrollApi = {
  entries: (params?: Record<string, unknown>) => api.get("/bankroll/entries", { params }),
  create: (data: Record<string, unknown>) => api.post("/bankroll/entries", data),
  update: (id: string, data: Record<string, unknown>) =>
    api.patch(`/bankroll/entries/${id}`, data),
  delete: (id: string) => api.delete(`/bankroll/entries/${id}`),
  stats: () => api.get("/bankroll/stats"),
  export: () => api.get("/bankroll/export", { responseType: "blob" }),
};

export const strategiesApi = {
  list: () => api.get("/strategies"),
  create: (data: Record<string, unknown>) => api.post("/strategies", data),
  update: (id: string, data: Record<string, unknown>) => api.patch(`/strategies/${id}`, data),
  delete: (id: string) => api.delete(`/strategies/${id}`),
  backtest: (id: string, params: { jours?: number; mise_fixe?: number }) =>
    api.post(`/strategies/${id}/backtest`, null, { params }),
};

export const assistantApi = {
  chat: (messages: Array<{ role: string; content: string }>, stream = true) =>
    api.post("/assistant/chat", { messages, stream }),
  chatStream: (messages: Array<{ role: string; content: string }>) =>
    `${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"}/api/v1/assistant/chat`,
};

export const misePlanApi = {
  get: (courseId: string, data: { montant: number; profil_risque?: string; bankroll?: number }) =>
    api.post(`/courses/${courseId}/mise-plan`, data),
};

export const statsApi = {
  public: () => api.get("/stats/public"),
  equityCurve: () => api.get("/stats/equity-curve"),
  mlStatus: () => api.get("/stats/ml-status"),
  dashboardSummary: () => api.get("/stats/dashboard-summary"),
  roiByDiscipline: () => api.get("/stats/roi-by-discipline"),
  perfPersonnelle: () => api.get("/stats/perf-personnelle"),
  trackRecord: () => api.get("/stats/track-record"),
  profils: () => api.get("/stats/profils"),
  palmaresGagnants: () => api.get("/stats/palmares-gagnants"),
  // Version PUBLIQUE du palmarès : `palmaresGagnants` est gardé par require_admin
  // → 401 pour tout visiteur. À utiliser partout où la page est accessible sans
  // compte (accueil, track-record), sinon la section reste vide pour les prospects.
  palmaresPublic: () => api.get("/stats/palmares-public"),
};

export const notificationsApi = {
  // `categorie` est filtrée par le SERVEUR (value_bet / resultat / systeme) : filtrer
  // une page de 50 côté client affichait un onglet vide alors que la catégorie avait
  // des dizaines d'entrées plus loin dans l'historique.
  list: (page = 1, limit = 50, categorie?: string) =>
    api.get("/notifications", { params: { page, limit, ...(categorie ? { categorie } : {}) } }),
  countUnread: () => api.get("/notifications/count-unread"),
  markRead: (id: string) => api.put(`/notifications/${id}/lue`),
  markAllRead: () => api.delete("/notifications/all"),
  getPrefs: () => api.get("/notifications/prefs"),
  updatePrefs: (data: { vb_niveau_min?: number; resultats_suivis?: boolean; alertes_systeme?: boolean }) =>
    api.put("/notifications/prefs", data),
};

export const adminApi = {
  dashboard: () => api.get("/dashboard", { baseURL: `${API_URL}/admin/api` }),
  users: (params?: Record<string, unknown>) =>
    api.get("/users", { baseURL: `${API_URL}/admin/api`, params }),
  userDetail: (id: string) =>
    api.get(`/users/${id}`, { baseURL: `${API_URL}/admin/api` }),
  updateUser: (id: string, data: Record<string, unknown>) =>
    api.patch(`/users/${id}`, data, { baseURL: `${API_URL}/admin/api` }),
  adjustBankroll: (id: string, montant: number, note?: string) =>
    api.post(`/users/${id}/bankroll-adjust`, { montant, note }, { baseURL: `${API_URL}/admin/api` }),
  exportUsers: () =>
    api.get("/users-export", { baseURL: `${API_URL}/admin/api`, responseType: "blob" }),
  models: () => api.get("/models", { baseURL: `${API_URL}/admin/api` }),
  deployModel: (version: number) =>
    api.post(`/models/${version}/deploy`, null, { baseURL: `${API_URL}/admin/api` }),
  retrain: () => api.post("/models/retrain", null, { baseURL: `${API_URL}/admin/api` }),
  scraperLogs: (params?: Record<string, unknown>) =>
    api.get("/scraper/logs", { baseURL: `${API_URL}/admin/api`, params }),
  scraperStatus: () => api.get("/scraper/status", { baseURL: `${API_URL}/admin/api` }),
  errors: (params?: Record<string, unknown>) =>
    api.get("/errors", { baseURL: `${API_URL}/admin/api`, params }),
  resolveError: (id: number) =>
    api.post(`/errors/${id}/resolve`, null, { baseURL: `${API_URL}/admin/api` }),
  // Adaptive learning & ML monitoring
  alState: () => api.get("/adaptive-learning/state", { baseURL: `${API_URL}/admin/api` }),
  alHistory: (limit = 50) =>
    api.get("/adaptive-learning/history", { baseURL: `${API_URL}/admin/api`, params: { limit } }),
  biasMatrix: () =>
    api.get("/adaptive-learning/bias-matrix", { baseURL: `${API_URL}/admin/api` }),
  calibrationQuality: () =>
    api.get("/calibration-quality", { baseURL: `${API_URL}/admin/api` }),
  learningSignals: () =>
    api.get("/learning-signals", { baseURL: `${API_URL}/admin/api` }),
  learningConvergence: () =>
    api.get("/learning-convergence", { baseURL: `${API_URL}/admin/api` }),
};
