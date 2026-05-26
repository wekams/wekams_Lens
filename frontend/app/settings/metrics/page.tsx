"use client";

import { useEffect, useState } from "react";
import {
  createMetric,
  deleteMetric,
  listMetrics,
  type Metric,
  type MetricCreate,
} from "@/lib/metrics";

export default function MetricsPage() {
  const [metrics, setMetrics] = useState<Metric[] | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  async function refresh() {
    try {
      setMetrics(await listMetrics());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load metrics");
      setMetrics(null);
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  if (metrics === undefined) {
    return <div className="mx-auto max-w-5xl p-6 text-sm text-muted">Loading metrics…</div>;
  }

  if (metrics === null) {
    return (
      <div className="mx-auto max-w-5xl p-6">
        <h1 className="text-lg font-semibold">Business metrics</h1>
        <p className="mt-2 text-sm text-muted">
          The semantic layer (metrics catalog) is a Pro / Enterprise feature.
          This instance is running the Community Edition, which doesn't expose
          centrally-defined metrics.
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
    <div className="mx-auto max-w-5xl p-6">
      <div className="flex items-baseline justify-between">
        <div>
          <h1 className="text-lg font-semibold">Business metrics</h1>
          <p className="mt-1 text-sm text-muted">
            Define metrics once — Lens uses them on every chat turn instead of
            asking the LLM to write SQL from scratch. This is the single most
            effective anti-hallucination layer in Pro.
          </p>
        </div>
        <button
          type="button"
          onClick={() => setShowForm((v) => !v)}
          className="rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-[var(--bg)] hover:opacity-90"
        >
          {showForm ? "Cancel" : "+ New metric"}
        </button>
      </div>

      {error && (
        <p className="mt-3 rounded-md border border-red-900/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">
          {error}
        </p>
      )}

      {showForm && (
        <NewMetricForm
          onCreated={async () => {
            await refresh();
            setShowForm(false);
          }}
          onError={(msg) => setError(msg)}
        />
      )}

      <div className="mt-6">
        {metrics.length === 0 ? (
          <div className="rounded-md border border-border bg-panel px-4 py-6 text-center text-xs text-muted">
            No metrics defined yet. Click <span className="text-neutral-200">+ New metric</span>{" "}
            to add your first.
          </div>
        ) : (
          <div className="space-y-3">
            {metrics.map((m) => (
              <MetricCard
                key={m.id}
                metric={m}
                onDelete={async () => {
                  if (!confirm(`Delete metric "${m.name}"?`)) return;
                  try {
                    await deleteMetric(m.id);
                    await refresh();
                  } catch (err) {
                    setError(err instanceof Error ? err.message : "Delete failed");
                  }
                }}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function MetricCard({
  metric,
  onDelete,
}: {
  metric: Metric;
  onDelete: () => void;
}) {
  return (
    <div className="rounded-lg border border-border bg-panel p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="font-mono text-sm font-medium text-emerald-300">{metric.name}</span>
            {metric.source_name && (
              <span className="text-[11px] text-muted">
                source: <span className="font-mono text-neutral-300">{metric.source_name}</span>
              </span>
            )}
          </div>
          {metric.description && (
            <p className="mt-1 text-xs text-neutral-300">{metric.description}</p>
          )}
          <pre className="mt-2 overflow-x-auto rounded-md bg-bg px-3 py-2 font-mono text-[11px] text-neutral-300">
            {metric.sql_template}
          </pre>
        </div>
        <button
          type="button"
          onClick={onDelete}
          className="shrink-0 text-xs text-red-400 hover:text-red-300"
        >
          Delete
        </button>
      </div>
    </div>
  );
}

function NewMetricForm({
  onCreated,
  onError,
}: {
  onCreated: () => Promise<void>;
  onError: (msg: string) => void;
}) {
  const [form, setForm] = useState<MetricCreate>({
    name: "",
    description: "",
    sql_template: "",
    source_name: "",
  });
  const [submitting, setSubmitting] = useState(false);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    try {
      await createMetric({
        name: form.name.trim(),
        description: form.description.trim(),
        sql_template: form.sql_template.trim(),
        source_name: form.source_name?.trim() || null,
      });
      await onCreated();
    } catch (err) {
      onError(err instanceof Error ? err.message : "Create failed");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="mt-4 rounded-lg border border-border bg-panel p-5"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Name" hint="lowercase_with_underscores">
          <input
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            required
            placeholder="revenue"
            className="block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-neutral-100 placeholder-muted focus:border-accent focus:outline-none"
          />
        </Field>
        <Field label="Source (optional)" hint="which registered source this metric queries">
          <input
            value={form.source_name ?? ""}
            onChange={(e) => setForm({ ...form, source_name: e.target.value })}
            placeholder="demo-shop"
            className="block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-neutral-100 placeholder-muted focus:border-accent focus:outline-none"
          />
        </Field>
      </div>
      <Field label="What does it mean (description)" hint="one short sentence for the LLM and humans">
        <input
          value={form.description}
          onChange={(e) => setForm({ ...form, description: e.target.value })}
          placeholder="Total paid order revenue"
          className="block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-neutral-100 placeholder-muted focus:border-accent focus:outline-none"
        />
      </Field>
      <Field label="SQL definition" hint="the canonical SQL expression for this metric">
        <textarea
          value={form.sql_template}
          onChange={(e) => setForm({ ...form, sql_template: e.target.value })}
          required
          rows={4}
          placeholder="SELECT SUM(amount) FROM public.orders WHERE status = 'paid'"
          spellCheck={false}
          className="block w-full rounded-md border border-border bg-bg px-3 py-2 font-mono text-xs text-neutral-100 placeholder-muted focus:border-accent focus:outline-none"
        />
      </Field>
      <div className="mt-4 flex items-center gap-3">
        <button
          type="submit"
          disabled={submitting || !form.name.trim() || !form.sql_template.trim()}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-[var(--bg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "Saving…" : "Save metric"}
        </button>
        <span className="text-xs text-muted">
          Metric takes effect on the next chat turn — no restart needed.
        </span>
      </div>
    </form>
  );
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: React.ReactNode;
}) {
  return (
    <label className="mt-3 block">
      <span className="block text-xs font-medium uppercase tracking-wide text-muted">{label}</span>
      {hint && <span className="block text-[11px] text-muted">{hint}</span>}
      <span className="mt-1 block">{children}</span>
    </label>
  );
}
