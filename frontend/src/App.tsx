import { useCallback, useEffect, useState } from "react";
import { api } from "./api";
import { AdminPanel } from "./components/AdminPanel";
import { ChatPanel } from "./components/ChatPanel";
import type { Message, Role } from "./types";

const STORAGE_KEY = "personaflow.conversation_id";

function currentView(): "chat" | "admin" {
  return window.location.hash === "#/admin" ? "admin" : "chat";
}

export default function App() {
  const [view, setView] = useState<"chat" | "admin">(currentView());
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [role, setRole] = useState<Role | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);

  const createConversation = useCallback(async () => {
    const roles = await api.listRoles();
    const selectedRole = roles.find((item) => item.role_id === "miko_cafe") ?? roles[0];
    if (!selectedRole) throw new Error("没有可用角色");
    const conversation = await api.createConversation(selectedRole.role_id);
    localStorage.setItem(STORAGE_KEY, conversation.id);
    setRole(selectedRole);
    setConversationId(conversation.id);
    setMessages([]);
    setRevision((value) => value + 1);
  }, []);

  useEffect(() => {
    const onHashChange = () => setView(currentView());
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);

  useEffect(() => {
    async function bootstrap() {
      setLoading(true);
      try {
        const roles = await api.listRoles();
        const selectedRole = roles.find((item) => item.role_id === "miko_cafe") ?? roles[0] ?? null;
        setRole(selectedRole);
        const savedId = localStorage.getItem(STORAGE_KEY);
        if (savedId) {
          try {
            const history = await api.listMessages(savedId);
            const debug = await api.getDebug(savedId);
            setConversationId(savedId);
            setMessages(history);
            setRole(debug.role);
            return;
          } catch {
            localStorage.removeItem(STORAGE_KEY);
          }
        }
        await createConversation();
      } catch (err) {
        setError(err instanceof Error ? err.message : "初始化失败");
      } finally {
        setLoading(false);
      }
    }
    void bootstrap();
  }, [createConversation]);

  async function sendMessage(content: string) {
    if (!conversationId) return;
    const optimistic: Message = {
      id: `pending-${Date.now()}`,
      sender: "user",
      type: "text",
      content,
      asset_url: null,
      created_at: new Date().toISOString(),
    };
    setMessages((current) => [...current, optimistic]);
    setSending(true);
    setError(null);
    try {
      await api.sendMessage(conversationId, content);
      setMessages(await api.listMessages(conversationId));
      setRevision((value) => value + 1);
    } catch (err) {
      setMessages((current) => current.filter((message) => message.id !== optimistic.id));
      setError(err instanceof Error ? err.message : "消息发送失败");
    } finally {
      setSending(false);
    }
  }

  async function resetConversation() {
    setLoading(true);
    setError(null);
    try {
      await createConversation();
      window.location.hash = "#/chat";
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建新对话失败");
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="paper-noise min-h-screen px-4 py-4 sm:px-6 sm:py-5">
      <nav className="mx-auto mb-4 flex max-w-6xl items-center justify-between">
        <div className="flex items-center gap-2 text-sm font-semibold tracking-[0.18em] text-stone-600">
          <span className="grid h-8 w-8 place-items-center rounded-xl bg-ink text-xs text-white">PF</span>
          PERSONAFLOW
        </div>
        <div className="flex rounded-xl border border-white/70 bg-white/60 p-1 shadow-sm">
          <a href="#/chat" className={`rounded-lg px-4 py-2 text-sm ${view === "chat" ? "bg-ink text-white" : "text-stone-600"}`}>Chat</a>
          <a href="#/admin" className={`rounded-lg px-4 py-2 text-sm ${view === "admin" ? "bg-ink text-white" : "text-stone-600"}`}>Admin</a>
        </div>
      </nav>

      {view === "chat" ? (
        <ChatPanel
          conversationId={conversationId}
          role={role}
          messages={messages}
          loading={loading}
          sending={sending}
          error={error}
          onSend={sendMessage}
          onReset={resetConversation}
        />
      ) : (
        <AdminPanel conversationId={conversationId} revision={revision} />
      )}
    </main>
  );
}
