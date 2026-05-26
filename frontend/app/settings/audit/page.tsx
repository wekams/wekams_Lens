"use client";

import { useCallback, useEffect, useState } from "react";
import { listAudit, type AuditEvent, type AuditPage } from "@/lib/audit";

const PAGE_SIZE = 50;

const KNOWN_TYPES = [
  "chat.query",
  "source.created",
  "source.deleted",
  "source.synced",
  "license.activated",
  "license.deactivated",
];

export default function AuditPage() {
  const [page, setPage] = useState<AuditPage | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [filterType, setFilterType] = useState<string>("");
  const [offset, setOffset] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    try {
      const p = await listAudit({
        limit: PAGE_SIZE,
        offset,
        event_type: filterType || undefined,
      });
      setPage(p);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load audit log");
      setPage(null);
    }
  }, [offset, filterType]);

  useEffect(() => {
    void load();
  }, [load]);

  function exportCsv() {
    if (!page || page.events.length === 0) return;
    const headers = [
      "occurred_at",
      "event_type",
      "outcome",
      "actor",
      "source_name",
      "license_id",
      "payload",
    ];
    const escape = (v: unknown) => {
      const s = v === null || v === undefined ? "" : typeof v === "object" ? JSON.stringify(v) : String(v);
      return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
    };
    const rows = page.events.map((e) =>
      headers
        .map((h) => escape(h === "payload" ? e.payload : (e as Record<string, unknown>)[h]))
        .join(","),
    );
    const blob = new Blob([headers.join(",") + "\n" + rows.join("\n")], {
      type: "text/csv;charset=utf-8;",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `wekams-audit-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  if (page === undefined) {
    return <div className="mx-auto max-w-6xl p-6 text-sm text-muted">Loading audit log…</div>;
  }

  if (page === null) {
    return (
      <div className="mx-auto max-w-6xl p-6">
        <h1 className="text-lg font-semibold">Audit log</h1>
        <p className="mt-2 text-sm text-muted">
          The audit log is a Pro / Enterprise feature. This instance is running
          the Community Edition, which doesn't record audit events.
        </p>
        {error && (
          <p className="mt-3 rounded-md border border-red-900/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto max-w-6xl p-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-semibold">Audit log</h1>
          <p className="mt-1 text-sm text-muted">
            Every security-relevant action that has occurred on this instance.
            Use the filter to narrow the view.
          </p>
        </div>
        <button
          type="button"
          onClick={exportCsv}
          disabled={page.events.length === 0}
          className="rounded-md border border-border bg-panel px-3 py-1.5 text-xs hover:bg-panel-2 disabled:opacity-50"
        >
          Export CSV
        </button>
      </div>

      <div className="mt-4 flex items-center gap-3 text-xs">
        <label className="text-muted" htmlFor="filterType">
          Filter:
        </label>
        <select
          id="filterType"
          value={filterType}
          onChange={(e) => {
            setOffset(0);
            setFilterType(e.target.value);
          }}
          className="rounded-md border border-border bg-bg px-2 py-1 text-xs text-neutral-100"
        >
          <option value="">All events</option>
          {KNOWN_TYPES.map((t) => (
            <option key={t} value={t}>
              {t}
            </option>
          ))}
        </select>
        <span className="ml-auto text-muted">
          Showing {page.count} event{page.count === 1 ? "" : "s"}
          {offset > 0 && <> (offset {offset})</>}
        </span>
      </div>

      {page.events.length === 0 ? (
        <div className="mt-6 rounded-md border border-border bg-panel px-4 py-6 text-center text-xs text-muted">
          No audit events yet. Activity will appear here as you query sources,
          register data sources, and manage licenses.
        </div>
      ) : (
        <div className="mt-4 overflow-hidden rounded-md border border-border bg-panel">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-neutral-900/50 text-left text-muted">
                <th className="px-3 py-2 font-medium">When</th>
                <th className="px-3 py-2 font-medium">Event</th>
                <th className="px-3 py-2 font-medium">Source</th>
                <th className="px-3 py-2 font-medium">Outcome</th>
                <th className="px-3 py-2 font-medium">Details</th>
              </tr>
            </thead>
            <tbody>
              {page.events.map((e) => (
                <Row key={e.id} event={e} />
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="mt-4 flex items-center gap-2 text-xs">
        <button
          type="button"
          onClick={() => setOffset(Math.max(0, offset - PAGE_SIZE))}
          disabled={offset === 0}
          className="rounded-md border border-border bg-panel px-3 py-1.5 hover:bg-panel-2 disabled:opacity-50"
        >
          ← Newer
        </button>
        <button
          type="button"
          onClick={() => setOffset(offset + PAGE_SIZE)}
          disabled={page.count < PAGE_SIZE}
          className="rounded-md border border-border bg-panel px-3 py-1.5 hover:bg-panel-2 disabled:opacity-50"
        >
          Older →
        </button>
      </div>
    </div>
  );
}

function Row({ event }: { event: AuditEvent }) {
  const [open, setOpen] = useState(false);
  const when = new Date(event.occurred_at);
  const ago = formatAgo(when);
  return (
    <>
      <tr className="border-b border-border/50 last:border-0 hover:bg-neutral-900/30">
        <td className="px-3 py-2 align-top tabular-nums text-neutral-300" title={event.occurred_at}>
          {ago}
        </td>
        <td className="px-3 py-2 align-top font-mono text-emerald-300">{event.event_type}</td>
        <td className="px-3 py-2 align-top text-neutral-300">{event.source_name ?? "—"}</td>
        <td className="px-3 py-2 align-top">
          <span
            className={
              event.outcome === "ok"
                ? "text-emerald-400"
                : event.outcome === "denied"
                  ? "text-yellow-400"
                  : "text-red-400"
            }
          >
            {event.outcome}
          </span>
        </td>
        <td className="px-3 py-2 align-top">
          <button
            type="button"
            onClick={() => setOpen((v) => !v)}
            className="text-muted hover:text-neutral-200"
          >
            {open ? "Hide" : "View"}
          </button>
        </td>
      </tr>
      {open && (
        <tr className="border-b border-border/50">
          <td colSpan={5} className="bg-neutral-900/40 px-3 py-3">
            <pre className="overflow-x-auto whitespace-pre-wrap font-mono text-[11px] text-neutral-300">
              {JSON.stringify(event.payload, null, 2)}
            </pre>
          </td>
        </tr>
      )}
    </>
  );
}

function formatAgo(d: Date): string {
  const seconds = (Date.now() - d.getTime()) / 1000;
  if (seconds < 60) return `${Math.floor(seconds)}s ago`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return d.toISOString().slice(0, 19).replace("T", " ");
}
