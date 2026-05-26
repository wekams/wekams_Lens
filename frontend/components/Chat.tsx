"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import ConversationSidebar from "@/components/ConversationSidebar";
import ExportMenu from "@/components/ExportMenu";
import {
  streamChat,
  type Message,
  type ToolCallEvent,
  type ToolResultData,
  type ToolResultEvent,
} from "@/lib/api";
import { getConversation, type StoredMessage } from "@/lib/conversations";

type Status = "idle" | "streaming" | "error";

type AssistantBlock =
  | { kind: "text"; text: string }
  | { kind: "tool_call"; call: ToolCallEvent }
  | { kind: "tool_result"; result: ToolResultEvent };

type Turn = { role: "user"; content: string } | { role: "assistant"; blocks: AssistantBlock[] };

// Keep the URL's ?chat= param in sync with the in-memory conversationId.
// Uses replaceState (not pushState) so back/forward don't whip the user
// through every conversation switch; reload + bookmark + share-link still
// work because the URL is updated in place.
function syncUrlChat(id: string | null): void {
  if (typeof window === "undefined") return;
  const url = new URL(window.location.href);
  if (id) {
    url.searchParams.set("chat", id);
  } else {
    url.searchParams.delete("chat");
  }
  window.history.replaceState(window.history.state, "", url.toString());
}

function readUrlChat(): string | null {
  if (typeof window === "undefined") return null;
  const v = new URL(window.location.href).searchParams.get("chat");
  return v && v.length > 0 ? v : null;
}

