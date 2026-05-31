import { cn } from "@/lib/utils";
import type { Analytics, TradesData } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  analytics: Analytics;
  trades: TradesData;
}

export default function AnalyticsGrid({ analytics, trades }: Props) {
  const metrics = [
    { label: "Sharpe", value: analytics.sharpe?.toFixed(2), good: (analytics.sharpe || 0) > 1, tip: "Risk-adjusted return — >1 good, >2 excellent" },
    { label: "Sortino", value: analytics.sortino?.toFixed(2), good: (analytics.sortino || 0) > 1.5, tip: "Downside risk-adjusted return — >1.5 good" },
    { label: "Max DD", value: analytics.max_dd != null ? `${analytics.max_dd.toFixed(1)}%` : undefined, good: (analytics.max_dd || 0) > -10, tip: "Worst peak-to-trough decline" },
    { label: "Alpha", value: analytics.alpha != null ? `${analytics.alpha.toFixed(2)}%` : undefined, good: (analytics.alpha || 0) > 0, tip: "Excess return vs. SPY benchmark" },
    { label: "Profit Factor", value: analytics.profit_factor?.toFixed(2), good: (analytics.profit_factor || 0) > 1.5, tip: "Gross profit / gross loss — >1.5 good" },
    { label: "Expectancy", value: analytics.expectancy != null ? `$${analytics.expectancy.toFixed(0)}` : undefined, good: (analytics.expectancy || 0) > 0, tip: "Expected profit per trade" },
    { label: "SQN", value: analytics.sqn?.toFixed(2), good: (analytics.sqn || 0) > 2, tip: "System Quality Number — >2 good, >3 excellent" },
    { label: "Win Rate", value: `${(trades.win_rate * 100).toFixed(0)}%`, good: trades.win_rate > 0.5, tip: `${trades.wins} wins / ${trades.losses} losses` },
  ];

  return (
    <div className="rounded-lg border bg-card p-4 h-full">
      <h3 className="text-sm font-medium mb-3">Analytics</h3>
      <div className="grid grid-cols-2 gap-3">
        {metrics.map((m) => (
          <Tooltip key={m.label}>
            <TooltipTrigger asChild>
              <div className="cursor-default">
                <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{m.label}</span>
                <p className={cn("text-sm font-mono font-medium", m.value != null && (m.good ? "text-green-600" : "text-red-600"))}>
                  {m.value ?? "---"}
                </p>
              </div>
            </TooltipTrigger>
            <TooltipContent>
              <p>{m.tip}</p>
            </TooltipContent>
          </Tooltip>
        ))}
      </div>

      {/* Signal distribution */}
      {analytics.wr_signal && analytics.wr_signal.length > 0 && (
        <div className="mt-4 pt-3 border-t">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2">By Signal</p>
          <div className="space-y-1">
            {analytics.wr_signal.map((s) => (
              <div key={s.signal} className="flex items-center justify-between text-[11px]">
                <span className="text-muted-foreground">{s.signal}</span>
                <span className="font-mono">{s.wr}% ({s.wins}W/{s.losses}L)</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
