"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { clearStoredToken, getAuthStatus, getStoredToken, verifyToken } from "@/lib/auth";
import LicenseBanner from "@/components/LicenseBanner";

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Chat" },
  { href: "/sources", label: "Sources" },
  { href: "/settings/metrics", label: "Metrics" },
  { href: "/settings/audit", label: "Audit" },
  { href: "/settings/license", label: "License" },
];

type AuthState = "checking" | "ok" | "redirecting";

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [authRequired, setAuthRequired] = useState<boolean>(false);

  useEffect(() => {
    if (pathname.startsWith("/login")) {
      setAuthState("ok");
      return;
    }
    let cancelled = false;
    (async () => {
      try {
        const status = await getAuthStatus();
        if (cancelled) return;
        setAuthRequired(status.required);
        if (!status.required) {
          setAuthState("ok");
          return;
        }
        const token = getStoredToken();
        if (token && (await verifyToken(token))) {
          if (cancelled) return;
          setAuthState("ok");
        } else {
          if (cancelled) return;
          clearStoredToken();
          const next = encodeURIComponent(pathname);
          setAuthState("redirecting");
          router.replace(`/login?next=${next}`);
        }
      } catch {
        if (cancelled) return;
        setAuthState("ok");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [pathname, router]);

  function onLogout() {
    clearStoredToken();
    router.replace("/login");
  }

  if (authState !== "ok") {
    return (
      <div className="flex h-screen items-center justify-center bg-bg text-muted">
        <span className="text-sm">Checking authentication…</span>
      </div>
    );
  }

  return (
    <div className="flex h-screen flex-col">
      <LicenseBanner />
      <header className="border-b border-border bg-bg">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-baseline gap-3">
            <Link href="/" className="text-base font-semibold tracking-tight hover:text-accent">
              Wekams Lens
            </Link>
            <span className="hidden text-xs text-muted sm:inline">
              One lens. Every data source. Even the logs.
            </span>
          </div>
          <nav className="flex items-center gap-1 text-sm">
            {NAV.map((item) => {
              const active =
                item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`rounded-md px-3 py-1.5 transition-colors ${
                    active
                      ? "bg-panel text-neutral-100"
                      : "text-muted hover:bg-panel hover:text-neutral-200"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
            {authRequired && (
              <button
                type="button"
                onClick={onLogout}
                className="ml-2 rounded-md px-3 py-1.5 text-xs text-muted hover:bg-panel hover:text-neutral-200"
                title="Clear the stored token and return to sign-in"
              >
                Sign out
              </button>
            )}
          </nav>
        </div>
      </header>
      <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  );
}
