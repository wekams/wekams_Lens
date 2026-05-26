"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { getStoredToken, setStoredToken, verifyToken, getAuthStatus } from "@/lib/auth";

export default function LoginPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextParam = searchParams.get("next") || "/";

  const [token, setToken] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [authStatusLoaded, setAuthStatusLoaded] = useState(false);

  // On mount: if auth is not required, or we already have a working token, bounce to next.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const status = await getAuthStatus();
        if (cancelled) return;
        if (!status.required) {
          router.replace(nextParam);
          return;
        }
        const existing = getStoredToken();
        if (existing && (await verifyToken(existing))) {
          if (cancelled) return;
          router.replace(nextParam);
          return;
        }
        setAuthStatusLoaded(true);
      } catch {
        setAuthStatusLoaded(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, nextParam]);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const ok = await verifyToken(token.trim());
      if (!ok) {
        setError("That token isn't accepted. Check WEKAMS_AUTH_TOKEN in your .env and try again.");
        setSubmitting(false);
        return;
      }
      setStoredToken(token.trim());
      router.replace(nextParam);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not reach the backend.");
      setSubmitting(false);
    }
  }

  if (!authStatusLoaded) {
    return (
      <div className="flex h-screen items-center justify-center bg-bg text-muted">
        <span className="text-sm">Checking authentication…</span>
      </div>
    );
  }

  return (
    <div className="flex h-screen items-center justify-center bg-bg px-4">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-sm rounded-xl border border-border bg-panel p-6 shadow-sm"
      >
        <h1 className="text-lg font-semibold tracking-tight text-neutral-100">Sign in to Wekams Lens</h1>
        <p className="mt-2 text-sm text-muted">
          Paste the access token configured by your administrator (the
          <code className="mx-1 rounded bg-bg px-1 py-0.5 text-xs">WEKAMS_AUTH_TOKEN</code>
          value from .env).
        </p>

        <label htmlFor="token" className="mt-5 block text-xs font-medium uppercase tracking-wide text-muted">
          Access token
        </label>
        <input
          id="token"
          type="password"
          autoComplete="off"
          autoFocus
          required
          value={token}
          onChange={(e) => setToken(e.target.value)}
          className="mt-1 block w-full rounded-md border border-border bg-bg px-3 py-2 text-sm text-neutral-100 placeholder-muted focus:border-accent focus:outline-none"
          placeholder="paste your token here"
        />

        {error && (
          <p className="mt-3 rounded-md border border-red-900/40 bg-red-950/40 px-3 py-2 text-xs text-red-300">
            {error}
          </p>
        )}

        <button
          type="submit"
          disabled={submitting || !token.trim()}
          className="mt-5 w-full rounded-md bg-accent px-3 py-2 text-sm font-medium text-[var(--bg)] hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {submitting ? "Verifying…" : "Sign in"}
        </button>

        <p className="mt-4 text-xs text-muted">
          Lost the token? Check your <code className="rounded bg-bg px-1 py-0.5">.env</code> file
          under <code className="rounded bg-bg px-1 py-0.5">WEKAMS_AUTH_TOKEN</code>.
        </p>
      </form>
    </div>
  );
}
