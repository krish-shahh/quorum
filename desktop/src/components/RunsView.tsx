import { useState } from "react";
import { useRuns } from "@/hooks/use-runs";
import { useRunDetail } from "@/hooks/use-run-detail";
import { cn, formatSignedUsd, formatUsd, gateColor, pnlTextColor } from "@/lib/utils";
import type { RunMode, RunSummary } from "@/lib/api";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Badge } from "@/components/ui/badge";

const MODES: (RunMode | "all")[] = ["all", "paper", "backtest", "shadow", "walkforward", "live"];

export default function RunsView({ onViewTrace }: { onViewTrace?: (cycleId: string) => void }) {
  const [mode, setMode] = useState<RunMode | "all">("all");
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const { data, isLoading } = useRuns(mode === "all" ? undefined : { mode });

  return (
    <div className="space-y-3">
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
            </tr>
          </thead>
          <tbody className="divide-y">
            {isLoading ? (
              <tr><td colSpan={6} className="text-center py-8 text-muted-foreground">Loading runs...</td></tr>
            ) : !data || data.runs.length === 0 ? (
              <tr><td colSpan={6} className="text-center py-8 text-muted-foreground">No runs yet.</td></tr>
            ) : (
              data.runs.map((r) => (
                <tr
                  key={r.run_id}
                  onClick={() => setSelectedRun(r.run_id)}
                  className="hover:bg-muted/30 cursor-pointer"
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
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>

      <RunDetailDialog runId={selectedRun} onClose={() => setSelectedRun(null)} onViewTrace={onViewTrace} />
    </div>
  );
}

function RunMetricsPreview({ r }: { r: RunSummary }) {
  const m = r.metrics as Record<string, number | undefined>;
  if (m.final_equity != null) return <>${Math.round(m.final_equity).toLocaleString()}</>;
  if (m.n_trades != null) return <>{m.n_trades} trades</>;
  return <>---</>;
}

function RunDetailDialog({
  runId, onClose, onViewTrace,
}: {
  runId: string | null;
  onClose: () => void;
  onViewTrace?: (cycleId: string) => void;
}) {
  const { data: detail, isLoading } = useRunDetail(runId);

  return (
    <Dialog open={runId != null} onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <div className="flex items-center justify-between gap-2 pr-6">
            <DialogTitle className="font-mono text-sm">{runId}</DialogTitle>
            {detail?.cycle_id && onViewTrace && (
              <button
                onClick={() => onViewTrace(detail.cycle_id!)}
                className="text-[11px] font-medium text-accent-foreground hover:underline shrink-0"
              >
                View trace →
              </button>
            )}
          </div>
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
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
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
