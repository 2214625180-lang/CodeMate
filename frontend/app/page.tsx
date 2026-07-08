import Link from "next/link";

export default function HomePage() {
  return (
    <section className="rounded-lg border border-border bg-white p-8">
      <p className="text-sm font-medium uppercase text-slate-500">Phase 1</p>
      <h1 className="mt-3 text-3xl font-semibold text-slate-950">
        CodeMate repository indexing
      </h1>
      <p className="mt-4 max-w-2xl text-slate-600">
        Add a Git repository, run the indexing task, and inspect the repository status and
        scanned source file count.
      </p>
      <Link
        href="/repos"
        className="mt-6 inline-flex rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800"
      >
        Open repositories
      </Link>
    </section>
  );
}
