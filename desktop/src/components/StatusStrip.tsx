import { cn, riskColor, regimeColor, formatSignedUsd, formatSignedPct } from "@/lib/utils";
import type { StatusData } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  status: StatusData;
}

export default function StatusStrip({ status }: Props) {
  const { live_risk, plan, regime } = status;

  return (
    <div className="flex items-center gap-2.5 px-4 py-2 rounded-lg border bg-card text-xs">
      {/* Risk level */}
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={cn("font-medium px-2 py-0.5 rounded-full cursor-default", riskColor(live_risk.risk_level))}>
            {live_risk.risk_level?.toUpperCase() || "---"}
          </span>
        </TooltipTrigger>
        <TooltipContent>Intraday risk circuit breaker</TooltipContent>
      </Tooltip>

      {/* Regime + macro indicators */}
      <Tooltip>
        <TooltipTrigger asChild>
          <span className={cn("font-medium px-2 py-0.5 rounded-full cursor-default", regimeColor(regime.regime))}>
            {regime.regime}
          </span>
        </TooltipTrigger>
        <TooltipContent>Market regime ({regime.confidence} confidence)</TooltipContent>
      </Tooltip>

      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-muted-foreground font-mono cursor-default">VIX {regime.vix}</span>
        </TooltipTrigger>
        <TooltipContent>CBOE Volatility Index</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-muted-foreground font-mono cursor-default">DXY {regime.dxy}</span>
        </TooltipTrigger>
        <TooltipContent>US Dollar Index</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="text-muted-foreground font-mono cursor-default">10Y {regime.yield_10y}</span>
        </TooltipTrigger>
        <TooltipContent>10-Year Treasury Yield</TooltipContent>
      </Tooltip>

      <div className="h-4 w-px bg-border" />

      {/* Day P&L */}
      <span className="text-muted-foreground">Day P&L:</span>
      <span className={cn("font-mono font-medium", live_risk.daily_pnl >= 0 ? "text-green-600" : "text-red-600")}>
        {formatSignedUsd(live_risk.daily_pnl)} ({formatSignedPct(live_risk.daily_pnl_pct * 100)})
      </span>

      {/* Intraday drawdown */}
      {live_risk.intraday_drawdown > 0 && (
        <>
          <div className="h-4 w-px bg-border" />
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="font-mono text-orange-600 cursor-default">
                DD: {(live_risk.intraday_drawdown * 100).toFixed(2)}%
              </span>
            </TooltipTrigger>
            <TooltipContent>Intraday drawdown from session high</TooltipContent>
          </Tooltip>
        </>
      )}

      <div className="h-4 w-px bg-border" />

      {/* Plan status */}
      {plan.active ? (
        <>
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="font-medium text-blue-700 bg-blue-50 px-2 py-0.5 rounded-full cursor-default">
                Plan Active
              </span>
            </TooltipTrigger>
            <TooltipContent>{plan.plan_type} plan — created {plan.created_at?.slice(0, 16)}</TooltipContent>
          </Tooltip>
          <span className="text-muted-foreground font-mono">
            B:{plan.buy_count} S:{plan.sell_count} H:{plan.hold_count}
          </span>
          {plan.adherence_rate != null && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="font-mono cursor-default">
                  {(plan.adherence_rate * 100).toFixed(0)}% adh.
                </span>
              </TooltipTrigger>
              <TooltipContent>Plan adherence — % of steps executed as planned</TooltipContent>
            </Tooltip>
          )}
        </>
      ) : (
        <span className="text-muted-foreground">No active plan</span>
      )}

      {/* Stop breaches */}
      {live_risk.stops_breached.length > 0 && (
        <>
          <div className="h-4 w-px bg-border" />
          <span className="text-red-600 font-medium">
            {live_risk.stops_breached.length} stop(s) breached
          </span>
        </>
      )}

      {/* Consecutive losses warning */}
      {live_risk.consecutive_losses >= 3 && (
        <>
          <div className="h-4 w-px bg-border" />
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-orange-600 font-medium cursor-default">
                {live_risk.consecutive_losses} consecutive losses
              </span>
            </TooltipTrigger>
            <TooltipContent>Consider reducing position size</TooltipContent>
          </Tooltip>
        </>
      )}
    </div>
  );
}
