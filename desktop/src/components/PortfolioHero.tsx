import { cn } from "@/lib/utils";
import type { AccountData, TradesData, BookData } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  account: AccountData;
  trades: TradesData;
}

export default function PortfolioHero({ account, trades }: Props) {
  const pnlPositive = account.pnl >= 0;
  const pnlColor = pnlPositive ? "text-green-600" : "text-red-600";

  // Format with enough precision — don't round small P&L to 0
  const fmtPnl = (v: number) => {
    const sign = v >= 0 ? "+" : "";
    return `${sign}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
  };
  const fmtPnlPct = (v: number) => {
    const pct = v * 100;
    const sign = pct >= 0 ? "+" : "";
    // Show 2 decimals for small percentages
    const decimals = Math.abs(pct) < 1 ? 2 : 1;
    return `${sign}${pct.toFixed(decimals)}%`;
  };

  return (
    <div className="rounded-lg border bg-card p-5">
      {/* Primary: Value + P&L — largest visual weight */}
      <div className="flex items-end justify-between">
        <div>
          <p className="text-3xl font-bold font-mono tracking-tight">
            ${account.portfolio_value.toLocaleString("en-US", { minimumFractionDigits: 2 })}
          </p>
          <p className={cn("text-lg font-mono font-semibold mt-0.5", pnlColor)}>
            {fmtPnl(account.pnl)}
            <span className="text-sm ml-2 font-medium">
              ({fmtPnlPct(account.pnl_pct)})
            </span>
          </p>
        </div>

        {/* Book allocation — secondary */}
        <div className="flex flex-wrap gap-1 max-w-sm justify-end">
          {account.books?.map((b) => (
            <span
              key={b.name}
              className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground"
            >
              {b.name.split(" ")[0]} {b.allocation_pct}%
            </span>
          ))}
          <span className="text-[11px] font-mono px-2 py-0.5 rounded-full bg-secondary text-secondary-foreground">
            Cash {((account.cash / account.portfolio_value) * 100).toFixed(1)}%
          </span>
        </div>
      </div>

      {/* Tertiary: Metrics row — smallest, supporting info */}
      <div className="grid grid-cols-5 gap-4 mt-4 pt-3 border-t">
        <MetricWithTooltip
          label="Cash Reserve"
          value={`${((account.cash / account.portfolio_value) * 100).toFixed(1)}%`}
          tooltip="Cash as % of portfolio"
        />
        <MetricWithTooltip
          label="Drawdown"
          value={`${(account.drawdown * 100).toFixed(2)}%`}
          tooltip={`Peak-to-trough decline — limit: ${(account.dd_limit * 100).toFixed(0)}%`}
          warn={account.drawdown > account.dd_limit * 0.7}
        />
        <MetricWithTooltip
          label="Positions"
          value={String(account.positions.length)}
          tooltip="Open positions"
        />
        <MetricWithTooltip
          label="Trades"
          value={`${trades.total}`}
          tooltip={`${trades.wins}W / ${trades.losses}L (${(trades.win_rate * 100).toFixed(0)}% WR)`}
        />
        <MetricWithTooltip
          label="Mode"
          value={account.execution_mode.toUpperCase()}
          tooltip="Execution mode — paper or live"
        />
      </div>
    </div>
  );
}

function MetricWithTooltip({ label, value, tooltip, warn }: { label: string; value: string; tooltip: string; warn?: boolean }) {
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <div className="cursor-default">
          <p className="text-[10px] text-muted-foreground uppercase tracking-wider">{label}</p>
          <p className={cn("text-xs font-mono font-medium mt-0.5", warn && "text-orange-600")}>{value}</p>
        </div>
      </TooltipTrigger>
      <TooltipContent>
        <p>{tooltip}</p>
      </TooltipContent>
    </Tooltip>
  );
}
