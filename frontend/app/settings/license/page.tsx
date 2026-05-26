"use client";

import { useEffect, useState } from "react";
import {
  activateLicense,
  clearLicense,
  getLicenseStatus,
  type LicenseStatus,
} from "@/lib/license";

export default function LicensePage() {
  const [status, setStatus] = useState<LicenseStatus | null | undefined>(undefined);
  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [info, setInfo] = useState<string | null>(null);

  useEffect(() => {
    void refresh();
  }, []);

  async function refresh() {
    try {
      const s = await getLicenseStatus();
      setStatus(s);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not load license status");
      setStatus(null);
    }
  }

  async function onActivate(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    setInfo(null);
    try {
      const updated = await activateLicense(token.trim());
      setStatus(updated);
      setToken("");
      setInfo("License activated.");
      // Notify the LicenseBanner (and any other listeners) to re-fetch.
      window.dispatchEvent(new Event("wekams:license-changed"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Activation failed");
    } finally {
      setSubmitting(false);
    }
  }

  async function onClear() {
    if (!confirm("Clear the active license? Pro / Enterprise features will lock until a new license is activated.")) {
      return;
    }
    setSubmitting(true);
    setError(null);
    setInfo(null);
    try {
      await clearLicense();
      await refresh();
      setInfo("License cleared.");
      window.dispatchEvent(new Event("wekams:license-changed"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not clear license");
    } finally {
      setSubmitting(false);
    }
  }

  if (status === undefined) {
    return (
      <div className="mx-auto max-w-3xl p-6 text-sm text-muted">Loading license status…</div>
    );
  }

  if (status === null) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <h1 className="text-lg font-semibold">License</h1>
        <p className="mt-2 text-sm text-muted">
          This is the Community Edition. License activation is not required — all
          Community features are unlocked.
        </p>
      </div>
    );
  }

  if (status.required && status.activated) {
    return (
      <div className="mx-auto max-w-3xl p-6">
        <h1 className="text-lg font-semibold">License</h1>
        <p className="mt-1 text-sm text-muted">
          Active license details. Replace it by activating a new file below.
        </p>

        <div className="mt-5 rounded-lg border border-border bg-panel p-5">
          <Row label="Customer" value={status.customer} />
          <Row label="License ID" value={status.license_id} mono />
          <Row label="Edition" value={status.edition} mono />
          <Row label="Seats" value={String(status.seats)} />
          <Row label="Workspaces" value={String(status.workspaces)} />
          <Row label="Features" value={status.features.join(", ") || "—"} />
          <Row label="Issued" value={status.issued_at} mono />
          <Row label="Expires" value={status.not_after} mono />
          <Row
            label="Status"
            value={
              status.expired
                ? "EXPIRED"
                : status.days_remaining != null
                  ? `${status.days_remaining} day${status.days_remaining === 1 ? "" : "s"} remaining`
                  : "Active"
            }
            highlight={status.expired ? "danger" : status.days_remaining != null && status.days_remaining <= 7 ? "warning" : null}
          />
        </div>

        <ActivateForm
          token={token}
          setToken={setToken}
          submitting={submitting}
          onSubmit={onActivate}
          error={error}
          info={info}
          heading="Replace with a new license"
        />

        <div className="mt-6">
          <button
            type="button"
            onClick={onClear}
            disabled={submitting}
            className="text-xs text-red-400 hover:text-red-300 disabled:opacity-50"
          >
            Clear active license
          </button>
        </div>
      </div>
    );
  }

  // status.required && !status.activated  → pending activation
  return (
    <div className="mx-auto max-w-3xl p-6">
      <h1 className="text-lg font-semibold">Activate Wekams Lens</h1>
      <p className="mt-2 text-sm text-muted">
        This instance is running the Pro / Enterprise build but has no active
        license yet. Paste the license token you received from{" "}
        <a className="underline" href="mailto:connect@wekams.com">
          connect@wekams.com
        </a>{" "}
        below to unlock features.
      </p>

      <ActivateForm
        token={token}
        setToken={setToken}
        submitting={submitting}
        onSubmit={onActivate}
        error={error}
        info={info}
      />
    </div>
  );
}

function Row({
  label,
  value,
  mono,
  highlight,
}: {
  label: string;
  value: string;
  mono?: boolean;
  highlight?: "danger" | "warning" | null;
}) {
  const color =
    highlight === "danger"
      ? "text-red-400"
      : highlight === "warning"
        ? "text-yellow-400"
        : "text-neutral-200";
  return (
    <div className="flex items-baseline gap-3 border-b border-border/50 py-2 text-sm last:border-0">
      <span className="w-32 shrink-0 text-xs uppercase tracking-wide text-muted">{label}</span>
      <span className={`${mono ? "font-mono text-xs" : ""} ${color}`}>{value}</span>
    </div>
  );
}

function ActivateForm({
  token,
  setToken,
  submitting,
  onSubmit,
  error,
  info,
  heading = "License token",
}: {
  token: string;
  setToken: (s: string) => void;
  submitting: boolean;
  onSubmit: (e: React.FormEvent) => void;
  error: string | null;
  info: string | null;
  heading?: string;
}) {
  return (
    <form onSubmit={onSubmit} className="mt-6">
      <label htmlFor="token" className="block text-xs font-medium uppercase tracking-wide text-muted">
        {heading}
      </label>
      <textarea
        id="token"
        value={token}
        onChange={(e) => setToken(e.target.value)}
        rows={6}
        placeholder="wekams.lic.v1.eyJ..."
        spellCheck={false}
        className="mt-1 block w-full rounded-md border border-border bg-bg px-3 py-2 font-mono text-xs text-neutral-100 placeholder-muted focus:border-accent focus:outline-none"
      />
      {error && (
        <p className="mt-3 rounded-md border border-red-900/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">
          {error}
        </p>
      )}
      {info && (
        <p className="mt-3 rounded-md border border-emerald-900/40 bg-emerald-950/20 px-3 py-2 text-xs text-emerald-300">
          {info}
        </p>
      )}
      <button
        type="submit"
        disabled={submitting || !token.trim()}
        className="mt-4 rounded-md bg-accent px-4 py-2 text-sm font-medium text-[var(--bg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
      >
        {submitting ? "Activating…" : "Activate"}
      </button>
    </form>
  );
}
