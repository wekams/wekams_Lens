"use client";

import { useEffect, useState } from "react";
import {
  deleteConversation,
  listConversations,
  type ConversationListItem,
} from "@/lib/conversations";

type Props = {
  selectedId: string | null;
  onSelect: (id: string | null) => void;
  // Bump this number to force a refresh (e.g. after a new conversation
  // gets a title from the first user message).
  refreshKey?: number;
};

export default function ConversationSidebar({
  selectedId,
  onSelect,
  refreshKey,
}: Props) {
  const [items, setItems] = useState<ConversationListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    listConversations()
      .then((cs) => {
        if (alive) setItems(cs);
      })
      .catch((e) => {
        if (alive) setErr(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [refreshKey]);

  async function onDelete(id: string, ev: React.MouseEvent) {
    ev.stopPropagation();
    if (!confirm("Delete this conversation? This cannot be undone.")) return;
    try {
      await deleteConversation(id);
      setItems((cur) => cur.filter((c) => c.id !== id));
      if (selectedId === id) onSelect(null);
    } catch (e) {
      alert(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <aside className="flex w-64 shrink-0 flex-col overflow-hidden border-r border-border bg-panel">
      <div className="flex items-center justify-between border-b border-border px-4 py-3">
        <h2 className="text-sm font-semibold">Chats</h2>
        <button
          onClick={() => onSelect(null)}
          className="rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-bg"
          title="Start a new conversation"
        >
          + New
        </button>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading && <div className="px-4 py-3 text-xs text-muted">Loading…</div>}
        {err && (
          <div className="m-3 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {err}
          </div>
        )}
        {!loading && items.length === 0 && !err && (
          <div className="px-4 py-3 text-xs text-muted">
            No conversations yet. Send a message to start one.
          </div>
        )}
        <ul className="divide-y divide-border">
          {items.map((c) => {
            const selected = selectedId === c.id;
            return (
              <li key={c.id}>
                {/* Row is a div (not a button) so the inline delete button
                    isn't a nested button — HTML doesn't allow that and
                    React's hydration check rightly flags it. */}
                <div
                  role="button"
                  tabIndex={0}
                  onClick={() => onSelect(c.id)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" || e.key === " ") {
                      e.preventDefault();
                      onSelect(c.id);
                    }
                  }}
                  className={`group flex w-full cursor-pointer items-start gap-2 px-4 py-2.5 text-left hover:bg-neutral-900/50 focus:outline-none focus:bg-neutral-900/70 ${
                    selected ? "bg-neutral-900/70" : ""
                  }`}
                >
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{c.title}</div>
                    <div className="text-xs text-muted">
                      {c.message_count} msg · {relativeTime(c.updated_at)}
                    </div>
                  </div>
                  <button
                    type="button"
                    onClick={(e) => void onDelete(c.id, e)}
                    className="opacity-0 transition group-hover:opacity-100 text-muted hover:text-red-400"
                    title="Delete"
                  >
                    ×
                  </button>
                </div>
              </li>
            );
          })}
        </ul>
      </div>
    </aside>
  );
}

function relativeTime(iso: string): string {
  const diffSec = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
  if (diffSec < 60) return "just now";
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m ago`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}h ago`;
  if (diffSec < 86400 * 7) return `${Math.floor(diffSec / 86400)}d ago`;
  return new Date(iso).toLocaleDateString();
}