export default function Chat() {
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [conversationTitle, setConversationTitle] = useState<string>("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [loadingHistory, setLoadingHistory] = useState(false);
  const [input, setInput] = useState("");
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [sidebarRefresh, setSidebarRefresh] = useState(0);
  const endRef = useRef<HTMLDivElement | null>(null);

  // Auto-scroll on new content.
  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [turns, status]);

  // Explicit load: triggered only by user action (sidebar click / + New),
  // NEVER by setConversationId firing from inside the streaming loop —
  // which used to race with the optimistic local state and duplicate
  // the user message.
  const onSelectConversation = useCallback(async (id: string | null) => {
    setConversationId(id);
    syncUrlChat(id);
    setError(null);
    if (id === null) {
      setTurns([]);
      setConversationTitle("");
      return;
    }
    setLoadingHistory(true);
    try {
      const c = await getConversation(id);
      setTurns(storedToTurns(c.messages));
      setConversationTitle(c.title);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoadingHistory(false);
    }
  }, []);

  // On first mount, restore from ?chat=<id> if present.
  const restoredRef = useRef(false);
  useEffect(() => {
    if (restoredRef.current) return;
    restoredRef.current = true;
    const id = readUrlChat();
    if (id) void onSelectConversation(id);
  }, [onSelectConversation]);

  async function send() {
    const text = input.trim();
    if (!text || status === "streaming") return;

    const userTurn: Turn = { role: "user", content: text };
    const assistantTurn: Turn = { role: "assistant", blocks: [] };
    setTurns((prev) => [...prev, userTurn, assistantTurn]);
    setInput("");
    setStatus("streaming");
    setError(null);

    // The server is the source of truth for history once a conversation
    // exists; we only need to send the new user message.
    const messagesToSend: Message[] = [{ role: "user", content: text }];

    let assignedConvId = conversationId;
    try {
      for await (const ev of streamChat(messagesToSend, {
        conversationId: assignedConvId,
      })) {
        if (ev.type === "conversation") {
          if (assignedConvId !== ev.id) {
            assignedConvId = ev.id;
            setConversationId(ev.id);
            syncUrlChat(ev.id);
          }
          setConversationTitle(ev.title);
        } else if (ev.type === "token") {
          setTurns((cur) => appendToLastAssistant(cur, (blocks) => appendText(blocks, ev.text)));
        } else if (ev.type === "tool_call") {
          setTurns((cur) =>
            appendToLastAssistant(cur, (blocks) => [...blocks, { kind: "tool_call", call: ev }]),
          );
        } else if (ev.type === "tool_result") {
          setTurns((cur) =>
            appendToLastAssistant(cur, (blocks) => [...blocks, { kind: "tool_result", result: ev }]),
          );
        } else if (ev.type === "error") {
          setError(ev.message);
          setStatus("error");
          setSidebarRefresh((n) => n + 1);
          return;
        } else if (ev.type === "done") {
          break;
        }
      }
      setStatus("idle");
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    } finally {
      // Refresh sidebar so the title (derived from the first user message)
      // appears and the conversation moves to the top.
      setSidebarRefresh((n) => n + 1);
    }
  }

  function onKey(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      void send();
    }
  }

  return (
    <div className="flex h-full">
      <ConversationSidebar
        selectedId={conversationId}
        onSelect={onSelectConversation}
        refreshKey={sidebarRefresh}
      />

      <div className="flex flex-1 flex-col overflow-hidden">
        {conversationId && (
          <div className="flex items-center justify-between border-b border-border bg-bg px-6 py-2">
            <div className="min-w-0 flex-1 truncate text-sm text-neutral-300">
              {conversationTitle || "Conversation"}
            </div>
            <ExportMenu conversationId={conversationId} title={conversationTitle || "conversation"} />
          </div>
        )}
        <div className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-3xl px-6 py-8">
            {loadingHistory ? (
              <div className="text-sm text-muted">Loading conversation…</div>
            ) : turns.length === 0 ? (
              <div className="text-sm text-muted">
                Ask anything. With <code className="rounded bg-panel px-1">demo-shop</code>,{" "}
                <code className="rounded bg-panel px-1">demo-lake</code>, and{" "}
                <code className="rounded bg-panel px-1">checkout-logs</code> registered, try:
                <ul className="ml-5 mt-2 list-disc space-y-1">
                  <li>How many customers do we have?</li>
                  <li>Which of our customers viewed the checkout page?</li>
                  <li>Compare orders last 5 days vs the 9 before, and check checkout-logs for any failure spike.</li>
                </ul>
              </div>
            ) : (
              <div className="space-y-6">
                {turns.map((t, i) => (
                  <TurnView
                    key={i}
                    turn={t}
                    streamingLast={status === "streaming" && i === turns.length - 1}
                  />
                ))}
              </div>
            )}

            {error && (
              <div className="mt-6 rounded-md border border-red-900 bg-red-950/40 px-4 py-3 text-sm text-red-300">
                {error}
              </div>
            )}

            <div ref={endRef} />
          </div>
        </div>

        <footer className="border-t border-border bg-panel">
          <div className="mx-auto max-w-3xl px-6 py-4">
            <div className="flex items-end gap-3">
              <textarea
                value={input}
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKey}
                rows={1}
                placeholder="Ask Lens…"
                className="flex-1 resize-none rounded-md border border-border bg-bg px-3 py-2 text-sm placeholder:text-muted focus:border-accent focus:outline-none"
              />
              <button
                onClick={() => void send()}
                disabled={status === "streaming" || !input.trim()}
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg disabled:cursor-not-allowed disabled:opacity-50"
              >
                {status === "streaming" ? "…" : "Send"}
              </button>
            </div>
            <div className="mt-2 text-xs text-muted">
              Enter to send · Shift+Enter for newline
            </div>
          </div>
        </footer>
      </div>
    </div>
  );
}

// ── Helpers ───────────────────────────────────────────────────────

function appendToLastAssistant(
  turns: Turn[],
  fn: (blocks: AssistantBlock[]) => AssistantBlock[],
): Turn[] {
  const copy = turns.slice();
  const last = copy[copy.length - 1];
  if (last && last.role === "assistant") {
    copy[copy.length - 1] = { role: "assistant", blocks: fn(last.blocks) };
  }
  return copy;
}

function appendText(blocks: AssistantBlock[], text: string): AssistantBlock[] {
  const last = blocks[blocks.length - 1];
  if (last && last.kind === "text") {
    const merged = { ...last, text: last.text + text };
    return [...blocks.slice(0, -1), merged];
  }
  return [...blocks, { kind: "text", text }];
}

