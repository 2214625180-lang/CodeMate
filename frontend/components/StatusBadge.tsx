import type { RepositoryStatus } from "@/lib/types";

const STYLES: Record<RepositoryStatus, string> = {
  pending: "bg-slate-100 text-slate-700",
  cloning: "bg-blue-100 text-blue-700",
  parsing: "bg-amber-100 text-amber-800",
  embedding: "bg-violet-100 text-violet-700",
  indexed: "bg-emerald-100 text-emerald-700",
  failed: "bg-red-100 text-red-700"
};

export function StatusBadge({ status }: { status: RepositoryStatus }) {
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${STYLES[status]}`}>
      {status}
    </span>
  );
}
