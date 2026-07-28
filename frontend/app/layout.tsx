import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "CodeMate",
  description: "Code repository Q&A and repair agent"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen">
          <header className="border-b border-border bg-white">
            <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
              <Link href="/" className="text-lg font-semibold">
                CodeMate
              </Link>
              <nav className="flex items-center gap-4 text-sm text-slate-600">
                <Link href="/repos" className="hover:text-slate-950">
                  Repositories
                </Link>
                <Link href="/repos/chat" className="hover:text-slate-950">
                  Multi-repo Q&A
                </Link>
                <Link href="/evaluations" className="hover:text-slate-950">
                  Evaluations
                </Link>
                <Link href="/evaluations/compare" className="hover:text-slate-950">
                  Regression
                </Link>
                <Link href="/evaluations/datasets" className="hover:text-slate-950">
                  Benchmarks
                </Link>
                <Link href="/mcp-operations" className="hover:text-slate-950">
                  MCP Ops
                </Link>
                <Link href="/mcp-registry" className="hover:text-slate-950">
                  MCP Registry
                </Link>
                <Link href="/mcp-tenancy" className="hover:text-slate-950">
                  MCP Tenancy
                </Link>
                <Link href="/mcp-quotas" className="hover:text-slate-950">
                  MCP Quotas
                </Link>
              </nav>
            </div>
          </header>
          <main className="mx-auto max-w-6xl px-6 py-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
