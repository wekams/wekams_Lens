// Backend API client. Single place that knows about NEXT_PUBLIC_API_BASE.
// Components never reference the URL directly.

export type Role = "system" | "user" | "assistant" | "tool";

export type ToolCallSpec = {
  id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type Message = {
  role: Role;
  content: string;
  // Only populated on role == "assistant" turns that called tools.
  tool_calls?: ToolCallSpec[];
  // Only populated on role == "tool" responses; the call id this answers.
  tool_call_id?: string;
};

export type ToolCallEvent = {
  type: "tool_call";
  call_id: string;
  name: string;
  arguments: Record<string, unknown>;
};

export type ToolResultData = {
  columns: string[];
  rows: Record<string, unknown>[];
  row_count: number;
  truncated: boolean;
  // Lineage / trace metadata (added in the trace-panel feature). All optional
  // so older persisted conversations still render cleanly.
  sources?: string[];
  referenced_tables?: string[];
  validated?: boolean;
  elapsed_ms?: number;
  federated?: boolean;
  estimated_rows?: number | null;
};

export type ToolResultEvent = {
  type: "tool_result";
  call_id: string;
  name: string;
  ok: boolean;
  summary: string;
  data: ToolResultData | null;
};

export type ConversationEvent = {
  type: "conversation";
  id: string;
  title: string;
};

export type StreamEvent =
  | { type: "token"; text: string }
  | { type: "done" }
  | { type: "error"; message: string }
  | ToolCallEvent
  | ToolResultEvent
  | ConversationEvent;

import { API_BASE, apiFetch } from "./auth";

/**
 * Stream a chat completion from the backend.
 *
 * The backend emits SSE events. We read the response body as a stream of
 * UTF-8 chunks, split on the SSE delimiter (\n\n after CRLF normalization),
 * and parse each `data:` line as JSON. Yields events as they arrive.
 */
export async function* streamChat(
  messages: Message[],
  options: { conversationId?: string | null; signal?: AbortSignal } = {},
): AsyncGenerator<StreamEvent> {
  const body: Record<string, unknown> = { messages };
  if (options.conversationId) body.conversation_id = options.conversationId;
  const response = await apiFetch(`${API_BASE}/api/v1/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal: options.signal,
  });

  if (!response.ok || !response.body) {
    yield {
      type: "error",
      message: `HTTP ${response.status} ${response.statusText}`,
    };
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    // sse_starlette emits CRLF line endings; normalize to LF so the rest
    // of the parser is line-ending agnostic.
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");

    let delimIdx;
    while ((delimIdx = buffer.indexOf("\n\n")) !== -1) {
      const rawEvent = buffer.slice(0, delimIdx);
      buffer = buffer.slice(delimIdx + 2);

      for (const line of rawEvent.split("\n")) {
        if (!line.startsWith("data:")) continue;
        const payload = line.slice(5).trim();
        if (!payload) continue;
        try {
          yield JSON.parse(payload) as StreamEvent;
        } catch {
          // Ignore malformed chunks; backend logs them.
        }
      }
    }
  }
}
