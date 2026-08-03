const stages = [
  {
    label: "Repository evidence",
    detail: "AST chunks, citations, symbol and reference lookup",
    accent: "bg-cyan-500"
  },
  {
    label: "Controlled Agent Loop",
    detail: "Schema-validated plans, budgets, checkpoints, reflection",
    accent: "bg-violet-500"
  },
  {
    label: "Isolated execution",
    detail: "Patch apply, allowlisted commands, network-disabled tests",
    accent: "bg-amber-500"
  },
  {
    label: "Verification & gates",
    detail: "Baseline, target and regression evidence; benchmark artifacts",
    accent: "bg-emerald-500"
  }
];

export function ArchitectureMap() {
  return (
    <ol className="grid gap-3 md:grid-cols-4" aria-label="CodeMate architecture">
      {stages.map((stage, index) => (
        <li key={stage.label} className="relative rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
          {index < stages.length - 1 ? (
            <span
              aria-hidden="true"
              className="absolute -right-2 top-1/2 z-10 hidden h-4 w-4 -translate-y-1/2 rotate-45 border-r border-t border-slate-300 bg-slate-50 md:block"
            />
          ) : null}
          <div className="flex items-center gap-2">
            <span className={`h-2.5 w-2.5 rounded-full ${stage.accent}`} />
            <span className="text-xs font-medium uppercase tracking-[0.14em] text-slate-500">
              0{index + 1}
            </span>
          </div>
          <h3 className="mt-4 text-base font-semibold text-slate-950">{stage.label}</h3>
          <p className="mt-2 text-sm leading-6 text-slate-600">{stage.detail}</p>
        </li>
      ))}
    </ol>
  );
}
