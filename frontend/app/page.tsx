import Link from "next/link";

import { ArchitectureMap } from "@/components/portfolio/ArchitectureMap";
import { DemoReplay } from "@/components/portfolio/DemoReplay";

const SAMPLE_REPOSITORY_ID = "d8ef36d0-7776-5bd1-b219-0bfcb44eaf4c";

const workflowSteps = [
  {
    number: "01",
    title: "复现问题",
    description: "在允许生成补丁之前，先在隔离工作区中运行问题对应的目标测试。"
  },
  {
    number: "02",
    title: "调查定位",
    description: "根据证据选择受限的代码工具：搜索、读取、符号查询、引用查询或测试。"
  },
  {
    number: "03",
    title: "补丁",
    description: "在文件、工具、Token、时间和迭代预算内生成可审查的 Diff。"
  },
  {
    number: "04",
    title: "验证修复",
    description: "只有目标测试和回归测试均实际执行并通过，才报告修复已验证。"
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
              可验证的代码修复助手
            </p>
            <h1 className="mt-6 max-w-3xl text-4xl font-semibold tracking-tight text-slate-950 sm:text-5xl lg:text-6xl">
              从失败测试，到 <span className="text-cyan-700">验证通过的补丁。</span>
            </h1>
            <p className="mt-6 max-w-2xl text-lg leading-8 text-slate-600">
              CodeMate 专注修复 TypeScript 和 Python 仓库中的缺陷：以可引用的代码证据指导每一步操作，在隔离沙箱中验证补丁，并保存完整执行轨迹，供审查和回归门禁使用。
            </p>
            <div className="mt-8 flex flex-wrap gap-3">
              <Link
                href={`/repos/${SAMPLE_REPOSITORY_ID}/fix`}
                className="inline-flex items-center rounded-lg bg-slate-950 px-5 py-3 text-sm font-semibold text-white shadow-lg shadow-slate-950/15 transition hover:-translate-y-0.5 hover:bg-slate-800"
              >
                体验示例修复
                <span aria-hidden="true" className="ml-2">→</span>
              </Link>
              <Link
                href="/evaluations/history"
                className="inline-flex items-center rounded-lg border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-800 transition hover:border-slate-400 hover:bg-slate-50"
              >
                查看评测证据
              </Link>
            </div>
            <p className="mt-3 text-xs leading-5 text-slate-500">
              示例任务由 <code className="rounded bg-slate-100 px-1.5 py-0.5">make demo</code> 创建，打开后可查看已保存的执行时间线。
            </p>
            <dl className="mt-10 grid max-w-xl grid-cols-2 gap-3 sm:grid-cols-3">
              <EvidenceStat value="30" label="个检索用例" />
              <EvidenceStat value="20" label="个修复用例" />
              <EvidenceStat value="4 个阶段" label="严格的成功判定规则" />
            </dl>
          </div>
          <DemoReplay />
        </div>
      </section>

      <section id="workflow" aria-labelledby="workflow-title">
        <div className="max-w-3xl">
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-cyan-700">修复闭环</p>
          <h2 id="workflow-title" className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">
            每一步都有证据支撑。
          </h2>
          <p className="mt-4 text-lg leading-8 text-slate-600">
            模型根据观察结果选择下一项代码工具。确定性策略限制可调用的工具、调用次数，以及结束任务所需的证据。
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
          <p className="text-sm font-semibold uppercase tracking-[0.16em] text-cyan-300">实测证据</p>
          <h2 id="evidence-title" className="mt-3 text-3xl font-semibold tracking-tight">
            用评测产物证明效果。
          </h2>
          <p className="mt-4 max-w-xl leading-7 text-slate-300">
            每次评测都会记录数据集快照、提示词哈希、服务商与模型配置、代码提交、耗时，以及判定结果所依据的证据。
          </p>
          <Link
            href="/evaluations/history"
            className="mt-7 inline-flex items-center text-sm font-semibold text-cyan-300 hover:text-cyan-200"
          >
            查看完整评测报告 <span aria-hidden="true" className="ml-2">→</span>
          </Link>
        </div>
        <div className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-8">
          <p className="text-sm font-semibold text-slate-500">最近提交的检索冒烟测试产物</p>
          <div className="mt-6 grid gap-5 sm:grid-cols-3">
            <Metric value="93.33%" label="混合检索 Recall@5" />
            <Metric value="0.6956" label="混合检索 MRR" />
            <Metric value="17.5 ms" label="混合检索 P95 耗时" />
          </div>
          <p className="mt-7 border-t border-slate-100 pt-4 text-sm leading-6 text-slate-500">
            共 30 个检索用例，测量于 2026-08-02。此产物明确标记为
            <strong className="font-semibold text-slate-700"> 仅用于工程冒烟测试</strong>：使用确定性的 Mock embedding，且工作区包含未提交修改，因此不能代表生产模型效果。修复成功率将在获得真实模型评测产物后发布。
          </p>
        </div>
      </section>

      <section aria-labelledby="architecture-title">
        <div className="flex flex-col justify-between gap-4 sm:flex-row sm:items-end">
          <div className="max-w-3xl">
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-violet-700">系统架构</p>
            <h2 id="architecture-title" className="mt-3 text-3xl font-semibold tracking-tight text-slate-950">
              围绕可验证的修复规则构建。
            </h2>
          </div>
          <Link href="/evaluations/compare" className="text-sm font-semibold text-slate-700 hover:text-slate-950">
            查看回归门禁 →
          </Link>
        </div>
        <div className="mt-8 rounded-2xl border border-slate-200 bg-slate-50 p-4 sm:p-6">
          <ArchitectureMap />
        </div>
      </section>

      <section className="rounded-2xl border border-slate-200 bg-white p-7 shadow-sm sm:p-8" aria-labelledby="extensions-title">
        <div className="grid gap-6 lg:grid-cols-[1fr_auto] lg:items-center">
          <div>
            <p className="text-sm font-semibold uppercase tracking-[0.16em] text-slate-500">生产环境扩展</p>
            <h2 id="extensions-title" className="mt-3 text-2xl font-semibold tracking-tight text-slate-950">
              深入了解运行管理能力。
            </h2>
            <p className="mt-3 max-w-3xl leading-7 text-slate-600">
              MCP 服务注册、租户配额、基于 KMS 的凭据管理、SIEM 审计投递和托管沙箱执行，供进一步研究工程实现。理解核心代码修复流程无需先掌握这些扩展。
            </p>
          </div>
          <Link
            href="/mcp-operations"
            className="inline-flex items-center justify-center rounded-lg border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-800 transition hover:border-slate-400 hover:bg-slate-50"
          >
            查看扩展功能
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
