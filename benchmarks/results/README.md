# Benchmark Results

This directory separates measured artifacts from claims. A number is published only when a
completed Evaluation artifact exists; unavailable runs remain explicitly `not_run`.

## Local retrieval engineering smoke run

Run time: 2026-08-02T16:00:18Z. Dataset: 30 retrieval cases, Top K = 5.

| Variant | Recall@5 | MRR | nDCG | File hit | Line overlap | Citation precision | p95 latency |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| vector-only | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | 0.0195 s |
| hybrid | 0.9333 | 0.6956 | 0.7600 | 0.9333 | 0.7917 | 0.3167 | 0.0175 s |
| hybrid + rerank/context | 0.9333 | 0.7067 | 0.7660 | 0.9333 | 0.7917 | 0.2944 | 0.0232 s |

These are real local measurements, but they are deliberately labeled
`engineering_smoke_only`: the embedding provider was `mock-deterministic-384d-v1`, the
vector-only arm returned no result above the shared 0.72 threshold, and the source worktree
was dirty. They demonstrate that the benchmark and ablation machinery executes end to end;
they are not a claim about a production embedding model.

Provenance:

- Artifact: [`local-retrieval-latest.json`](local-retrieval-latest.json)
- Code commit at execution: `96c0a2a2e057eb436f37d861a16b4ff46358a3f0` (`code_worktree_dirty=true`)
- Dataset snapshot id: `d9c4ad03-ad63-46db-915b-6ee2174f3528`
- Normalized dataset cases SHA-256: `dc0a2bfeaac2e4658b5839fe95998e84237939391e7af7b74cf8a0659c1edf40`
- Prompt bundle SHA-256: `e833cedf4267ab86741352579ec5465ad489dbd33b4b33337e2b392d0fa0ca48`
- Fixture commits: recorded and verified in [`../fixtures/manifest.json`](../fixtures/manifest.json)

## Fix and agent-loop results

Status: `not_run`.

No real LLM credential was available in the execution environment, so Verified Fix@1,
final Verified Fix Rate, reflection-loop, and fixed-vs-adaptive planner percentages are not
published. The runner will produce those values only from completed artifacts:

```bash
python scripts/run_benchmark_matrix.py \
  --variant retrieval-vector-only=https://vector.example \
  --variant retrieval-hybrid=https://hybrid.example \
  --variant retrieval-hybrid-rerank-context=https://rerank.example \
  --variant fix-single-shot-adaptive=https://single.example \
  --variant fix-reflection-adaptive=https://adaptive.example \
  --variant fix-reflection-fixed=https://fixed.example
```

Each endpoint must be deployed with the environment recorded in
[`../ablations.json`](../ablations.json). The runner rejects a deployment when its captured
config snapshot does not match the named variant.
