// Metrics-catalog API client. Returns null on Community builds (where
// /api/v1/metrics returns 404) so the UI can show the "Pro feature" placeholder.

import { API_BASE, apiFetch } from "./auth";

export type Metric = {
  id: number;
  name: string;
  description: string;
  sql_template: string;
  source_name: string | null;
  created_at: string;
  created_by: string | null;
};

export type MetricCreate = {
  name: string;
  description: string;
  sql_template: string;
  source_name?: string | null;
};

export async function listMetrics(): Promise<Metric[] | null> {
  const r = await apiFetch(`${API_BASE}/api/v1/metrics`);
  if (r.status === 404) return null; // Community build
  if (!r.ok) throw new Error(`metrics list returned ${r.status}`);
  return (await r.json()) as Metric[];
}

export async function createMetric(req: MetricCreate): Promise<Metric> {
  const r = await apiFetch(`${API_BASE}/api/v1/metrics`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* ignore */
    }
    throw new Error(msg);
  }
  return (await r.json()) as Metric;
}

export async function deleteMetric(id: number): Promise<void> {
  const r = await apiFetch(`${API_BASE}/api/v1/metrics/${id}`, { method: "DELETE" });
  if (!r.ok && r.status !== 204) throw new Error(`HTTP ${r.status}`);
}
