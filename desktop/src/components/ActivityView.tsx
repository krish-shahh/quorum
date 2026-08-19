import { useEffect, useState } from "react";
import { useRuns } from "@/hooks/use-runs";
import { useRunDetail } from "@/hooks/use-run-detail";
import { useDailyRecap, useDailyRecaps } from "@/hooks/use-daily-recap";
import { useCycleDetail } from "@/hooks/use-cycles";
import { cn, formatSignedUsd, formatUsd, gateColor, pnlTextColor } from "@/lib/utils";
import type { RunMode, RunSummary, TraceEvent } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";
import CommentButton from "@/components/CommentButton";

const MODES: (RunMode | "all")[] = ["all", "paper", "backtest", "shadow", "walkforward", "live"];
const today = () => new Date().toISOString().slice(0, 10);

/** The data engineer's / PM's blotter — every run the strategy engine has
 * produced, todays activity front and center, drill into any row for the
 * full decision + reasoning trace. Merges the old Runs, Today, and Logs
 * tabs: those were really one "what happened, and why" workflow split
 * across three pages. */
export default function ActivityView() {
  const [scope, setScope] = useState<"today" | "all">("today");
  const [mode, setMode] = useState<RunMode | "all">("all");
  const [selectedDate, setSelectedDate] = useState(today());
  const [selectedRun, setSelectedRun] = useState<string | null>(null);

  const { data: recentDays } = useDailyRecaps(14);
  const { data: recap } = useDailyRecap(selectedDate);
  const { data, isLoading } = useRuns(mode === "all" ? undefined : { mode });

  const rows = scope === "today"
    ? (data?.runs ?? []).filter((r) => r.started_at.startsWith(selectedDate))
    : (data?.runs ?? []);

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-1.5">
          <ScopeButton active={scope === "today"} onClick={() => setScope("today")}>Today</ScopeButton>
          <ScopeButton active={scope === "all"} onClick={() => setScope("all")}>All runs</ScopeButton>
        </div>

        {scope === "today" ? (
          <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
            {(recentDays?.recaps ?? []).map((r) => (
              <button
                key={r.d}
                onClick={() => setSelectedDate(r.d)}
                className={cn(
                  "text-[11px] font-mono px-2.5 py-1 rounded-full whitespace-nowrap transition-colors",
                  selectedDate === r.d ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"
                )}
              >
                {r.d}
              </button>
            ))}
          </div>
        ) : (
          <div className="flex items-center gap-1.5">
            {MODES.map((m) => (
              <button
                key={m}
                onClick={() => setMode(m)}
                className={cn(
                  "text-[11px] font-medium px-2.5 py-1 rounded-full transition-colors",
                  mode === m ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"
                )}
              >
                {m}
              </button>
            ))}
          </div>
        )}
      </div>

      {scope === "today" && recap && (
        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
          <Kpi label="Runs" value={String(recap.summary.n_runs)} />
          <Kpi label="Candidates" value={String(recap.summary.n_candidates)} />
          <Kpi label="Decisions" value={String(recap.summary.n_decisions)} />
          <Kpi label="Fills" value={String(recap.summary.n_fills)} />
          <Kpi
            label="Realized P&L"
            value={recap.summary.realized_pnl != null ? formatSignedUsd(recap.summary.realized_pnl) : "---"}
            className={pnlTextColor(recap.summary.realized_pnl)}
          />
        </div>
      )}

      <div className="rounded-lg border bg-card overflow-hidden">
        <table className="w-full text-xs">
          <thead className="bg-muted/50 text-muted-foreground">
            <tr>
              <th className="text-left font-medium px-3 py-2">Strategy</th>
              <th className="text-left font-medium px-3 py-2">Mode</th>
              <th className="text-left font-medium px-3 py-2">Status</th>
              <th className="text-left font-medium px-3 py-2">Started</th>
              <th className="text-right font-medium px-3 py-2">Gate</th>
              <th className="text-right font-medium px-3 py-2">Metrics</th>
              <th className="w-8 px-1 py-2"></th>
            </tr>
          </thead>
          <tbody className="divide-y">
            {isLoading ? (
              <tr><td colSpan={7} className="text-center py-8 text-muted-foreground">Loading runs...</td></tr>
            ) : rows.length === 0 ? (
              <tr>
                <td colSpan={7} className="text-center py-8 text-muted-foreground">
                  {scope === "today" ? `No runs on ${selectedDate}.` : "No runs yet."}
                </td>
              </tr>
            ) : (
              rows.map((r) => (
                <tr
                  key={r.run_id}
                  onClick={() => setSelectedRun(r.run_id)}
                  className="group hover:bg-muted/30 cursor-pointer"
                >
                  <td className="px-3 py-2 font-mono">{r.strategy_id}</td>
                  <td className="px-3 py-2">
                    <Badge variant="secondary" className="font-normal">{r.mode}</Badge>
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">{r.status}</td>
                  <td className="px-3 py-2 text-muted-foreground font-mono">{r.started_at}</td>
                  <td className="px-3 py-2 text-right">
                    <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", gateColor(r.gate_passed))}>
                      {r.gate_passed === null ? "N/A" : r.gate_passed ? "PASS" : "FAIL"}
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono text-muted-foreground">
                    <RunMetricsPreview r={r} />
                  </td>
                  <td className="px-1 py-2" onClick={(e) => e.stopPropagation()}>
                    <CommentButton anchorType="run" anchor={{ run_id: r.run_id }} />
                  </td>
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      {scope === "today" && recap && recap.closed_trades.length > 0 && (
        <div className="rounded-lg border bg-card p-4">
          <h3 className="text-sm font-medium mb-2">Closed today</h3>
          <div className="space-y-1">
            {recap.closed_trades.map((t, i) => (
              <div key={i} className="flex items-center justify-between text-xs px-2 py-1 rounded bg-muted/40">
                <span className="font-mono">{t.symbol} × {t.qty}</span>
                <span className={cn("font-mono", pnlTextColor(t.pnl))}>{formatSignedUsd(t.pnl)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      <RunDetailDialog runId={selectedRun} onClose={() => setSelectedRun(null)} />
    </div>
  );
}

function ScopeButton({ active, onClick, children }: { active: boolean; onClick: () => void; children: React.ReactNode }) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "text-[11px] font-medium px-2.5 py-1 rounded-full transition-colors",
        active ? "bg-accent text-accent-foreground" : "text-muted-foreground hover:bg-accent/50"
      )}
    >
      {children}
    </button>
  );
}

function Kpi({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div className="rounded-lg border bg-card p-3">
      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
      <p className={cn("text-sm font-mono font-medium mt-0.5", className)}>{value}</p>
    </div>
  );
}

function RunMetricsPreview({ r }: { r: RunSummary }) {
  const m = r.metrics as Record<string, number | undefined>;
  if (m.final_equity != null) return <>${Math.round(m.final_equity).toLocaleString()}</>;
  if (m.n_trades != null) return <>{m.n_trades} trades</>;
  return <>---</>;
}

function RunDetailDialog({ runId, onClose }: { runId: string | null; onClose: () => void }) {
  const { data: detail, isLoading } = useRunDetail(runId);
  const [showTrace, setShowTrace] = useState(false);

  // Collapsed by default — reset when a different run is opened.
  useEffect(() => setShowTrace(false), [runId]);

  return (
    <Dialog open={runId != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="font-mono text-sm">{runId}</DialogTitle>
        </DialogHeader>

        {isLoading || !detail ? (
          <p className="text-sm text-muted-foreground py-8 text-center">Loading run detail...</p>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="grid grid-cols-3 gap-2">
              <Field label="Strategy" value={detail.strategy_id} />
              <Field label="Mode" value={detail.mode} />
              <Field label="Status" value={detail.status} />
            </div>

            {detail.gate.checks && (
              <Section title="Gate checklist">
                <div className="space-y-1">
                  {detail.gate.checks.map((c) => (
                    <div key={c.name} className="flex items-center justify-between px-2 py-1 rounded bg-muted/40">
                      <span className="font-mono">{c.name}</span>
                      <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", gateColor(c.passed))}>
                        {c.passed ? "PASS" : "FAIL"}
                      </span>
                    </div>
                  ))}
                </div>
              </Section>
            )}

            <Section title={`Candidates (${detail.candidates.length} fired, ${detail.n_signals_suppressed} suppressed)`}>
              {detail.candidates.length === 0 ? (
                <Empty />
              ) : (
                <div className="space-y-1">
                  {detail.candidates.map((c, i) => (
                    <div key={i} className="flex items-center justify-between px-2 py-1 rounded bg-muted/40">
                      <span className="font-mono">{c.symbol}</span>
                      <span className="text-muted-foreground">{c.direction > 0 ? "long" : "short"}{c.score != null ? ` · score ${c.score.toFixed(2)}` : ""}</span>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section title={`Orders & Fills (${detail.orders.length})`}>
              {detail.orders.length === 0 ? (
                <Empty />
              ) : (
                <div className="space-y-1">
                  {detail.orders.map((o, i) => (
                    <div key={i} className="flex items-center justify-between px-2 py-1 rounded bg-muted/40">
                      <span className="font-mono">{o.side.toUpperCase()} {o.qty} {o.symbol}</span>
                      <span className="text-muted-foreground">
                        {o.price != null ? `@ ${formatUsd(o.price)}` : o.status}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section title={`Decisions (${detail.decisions.length})`}>
              {detail.decisions.length === 0 ? (
                <Empty />
              ) : (
                <div className="space-y-1">
                  {detail.decisions.map((d, i) => (
                    <div key={i} className="px-2 py-1.5 rounded bg-muted/40">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="font-medium">{d.kind}</span>
                        <span className="text-muted-foreground">{d.author}</span>
                      </div>
                      <p className="text-muted-foreground">{d.body}</p>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            <Section title={`Closed Trades (${detail.closed_trades.length})`}>
              {detail.closed_trades.length === 0 ? (
                <Empty />
              ) : (
                <div className="space-y-1">
                  {detail.closed_trades.map((t, i) => (
                    <div key={i} className="flex items-center justify-between px-2 py-1 rounded bg-muted/40">
                      <span className="font-mono">{t.symbol} × {t.qty}</span>
                      <span className={cn("font-mono", pnlTextColor(t.pnl))}>{formatSignedUsd(t.pnl)}</span>
                    </div>
                  ))}
                </div>
              )}
            </Section>

            {detail.cycle_id && (
              <div>
                <button
                  onClick={() => setShowTrace((v) => !v)}
                  className="text-[11px] font-medium text-accent-foreground hover:underline"
                >
                  {showTrace ? "Hide reasoning trace ▲" : "Show reasoning trace ▼"}
                </button>
                {showTrace && <TraceTimeline cycleId={detail.cycle_id} />}
              </div>
            )}
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function TraceTimeline({ cycleId }: { cycleId: string }) {
  const { data, isLoading } = useCycleDetail(cycleId);

  if (isLoading || !data) {
    return <p className="text-muted-foreground py-4 text-center">Loading trace...</p>;
  }

  return (
    <div className="mt-2 rounded-lg border bg-card p-3 max-h-[40vh] overflow-y-auto space-y-1.5">
      {data.trace_events.length === 0 ? (
        <p className="text-muted-foreground text-center py-6">No events in this cycle.</p>
      ) : (
        data.trace_events.map((e) => <TraceEventRow key={e.event_id} event={e} />)
      )}
    </div>
  );
}

function TraceEventRow({ event }: { event: TraceEvent }) {
  const nested = event.parent_tool_use_id != null;

  return (
    <div className={cn("rounded px-2 py-1.5", nested ? "ml-5 border-l-2 border-accent bg-muted/30" : "bg-muted/40")}>
      <div className="flex items-center gap-2 mb-0.5">
        <span className="text-[9px] font-mono text-muted-foreground">{event.ts}</span>
        <span className={cn("text-[9px] uppercase tracking-wider font-medium", eventTypeColor(event.event_type))}>
          {event.event_type}
        </span>
        {nested && <span className="text-[9px] text-muted-foreground">(subagent)</span>}
      </div>

      {event.event_type === "tool_use" ? (
        <div>
          <span className="font-mono font-medium">{event.tool_name}</span>
          {event.tool_input && Object.keys(event.tool_input).length > 0 && (
            <pre className="mt-1 text-[10px] text-muted-foreground whitespace-pre-wrap break-all">
              {JSON.stringify(event.tool_input)}
            </pre>
          )}
        </div>
      ) : event.event_type === "tool_result" ? (
        <p className="text-muted-foreground whitespace-pre-wrap break-words">{event.tool_output_summary}</p>
      ) : (
        <p className={cn("whitespace-pre-wrap break-words", event.event_type === "thinking" && "text-muted-foreground italic")}>
          {event.text}
        </p>
      )}
    </div>
  );
}

function eventTypeColor(type: TraceEvent["event_type"]): string {
  switch (type) {
    case "tool_use": return "text-accent-foreground";
    case "tool_result": return "text-muted-foreground";
    case "thinking": return "text-muted-foreground";
    default: return "text-foreground";
  }
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
      <p className="font-mono">{value}</p>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h4 className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">{title}</h4>
      {children}
    </div>
  );
}

function Empty() {
  return <p className="text-muted-foreground px-2 py-1">None.</p>;
}
