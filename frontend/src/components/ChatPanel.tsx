import { FormEvent, useEffect, useRef, useState } from "react";
import { resolveAssetUrl } from "../api";
import type { Message, Role } from "../types";

type Props = {
  conversationId: string | null;
  role: Role | null;
  messages: Message[];
  loading: boolean;
  sending: boolean;
  error: string | null;
  onSend: (content: string) => Promise<void>;
  onReset: () => Promise<void>;
};

export function ChatPanel({
  conversationId,
  role,
  messages,
  loading,
  sending,
  error,
  onSend,
  onReset,
}: Props) {
  const [input, setInput] = useState("");
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, sending]);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const content = input.trim();
    if (!content || sending || !conversationId) return;
    setInput("");
    await onSend(content);
  }

  return (
    <section className="mx-auto flex h-[calc(100vh-7rem)] min-h-[560px] w-full max-w-4xl flex-col overflow-hidden rounded-[28px] border border-white/70 bg-paper shadow-soft">
      <header className="flex items-center justify-between border-b border-stone-200/80 bg-white/60 px-6 py-4 backdrop-blur">
        <div className="flex min-w-0 items-center gap-3">
          <img
            src={resolveAssetUrl(role?.avatar ?? null) ?? undefined}
            alt={role?.display_name ?? "角色头像"}
            className="h-12 w-12 rounded-2xl border border-white object-cover shadow-sm"
          />
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <h1 className="truncate text-lg font-semibold text-ink">{role?.display_name ?? "正在连接…"}</h1>
              <span className="h-2 w-2 rounded-full bg-emerald-500" aria-label="在线" />
            </div>
            <p className="truncate text-sm text-stone-500">{role?.description ?? "正在加载角色资料"}</p>
          </div>
        </div>
        <button
          type="button"
          onClick={() => void onReset()}
          disabled={loading || sending}
          className="rounded-xl border border-stone-200 bg-white px-3 py-2 text-sm text-stone-600 transition hover:border-stone-300 hover:text-ink disabled:opacity-50"
        >
          新对话
        </button>
      </header>

      <div className="scrollbar-thin flex-1 space-y-5 overflow-y-auto px-5 py-6 sm:px-8">
        {loading && <p className="py-20 text-center text-sm text-stone-500">正在恢复对话…</p>}
        {!loading && messages.length === 0 && (
          <div className="mx-auto mt-16 max-w-md rounded-2xl border border-stone-200/70 bg-white/60 px-5 py-4 text-center text-sm leading-6 text-stone-600">
            雨刚停，旧书店里很安静。和小满打个招呼吧。
          </div>
        )}

        {messages.map((message) => {
          const isUser = message.sender === "user";
          return (
            <article key={message.id} className={`flex ${isUser ? "justify-end" : "justify-start"}`}>
              <div className={`max-w-[78%] ${isUser ? "items-end" : "items-start"} flex flex-col gap-2`}>
                <div
                  className={`rounded-2xl px-4 py-3 text-[15px] leading-6 shadow-sm ${
                    isUser
                      ? "rounded-br-md bg-moss text-white"
                      : "rounded-bl-md border border-stone-200/70 bg-white text-ink"
                  }`}
                >
                  {message.content}
                </div>
                {message.asset_url && (
                  <img
                    src={resolveAssetUrl(message.asset_url) ?? undefined}
                    alt="角色发送的剧情图片"
                    className="max-h-[420px] w-full max-w-md rounded-2xl border-4 border-white object-cover shadow-soft"
                  />
                )}
              </div>
            </article>
          );
        })}

        {sending && (
          <div className="flex justify-start">
            <div className="flex items-center gap-1 rounded-2xl rounded-bl-md border border-stone-200 bg-white px-4 py-3" aria-label="角色正在输入">
              <span className="h-2 w-2 rounded-full bg-stone-400" />
              <span className="h-2 w-2 rounded-full bg-stone-300" />
              <span className="h-2 w-2 rounded-full bg-stone-200" />
            </div>
          </div>
        )}
        <div ref={endRef} />
      </div>

      <footer className="border-t border-stone-200/80 bg-white/55 p-4 sm:p-5">
        {error && <p className="mb-3 rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700">{error}</p>}
        <form onSubmit={submit} className="flex gap-3">
          <input
            value={input}
            onChange={(event) => setInput(event.target.value)}
            placeholder="输入消息…"
            maxLength={2000}
            disabled={!conversationId || loading || sending}
            className="min-w-0 flex-1 rounded-2xl border border-stone-200 bg-white px-4 py-3 text-ink outline-none transition placeholder:text-stone-400 focus:border-clay focus:ring-4 focus:ring-clay/10 disabled:bg-stone-100"
          />
          <button
            type="submit"
            disabled={!input.trim() || !conversationId || loading || sending}
            className="rounded-2xl bg-clay px-5 py-3 font-medium text-white transition hover:bg-[#925844] disabled:cursor-not-allowed disabled:opacity-45"
          >
            发送
          </button>
        </form>
      </footer>
    </section>
  );
}
