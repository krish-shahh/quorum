import { useState } from "react";
import { useDailyRecap, useDailyRecaps } from "@/hooks/use-daily-recap";
import { cn, formatSignedUsd, pnlTextColor } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";

export default function TodayView() {
  const { data: recentDays, isLoading: loadingList } = useDailyRecaps(14);
  const today = new Date().toISOString().slice(0, 10);
  const [selectedDate, setSelectedDate] = useState(today);
  const { data: recap, isLoading: loadingRecap, isError } = useDailyRecap(selectedDate);

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
        {loadingList ? (
          <span className="text-xs text-muted-foreground">Loading days...</span>
        ) : (recentDays?.recaps.length ?? 0) === 0 ? (
          <span className="text-xs text-muted-foreground">
            No days saved yet — run <code className="font-mono">quorum daily-recap</code> at end of day.
          </span>
        ) : (
          recentDays!.recaps.map((r) => (
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
          ))
        )}
      </div>

      {loadingRecap ? (
        <p className="text-sm text-muted-foreground py-12 text-center">Loading play-by-play...</p>
      ) : isError || !recap ? (
        <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          No recap saved for {selectedDate} yet.
        </div>
      ) : (
        <div className="space-y-4">
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

          {recap.runs.length === 0 ? (
            <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
              No runs started this day.
            </div>
          ) : (
            <div className="space-y-3">
              {recap.runs.map((run) => (
                <div key={run.run_id} className="rounded-lg border bg-card p-4">
                  <div className="flex items-center justify-between mb-2">
                    <div className="flex items-center gap-2">
                      <span className="font-mono text-sm font-medium">{run.strategy_id}</span>
                      <Badge variant="secondary" className="font-normal">{run.mode}</Badge>
                    </div>
                    <span className="text-[11px] text-muted-foreground font-mono">{run.started_at}</span>
                  </div>

                  {run.candidates.length > 0 && (
                    <div className="mb-2 flex flex-wrap gap-1">
                      {run.candidates.map((c, i) => (
                        <span key={i} className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-muted text-muted-foreground">
                          {c.symbol} {c.direction > 0 ? "long" : "short"}
                        </span>
                      ))}
                    </div>
                  )}

                  {run.decisions.map((d, i) => (
                    <p key={i} className="text-xs text-muted-foreground mb-1">
                      <span className="font-medium text-foreground">{d.kind}</span> — {d.body}
                    </p>
                  ))}

                  {run.orders.map((o, i) => (
                    <p key={i} className="text-xs font-mono text-muted-foreground">
                      {o.side.toUpperCase()} {o.qty} {o.symbol} {o.price != null ? `@ $${o.price}` : `(${o.status})`}
                    </p>
                  ))}
                </div>
              ))}
            </div>
          )}

          {recap.closed_trades.length > 0 && (
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
        </div>
      )}
    </div>
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
