# CI Evaluation Gate

This example shows how to run CodeMate's benchmark regression gate in CI and upload
the generated evaluation artifacts.

## Prerequisites

Before enabling this workflow:

- The CodeMate backend must be reachable from the CI runner.
- A benchmark dataset must have a baseline run configured in the Evaluation Center.
- The CI job needs the benchmark dataset id.
- If the backend sets Evaluation service tokens, use `EVALUATION_CI_TOKEN` for
  this workflow and expose that value as `CODEMATE_EVALUATION_API_TOKEN`. The
  CI token can read Evaluation resources and trigger evaluation runs without
  gaining dataset mutation, delete, or backfill privileges. All Evaluation CLI
  scripts read `CODEMATE_EVALUATION_API_TOKEN` automatically and send it as a
  Bearer token.

The recommended CI script creates a candidate evaluation run from the dataset,
waits for completion, checks the regression gate, and writes both JSON and
Markdown artifacts to `artifacts/evaluations` by default. When running in
GitHub Actions, it also appends a readable gate report to `$GITHUB_STEP_SUMMARY`
and writes `<run-id>-gate-summary.md` for PR comments. It also exports dataset
trend reports as `<dataset-id>-trend.md/json`, so the same CI step produces the
candidate run artifact, gate summary, and history trend report. Pass
`--snapshot-backfill-audit` to also include a dry-run dataset snapshot backfill
audit report in the same artifact directory. That optional audit calls the
backfill admin endpoint, so it requires an admin token instead of the narrower
CI token:

```bash
scripts/run_dataset_eval_gate.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --name "ci-${GITHUB_SHA:-local}" \
  --artifact-dir artifacts/evaluations \
  --snapshot-backfill-audit
```

For one-time migrations or standalone scheduled audit jobs, run the API-based
snapshot backfill script directly. It writes both JSON and Markdown migration
reports to the same artifact directory, proving which historical runs were bound
to dataset snapshots without giving CI direct database access:

```bash
scripts/backfill_dataset_snapshots_api.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --dry-run \
  --full \
  --artifact-dir artifacts/evaluations
```

Use `--apply` to apply the migration after reviewing the dry-run report.

Exit codes:

- `0`: gate passed
- `1`: gate failed
- `2`: inconclusive or API/network error

## GitHub Actions Example

Save this as `.github/workflows/evaluation-gate.yml` after replacing the trigger
and variables for your environment.

```yaml
name: Evaluation Gate

on:
  pull_request:
  workflow_dispatch:
    inputs:
      dataset_id:
        description: Benchmark dataset id. Defaults to vars.CODEMATE_EVAL_DATASET_ID for pull requests.
        required: true
      run_name:
        description: Optional candidate evaluation run name
        required: false

permissions:
  contents: read
  pull-requests: write

jobs:
  evaluation-gate:
    runs-on: ubuntu-latest
    env:
      CODEMATE_API_BASE_URL: ${{ vars.CODEMATE_API_BASE_URL }}
      CODEMATE_EVAL_DATASET_ID: ${{ inputs.dataset_id || vars.CODEMATE_EVAL_DATASET_ID }}
      CODEMATE_EVALUATION_API_TOKEN: ${{ secrets.CODEMATE_EVALUATION_API_TOKEN }}

    steps:
      - name: Checkout
        uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Run candidate evaluation and regression gate
        run: |
          RUN_NAME="${{ inputs.run_name }}"
          if [ -z "$RUN_NAME" ]; then
            RUN_NAME="ci-${GITHUB_SHA}"
          fi

          scripts/run_dataset_eval_gate.py \
            --base-url "$CODEMATE_API_BASE_URL" \
            --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
            --name "$RUN_NAME" \
            --artifact-dir artifacts/evaluations \
            --snapshot-backfill-audit

      - name: Comment evaluation summary on PR
        if: always() && github.event_name == 'pull_request'
        continue-on-error: true
        env:
          GITHUB_TOKEN: ${{ github.token }}
        run: |
          SUMMARY_FILE="$(find artifacts/evaluations -name '*-gate-summary.md' -print -quit)"
          if [ -n "$SUMMARY_FILE" ]; then
            scripts/upsert_pr_comment.py \
              --repo "${{ github.repository }}" \
              --pr-number "${{ github.event.pull_request.number }}" \
              --body-file "$SUMMARY_FILE"
          fi

      - name: Upload evaluation artifacts
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: evaluation-artifacts
          path: artifacts/evaluations
          if-no-files-found: warn
```

## Usage Notes

If a candidate evaluation run already exists, use `check_regression_gate.py`
directly:

```bash
scripts/check_regression_gate.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --candidate-run-id "$CODEMATE_CANDIDATE_RUN_ID" \
  --artifact-dir artifacts/evaluations
```

All scripts also accept `--api-token` when passing the token explicitly is more
convenient than using `CODEMATE_EVALUATION_API_TOKEN`.

