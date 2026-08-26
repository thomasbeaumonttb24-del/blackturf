"use client";

import { useState, useRef, useEffect } from "react";
import Link from "next/link";
import { Send, Loader2, Bot, User, Zap, RefreshCw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { useRequireAuth } from "@/hooks/useAuth";

import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import useSWR from "swr";

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  loading?: boolean;
}

const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// Rendu léger du markdown **gras** (le moteur renvoie du markdown simple).
function renderRich(text: string) {
  return text.split(/\*\*(.+?)\*\*/g).map((part, i) =>
    i % 2 === 1
      ? <strong key={i} className="font-semibold text-gray-900">{part}</strong>
      : <span key={i}>{part}</span>
  );
}

export default function AssistantPage() {
  const { user, loading: authLoading } = useRequireAuth();
  const [messages, setMessages] = useState<Message[]>([
    {
      id: "welcome",
      role: "assistant",
      content:
        "Bonjour ! Je suis BlackTurf IA, votre expert en courses hippiques. Posez-moi n'importe quelle question sur les courses du jour, les paris de valeur, ou la gestion de votre capital.\n\n⚠️ Je suis un outil d'aide à la décision — aucune garantie de gain.",
    },
  ]);
  const [input, setInput] = useState("");
  const [streaming, setStreaming] = useState(false);
  const bottomRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const { data: suggestions } = useSWR(
    user?.plan === "expert" ? "/assistant/suggestions" : null,
    () => api.get("/assistant/suggestions").then((r) => r.data.suggestions as string[])
  );

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages]);

  async function sendMessage(text?: string) {
    const content = text || input.trim();
    if (!content || streaming) return;

    const userMsg: Message = { id: Date.now().toString(), role: "user", content };
    const assistantMsg: Message = {
      id: (Date.now() + 1).toString(),
      role: "assistant",
      content: "",
      loading: true,
    };

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setInput("");
    setStreaming(true);

    const history = [
      ...messages.filter((m) => !m.loading),
      userMsg,
    ].map((m) => ({ role: m.role, content: m.content }));

    try {
      // `credentials: "include"` : le flux SSE passe par fetch() et non par axios,
      // il faut donc lui demander explicitement d'envoyer le cookie de session.
      const response = await fetch(`${API_URL}/api/v1/assistant/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "include",
        body: JSON.stringify({ messages: history, stream: true }),
      });

      if (!response.ok || !response.body) {
        throw new Error(`HTTP ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let accumulated = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        const chunk = decoder.decode(value, { stream: true });
        const lines = chunk.split("\n");

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          const data = line.slice(6);
          if (data === "[DONE]") break;
          try {
            const parsed = JSON.parse(data);
            if (parsed.type === "text") {
              accumulated += parsed.text;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, content: accumulated, loading: false }
                    : m
                )
              );
            } else if (parsed.type === "error") {
              accumulated = parsed.text;
              setMessages((prev) =>
                prev.map((m) =>
                  m.id === assistantMsg.id
                    ? { ...m, content: accumulated, loading: false }
                    : m
                )
              );
            }
          } catch {}
        }
      }
    } catch {
      setMessages((prev) =>
        prev.map((m) =>
          m.id === assistantMsg.id
            ? { ...m, content: "Erreur de connexion. Réessayez.", loading: false }
            : m
        )
      );
    } finally {
      setStreaming(false);
      inputRef.current?.focus();
    }
  }

  if (authLoading) return (
    <div className="flex justify-center py-20">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
    </div>
  );

  if (!user || user.plan !== "expert") {
    return (
      <div className="max-w-lg mx-auto px-4 py-20 text-center space-y-5">
        <div className="mx-auto h-20 w-20 rounded-3xl bg-gradient-to-br from-amber-400 to-orange-400 flex items-center justify-center shadow-lg shadow-amber-200">
          <Bot className="h-9 w-9 text-white" />
        </div>
        <div>
          <h1 className="text-3xl font-bold text-gray-900 mb-2">BlackTurf IA</h1>
          <p className="text-gray-600 leading-relaxed">
            Posez vos questions en langage naturel. L&apos;IA accède aux données en temps réel :
            programme du jour, paris de valeur, prédictions, indicateurs de mouvement.
          </p>
        </div>
        <div className="rounded-2xl border border-amber-200 bg-amber-50 px-6 py-5 space-y-3 text-left">
          {[
            "\"Quels sont les meilleurs paris de valeur aujourd'hui ?\"",
            "\"Analyse le cheval N°4 de la R3 Vincennes\"",
            "\"Mon capital est de 500€, comment répartir mes mises ?\"",
          ].map((ex) => (
            <p key={ex} className="text-sm text-amber-800 font-medium flex items-start gap-2">
              <span className="text-amber-700 mt-0.5">›</span> {ex}
            </p>
          ))}
        </div>
        <div>
          <p className="text-sm text-gray-600 mb-4">
            Fonctionnalité réservée au plan <strong className="text-amber-700">Expert</strong>.
          </p>
          <Link
            href="/tarifs"
            className="inline-flex items-center gap-2 rounded-2xl bg-amber-500 hover:bg-amber-600 text-brand-dark font-semibold px-6 py-3 transition-colors shadow-sm shadow-amber-200"
          >
            <Zap className="h-4 w-4" /> Passer Expert
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-3xl px-4 sm:px-6 py-6 flex flex-col h-[calc(100dvh-4rem-1px)]">

      {/* Header */}
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <div className="flex items-center gap-3">
          <div className="h-9 w-9 rounded-2xl bg-gradient-to-br from-amber-400 to-orange-400 flex items-center justify-center shadow-sm shadow-amber-200">
            <Bot className="h-4.5 w-4.5 text-white" />
          </div>
          <div>
            <h1 className="font-bold text-gray-900 text-sm">BlackTurf IA</h1>
            <div className="flex items-center gap-1.5">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-xs text-gray-600">Moteur BlackTurf · Données en direct</span>
            </div>
          </div>
        </div>
        <button
          onClick={() => setMessages([{
            id: "welcome",
            role: "assistant",
            content: "Conversation réinitialisée. Comment puis-je vous aider ?",
          }])}
          className="flex items-center gap-1.5 text-xs text-gray-600 hover:text-gray-800 rounded-xl px-3 py-1.5 hover:bg-gray-100 transition-colors"
        >
          <RefreshCw className="h-3.5 w-3.5" /> Réinitialiser
        </button>
      </div>

      {/* Messages */}
      <div className="flex-1 overflow-y-auto space-y-3 pb-4 scroll-smooth">
        {messages.map((msg) => (
          <div
            key={msg.id}
            className={cn("flex gap-2.5", msg.role === "user" && "flex-row-reverse")}
          >
            {/* Avatar */}
            <div
              className={cn(
                "h-7 w-7 rounded-xl flex items-center justify-center flex-shrink-0 mt-1",
                msg.role === "assistant"
                  ? "bg-gradient-to-br from-amber-400 to-orange-400 shadow-sm"
                  : "bg-gray-200",
              )}
            >
              {msg.role === "assistant" ? (
                <Bot className="h-3.5 w-3.5 text-white" />
              ) : (
                <User className="h-3.5 w-3.5 text-gray-600" />
              )}
            </div>

            {/* Bubble */}
            <div
              className={cn(
                "max-w-[82%] rounded-2xl px-4 py-3 text-sm leading-relaxed",
                msg.role === "assistant"
                  ? "bg-white border border-gray-200 text-gray-800 shadow-sm"
                  : "bg-gray-900 text-white",
              )}
            >
              {msg.loading ? (
                <div className="flex items-center gap-1.5 py-0.5">
                  {[0, 1, 2].map((i) => (
                    <div
                      key={i}
                      className="h-2 w-2 rounded-full bg-gray-300 animate-bounce"
                      style={{ animationDelay: `${i * 0.15}s` }}
                    />
                  ))}
                </div>
              ) : (
                <div className="whitespace-pre-wrap">{renderRich(msg.content)}</div>
              )}
            </div>
          </div>
        ))}
        <div ref={bottomRef} />
      </div>

      {/* Suggestion chips */}
      {suggestions && suggestions.length > 0 && messages.length <= 1 && (
        <div className="flex flex-wrap gap-1.5 mb-3 flex-shrink-0">
          {suggestions.map((s) => (
            <button
              key={s}
              onClick={() => sendMessage(s)}
              className="text-xs px-3 py-1.5 rounded-xl border border-gray-200 text-gray-600 hover:border-amber-300 hover:text-amber-700 hover:bg-amber-50 transition-all"
            >
              {s}
            </button>
          ))}
        </div>
      )}

      {/* Input area */}
      <div className="flex-shrink-0 flex gap-2 pt-3 border-t border-gray-100">
        <input
          ref={inputRef}
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && !e.shiftKey && sendMessage()}
          placeholder="Posez votre question sur les courses…"
          className="flex-1 rounded-2xl border border-gray-200 bg-white px-4 py-3 text-sm outline-none focus:border-amber-400 focus:ring-2 focus:ring-amber-100 placeholder:text-gray-600 transition-all"
          disabled={streaming}
        />
        <button
          onClick={() => sendMessage()}
          disabled={!input.trim() || streaming}
          className="h-12 w-12 rounded-2xl bg-amber-500 hover:bg-amber-600 disabled:opacity-40 text-brand-dark flex items-center justify-center transition-all flex-shrink-0 shadow-sm shadow-amber-200"
        >
          {streaming ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
        </button>
      </div>

      <p className="text-center text-[10px] text-gray-600 mt-2 flex-shrink-0">
        Outil d&apos;aide à la décision — aucune garantie de gain — jouez de façon responsable
      </p>
    </div>
  );
}
