// Conversations API client.

import type { ToolResultData } from "./api";

import { API_BASE, apiFetch } from "./auth";

export type StoredMessage = {
  id: string;
  sequence: number;
  role: "system" | "user" | "assistant" | "tool";
  content: string;
  tool_calls?: Array<{
    id: string;
    type: "function";
    function: { name: string; arguments: string };
  }> | null;
  tool_call_id?: string | null;
  tool_data?: ToolResultData | null;
  created_at: string;
};

export type ConversationListItem = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages: never[]; // list endpoint omits messages
};

export type ConversationFull = {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
  message_count: number;
  messages: StoredMessage[];
};

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    let msg = `HTTP ${res.status}`;
    try {
      const body = JSON.parse(text);
      msg = body.detail ?? body.message ?? msg;
    } catch {
      if (text) msg = text;
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function listConversations(): Promise<ConversationListItem[]> {
  return jsonOrThrow<ConversationListItem[]>(
    await apiFetch(`${API_BASE}/api/v1/conversations`),
  );
}

export async function getConversation(id: string): Promise<ConversationFull> {
  return jsonOrThrow<ConversationFull>(
    await apiFetch(`${API_BASE}/api/v1/conversations/${id}`),
  );
}

export async function createConversation(title?: string): Promise<ConversationFull> {
  return jsonOrThrow<ConversationFull>(
    await apiFetch(`${API_BASE}/api/v1/conversations`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function deleteConversation(id: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/api/v1/conversations/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) throw new Error(`HTTP ${res.status}`);
}

export async function renameConversation(
  id: string,
  title: string,
): Promise<ConversationListItem> {
  return jsonOrThrow<ConversationListItem>(
    await apiFetch(`${API_BASE}/api/v1/conversations/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title }),
    }),
  );
}

export async function fetchConversationMarkdown(id: string): Promise<string> {
  const res = await apiFetch(`${API_BASE}/api/v1/conversations/${id}/export.md`);
  if (!res.ok) {
    throw new Error(`HTTP ${res.status}`);
  }
  return res.text();
}

export function downloadConversationMarkdownUrl(id: string): string {
  return `${API_BASE}/api/v1/conversations/${id}/export.md?download=1`;
}
