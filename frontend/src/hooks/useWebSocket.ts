"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { getAccessToken } from "@/lib/auth";

const WS_URL = process.env.NEXT_PUBLIC_WS_URL || "ws://localhost:8000/ws";

export function useWebSocket(path: string, enabled = true) {
  const [messages, setMessages] = useState<unknown[]>([]);
  const [connected, setConnected] = useState(false);
  const wsRef = useRef<WebSocket | null>(null);
  const retryRef = useRef<ReturnType<typeof setTimeout>>();

  const connect = useCallback(() => {
    if (!enabled) return;
    const token = getAccessToken();
    if (!token) return;

    const url = `${WS_URL}${path}?token=${token}`;
    const ws = new WebSocket(url);
    wsRef.current = ws;

    ws.onopen = () => setConnected(true);
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data);
        setMessages((prev) => [data, ...prev].slice(0, 100));
      } catch {}
    };
    ws.onclose = () => {
      setConnected(false);
      // Reconnect 5s
      retryRef.current = setTimeout(connect, 5000);
    };
    ws.onerror = () => ws.close();
  }, [path, enabled]);

  useEffect(() => {
    connect();
    return () => {
      clearTimeout(retryRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((data: unknown) => {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify(data));
    }
  }, []);

  const clear = useCallback(() => setMessages([]), []);

  return { messages, connected, send, clear };
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
  return { alertes: messages, connected };
}
