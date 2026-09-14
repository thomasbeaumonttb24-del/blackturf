"use client";

import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { hasSessionHint } from "@/lib/auth";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

type WebSocketOptions = {
  /** Appelé pour CHAQUE trame métier. `messages` (état React) peut regrouper
   *  plusieurs trames dans un même rendu : lire seulement `messages[0]` en perd. */
  onMessage?: (data: unknown) => void;
  /** Appelé à chaque ouverture, reconnexions comprises. */
  onOpen?: () => void;
};

export function useWebSocket(path: string, enabled = true, options: WebSocketOptions = {}) {
  const [messages, setMessages] = useState<unknown[]>([]);
  const [connected, setConnected] = useState(false);
  const [closeCode, setCloseCode] = useState<number | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout>>();
  const attemptRef = useRef(0);     // compteur de tentatives (backoff)
  const closingRef = useRef(false); // true après unmount → bloque la reconnexion
  const optionsRef = useRef(options);
  useEffect(() => { optionsRef.current = options; });

  const connect = useCallback(() => {
    if (!enabled || closingRef.current) return;
    // Pas de session ouverte → inutile d'ouvrir une socket qui sera fermée en 4401.
    if (!hasSessionHint()) return;

    // Le jeton n'est plus accessible en JavaScript (cookie httpOnly) : le navigateur
    // l'envoie de lui-même dans la poignée de main, comme pour toute requête vers
    // l'API. Rien ne transite donc par l'URL (les query strings finissent dans les
    // access logs des proxies = fuite de credential) ni par un message applicatif.
    const url = `${WS_URL}${path}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => {
      attemptRef.current = 0; // connexion OK → reset du backoff
      setConnected(true);
      setCloseCode(null);
      optionsRef.current.onOpen?.();
    };
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);

        // HEARTBEAT — le serveur envoie un ping toutes les 30 s et FERME la
        // connexion s'il ne reçoit pas de pong dans les 45 s (ws.py, PONG_TIMEOUT).
        // Le client ne répondait jamais : chaque canal (cotes live, paris de valeur,
        // alertes) mourait au bout de ~45 s, se reconnectait avec backoff, puis
        // abandonnait après 8 tentatives → « temps réel » silencieusement mort.
        if (data?.type === "ping") {
          try { ws.send(JSON.stringify({ type: "pong" })); } catch {}
          return; // trame de service : ne pas la pousser dans les messages métier
        }
        if (data?.type === "pong") return;

        optionsRef.current.onMessage?.(data);
        setMessages((prev) => [data, ...prev].slice(0, 100));
      } catch {}
    };
    ws.onclose = (e) => {
      // Socket PÉRIMÉE (remplacée par une plus récente) : sa fermeture ne doit rien
      // relancer. Sans ce garde, un démontage/remontage rapide (StrictMode, navigation)
      // laissait la vieille socket armer une reconnexion → deux flux ouverts, chaque
      // trame reçue en double.
      if (wsRef.current !== ws) return;
      setConnected(false);
      setCloseCode(e.code);
      // 4403 = refus définitif (paywall, bannissement) : se reconnecter ne changera rien.
      if (e.code === 4403) return;
      // Pas de reconnexion si démonté/désactivé, et plafond de tentatives (évite la
      // tempête : avant, reconnexion toutes les 5s à l'infini même serveur down).
      if (closingRef.current || !enabled || attemptRef.current >= 8) return;
      const delay = Math.min(30000, 1000 * 2 ** attemptRef.current) + Math.random() * 500;
      attemptRef.current += 1;
      retryRef.current = setTimeout(connect, delay);
    };
    ws.onerror = () => ws.close();
  }, [path, enabled]);

  useEffect(() => {
    closingRef.current = false;
    connect();
    return () => {
      // Marque le démontage AVANT close() pour que onclose ne ré-arme pas un timer
      // (sinon WS zombie qui reconnecte un composant démonté).
      closingRef.current = true;
      clearTimeout(retryRef.current);
      const ws = wsRef.current;
      wsRef.current = null;
      if (ws) {
        ws.onmessage = null;
        ws.close();
      }
    };
  }, [connect]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const clear = useCallback(() => setMessages([]), []);

  /** Relance manuelle après abandon (plafond de tentatives atteint). */
  const reconnect = useCallback(() => {
    clearTimeout(retryRef.current);
    attemptRef.current = 0;
    const ws = wsRef.current;
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
    connect();
  }, [connect]);

  return { messages, connected, closeCode, send, clear, reconnect };
}

export function useCotesLive(courseId: string, enabled = true) {
  const { messages, connected } = useWebSocket(`/courses/${courseId}/cotes`, enabled);
  const latest = messages[0] as { partants?: unknown[] } | undefined;
  return { partants: latest?.partants ?? [], connected };
}

export function useValueBetsStream(enabled = true) {
  const { messages, connected } = useWebSocket("/value-bets", enabled);
  const latest = messages[0] as { data?: unknown[] } | undefined;
  return { valueBets: latest?.data ?? [], connected };
}

export function useAlertesStream(enabled = true) {
  const { messages, connected } = useWebSocket("/user/alertes", enabled);
  // Les trames `chat_message` (bulle de la Communauté) passent par ce canal mais ne
  // sont pas des alertes : elles ne doivent pas relancer la liste des notifications.
  const alertes = useMemo(
    () => messages.filter((m) => (m as { type?: string } | null)?.type !== "chat_message"),
    [messages],
  );
  return { alertes, connected };
}
