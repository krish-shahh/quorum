import { cn } from "@/lib/utils";
import type { WatchlistEntry } from "@/lib/api";

interface Props {
  watchlist: WatchlistEntry[];
}

const SECTOR_COLORS: Record<string, string> = {
  tech: "bg-purple-50 text-purple-700",
  financials: "bg-cyan-50 text-cyan-700",
  healthcare: "bg-emerald-50 text-emerald-700",
  consumer: "bg-risk-orange/10 text-risk-orange",
  cyclical: "bg-stone-100 text-stone-700",
};

export default function WatchlistTable({ watchlist }: Props) {
  if (watchlist.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Watchlist</h3>
        <p className="text-xs text-muted-foreground">No tickers on the watchlist</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b">
        <h3 className="text-sm font-medium">Watchlist ({watchlist.length})</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left px-4 py-2 font-medium text-muted-foreground">Ticker</th>
              <th className="text-left px-3 py-2 font-medium text-muted-foreground">Sector</th>
              <th className="text-left px-3 py-2 font-medium text-muted-foreground">Asset Class</th>
            </tr>
          </thead>
          <tbody>
            {watchlist.map((w) => (
              <tr key={w.ticker} className="border-b last:border-0 hover:bg-muted/30 transition-colors">
                <td className="px-4 py-2.5">
                  <span className="font-medium font-mono">{w.ticker}</span>
                </td>
                <td className="px-3 py-2.5">
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded", SECTOR_COLORS[w.sector] || "bg-muted text-muted-foreground")}>
                    {w.sector || w.asset_class}
                  </span>
                </td>
                <td className="px-3 py-2.5 text-muted-foreground">{w.asset_class}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
