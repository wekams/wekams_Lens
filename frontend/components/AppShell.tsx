"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV: { href: string; label: string }[] = [
  { href: "/", label: "Chat" },
  { href: "/sources", label: "Sources" },
];

export default function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  return (
    <div className="flex h-screen flex-col">
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
          </nav>
        </div>
      </header>
      <main className="flex flex-1 flex-col overflow-hidden">{children}</main>
    </div>
  );
}
