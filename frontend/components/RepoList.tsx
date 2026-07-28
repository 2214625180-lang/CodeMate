"use client";

import Link from "next/link";

import type { Repository } from "@/lib/types";
import { StatusBadge } from "./StatusBadge";

export function RepoList({ repositories }: { repositories: Repository[] }) {
  if (repositories.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-white p-8 text-center text-sm text-slate-500">
        No repositories have been added yet.
      </div>
    );
  }

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-white">
      <table className="w-full text-left text-sm">
        <thead className="bg-panel text-xs uppercase text-slate-500">
          <tr>
            <th className="px-4 py-3">Name</th>
            <th className="px-4 py-3">Status</th>
            <th className="px-4 py-3">Files</th>
            <th className="px-4 py-3">Chunks</th>
            <th className="px-4 py-3">Updated</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {repositories.map((repo) => (
            <tr key={repo.id} className="hover:bg-slate-50">
              <td className="px-4 py-3">
                <Link href={`/repos/${repo.id}`} className="font-medium text-slate-950">
                  {repo.name}
                </Link>
                <p className="mt-1 max-w-xl truncate text-xs text-slate-500">{repo.repo_url}</p>
              </td>
              <td className="px-4 py-3">
                <StatusBadge status={repo.status} />
              </td>
              <td className="px-4 py-3 text-slate-600">{repo.file_count}</td>
              <td className="px-4 py-3 text-slate-600">{repo.chunk_count}</td>
              <td className="px-4 py-3 text-slate-500">
                {new Date(repo.updated_at).toLocaleString()}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
