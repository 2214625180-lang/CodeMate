type TestEvidence = Record<string, unknown>;

export function TestResultPanel({ result }: { result: unknown }) {
  const data = isRecord(result) ? result : {};
  const phases = [
    ["Baseline reproduction", recordValue(data.baseline)],
    ["Targeted tests", recordValue(data.targeted)],
    ["Regression checks", recordValue(data.regression)]
  ].filter((entry): entry is [string, TestEvidence] => entry[1] !== null);
  const verdict = stringValue(data.status) ?? evidenceOutcome(data);

  return (
    <div className="rounded-md border border-border bg-white p-4">
      <div className="flex items-center justify-between gap-4">
        <h3 className="text-sm font-semibold text-slate-950">
          {phases.length > 0 ? "Verification Evidence" : phaseTitle(data)}
        </h3>
        <VerdictBadge value={verdict} />
      </div>
      {typeof data.reason === "string" ? (
        <p className="mt-2 text-xs text-slate-600">{data.reason}</p>
      ) : null}
      {phases.length > 0 ? (
        <div className="mt-4 space-y-3">
          {phases.map(([label, evidence]) => (
            <EvidenceCard key={label} label={label} evidence={evidence} />
          ))}
        </div>
      ) : (
        <EvidenceDetails evidence={data} />
      )}
    </div>
  );
}

function EvidenceCard({ label, evidence }: { label: string; evidence: TestEvidence }) {
  return (
    <section className="rounded-md border border-slate-200 p-3">
      <div className="flex items-center justify-between gap-3">
        <p className="text-xs font-semibold text-slate-800">{label}</p>
        <VerdictBadge value={evidenceOutcome(evidence)} />
      </div>
      <EvidenceDetails evidence={evidence} />
    </section>
  );
}

function EvidenceDetails({ evidence }: { evidence: TestEvidence }) {
  const output = [evidence.stdout, evidence.stderr].filter(Boolean).join("\n");
  return (
    <>
      <div className="mt-3 grid gap-2 text-xs text-slate-600 sm:grid-cols-3">
        <span>command: {String(evidence.command ?? "n/a")}</span>
        <span>exit: {String(evidence.exit_code ?? "n/a")}</span>
        <span>ran: {String(evidence.tests_ran ?? false)}</span>
      </div>
      {evidence.skipped_reason ? (
        <p className="mt-2 text-xs text-amber-700">
          skipped: {String(evidence.skipped_reason)}
        </p>
      ) : null}
      <pre className="mt-3 max-h-72 overflow-auto rounded bg-slate-950 p-3 text-xs text-slate-100">
        <code>{output || "(no output)"}</code>
      </pre>
    </>
  );
}

function VerdictBadge({ value }: { value: string }) {
  const style = badgeStyle(value);
  return (
    <span className={`rounded-full px-2.5 py-1 text-xs font-medium ${style}`}>
      {value}
    </span>
  );
}

function evidenceOutcome(evidence: TestEvidence) {
  if (evidence.tests_ran === true && evidence.exit_code === 0 && evidence.passed === true) {
    return "passed";
  }
  if (evidence.failure_kind === "infrastructure" || evidence.timed_out === true) {
    return "infra_error";
  }
  if (evidence.failure_kind === "skipped" || evidence.skipped_reason) {
    return "skipped";
  }
  if (evidence.tests_ran === true) {
    return "failed";
  }
  return "not_run";
}

function phaseTitle(evidence: TestEvidence) {
  const phase = stringValue(evidence.phase);
  if (phase === "baseline") return "Baseline Reproduction";
  if (phase === "targeted") return "Targeted Tests";
  if (phase === "regression") return "Regression Checks";
  return "Test Result";
}

function badgeStyle(value: string) {
  if (value === "passed" || value === "verified_success") {
    return "bg-emerald-100 text-emerald-700";
  }
  if (value === "skipped" || value === "unverified_patch" || value === "not_reproduced") {
    return "bg-amber-100 text-amber-800";
  }
  if (value === "not_run") {
    return "bg-slate-100 text-slate-700";
  }
  return "bg-red-100 text-red-700";
}

function recordValue(value: unknown): TestEvidence | null {
  return isRecord(value) ? value : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" && value.length > 0 ? value : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}
