"use client";

import { useState } from "react";
import {
  deleteSource as apiDelete,
  syncSource as apiSync,
  type SourceView,
} from "@/lib/sources";

type Props = {
  source: SourceView;
  onChange: (s: SourceView | null) => void;
};

const STATUS_COLOR: Record<string, string> = {
  ready: "bg-accent/20 text-accent",
  pending: "bg-yellow-500/20 text-yellow-300",
  error: "bg-red-500/20 text-red-300",
  disabled: "bg-neutral-500/20 text-neutral-400",
};

export default function SourceDetail({ source, onChange }: Props) {
  const [busy, setBusy] = useState<"sync" | "delete" | null>(null);
  const [err, setErr] = useState<string | null>(null);

  async function onSync() {
    setBusy("sync");
    setErr(null);
    try {
      const refreshed = await apiSync(source.id);
      onChange(refreshed);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }

  async function onDelete() {
    if (!confirm(`Delete source "${source.name}"? This removes it from the catalog only — your actual database is untouched.`)) {
      return;
    }
    setBusy("delete");
    setErr(null);
    try {
      await apiDelete(source.id);
      onChange(null);
    } catch (e) {
      setErr(e instanceof Error ? e.message : String(e));
      setBusy(null);
    }
  }

  const config = source.config as Record<string, unknown>;
  const statusClass = STATUS_COLOR[source.status] ?? "bg-neutral-500/20 text-neutral-400";

  return (
    <div className="space-y-5">
      <div>
        <div className="flex items-baseline justify-between">
          <div>
            <h2 className="text-base font-semibold">{source.name}</h2>
            <div className="mt-0.5 text-xs text-muted">{source.type}</div>
          </div>
          <div className="flex items-center gap-2">
            <span className={`rounded px-2 py-0.5 text-xs uppercase tracking-wider ${statusClass}`}>
              {source.status}
            </span>
            <button
              onClick={onSync}
              disabled={busy !== null}
              className="rounded-md border border-border px-2.5 py-1 text-xs hover:bg-panel disabled:opacity-50"
            >
              {busy === "sync" ? "Syncing…" : "Re-sync"}
            </button>
            <button
              onClick={onDelete}
              disabled={busy !== null}
              className="rounded-md border border-red-900 px-2.5 py-1 text-xs text-red-300 hover:bg-red-950/40 disabled:opacity-50"
            >
              Delete
            </button>
          </div>
        </div>

        {err && (
          <div className="mt-3 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {err}
          </div>
        )}

        {source.status === "error" && source.last_error && (
          <div className="mt-3 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            <div className="font-medium">Last sync failed:</div>
            <div className="mt-0.5 font-mono">{source.last_error}</div>
          </div>
        )}
      </div>

      <section>
        <h3 className="mb-2 text-xs uppercase tracking-wider text-muted">Connection</h3>
        <div className="rounded-md border border-border bg-panel">
          <dl className="divide-y divide-border text-sm">
            {Object.entries(config).map(([k, v]) => (
              <div key={k} className="flex gap-3 px-3 py-2">
                <dt className="w-32 text-muted">{k}</dt>
                <dd className="font-mono text-neutral-200">
                  {Array.isArray(v) ? v.join(", ") : String(v)}
                </dd>
              </div>
            ))}
          </dl>
        </div>
      </section>

      <section>
        <h3 className="mb-2 text-xs uppercase tracking-wider text-muted">
          Catalog ({source.tables.length} table{source.tables.length === 1 ? "" : "s"})
        </h3>
        {source.tables.length === 0 ? (
          <div className="rounded-md border border-border bg-panel px-3 py-3 text-xs text-muted">
            No tables introspected yet. Hit Re-sync to refresh.
          </div>
        ) : (
          <div className="space-y-2">
            {source.tables.map((t) => (
              <TableCard key={`${t.schema_name}.${t.name}`} table={t} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function TableCard({ table }: { table: SourceView["tables"][number] }) {
  const [open, setOpen] = useState(false);
  return (
    <div className="overflow-hidden rounded-md border border-border bg-panel">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex w-full items-center justify-between px-3 py-2 text-left hover:bg-neutral-900/50"
      >
        <div>
          <div className="text-sm">
            <span className="text-muted">{table.schema_name}.</span>
            <span className="font-medium">{table.name}</span>
          </div>
          {table.description && (
            <div className="mt-0.5 text-xs text-muted">{table.description}</div>
          )}
        </div>
        <div className="flex items-center gap-3 text-xs text-muted">
          <span>{table.columns.length} cols</span>
          {table.row_count_est !== null && <span>~{table.row_count_est} rows</span>}
          <span className="text-neutral-500">{open ? "▾" : "▸"}</span>
        </div>
      </button>
      {open && (
        <div className="border-t border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-neutral-900/50 text-muted">
                <th className="px-3 py-1.5 text-left font-normal">name</th>
                <th className="px-3 py-1.5 text-left font-normal">type</th>
                <th className="px-3 py-1.5 text-left font-normal">flags</th>
                <th className="px-3 py-1.5 text-left font-normal">description</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((c) => (
                <tr key={c.name} className="border-b border-border/50 last:border-0">
                  <td className="px-3 py-1 font-mono text-neutral-200">{c.name}</td>
                  <td className="px-3 py-1 font-mono text-neutral-300">{c.data_type}</td>
                  <td className="px-3 py-1 text-muted">
                    {[c.is_primary_key && "PK", !c.nullable && "NOT NULL"]
                      .filter(Boolean)
                      .join(" · ") || "—"}
                  </td>
                  <td className="px-3 py-1 text-muted">{c.description ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
