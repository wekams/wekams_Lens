import type { Metadata } from "next";
import AppShell from "@/components/AppShell";
import "./globals.css";

export const metadata: Metadata = {
  title: "Wekams Lens",
  description: "One lens. Every data source. Even the logs.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-bg text-neutral-100 antialiased">
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
