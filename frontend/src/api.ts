import type { Conversation, DebugSnapshot, Message, Role } from "./types";

const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: { "Content-Type": "application/json", ...options?.headers },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`${response.status}: ${detail || response.statusText}`);
  }
  return response.json() as Promise<T>;
}

export function resolveAssetUrl(url: string | null): string | null {
  if (!url || /^https?:\/\//.test(url)) return url;
  return `${API_BASE}${url}`;
}

export const api = {
  listRoles: () => request<Role[]>("/api/roles"),
  createConversation: (roleId: string) =>
    request<Conversation>("/api/conversations", {
      method: "POST",
      body: JSON.stringify({ role_id: roleId }),
    }),
  listMessages: (conversationId: string) =>
    request<Message[]>(`/api/conversations/${conversationId}/messages`),
  sendMessage: (conversationId: string, content: string) =>
    request<Message>(`/api/conversations/${conversationId}/messages`, {
      method: "POST",
      body: JSON.stringify({ content }),
    }),
  getDebug: (conversationId: string) =>
    request<DebugSnapshot>(`/api/conversations/${conversationId}/debug`),
};