// Convert stored chat-message rows back into the Turn[] shape the UI renders.
function storedToTurns(messages: StoredMessage[]): Turn[] {
  const sorted = [...messages].sort((a, b) => a.sequence - b.sequence);
  const turns: Turn[] = [];

  function ensureAssistant(): Extract<Turn, { role: "assistant" }> {
    const last = turns[turns.length - 1];
    if (last && last.role === "assistant") return last;
    const fresh: Turn = { role: "assistant", blocks: [] };
    turns.push(fresh);
    return fresh as Extract<Turn, { role: "assistant" }>;
  }

  for (const m of sorted) {
    if (m.role === "user") {
      turns.push({ role: "user", content: m.content });
    } else if (m.role === "assistant") {
      const turn = ensureAssistant();
      if (m.tool_calls && m.tool_calls.length > 0) {
        for (const tc of m.tool_calls) {
          let args: Record<string, unknown> = {};
          try {
            args = JSON.parse(tc.function.arguments) as Record<string, unknown>;
          } catch {
            args = {};
          }
          turn.blocks.push({
            kind: "tool_call",
            call: {
              type: "tool_call",
              call_id: tc.id,
              name: tc.function.name,
              arguments: args,
            },
          });
        }
      }
      if (m.content) {
        turn.blocks.push({ kind: "text", text: m.content });
      }
    } else if (m.role === "tool") {
      const turn = ensureAssistant();
      // Persistence envelope is { ok, data } as of Phase 3-polish-c. Older
      // rows wrote the raw data dict directly; treat those as ok=true.
      const raw = m.tool_data as { ok?: boolean; data?: ToolResultData | null } | null;
      const hasEnvelope = !!raw && typeof raw === "object" && "ok" in raw;
      const ok = hasEnvelope ? raw!.ok !== false : true;
      const innerData: ToolResultData | null = hasEnvelope
        ? raw!.data ?? null
        : (m.tool_data as unknown as ToolResultData | null) ?? null;
      turn.blocks.push({
        kind: "tool_result",
        result: {
          type: "tool_result",
          call_id: m.tool_call_id ?? "",
          name: "query",
          ok,
          summary: m.content || "",
          data: innerData,
        },
      });
    }
  }
  return turns;
}

// ── Sub-components ────────────────────────────────────────────────

function TurnView({ turn, streamingLast }: { turn: Turn; streamingLast: boolean }) {
  if (turn.role === "user") {
    return (
      <div>
        <div className="mb-1 text-xs uppercase tracking-wider text-muted">You</div>
        <div className="whitespace-pre-wrap text-sm leading-relaxed">{turn.content}</div>
      </div>
    );
  }
  return (
    <div>
      <div className="mb-1 text-xs uppercase tracking-wider text-muted">Lens</div>
      <div className="space-y-3 text-sm leading-relaxed">
        {turn.blocks.length === 0 && streamingLast && <ThinkingDots />}
        {turn.blocks.map((b, i) => {
          if (b.kind === "text") {
            const isLast = i === turn.blocks.length - 1;
            return (
              <div key={i} className="whitespace-pre-wrap">
                {b.text}
                {streamingLast && isLast && (
                  <span className="ml-0.5 inline-block h-3 w-1.5 animate-pulse bg-accent align-baseline" />
                )}
              </div>
            );
          }
          if (b.kind === "tool_call") return <ToolCallView key={i} call={b.call} />;
          return <ToolResultView key={i} result={b.result} />;
        })}
      </div>
    </div>
  );
}

function ThinkingDots() {
  return (
    <div className="flex items-center gap-1 text-muted">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:0.2s]" />
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-muted [animation-delay:0.4s]" />
    </div>
  );
}

function ToolCallView({ call }: { call: ToolCallEvent }) {
  const sql = typeof call.arguments?.sql === "string" ? (call.arguments.sql as string) : "";
  const source = typeof call.arguments?.source === "string" ? (call.arguments.source as string) : "";
  const sourcesRaw = call.arguments?.sources;
  const sources = Array.isArray(sourcesRaw)
    ? (sourcesRaw.filter((s) => typeof s === "string") as string[])
    : [];
  const isFederated = call.name === "query_federated" || sources.length > 0;

  return (
    <div className="rounded-md border border-border bg-panel">
      <div className="flex items-center gap-2 border-b border-border px-3 py-1.5 text-xs text-muted">
        <span
          className={`inline-flex h-2 w-2 animate-pulse rounded-full ${
            isFederated ? "bg-purple-500" : "bg-yellow-500"
          }`}
        />
        <span className="uppercase tracking-wider text-neutral-300">
          {isFederated ? "Federating across" : "Querying"}
        </span>
        {isFederated ? (
          <span className="flex flex-wrap items-center gap-1">
            {sources.map((s, i) => (
              <span key={s} className="flex items-center gap-1">
                <code className="rounded bg-neutral-800 px-1.5 py-0.5 text-neutral-200">{s}</code>
                {i < sources.length - 1 && <span className="text-neutral-500">+</span>}
              </span>
            ))}
          </span>
        ) : (
          <>
            <span className="text-neutral-400">source:</span>
            <code className="text-neutral-200">{source}</code>
          </>
        )}
      </div>
      {sql && (
        <pre className="overflow-x-auto px-3 py-2 font-mono text-xs leading-relaxed text-neutral-200">
          {sql}
        </pre>
      )}
    </div>
  );
}

