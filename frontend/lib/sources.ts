// Sources API client. Mirrors backend/app/api/sources.py.

import { API_BASE, apiFetch } from "./auth";

// Built-in types remain a useful hint for forms, but the backend now
// accepts any registered type string — so this is `string` for safety.
export type SourceType = string;
export type SourceStatus = "pending" | "ready" | "error" | "disabled";

export type ColumnView = {
  name: string;
  data_type: string;
  nullable: boolean;
  is_primary_key: boolean;
  position: number;
  description: string | null;
};

export type TableView = {
  schema_name: string;
  name: string;
  description: string | null;
  row_count_est: number | null;
  columns: ColumnView[];
};

export type SourceView = {
  id: string;
  name: string;
  type: SourceType;
  status: SourceStatus;
  config: Record<string, unknown>;
  last_error: string | null;
  tables: TableView[];
};

export type CreateSourceRequest = {
  name: string;
  type: SourceType;
  connection: Record<string, unknown>;
};

async function jsonOrThrow<T>(res: Response): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    let msg = `HTTP ${res.status}`;
    try {
      const body = JSON.parse(text);
      msg = body.detail ?? body.message ?? msg;
    } catch {
      if (text) msg = text;
    }
    throw new Error(msg);
  }
  return res.json() as Promise<T>;
}

export async function listSourceTypes(): Promise<SourceType[]> {
  return jsonOrThrow<SourceType[]>(await apiFetch(`${API_BASE}/api/v1/sources/types`));
}

export type SourceTypeDetail = {
  type: string;
  display_name: string;
  credential_keys: string[];
  module: string;
  builtin: boolean;
};

export async function listSourceTypeDetails(): Promise<SourceTypeDetail[]> {
  return jsonOrThrow<SourceTypeDetail[]>(
    await apiFetch(`${API_BASE}/api/v1/sources/types/details`),
  );
}

export async function listSources(): Promise<SourceView[]> {
  return jsonOrThrow<SourceView[]>(await apiFetch(`${API_BASE}/api/v1/sources`));
}

export async function getSource(id: string): Promise<SourceView> {
  return jsonOrThrow<SourceView>(await apiFetch(`${API_BASE}/api/v1/sources/${id}`));
}

export async function createSource(req: CreateSourceRequest): Promise<SourceView> {
  return jsonOrThrow<SourceView>(
    await apiFetch(`${API_BASE}/api/v1/sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(req),
    }),
  );
}

export async function deleteSource(id: string): Promise<void> {
  const res = await apiFetch(`${API_BASE}/api/v1/sources/${id}`, { method: "DELETE" });
  if (!res.ok && res.status !== 204) {
    throw new Error(`HTTP ${res.status}`);
  }
}

export async function syncSource(id: string): Promise<SourceView> {
  return jsonOrThrow<SourceView>(
    await apiFetch(`${API_BASE}/api/v1/sources/${id}/sync`, { method: "POST" }),
  );
}

export async function testConnection(
  type: SourceType,
  connection: Record<string, unknown>,
): Promise<{ ok: boolean; error?: string }> {
  return jsonOrThrow<{ ok: boolean; error?: string }>(
    await apiFetch(`${API_BASE}/api/v1/sources/test`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ type, connection }),
    }),
  );
}
