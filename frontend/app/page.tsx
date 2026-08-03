import Link from "next/link";

import { ArchitectureMap } from "@/components/portfolio/ArchitectureMap";
import { DemoReplay } from "@/components/portfolio/DemoReplay";

const SAMPLE_REPOSITORY_ID = "d8ef36d0-7776-5bd1-b219-0bfcb44eaf4c";

const workflowSteps = [
  {
    number: "01",
    title: "Reproduce",
    description: "Run the reported target test in an isolated workspace before any patch is allowed."
  },
  {
    number: "02",
    title: "Investigate",
    description: "Choose bounded code tools from evidence: search, read, symbols, references, or tests."
  },
  {
    number: "03",
    title: "Patch",
    description: "Generate a reviewable diff under file, tool, token, time, and iteration budgets."
  },
  {
    number: "04",
    title: "Verify",
    description: "Require executed, passing target and regression tests before reporting verified success."
  }
];

export default function HomePage() {
  return (
    <div className="space-y-20 pb-10">
      <section className="portfolio-grid relative overflow-hidden rounded-3xl border border-slate-200 bg-white px-6 py-12 shadow-sm sm:px-10 sm:py-16">
        <div className="absolute -right-32 -top-40 h-96 w-96 rounded-full bg-cyan-100/70 blur-3xl" />
        <div className="absolute -bottom-44 left-1/3 h-80 w-80 rounded-full bg-violet-100/70 blur-3xl" />
        <div className="relative grid items-center gap-10 lg:grid-cols-[1.05fr_0.95fr]">
          <div>
            <p className="inline-flex rounded-full border border-cyan-200 bg-cyan-50 px-3 py-1 text-xs font-semibold uppercase tracking-[0.16em] text-cyan-800">
              Verifiable code repair agent
            </p>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl lg:text-6xl">
              From failing test to <span className="text-cyan-700">verified patch.</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
              CodeMate repairs focused TypeScript and Python repository defects by grounding each
              action in cited code evidence, validating patches in an isolated sandbox, and
              preserving the full execution trail for review and regression gates.
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href={`/repos/${SAMPLE_REPOSITORY_ID}/fix`}
                className="inline-flex items-center rounded-lg bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/15 transition hover:-translate-y-0.5 hover:bg-slate-800"
              >
                Try sample run
                <span aria-hidden="true" className="ml-2">→</span>
              </Link>
              <Link
                href="/evaluations/history"
                className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-800 transition hover:border-slate-400 hover:bg-slate-50"
              >
                View evaluation evidence
              </Link>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              Sample run is seeded by <code className="rounded bg-slate-100 px-1.5 py-0.5">make demo</code> and opens its persisted Timeline.
            </p>
            <dl className="mt-10 grid max-w-xl grid-cols-2 gap-3 sm:grid-cols-3">
              <EvidenceStat value="30" label="retrieval cases" />
              <EvidenceStat value="20" label="fix cases" />
              <EvidenceStat value="4 phases" label="strict success contract" />
            </dl>
          </div>
          <DemoReplay />
        </div>
      </section>

      <section id="workflow" aria-labelledby="workflow-title">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-cyan-700">The repair loop</p>
          <h2 id="workflow-title" className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">
            A narrow loop with evidence at every boundary.
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            The model chooses the next local code tool from observations. Deterministic policy
            controls what it may call, how often, and what evidence is sufficient to finish.
          </p>
        </div>
        <ol className="mt-8 grid gap-4 md:grid-cols-2 xl:grid-cols-4">
          {workflowSteps.map((step) => (
            <li key={step.number} className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm">
              <span className="font-mono text-sm font-semibold text-cyan-700">{step.number}</span>
              <h3 className="mt-5 text-xl font-semibold text-slate-950">{step.title}</h3>
              <p className="mt-3 text-sm leading-6 text-slate-600">{step.description}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="grid gap-6 lg:grid-cols-[0.92fr_1.08fr]" aria-labelledby="evidence-title">
        <div className="rounded-2xl bg-slate-950 p-7 text-white shadow-xl shadow-slate-950/10 sm:p-8">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-cyan-300">Measured evidence</p>
          <h2 id="evidence-title" className="mt-3 text-3xl font-semibold tracking-tight">
            Benchmarks are artifacts, not marketing copy.
          </h2>
          <p className="mt-4 max-w-xl leading-7 text-slate-300">
            Every evaluation records dataset snapshot, prompt hash, provider/model configuration,
            code commit, latency, and the evidence behind its verdict.
          </p>
          <Link
            href="/evaluations/history"
            className="mt-7 inline-flex items-center text-sm font-semibold text-cyan-300 hover:text-cyan-200"
          >
            Open complete evaluation reports <span aria-hidden="true" className="ml-2">→</span>
          </Link>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-8">
          <p className="text-sm font-semibold text-slate-500">Latest committed retrieval smoke artifact</p>
          <div className="mt-6 grid gap-5 sm:grid-cols-3">
            <Metric value="93.33%" label="Hybrid Recall@5" />
            <Metric value="0.6956" label="Hybrid MRR" />
            <Metric value="17.5 ms" label="Hybrid p95 latency" />
          </div>
          <p className="mt-7 border-t border-slate-100 pt-4 text-sm leading-6 text-slate-500">
            30 retrieval cases, measured 2026-08-02. This artifact is explicitly
            <strong className="font-semibold text-slate-700"> engineering-smoke-only</strong>:
            deterministic mock embeddings and a dirty worktree mean it is not a production-model claim. Fix-agent rates remain unpublished until real-model artifacts exist.
          </p>
        </div>
      </section>

      <section aria-labelledby="architecture-title">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-violet-700">Architecture</p>
            <h2 id="architecture-title" className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">
              Built around a verifiable repair contract.
            </h2>
          </div>
          <Link href="/evaluations/compare" className="text-sm font-semibold text-slate-700 hover:text-slate-950">
            Inspect regression gates →
          </Link>
        </div>
        <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-6">
          <ArchitectureMap />
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-8" aria-labelledby="extensions-title">
        <div className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">Production extensions</p>
            <h2 id="extensions-title" className="mt-3 text-2xl font-semibold tracking-tight text-slate-950">
              Deeper operational controls, deliberately outside the repair story.
            </h2>
            <p className="mt-3 max-w-3xl leading-7 text-slate-600">
              MCP Registry, tenant quotas, KMS-backed credentials, SIEM audit delivery, and managed
              sandbox execution are available for engineering deep dives. They are not required to understand the core Fix Agent loop.
            </p>
          </div>
          <Link
            href="/mcp-operations"
            className="inline-flex items-center justify-center rounded-lg border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-800 transition hover:border-slate-400 hover:bg-slate-50"
          >
            Explore extensions
          </Link>
        </div>
      </section>
    </div>
  );
}

function EvidenceStat({ value, label }: { value: string; label: string }) {
  return (
    <div className="rounded-xl border border-slate-200 bg-slate-50 p-3">
      <dt className="text-lg font-semibold text-slate-950">{value}</dt>
      <dd className="mt-1 text-xs leading-5 text-slate-500">{label}</dd>
    </div>
  );
}

function Metric({ value, label }: { value: string; label: string }) {
  return (
    <div>
      <p className="text-3xl font-semibold tracking-tight text-slate-950">{value}</p>
      <p className="mt-1 text-sm text-slate-500">{label}</p>
    </div>
  );
}
