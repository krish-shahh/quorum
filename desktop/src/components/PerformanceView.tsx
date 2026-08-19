import { useState } from "react";
import { LineChart } from "@/components/dither-kit/area-chart";
import { BarChart } from "@/components/dither-kit/bar-chart";
import { Line } from "@/components/dither-kit/area";
import { Bar } from "@/components/dither-kit/bar";
import { Grid } from "@/components/dither-kit/grid";
import { XAxis } from "@/components/dither-kit/x-axis";
import { YAxis } from "@/components/dither-kit/y-axis";
import { ReferenceLine } from "@/components/dither-kit/reference-line";
import { Tooltip as DitherTooltip } from "@/components/dither-kit/tooltip";
import type { ChartConfig } from "@/components/dither-kit/chart-context";
import { usePerformance } from "@/hooks/use-performance";
import { useRuns } from "@/hooks/use-runs";
import { cn, formatPct, formatSignedUsd, pnlTextColor } from "@/lib/utils";
import type { WinRateBucket } from "@/lib/api";
import CommentButton from "@/components/CommentButton";

const DAY_ORDER = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function PerformanceView() {
  const [runId, setRunId] = useState<string | null>(null);
  const { data: runsData } = useRuns({ limit: 50 });
  const { data, isLoading } = usePerformance(runId);

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-end">
        <select
          value={runId ?? ""}
          onChange={(e) => setRunId(e.target.value || null)}
          className="text-xs font-mono rounded-md border bg-card px-2 py-1.5 text-foreground"
        >
          <option value="">Live book</option>
          {runsData?.runs.map((r) => (
            <option key={r.run_id} value={r.run_id}>
              {r.strategy_id} · {r.mode} · {r.started_at}
            </option>
          ))}
        </select>
      </div>

      {isLoading || !data ? (
        <p className="text-sm text-muted-foreground py-12 text-center">Loading performance...</p>
      ) : (
        <PerformanceBody data={data} />
      )}
    </div>
  );
}

function PerformanceBody({ data }: { data: NonNullable<ReturnType<typeof usePerformance>["data"]> }) {
  const noTrades = data.total_trades === 0;

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-8 gap-3">
        <Kpi label="Sharpe" value={data.sharpe_ratio.toFixed(2)} good={data.sharpe_ratio > 1} />
        <Kpi label="Sortino" value={data.sortino_ratio.toFixed(2)} good={data.sortino_ratio > 1.5} />
        <Kpi label="Max DD" value={formatPct(data.max_drawdown)} good={data.max_drawdown > -0.1} />
        <Kpi label="Profit Factor" value={data.profit_factor === Infinity ? "∞" : data.profit_factor.toFixed(2)} good={data.profit_factor > 1.5} />
        <Kpi label="Expectancy" value={formatSignedUsd(data.expectancy)} good={data.expectancy > 0} />
        <Kpi label="SQN" value={data.sqn.toFixed(2)} good={data.sqn > 2} />
        <Kpi label="Win Rate" value={formatPct(data.win_rate)} good={data.win_rate > 0.5} />
        <Kpi label="Alpha vs SPY" value={formatPct(data.alpha_vs_benchmark.alpha)} good={data.alpha_vs_benchmark.alpha > 0} />
      </div>

      {noTrades ? (
        <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
          No closed trades in the live paper book yet — this view fills in as pod-cycle runs accumulate fills.
        </div>
      ) : (
        <>
          <div className="group relative rounded-lg border bg-card p-4">
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-medium">Rolling Sharpe &amp; Sortino (20-trade window)</h3>
              <CommentButton anchorType="chart_series" anchor={{ view: "performance", chart: "rolling_metrics" }} />
            </div>
            {data.rolling_metrics.length === 0 ? (
              <p className="text-xs text-muted-foreground py-6 text-center">Need at least 20 trades for a rolling window.</p>
            ) : (
              <div className="h-[200px]">
                <LineChart data={data.rolling_metrics} config={ROLLING_METRICS_CONFIG}>
                  <Grid />
                  <XAxis dataKey="time" />
                  <YAxis />
                  <ReferenceLine y={0} />
                  <Line dataKey="rolling_sharpe" />
                  <Line dataKey="rolling_sortino" />
                  <DitherTooltip />
                </LineChart>
              </div>
            )}
          </div>

          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            <WinRateBarCard title="Win Rate by Day of Week" data={sortDayOfWeek(data.win_rate_by_day_of_week)} />
            <WinRateBarCard title="Win Rate by Signal" data={Object.entries(data.win_rate_by_signal).map(([k, v]) => ({ key: k, ...v }))} />
          </div>

          <div className="rounded-lg border bg-card p-4">
            <h3 className="text-sm font-medium mb-3">Win Rate by Ticker</h3>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-2">
              {Object.entries(data.win_rate_by_ticker)
                .sort((a, b) => b[1].wins + b[1].losses - (a[1].wins + a[1].losses))
                .slice(0, 12)
                .map(([ticker, bucket]) => (
                  <div key={ticker} className="group relative flex items-center justify-between text-[11px] px-2 py-1.5 rounded bg-muted/50">
                    <span className="font-mono">{ticker}</span>
                    <span className={cn("font-mono", pnlTextColor(bucket.win_rate - 0.5))}>
                      {formatPct(bucket.win_rate)} ({bucket.wins}W/{bucket.losses}L)
                    </span>
                    <CommentButton
                      anchorType="table_row"
                      anchor={{ view: "performance", table: "win_rate_by_ticker", ticker }}
                      className="absolute -top-1.5 -right-1.5 bg-card border rounded-full"
                    />
                  </div>
                ))}
            </div>
          </div>

          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Kpi label="Best Trade" value={formatSignedUsd(data.best_trade)} good={data.best_trade >= 0} />
            <Kpi label="Worst Trade" value={formatSignedUsd(data.worst_trade)} good={data.worst_trade >= 0} />
            <Kpi label="Avg Trade" value={formatSignedUsd(data.avg_trade_pnl)} good={data.avg_trade_pnl >= 0} />
            <Kpi label="Total Realized" value={formatSignedUsd(data.total_realized_pnl)} good={data.total_realized_pnl >= 0} />
          </div>
        </>
      )}
    </div>
  );
}

