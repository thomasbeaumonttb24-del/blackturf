import axios from "axios";

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export const api = axios.create({
  baseURL: `${API_URL}/api/v1`,
  headers: { "Content-Type": "application/json" },
});

// Attach JWT from localStorage (client-side only)
if (typeof window !== "undefined") {
  api.interceptors.request.use((config) => {
    const token = localStorage.getItem("access_token");
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  });

  // Auto-refresh on 401
  api.interceptors.response.use(
    (r) => r,
    async (error) => {
      if (error.response?.status === 401) {
        const refresh = localStorage.getItem("refresh_token");
        if (refresh) {
          try {
            const res = await axios.post(`${API_URL}/api/v1/auth/refresh`, {
              refresh_token: refresh,
            });
            const { access_token } = res.data;
            localStorage.setItem("access_token", access_token);
            error.config.headers.Authorization = `Bearer ${access_token}`;
            return api(error.config);
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
  pariDuJour: () => api.get("/pari-du-jour"),
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
};

export const notificationsApi = {
  list: (page = 1, limit = 50) => api.get("/notifications", { params: { page, limit } }),
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
  updateUser: (id: string, data: Record<string, unknown>) =>
    api.patch(`/users/${id}`, data, { baseURL: `${API_URL}/admin/api` }),
  models: () => api.get("/models", { baseURL: `${API_URL}/admin/api` }),
  deployModel: (version: number) =>
    api.post(`/models/${version}/deploy`, null, { baseURL: `${API_URL}/admin/api` }),
  retrain: () => api.post("/models/retrain", null, { baseURL: `${API_URL}/admin/api` }),
  scraperLogs: (params?: Record<string, unknown>) =>
    api.get("/scraper/logs", { baseURL: `${API_URL}/admin/api`, params }),
  scraperStatus: () => api.get("/scraper/status", { baseURL: `${API_URL}/admin/api` }),
  // Adaptive learning & ML monitoring
  alState: () => api.get("/adaptive-learning/state", { baseURL: `${API_URL}/admin/api` }),
  alHistory: (limit = 50) =>
    api.get("/adaptive-learning/history", { baseURL: `${API_URL}/admin/api`, params: { limit } }),
  biasMatrix: () =>
    api.get("/adaptive-learning/bias-matrix", { baseURL: `${API_URL}/admin/api` }),
  calibrationQuality: () =>
    api.get("/calibration-quality", { baseURL: `${API_URL}/admin/api` }),
};
