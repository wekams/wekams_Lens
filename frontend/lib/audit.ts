// Audit-log API client. Returns null on Community builds (where
// /api/v1/audit returns 404) so the UI can show the "Pro feature" placeholder.

import { API_BASE, apiFetch } from "./auth";

export type AuditEvent = {
  id: number;
  occurred_at: string;
  event_type: string;
  actor: string | null;
  outcome: string;
  source_name: string | null;
  license_id: string | null;
  payload: Record<string, unknown>;
};

export type AuditPage = {
  limit: number;
  offset: number;
  count: number;
  events: AuditEvent[];
};

export type AuditFilters = {
  limit?: number;
  offset?: number;
  event_type?: string;
  source_name?: string;
  since?: string;
};

function buildQuery(f: AuditFilters): string {
  const p = new URLSearchParams();
  if (f.limit !== undefined) p.set("limit", String(f.limit));
  if (f.offset !== undefined) p.set("offset", String(f.offset));
  if (f.event_type) p.set("event_type", f.event_type);
  if (f.source_name) p.set("source_name", f.source_name);
  if (f.since) p.set("since", f.since);
  return p.toString();
}

export async function listAudit(f: AuditFilters = {}): Promise<AuditPage | null> {
  const qs = buildQuery(f);
  const url = `${API_BASE}/api/v1/audit${qs ? "?" + qs : ""}`;
  const r = await apiFetch(url);
  if (r.status === 404) return null; // Community build.
  if (!r.ok) throw new Error(`audit list returned ${r.status}`);
  return (await r.json()) as AuditPage;
}
