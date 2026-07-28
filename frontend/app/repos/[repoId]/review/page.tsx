"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useState } from "react";

import { CitationCard } from "@/components/chat/CitationCard";
import { reviewRepository } from "@/lib/api";
import type { ReviewResponse } from "@/lib/types";

const SEVERITY_STYLES = {
  info: "bg-slate-100 text-slate-700",
  low: "bg-sky-100 text-sky-700",
  medium: "bg-amber-100 text-amber-700",
  high: "bg-red-100 text-red-700"
};

export default function RepoReviewPage() {
  const params = useParams<{ repoId: string }>();
  const repoId = params.repoId;
  const [diff, setDiff] = useState("");
  const [baseRef, setBaseRef] = useState("");
  const [headRef, setHeadRef] = useState("");
  const [question, setQuestion] = useState("");
  const [review, setReview] = useState<ReviewResponse | null>(null);
  const [isReviewing, setIsReviewing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (isReviewing) {
      return;
    }

    setReview(null);
    setError(null);
    setIsReviewing(true);
    try {
      const payload =
        diff.trim().length > 0
          ? { diff: diff.trim(), question: question.trim() || undefined }
          : {
              base_ref: baseRef.trim(),
              head_ref: headRef.trim(),
              question: question.trim() || undefined
            };
      const response = await reviewRepository(repoId, payload);
      setReview(response);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to review changes");
    } finally {
      setIsReviewing(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href={`/repos/${repoId}`} className="text-sm text-slate-600 hover:text-slate-950">
          Back to repository
        </Link>
        <h1 className="mt-3 text-2xl font-semibold text-slate-950">PR Review</h1>
      </div>

      <form onSubmit={handleSubmit} className="rounded-lg border border-border bg-white p-5">
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <label htmlFor="base-ref" className="text-sm font-medium text-slate-700">
              Base ref
            </label>
            <input
              id="base-ref"
              value={baseRef}
              onChange={(event) => setBaseRef(event.target.value)}
              placeholder="origin/main"
              className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
            />
          </div>
          <div>
            <label htmlFor="head-ref" className="text-sm font-medium text-slate-700">
              Head ref
            </label>
            <input
              id="head-ref"
              value={headRef}
              onChange={(event) => setHeadRef(event.target.value)}
              placeholder="origin/feature"
              className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
            />
          </div>
        </div>

        <label htmlFor="diff" className="mt-4 block text-sm font-medium text-slate-700">
          Diff
        </label>
        <textarea
          id="diff"
          value={diff}
          onChange={(event) => setDiff(event.target.value)}
          placeholder="diff --git a/src/file.ts b/src/file.ts"
          className="mt-2 min-h-56 w-full resize-y rounded-md border border-border px-3 py-2 font-mono text-xs outline-none focus:border-slate-500"
        />

        <label htmlFor="question" className="mt-4 block text-sm font-medium text-slate-700">
          Review focus
        </label>
        <input
          id="question"
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Focus on correctness, tests, and security"
          className="mt-2 min-h-10 w-full rounded-md border border-border px-3 text-sm outline-none focus:border-slate-500"
        />

        <div className="mt-4 flex justify-end">
          <button
            type="submit"
            disabled={isReviewing}
            className="rounded-md bg-slate-950 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:bg-slate-400"
          >
            {isReviewing ? "Reviewing..." : "Run review"}
          </button>
        </div>
      </form>

      {error ? <div className="rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

      {review ? (
        <section className="grid gap-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(320px,0.8fr)]">
          <div className="space-y-4">
            <section className="rounded-lg border border-border bg-white p-5">
              <h2 className="text-lg font-semibold text-slate-950">Summary</h2>
              <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                {review.summary}
              </p>
            </section>

            <section className="space-y-3">
              <h2 className="text-lg font-semibold text-slate-950">Findings</h2>
              {review.findings.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border bg-white p-5 text-sm text-slate-500">
                  No findings returned.
                </div>
              ) : (
                review.findings.map((finding, index) => (
                  <article
                    key={`${finding.file_path}-${index}`}
                    className="rounded-lg border border-border bg-white p-5"
                  >
                    <div className="flex flex-wrap items-center gap-3">
                      <span
                        className={`rounded px-2 py-1 text-xs font-medium ${SEVERITY_STYLES[finding.severity]}`}
                      >
                        {finding.severity}
                      </span>
                      <h3 className="text-sm font-semibold text-slate-950">{finding.title}</h3>
                    </div>
                    {finding.file_path ? (
                      <p className="mt-2 font-mono text-xs text-slate-500">
                        {finding.file_path}:{finding.start_line ?? "?"}-{finding.end_line ?? "?"}
                      </p>
                    ) : null}
                    <p className="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">
                      {finding.body}
                    </p>
                    {finding.suggestion ? (
                      <p className="mt-3 rounded-md bg-slate-50 p-3 text-sm text-slate-700">
                        {finding.suggestion}
                      </p>
                    ) : null}
                  </article>
                ))
              )}
            </section>
          </div>

          <div className="space-y-4">
            <section className="rounded-lg border border-border bg-white p-5">
              <h2 className="text-lg font-semibold text-slate-950">Changed files</h2>
              {review.changed_files.length === 0 ? (
                <p className="mt-3 text-sm text-slate-500">No changed files detected.</p>
              ) : (
                <ul className="mt-3 space-y-2">
                  {review.changed_files.map((file) => (
                    <li key={file} className="break-all font-mono text-xs text-slate-700">
                      {file}
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="space-y-3">
              <h2 className="text-lg font-semibold text-slate-950">Citations</h2>
              {review.citations.length === 0 ? (
                <div className="rounded-lg border border-dashed border-border bg-white p-5 text-sm text-slate-500">
                  No citations returned.
                </div>
              ) : (
                review.citations.map((citation) => (
                  <CitationCard key={citation.chunk_id} repoId={repoId} citation={citation} />
                ))
              )}
            </section>
          </div>
        </section>
      ) : null}
    </div>
  );
}
