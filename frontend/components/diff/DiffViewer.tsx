export function DiffViewer({ diff }: { diff: string | null | undefined }) {
  if (!diff) {
    return (
      <div className="rounded-lg border border-dashed border-border bg-white p-5 text-sm text-slate-500">
        No diff yet.
      </div>
    );
  }

  return (
    <pre className="max-h-[520px] overflow-auto rounded-lg border border-border bg-slate-950 p-4 text-xs leading-5">
      <code>
        {diff.split("\n").map((line, index) => (
          <div key={`${index}-${line}`} className={lineClass(line)}>
            {line || " "}
          </div>
        ))}
      </code>
    </pre>
  );
}

function lineClass(line: string) {
  if (line.startsWith("+") && !line.startsWith("+++")) {
    return "text-emerald-300";
  }
  if (line.startsWith("-") && !line.startsWith("---")) {
    return "text-red-300";
  }
  if (line.startsWith("@@")) {
    return "text-sky-300";
  }
  return "text-slate-200";
}
