"use client";

import { FormEvent, useState } from "react";

import { createRepository } from "@/lib/api";
import type { Repository } from "@/lib/types";

type Props = {
  onCreated: (repository: Repository) => void;
};

export function RepoForm({ onCreated }: Props) {
  const [repoUrl, setRepoUrl] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    setIsSubmitting(true);

    try {
      const repository = await createRepository(repoUrl);
      setRepoUrl("");
      onCreated(repository);
    } catch (err) {
      setError(err instanceof Error ? err.message : "创建仓库失败");
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
      <label htmlFor="repo-url" className="text-sm font-medium text-slate-700">
        Git 仓库地址
      </label>
      <div className="mt-2 flex flex-col gap-3 sm:flex-row">
        <input
          id="repo-url"
          value={repoUrl}
          onChange={(event) => setRepoUrl(event.target.value)}
          placeholder="https://github.com/user/repo.git"
          className="min-h-10 flex-1 rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
          required
        />
        <button
          type="submit"
          disabled={isSubmitting}
          className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
        >
          {isSubmitting ? "正在创建…" : "添加仓库"}
        </button>
      </div>
      {error ? <p className="mt-3 text-sm text-red-600">{error}</p> : null}
    </form>
  );
}
