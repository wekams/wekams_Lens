"use client";

import { useCallback, useEffect, useState } from "react";
import AddSourceForm from "@/components/AddSourceForm";
import SourceDetail from "@/components/SourceDetail";
import {
  getSource,
  listSources,
  type SourceView,
} from "@/lib/sources";

type RightPane = { kind: "empty" } | { kind: "add" } | { kind: "view"; source: SourceView };

const STATUS_DOT: Record<string, string> = {
  ready: "bg-accent",
  pending: "bg-yellow-500",
  error: "bg-red-500",
  disabled: "bg-neutral-500",
};

export default function SourcesPage() {
  const [sources, setSources] = useState<SourceView[]>([]);
  const [loading, setLoading] = useState(true);
  const [listError, setListError] = useState<string | null>(null);
  const [right, setRight] = useState<RightPane>({ kind: "empty" });

  const refresh = useCallback(async () => {
    setLoading(true);
    setListError(null);
    try {
      const next = await listSources();
      setSources(next);
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  // Re-poll a single source while it's pending (initial sync runs in
  // background after POST). Stops once status becomes ready or error.
  async function selectSource(id: string) {
    try {
      let s = await getSource(id);
      setRight({ kind: "view", source: s });
      let tries = 0;
      while (s.status === "pending" && tries < 10) {
        await new Promise((r) => setTimeout(r, 800));
        s = await getSource(id);
        setRight({ kind: "view", source: s });
        tries += 1;
      }
      void refresh();
    } catch (e) {
      setListError(e instanceof Error ? e.message : String(e));
    }
  }

  function onSourceChanged(s: SourceView | null) {
    if (s === null) {
      setRight({ kind: "empty" });
      void refresh();
    } else {
      setRight({ kind: "view", source: s });
      setSources((cur) => cur.map((x) => (x.id === s.id ? s : x)));
    }
  }

  return (
    <div className="flex h-full">
      {/* Left: list */}
      <aside className="w-72 shrink-0 overflow-y-auto border-r border-border bg-panel">
        <div className="flex items-center justify-between border-b border-border px-4 py-3">
          <h2 className="text-sm font-semibold">Sources</h2>
          <button
            onClick={() => setRight({ kind: "add" })}
            className="rounded-md bg-accent px-2.5 py-1 text-xs font-medium text-bg"
          >
            + Add
          </button>
        </div>

        {loading && <div className="px-4 py-3 text-xs text-muted">Loading…</div>}
        {listError && (
          <div className="m-3 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {listError}
          </div>
        )}

        {!loading && sources.length === 0 && !listError && (
          <div className="px-4 py-3 text-xs text-muted">
            No sources yet. Click <span className="font-medium">+ Add</span> to connect a Postgres database.
          </div>
        )}

        <ul className="divide-y divide-border">
          {sources.map((s) => {
            const selected = right.kind === "view" && right.source.id === s.id;
            const dot = STATUS_DOT[s.status] ?? "bg-neutral-500";
            return (
              <li key={s.id}>
                <button
                  onClick={() => void selectSource(s.id)}
                  className={`flex w-full items-center gap-2 px-4 py-2.5 text-left hover:bg-neutral-900/50 ${
                    selected ? "bg-neutral-900/70" : ""
                  }`}
                >
                  <span className={`h-2 w-2 shrink-0 rounded-full ${dot}`} />
                  <div className="min-w-0 flex-1">
                    <div className="truncate text-sm">{s.name}</div>
                    <div className="text-xs text-muted">
                      {s.type} · {s.status}
                    </div>
                  </div>
                </button>
              </li>
            );
          })}
        </ul>
      </aside>

      {/* Right: detail or add form */}
      <section className="flex-1 overflow-y-auto">
        <div className="mx-auto max-w-3xl px-6 py-8">
          {right.kind === "empty" && (
            <div className="text-sm text-muted">
              Select a source on the left to inspect its catalog, or click <span className="font-medium">+ Add</span> to connect a new one.
            </div>
          )}
          {right.kind === "add" && (
            <AddSourceForm
              onCancel={() => setRight({ kind: "empty" })}
              onCreated={(s) => {
                void refresh();
                void selectSource(s.id);
              }}
            />
          )}
          {right.kind === "view" && (
            <SourceDetail source={right.source} onChange={onSourceChanged} />
          )}
        </div>
      </section>
    </div>
  );
}
