import { useState } from "react";
import { cn, formatUsd } from "@/lib/utils";
import type { RecentTrade } from "@/lib/api";

interface Props {
  trades: RecentTrade[];
}

export default function RecentTrades({ trades }: Props) {
  const [expanded, setExpanded] = useState(false);
  const visible = expanded ? trades.slice(0, 20) : trades.slice(0, 10);

  if (trades.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Recent Trades</h3>
        <p className="text-xs text-muted-foreground">No trades yet</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b flex items-center justify-between">
        <h3 className="text-sm font-medium">Recent Trades</h3>
        {trades.length > 10 && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            {expanded ? "Show less" : `Show all (${trades.length})`}
          </button>
        )}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left px-4 py-2 font-medium text-muted-foreground">Time</th>
              <th className="text-left px-3 py-2 font-medium text-muted-foreground">Ticker</th>
              <th className="text-center px-3 py-2 font-medium text-muted-foreground">Side</th>
              <th className="text-right px-3 py-2 font-medium text-muted-foreground">Qty</th>
              <th className="text-right px-3 py-2 font-medium text-muted-foreground">Fill</th>
              <th className="text-right px-3 py-2 font-medium text-muted-foreground">Notional</th>
              <th className="text-center px-3 py-2 font-medium text-muted-foreground">Signal</th>
              <th className="text-center px-4 py-2 font-medium text-muted-foreground">Status</th>
            </tr>
          </thead>
          <tbody>
            {visible.map((t, i) => (
              <tr key={`${t.ticker}-${t.time}-${i}`} className="border-b last:border-0 hover:bg-muted/30">
                <td className="px-4 py-2.5 text-muted-foreground font-mono">{t.time}</td>
                <td className="px-3 py-2.5 font-mono font-medium">{t.ticker}</td>
                <td className="text-center px-3 py-2.5">
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded-full text-[10px] font-medium",
                      t.side === "BUY" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    )}
                  >
                    {t.side}
                  </span>
                </td>
                <td className="text-right px-3 py-2.5 font-mono">{t.qty}</td>
                <td className="text-right px-3 py-2.5 font-mono">{t.fill != null ? formatUsd(t.fill) : "---"}</td>
                <td className="text-right px-3 py-2.5 font-mono">{formatUsd(t.notional)}</td>
                <td className="text-center px-3 py-2.5">
                  <span className="text-muted-foreground">{t.signal}</span>
                </td>
                <td className="text-center px-4 py-2.5">
                  <span
                    className={cn(
                      "px-2 py-0.5 rounded-full text-[10px] font-medium",
                      t.action === "executed" ? "bg-green-50 text-green-600" : "bg-gray-100 text-gray-500"
                    )}
                  >
                    {t.action}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