For browser access to the Evaluation Center, do not put
`CODEMATE_EVALUATION_API_TOKEN` in a `NEXT_PUBLIC_*` variable. Set it only on
the frontend server, configure `FRONTEND_ADMIN_PASSWORD`, and let the Next.js
server-side proxy forward Evaluation API calls. The proxy sends the backend
token plus trusted `X-CodeMate-Evaluation-Role`, `X-CodeMate-Evaluation-User`,
and `X-CodeMate-Evaluation-Provider` headers, so the backend also enforces
viewer/admin RBAC. The proxy signs those identity headers with
`X-CodeMate-Evaluation-Identity-Timestamp`,
`X-CodeMate-Evaluation-Identity-Nonce`, and
`X-CodeMate-Evaluation-Identity-Signature`; set the same
`CODEMATE_PROXY_IDENTITY_SECRET` on the frontend and backend servers. During
rotation, put the new value in `CODEMATE_PROXY_IDENTITY_SECRET` and keep the old
value in `CODEMATE_PROXY_IDENTITY_PREVIOUS_SECRET` on the backend until all
frontend instances have moved. The backend consumes each nonce once for
`CODEMATE_PROXY_IDENTITY_TTL_SECONDS` seconds, so replayed signed identity
headers are rejected. If the current secret is omitted, the evaluation API token
is used as the signing key for compatibility, but production deployments should
use a separate secret and `CODEMATE_PROXY_IDENTITY_NONCE_STORE=redis`. Set
`CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY=true` to reject browser/proxy
token-only fallback while keeping direct CI script calls available under their
configured service-token scope. When `APP_ENV=production`,
`CODEMATE_REQUIRE_SIGNED_BROWSER_IDENTITY` must be set explicitly.

For team SSO, configure a GitHub OAuth app with callback
`https://<frontend-host>/api/auth/github/callback`, set
`GITHUB_OAUTH_CLIENT_ID` and `GITHUB_OAUTH_CLIENT_SECRET`, then map roles with
`CODEMATE_RBAC_ADMIN_USERS`, `CODEMATE_RBAC_ADMIN_TEAMS`,
`CODEMATE_RBAC_VIEWER_USERS`, `CODEMATE_RBAC_VIEWER_TEAMS`, or
`CODEMATE_RBAC_VIEWER_ORGS`. Team values use `org/team-slug`.
Security events are appended to `SECURITY_AUDIT_LOG_PATH`, defaulting to
`artifacts/security/events.jsonl`. The backend also writes Evaluation request
audit events with the resolved principal role/provider and request status, and
only Evaluation admins can view recent events from `/evaluations/security`.

To write the gate summary to a custom path, pass `--summary-output`. To disable
the automatic Actions step summary append, pass `--no-github-step-summary`.

PR comments are updated in place by `scripts/upsert_pr_comment.py` using the
hidden marker `<!-- codemate:evaluation-gate-summary -->`, so repeated CI runs
do not add duplicate CodeMate comments.

For large fix-agent traces, reduce artifact size by excluding agent step payloads:

```bash
scripts/run_dataset_eval_gate.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --artifact-dir artifacts/evaluations \
  --no-agent-steps
```

For fix datasets where test execution is not required by the benchmark, pass
`--allow-skipped-tests`. For retrieval datasets, tune retrieval depth with
`--top-k`.

To filter the trend report generated by the full CI script, pass history filter
options such as `--history-status completed`, `--history-gate-status failed`,
`--history-provider openai`, or `--history-model gpt-4.1`. To skip trend report
export, pass `--no-export-history-report`.

To generate a migration audit report for README or CI artifacts:

```bash
scripts/backfill_dataset_snapshots_api.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --dry-run \
  --full \
  --artifact-dir artifacts/evaluations
```

The script writes `<dataset-id>-snapshot-backfill-dry-run.md/json` for previews
and `<dataset-id>-snapshot-backfill-applied.md/json` when run with `--apply`.
For local maintenance tasks that intentionally run beside the backend database,
`scripts/backfill_dataset_snapshots.py` remains available as a direct database
variant.

The full CI script can export the same dry-run reports with one flag:

```bash
scripts/run_dataset_eval_gate.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --artifact-dir artifacts/evaluations \
  --snapshot-backfill-audit
```

If you only want to export artifacts without failing the job, call
`scripts/export_eval_report.py` directly:

```bash
scripts/export_eval_report.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --run-id "$CODEMATE_CANDIDATE_RUN_ID" \
  --format markdown \
  --output "artifacts/evaluations/$CODEMATE_CANDIDATE_RUN_ID.md"
```

To export a filtered trend report for README or CI artifacts:

```bash
scripts/export_eval_history_report.py \
  --base-url "$CODEMATE_API_BASE_URL" \
  --dataset-id "$CODEMATE_EVAL_DATASET_ID" \
  --format markdown \
  --status completed \
  --gate-status failed \
  --limit 50 \
  --output "artifacts/evaluations/$CODEMATE_EVAL_DATASET_ID-trend.md"
```

The recommended CI behavior is to use `run_dataset_eval_gate.py` for the full
evaluation flow and `if: always()` for artifact upload, so artifacts are
available for passing, failing, and inconclusive runs.
