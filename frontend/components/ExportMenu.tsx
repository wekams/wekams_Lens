"use client";

import { useEffect, useRef, useState } from "react";
import {
  downloadConversationMarkdownUrl,
  fetchConversationMarkdown,
} from "@/lib/conversations";

type Props = {
  conversationId: string;
  title: string;
};

type Status = "idle" | "copying" | "copied" | "linked" | "error";

export default function ExportMenu({ conversationId, title }: Props) {
  const [open, setOpen] = useState(false);
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const ref = useRef<HTMLDivElement | null>(null);

  function conversationUrl(): string {
    if (typeof window === "undefined") return "";
    const u = new URL(window.location.href);
    u.searchParams.set("chat", conversationId);
    return u.toString();
  }

  async function copyLink() {
    setStatus("copying");
    setError(null);
    try {
      await navigator.clipboard.writeText(conversationUrl());
      setStatus("linked");
      setTimeout(() => setStatus("idle"), 1800);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  }

  // Close on outside click + Esc.
  useEffect(() => {
    if (!open) return;
    function onDocClick(e: MouseEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === "Escape") setOpen(false);
    }
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  async function copyMarkdown() {
    setStatus("copying");
    setError(null);
    try {
      const md = await fetchConversationMarkdown(conversationId);
      await navigator.clipboard.writeText(md);
      setStatus("copied");
      setTimeout(() => setStatus("idle"), 1800);
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      setStatus("error");
    }
  }

  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="rounded-md border border-border bg-bg px-2.5 py-1 text-xs text-neutral-300 hover:bg-panel"
        title={`Export "${title}"`}
      >
        {status === "copied"
          ? "✓ Copied"
          : status === "linked"
            ? "✓ Link copied"
            : "Export ▾"}
      </button>
      {open && (
        <div className="absolute right-0 z-10 mt-1 w-64 overflow-hidden rounded-md border border-border bg-panel shadow-xl">
          <button
            type="button"
            onClick={() => void copyLink()}
            disabled={status === "copying"}
            className="block w-full px-3 py-2 text-left text-sm hover:bg-neutral-900/60 disabled:opacity-50"
          >
            <div>Copy link to conversation</div>
            <div className="text-xs text-muted">
              Anyone on this Lens instance with the URL sees the same chat.
            </div>
          </button>
          <button
            type="button"
            onClick={() => void copyMarkdown()}
            disabled={status === "copying"}
            className="block w-full border-t border-border px-3 py-2 text-left text-sm hover:bg-neutral-900/60 disabled:opacity-50"
          >
            <div>Copy as Markdown</div>
            <div className="text-xs text-muted">
              Paste into Slack, GitHub, Notion, anywhere.
            </div>
          </button>
          <a
            href={downloadConversationMarkdownUrl(conversationId)}
            download
            onClick={() => setOpen(false)}
            className="block border-t border-border px-3 py-2 text-left text-sm hover:bg-neutral-900/60"
          >
            <div>Download .md file</div>
            <div className="text-xs text-muted">Saves the transcript locally.</div>
          </a>
        </div>
      )}
      {error && (
        <div className="absolute right-0 z-10 mt-1 w-72 rounded-md border border-red-900 bg-red-950/40 px-3 py-2 text-xs text-red-300">
          {error}
        </div>
      )}
    </div>
  );
}
