// Auth helper for the Community single-user Bearer token flow.
// One token kept in localStorage; attached to every API request; on 401 the
// token is cleared and the user is sent to /login.

const STORAGE_KEY = "wekams_lens_token";

export const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

export function getStoredToken(): string | null {
  if (typeof window === "undefined") return null;
  return window.localStorage.getItem(STORAGE_KEY);
}

export function setStoredToken(token: string): void {
  if (typeof window === "undefined") return;
  window.localStorage.setItem(STORAGE_KEY, token);
}

export function clearStoredToken(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

export type AuthStatus = { required: boolean };

export async function getAuthStatus(): Promise<AuthStatus> {
  const r = await fetch(`${API_BASE}/api/v1/auth/required`);
  if (!r.ok) throw new Error(`auth/required returned ${r.status}`);
  return (await r.json()) as AuthStatus;
}

export async function verifyToken(token: string): Promise<boolean> {
  const r = await fetch(`${API_BASE}/api/v1/auth/check`, {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
  return r.ok;
}

/**
 * Drop-in fetch wrapper that:
 *  - attaches Authorization: Bearer <token> from localStorage if present
 *  - on 401, clears the stored token and redirects to /login
 *
 * Use this anywhere we used to call fetch() against the backend.
 */
export async function apiFetch(input: string, init?: RequestInit): Promise<Response> {
  const token = getStoredToken();
  const headers = new Headers(init?.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(input, { ...init, headers });
  if (resp.status === 401) {
    clearStoredToken();
    if (typeof window !== "undefined" && !window.location.pathname.startsWith("/login")) {
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
  }
  return resp;
}
