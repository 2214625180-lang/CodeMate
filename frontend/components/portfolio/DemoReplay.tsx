"use client";

import { useEffect, useMemo, useState } from "react";

const LOOP_DURATION_MS = 36_000;
const TICK_INTERVAL_MS = 100;

const replaySteps = [
  {
    id: "reproduce",
    label: "复现问题",
    durationMs: 8_000,
    command: "npm run test:targeted",
    result: "失败 · -20 !== 0",
    detail: "固定优惠券使购物车折后小计变成负数。",
    tone: "rose"
  },
  {
    id: "investigate",
    label: "调查定位",
    durationMs: 9_000,
    command: "SearchCode → ReadFile → FindReferences",
    result: "证据 · cart.js + checkout.js",
    detail: "Agent 沿折后小计的调用链定位到结算税费计算。",
    tone: "amber"
  },
  {
    id: "patch",
    label: "补丁",
    durationMs: 9_000,
    command: "GeneratePatch → ApplyPatch",
    result: "修改了 2 个生产代码文件",
    detail: "将折后小计下限设为 0，并按折后小计计算税费。",
    tone: "violet"
  },
  {
    id: "verify",
    label: "验证修复",
    durationMs: 10_000,
    command: "目标测试 → 回归测试",
    result: "修复验证通过 · 3/3 通过",
    detail: "只有修前失败、目标测试通过和回归测试通过的证据齐全，才判定修复成功。",
    tone: "emerald"
  }
] as const;

type ReplayStep = (typeof replaySteps)[number];