const ROLLING_METRICS_CONFIG: ChartConfig = {
  rolling_sharpe: { label: "Sharpe", color: "green" },
  rolling_sortino: { label: "Sortino", color: "blue" },
};

const WIN_RATE_CONFIG: ChartConfig = {
  win_rate: { label: "Win rate", color: "blue" },
};

function sortDayOfWeek(byDay: Record<string, WinRateBucket>) {
  return DAY_ORDER
    .filter((d) => byDay[d])
    .map((d) => ({ key: d, ...byDay[d] }));
}

function WinRateBarCard({ title, data }: { title: string; data: (WinRateBucket & { key: string })[] }) {
  return (
    <div className="rounded-lg border bg-card p-4">
      <h3 className="text-sm font-medium mb-3">{title}</h3>
      {data.length === 0 ? (
        <p className="text-xs text-muted-foreground py-6 text-center">No data yet.</p>
      ) : (
        <div className="h-[180px]">
          <BarChart data={data} config={WIN_RATE_CONFIG}>
            <Grid />
            <XAxis dataKey="key" />
            <YAxis tickFormatter={(v) => `${Math.round(v * 100)}%`} />
            <ReferenceLine y={0.5} label="50%" />
            <Bar dataKey="win_rate" />
            <DitherTooltip valueFormatter={(v) => `${(v * 100).toFixed(0)}%`} />
          </BarChart>
        </div>
      )}
    </div>
  );
}

function Kpi({ label, value, good }: { label: string; value: string; good: boolean }) {
  return (
    <div className="group relative rounded-lg border bg-card p-3">
      <div className="flex items-start justify-between gap-1">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</span>
        <CommentButton anchorType="kpi" anchor={{ view: "performance", metric: label }} className="-mt-1 -mr-1" />
      </div>
      <p className={cn("text-sm font-mono font-medium mt-0.5", good ? "text-profit" : "text-loss")}>{value}</p>
    </div>
  );
}

/** Compact 4-metric strip for the Overview tab — the full breakdown lives
 * in the Performance tab; this is just enough to scan at a glance. */
export function OverviewKpiStrip() {
  const { data } = usePerformance();
  if (!data) return null;

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
      <Kpi label="Sharpe" value={data.sharpe_ratio.toFixed(2)} good={data.sharpe_ratio > 1} />
      <Kpi label="Win Rate" value={formatPct(data.win_rate)} good={data.win_rate > 0.5} />
      <Kpi label="Expectancy" value={formatSignedUsd(data.expectancy)} good={data.expectancy > 0} />
      <Kpi label="Total Realized" value={formatSignedUsd(data.total_realized_pnl)} good={data.total_realized_pnl >= 0} />
    </div>
  );
}
