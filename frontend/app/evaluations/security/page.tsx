"use client";

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import type { SecurityAuditRecord } from "@/lib/securityAudit";

export default function EvaluationSecurityLogPage() {
  const [events, setEvents] = useState<SecurityAuditRecord[]>([]);
  const [limit, setLimit] = useState(100);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const loadEvents = useCallback(async () => {
    setIsLoading(true);
    try {
      const response = await fetch(`/api/admin/security-events?limit=${limit}`, {
        cache: "no-store"
      });
      const data = (await response.json().catch(() => ({}))) as {
        events?: SecurityAuditRecord[];
        detail?: string;
      };
      if (!response.ok) {
        throw new Error(data.detail || `Request failed with status ${response.status}`);
      }
      setEvents(data.events ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load security events");
    } finally {
      setIsLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    void loadEvents();
  }, [loadEvents]);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <p className="text-sm font-medium uppercase text-slate-500">Security</p>
          <h1 className="mt-2 text-2xl font-semibold text-slate-950">Security Event Log</h1>
          <p className="mt-2 max-w-3xl text-sm text-slate-600">
            Review Evaluation Center authentication, RBAC, proxy, and audit-read events.
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link
            href="/evaluations"
            className="rounded-md border border-border px-3 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Evaluation Center
          </Link>
          <button
            type="button"
            onClick={() => void loadEvents()}
            className="rounded-md bg-slate-950 px-3 py-2 text-sm font-medium text-white hover:bg-slate-800"
          >
            Refresh
          </button>
        </div>
      </div>

      <section className="rounded-lg border border-border bg-white p-5">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <label className="text-sm font-medium text-slate-700" htmlFor="security-limit">
            Recent events
          </label>
          <select
            id="security-limit"
            value={limit}
            onChange={(event) => setLimit(Number(event.target.value))}
            className="min-h-10 rounded-md border border-border bg-white px-3 text-sm outline-none focus:border-slate-500"
          >
            {[50, 100, 200, 500].map((value) => (
              <option key={value} value={value}>
                {value}
              </option>
            ))}
          </select>
        </div>

        {error ? <div className="mt-4 rounded-md bg-red-50 p-3 text-sm text-red-700">{error}</div> : null}

        {isLoading ? (
          <div className="mt-4 text-sm text-slate-500">Loading security events...</div>
        ) : events.length === 0 ? (
          <div className="mt-4 text-sm text-slate-500">No security events recorded yet.</div>
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead>
                <tr className="border-b border-border text-xs uppercase text-slate-500">
                  <th className="py-2 pr-4 font-medium">Time</th>
                  <th className="py-2 pr-4 font-medium">Event</th>
                  <th className="py-2 pr-4 font-medium">Outcome</th>
                  <th className="py-2 pr-4 font-medium">Actor</th>
                  <th className="py-2 pr-4 font-medium">Request</th>
                  <th className="py-2 pr-4 font-medium">Reason</th>
                </tr>
              </thead>
              <tbody>
                {events.map((event) => (
                  <tr key={event.id} className="border-b border-border last:border-0">
                    <td className="whitespace-nowrap py-2 pr-4 text-xs text-slate-600">
                      {formatDate(event.timestamp)}
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-800">
                      {event.eventType}
                    </td>
                    <td className="py-2 pr-4">
                      <OutcomeBadge outcome={event.outcome} />
                    </td>
                    <td className="py-2 pr-4 text-slate-700">
                      {event.actor?.login ?? "anonymous"}
                      <span className="ml-1 text-xs text-slate-500">
                        {event.actor?.role ?? "none"}
                      </span>
                    </td>
                    <td className="py-2 pr-4 font-mono text-xs text-slate-700">
                      {event.method ?? "n/a"} {event.path ?? ""}
                      {event.status ? <span className="ml-2 text-slate-500">{event.status}</span> : null}
                    </td>
                    <td className="max-w-[260px] truncate py-2 pr-4 text-slate-600">
                      {event.reason ?? "n/a"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function OutcomeBadge({ outcome }: { outcome: SecurityAuditRecord["outcome"] }) {
  const className =
    outcome === "success"
      ? "bg-emerald-50 text-emerald-700"
      : outcome === "blocked"
        ? "bg-amber-50 text-amber-700"
        : "bg-red-50 text-red-700";
  return (
    <span className={`rounded-md px-2 py-1 text-xs font-medium ${className}`}>
      {outcome}
    </span>
  );
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString();
}
