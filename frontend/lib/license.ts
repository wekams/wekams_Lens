// License API client. Only meaningful in Pro / Enterprise builds — the
// backend returns 404 for these endpoints when ee/ is not present, in which
// case the UI hides all license affordances.

import { API_BASE, apiFetch } from "./auth";

export type LicenseStatus =
  | { required: true; activated: false }
  | {
      required: true;
      activated: true;
      license_id: string;
      customer: string;
      edition: string;
      seats: number;
      workspaces: number;
      features: string[];
      issued_at: string;
      not_after: string;
      days_remaining: number | null;
      expired: boolean;
      activated_at: string | null;
    }
  | { required: false; activated: false };

export async function getLicenseStatus(): Promise<LicenseStatus | null> {
  const r = await apiFetch(`${API_BASE}/api/v1/license`);
  if (r.status === 404) return null; // Community build — no license layer.
  if (!r.ok) throw new Error(`license status returned ${r.status}`);
  return (await r.json()) as LicenseStatus;
}

export async function activateLicense(token: string): Promise<LicenseStatus> {
  const r = await apiFetch(`${API_BASE}/api/v1/license/activate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
  if (!r.ok) {
    const detail = await r.text();
    let msg = `HTTP ${r.status}`;
    try {
      msg = JSON.parse(detail).detail ?? msg;
    } catch {
      if (detail) msg = detail;
    }
    throw new Error(msg);
  }
  return (await r.json()) as LicenseStatus;
}

export async function clearLicense(): Promise<void> {
  const r = await apiFetch(`${API_BASE}/api/v1/license`, { method: "DELETE" });
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
}