export function DemoReplay() {
  const [elapsedMs, setElapsedMs] = useState(0);
  const [isPlaying, setIsPlaying] = useState(true);

  useEffect(() => {
    if (!isPlaying) {
      return undefined;
    }
    const interval = window.setInterval(() => {
      setElapsedMs((current) => (current + TICK_INTERVAL_MS) % LOOP_DURATION_MS);
    }, TICK_INTERVAL_MS);
    return () => window.clearInterval(interval);
  }, [isPlaying]);

  const activeIndex = useMemo(() => {
    let boundary = 0;
    for (const [index, step] of replaySteps.entries()) {
      boundary += step.durationMs;
      if (elapsedMs < boundary) {
        return index;
      }
    }
    return replaySteps.length - 1;
  }, [elapsedMs]);
  const activeStep = replaySteps[activeIndex];
  const elapsedSeconds = Math.floor(elapsedMs / 1_000)
    .toString()
    .padStart(2, "0");

  function restart() {
    setElapsedMs(0);
    setIsPlaying(true);
  }

  return (
    <section
      aria-label="36 秒示例运行引导回放"
      className="overflow-hidden rounded-2xl border border-slate-800 bg-slate-950 shadow-2xl shadow-slate-950/20"
    >
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-800 px-4 py-3 sm:px-5">
        <div className="flex items-center gap-3">
          <span className="flex h-2.5 w-2.5 rounded-full bg-emerald-400 shadow-[0_0_14px_rgba(74,222,128,0.9)]" />
          <div>
            <p className="font-mono text-xs font-semibold uppercase tracking-[0.18em] text-slate-200">
              示例运行回放
            </p>
            <p className="mt-0.5 text-xs text-slate-400">
              demo-cart-bug 示例 · 36 秒循环
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <span className="font-mono text-xs text-slate-400">00:{elapsedSeconds} / 00:36</span>
          <button
            type="button"
            onClick={() => setIsPlaying((current) => !current)}
            className="rounded-md border border-slate-700 px-2.5 py-1.5 text-xs font-medium text-slate-200 transition hover:border-slate-500 hover:bg-slate-800"
          >
            {isPlaying ? "暂停" : "播放"}
          </button>
          <button
            type="button"
            onClick={restart}
            className="rounded-md px-2.5 py-1.5 text-xs font-medium text-slate-400 transition hover:bg-slate-800 hover:text-white"
          >
            重新播放
          </button>
        </div>
      </div>

      <div className="px-4 pt-4 sm:px-5">
        <div className="h-1 overflow-hidden rounded-full bg-slate-800">
          <div
            className="h-full rounded-full bg-gradient-to-r from-cyan-400 via-violet-400 to-emerald-400 transition-[width] duration-100"
            style={{ width: `${(elapsedMs / LOOP_DURATION_MS) * 100}%` }}
          />
        </div>
      </div>

      <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[0.9fr_1.1fr]">
        <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-1" aria-label="回放阶段">
          {replaySteps.map((step, index) => {
            const isActive = activeIndex === index;
            const isComplete = activeIndex > index;
            return (
              <li
                key={step.id}
                className={`rounded-xl border p-3 transition ${
                  isActive
                    ? "border-cyan-400/70 bg-slate-800 shadow-[0_0_0_1px_rgba(34,211,238,0.16)]"
                    : "border-slate-800 bg-slate-900/50"
                }`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-bold ${
                      isActive
                        ? "bg-cyan-300 text-slate-950"
                        : isComplete
                          ? "bg-emerald-400 text-emerald-950"
                          : "bg-slate-800 text-slate-500"
                    }`}
                  >
                    {isComplete ? "✓" : index + 1}
                  </span>
                  <div className="min-w-0">
                    <p className={`text-sm font-semibold ${isActive ? "text-white" : "text-slate-300"}`}>
                      {step.label}
                    </p>
                    <p className="truncate font-mono text-[11px] text-slate-500">{step.command}</p>
                  </div>
                </div>
              </li>
            );
          })}
        </ol>

        <ReplayConsole step={activeStep} />
      </div>

      <p className="border-t border-slate-800 px-4 py-3 text-xs leading-5 text-slate-400 sm:px-5">
        此回放根据仓库内置示例的验证规则展示流程，并非实际生产任务记录。点击示例按钮发起真实任务后，可查看已保存的执行证据。
      </p>
    </section>
  );
}

function ReplayConsole({ step }: { step: ReplayStep }) {
  const toneClasses = {
    rose: "border-rose-400/30 bg-rose-400/10 text-rose-200",
    amber: "border-amber-400/30 bg-amber-400/10 text-amber-200",
    violet: "border-violet-400/30 bg-violet-400/10 text-violet-200",
    emerald: "border-emerald-400/30 bg-emerald-400/10 text-emerald-200"
  } as const;

  return (
    <div className="relative overflow-hidden rounded-xl border border-slate-800 bg-[#0b1220] p-4">
      <div className="pointer-events-none absolute inset-0 portfolio-replay-glow" />
      <div className="relative">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <span className="font-mono text-xs uppercase tracking-[0.16em] text-slate-500">
            Agent 执行时间线
          </span>
          <span className={`rounded-full border px-2.5 py-1 font-mono text-[11px] ${toneClasses[step.tone]}`}>
            {step.result}
          </span>
        </div>
        <p className="mt-6 font-mono text-xs text-cyan-300">$ {step.command}</p>
        <p className="mt-3 text-lg font-semibold leading-7 text-white">{step.detail}</p>
        <div className="mt-6 rounded-lg border border-slate-800 bg-slate-950/80 p-3 font-mono text-xs leading-6 text-slate-300">
          {step.id === "reproduce" ? (
            <>
              <p className="text-rose-300">AssertionError: -20 !== 0</p>
              <p className="text-slate-500">tests/cart-coupon.targeted.test.js:7</p>
            </>
          ) : null}
          {step.id === "investigate" ? (
            <>
              <p>evidence[0] src/cart.js · applyFixedCoupon</p>
              <p>evidence[1] src/checkout.js · quoteCheckout</p>
              <p className="text-slate-500">假设：税费必须基于 discountedSubtotal 计算</p>
            </>
          ) : null}
          {step.id === "patch" ? (
            <>
              <p className="text-rose-300">- return subtotal - couponAmount;</p>
              <p className="text-emerald-300">+ return Math.max(0, subtotal - couponAmount);</p>
              <p className="text-emerald-300">+ const tax = calculateTax(discountedSubtotal, taxRate);</p>
            </>
          ) : null}
          {step.id === "verify" ? (
            <>
              <p className="text-emerald-300">targeted: tests_ran=true · exit_code=0</p>
              <p className="text-emerald-300">regression: tests_ran=true · 3 passed</p>
              <p className="text-cyan-300">status: verified_success</p>
            </>
          ) : null}
        </div>
      </div>
    </div>
  );
}
