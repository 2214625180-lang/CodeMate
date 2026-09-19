const stages = [
  {
    label: "仓库证据",
    detail: "AST 代码块、代码引用、符号与引用查询",
    accent: "bg-cyan-500"
  },
  {
    label: "受控 Agent 循环",
    detail: "结构校验、预算、检查点与失败复盘",
    accent: "bg-violet-500"
  },
  {
    label: "隔离执行",
    detail: "应用补丁、命令白名单、禁网测试",
    accent: "bg-amber-500"
  },
  {
    label: "验证与门禁",
    detail: "修前、目标与回归测试证据；基准评测产物",
    accent: "bg-emerald-500"
  }
];

export function ArchitectureMap() {
  return (
    <ol className="grid gap-3 md:grid-cols-4" aria-label="CodeMate 系统架构">
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
