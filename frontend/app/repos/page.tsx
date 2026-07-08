"use client";

import { useCallback, useEffect, useState } from "react";

import { RepoForm } from "@/components/RepoForm";
import { RepoList } from "@/components/RepoList";
import { listRepositories } from "@/lib/api";
import type { Repository } from "@/lib/types";

export default function ReposPage() {
  const [repositories, setRepositories] = useState<Repository[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadRepositories = useCallback(async () => {
    try {
      const data = await listRepositories();
      setRepositories(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load repositories");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void loadRepositories();
    const interval = window.setInterval(() => {
      void loadRepositories();
    }, 3000);
    return () => window.clearInterval(interval);
  }, [loadRepositories]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-slate-950">Repositories</h1>
        <p className="mt-2 text-sm text-slate-600">
          Add a Git URL and watch the indexing status move through the Phase 1 pipeline.
        </p>
      </div>

      <RepoForm
        onCreated={(repository) => {
          setRepositories((current) => [repository, ...current]);
          void loadRepositories();
        }}
      />

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}
      {isLoading ? (
        <div className="rounded-lg border border-border bg-white p-5 text-sm text-slate-500">
          Loading repositories...
        </div>
      ) : (
        <RepoList repositories={repositories} />
      )}
    </div>
  );
}
