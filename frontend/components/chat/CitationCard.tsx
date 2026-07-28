"use client";

import { useState } from "react";

import { getFileContent } from "@/lib/api";
import type { CodeCitation, FileContent } from "@/lib/types";

type Props = {
  repoId?: string;
  citation: CodeCitation;
};

export function CitationCard({ repoId, citation }: Props) {
  const [content, setContent] = useState<FileContent | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const sourceRepoId = citation.repo_id ?? repoId;

  async function handleOpen() {
    if (content || isLoading || !sourceRepoId) {
      return;
    }
    setIsLoading(true);
    setError(null);
    try {
      const data = await getFileContent(
        sourceRepoId,
        citation.file_path,
        citation.start_line,
        citation.end_line
      );
      setContent(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load file content");
    } finally {
      setIsLoading(false);
    }
  }

  return (
    <div className="rounded-lg border border-border bg-white">
      <button
        type="button"
        onClick={handleOpen}
        disabled={!sourceRepoId}
        className="flex w-full flex-col gap-1 px-4 py-3 text-left hover:bg-slate-50"
      >
        <span className="font-mono text-sm font-medium text-slate-950">
          {citation.repo_name ? `${citation.repo_name}/` : ""}
          {citation.file_path}:{citation.start_line ?? "?"}-{citation.end_line ?? "?"}
        </span>
        <span className="text-xs text-slate-500">
          {citation.symbol_name ?? "unknown symbol"}
          {citation.symbol_type ? ` · ${citation.symbol_type}` : ""}
        </span>
      </button>

      {isLoading ? <p className="px-4 pb-3 text-sm text-slate-500">Loading snippet...</p> : null}
      {error ? <p className="px-4 pb-3 text-sm text-red-600">{error}</p> : null}
      {content ? (
        <pre className="max-h-96 overflow-auto border-t border-border bg-slate-950 p-4 text-xs leading-5 text-slate-100">
          <code>{content.content || "(empty snippet)"}</code>
        </pre>
      ) : null}
    </div>
  );
}
