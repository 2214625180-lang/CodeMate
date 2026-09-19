import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "CodeMate | 可验证的代码修复助手",
  description:
    "面向 TypeScript 和 Python 仓库的可验证代码修复助手。"
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
                  代码修复
                </Link>
                <Link href="/evaluations" className="hover:text-slate-950">
                  评测
                </Link>
                <Link href="/mcp-operations" className="hover:text-slate-950">
                  扩展功能
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