function ToolResultView({ result }: { result: ToolResultEvent }) {
  if (!result.ok) {
    return (
      <div className="overflow-hidden rounded-md border border-red-900/60 bg-red-950/30">
        <div className="flex items-center gap-2 border-b border-red-900/60 bg-red-950/40 px-3 py-1.5 text-xs">
          <span className="inline-flex h-2 w-2 rounded-full bg-red-500" />
          <span className="uppercase tracking-wider text-red-300">Query failed</span>
          <span className="text-red-300/60">— Lens will try a different approach</span>
        </div>
        <pre className="overflow-x-auto whitespace-pre-wrap px-3 py-2 font-mono text-xs text-red-200">
          {result.summary}
        </pre>
      </div>
    );
  }
  const data = result.data;
  if (!data || data.rows.length === 0) {
    return (
      <div className="rounded-md border border-border bg-panel px-3 py-2 text-xs text-muted">
        Query returned 0 rows.
      </div>
    );
  }

  const showRows = data.rows.slice(0, 10);
  const hasMore = data.row_count > showRows.length;

  return (
    <div className="overflow-hidden rounded-md border border-border bg-panel">
      <TraceStrip data={data} />
      <div className="flex items-center justify-between border-b border-border px-3 py-1.5 text-xs text-muted">
        <span>
          <span className="text-neutral-200">{data.row_count}</span> row{data.row_count === 1 ? "" : "s"}
          {hasMore && <span className="ml-1 text-neutral-400">(showing first {showRows.length})</span>}
          {data.truncated && <span className="ml-1 text-yellow-400">(truncated by row cap)</span>}
        </span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border bg-neutral-900/50">
              {data.columns.map((c) => (
                <th key={c} className="px-3 py-1.5 text-left font-medium text-neutral-300">
                  {c}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {showRows.map((row, i) => (
              <tr key={i} className="border-b border-border/50 last:border-0">
                {data.columns.map((c) => (
                  <td key={c} className="px-3 py-1.5 font-mono text-neutral-200">
                    {formatCell(row[c])}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function formatCell(v: unknown): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

/**
 * Compact lineage strip above the result table: which sources, how long,
 * federated yes/no, schema-validated yes/no. Renders nothing if the backend
 * didn't ship trace data (older persisted conversations).
 */
function TraceStrip({ data }: { data: ToolResultData }) {
  const sources = data.sources ?? [];
  const elapsed = data.elapsed_ms;
  const validated = data.validated === true;
  const federated = data.federated === true;
  const referenced = data.referenced_tables ?? [];

  if (sources.length === 0 && elapsed === undefined && !validated && !federated) {
    return null;
  }

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-border bg-neutral-900/40 px-3 py-1.5 text-[11px] text-neutral-400">
      {validated && (
        <span
          className="inline-flex items-center gap-1 text-emerald-400"
          title={referenced.length > 0 ? `Tables: ${referenced.join(", ")}` : "SQL parsed and all referenced tables/columns exist in the catalog"}
        >
          <span aria-hidden>✓</span>
          <span>Schema-validated</span>
        </span>
      )}

      {sources.length > 0 && (
        <span>
          {federated ? "Federated across" : "Source"}
          {sources.length === 1 ? ":" : ` ${sources.length} sources:`}{" "}
          <span className="font-mono text-neutral-200">{sources.join(" + ")}</span>
        </span>
      )}

      {!federated && referenced.length > 0 && (
        <span className="hidden sm:inline">
          tables: <span className="font-mono text-neutral-300">{referenced.join(", ")}</span>
        </span>
      )}

      {elapsed !== undefined && (
        <span className="ml-auto tabular-nums">{formatElapsed(elapsed)}</span>
      )}
    </div>
  );
}

function formatElapsed(ms: number): string {
  if (ms < 1000) return `${ms.toFixed(0)} ms`;
  return `${(ms / 1000).toFixed(2)} s`;
}
