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
      setError(err instanceof Error ? err.message : "加载仓库列表失败");
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
        <h1 className="text-2xl font-semibold text-slate-950">仓库</h1>
        <p className="mt-2 text-sm text-slate-600">
          添加 Git 仓库地址，查看克隆、解析和向量索引的进度。
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
          正在加载仓库列表…
        </div>
      ) : (
        <RepoList repositories={repositories} />
      )}
    </div>
  );
}
