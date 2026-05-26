"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { getLicenseStatus, type LicenseStatus } from "@/lib/license";

/**
 * Top-of-app strip that appears when the Pro / Enterprise build needs a
 * license (or has one that's expiring / expired). Renders nothing in
 * Community builds (where the /api/v1/license endpoint returns 404).
 */
export default function LicenseBanner() {
  const [status, setStatus] = useState<LicenseStatus | null>(null);

  useEffect(() => {
    let cancelled = false;
    async function fetchStatus() {
      try {
        const s = await getLicenseStatus();
        if (!cancelled) setStatus(s);
      } catch {
        // Silently ignore — banner is purely informational.
      }
    }
    void fetchStatus();

    // Re-fetch when the License page emits a change event after activation
    // or clearing. Also re-poll once an hour to catch slow-drift (e.g.,
    // crossing the 30/7/24h expiry thresholds while the tab is open).
    const onChange = () => void fetchStatus();
    window.addEventListener("wekams:license-changed", onChange);
    const interval = window.setInterval(fetchStatus, 60 * 60 * 1000);
    return () => {
      cancelled = true;
      window.removeEventListener("wekams:license-changed", onChange);
      window.clearInterval(interval);
    };
  }, []);

  if (!status || !status.required) return null;

  if (!status.activated) {
    return (
      <BannerRow tone="danger">
        <span>
          <strong className="font-medium">Pending activation — Lens is locked.</strong>{" "}
          This is the Pro / Enterprise build. Upload your license file to unlock.
        </span>
        <Link href="/settings/license" className="ml-auto underline">
          Activate →
        </Link>
      </BannerRow>
    );
  }

  if (status.expired) {
    return (
      <BannerRow tone="danger">
        <span>
          <strong className="font-medium">License expired — Lens is locked.</strong>{" "}
          {status.customer}. Email{" "}
          <a className="underline" href="mailto:connect@wekams.com">
            connect@wekams.com
          </a>{" "}
          for a renewal file.
        </span>
        <Link href="/settings/license" className="ml-auto underline">
          Upload renewal →
        </Link>
      </BannerRow>
    );
  }

  const days = status.days_remaining;
  if (days !== null && days <= 1) {
    return (
      <BannerRow tone="danger">
        <span>
          <strong className="font-medium">License expires in {days <= 0 ? "less than" : ""} 24 hours — read-only mode.</strong>{" "}
          New queries are blocked until renewal. {status.customer}.
        </span>
        <Link href="/settings/license" className="ml-auto underline">
          Upload renewal →
        </Link>
      </BannerRow>
    );
  }
  if (days !== null && days <= 7) {
    return (
      <BannerRow tone="danger">
        <span>
          <strong className="font-medium">License expires in {days} day{days === 1 ? "" : "s"}.</strong>{" "}
          Renew now to avoid lockout. {status.customer} ({status.edition}).
        </span>
        <Link href="/settings/license" className="ml-auto underline">
          View →
        </Link>
      </BannerRow>
    );
  }
  if (days !== null && days <= 30) {
    return (
      <BannerRow tone="warning">
        <span>
          <strong className="font-medium">License expires in {days} days.</strong>{" "}
          {status.customer} ({status.edition}).
        </span>
        <Link href="/settings/license" className="ml-auto underline">
          View →
        </Link>
      </BannerRow>
    );
  }

  return null;
}

function BannerRow({
  tone,
  children,
}: {
  tone: "warning" | "danger";
  children: React.ReactNode;
}) {
  const cls =
    tone === "danger"
      ? "border-red-900/60 bg-red-950/40 text-red-200"
      : "border-yellow-900/60 bg-yellow-950/30 text-yellow-200";
  return (
    <div className={`flex items-center gap-3 border-b px-4 py-2 text-xs ${cls}`}>{children}</div>
  );
}
