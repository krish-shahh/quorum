import { cn, scoreColor, signalColor, timeAgo } from "@/lib/utils";
import type { TickerState } from "@/lib/api";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface Props {
  states: TickerState[];
  onSelectTicker: (ticker: string) => void;
}

const SECTOR_COLORS: Record<string, string> = {
  tech: "bg-purple-50 text-purple-700",
  financials: "bg-cyan-50 text-cyan-700",
  healthcare: "bg-emerald-50 text-emerald-700",
  consumer: "bg-orange-50 text-orange-700",
  cyclical: "bg-stone-100 text-stone-700",
};

export default function WatchlistTable({ states, onSelectTicker }: Props) {
  if (states.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Council Scores</h3>
        <p className="text-xs text-muted-foreground">No watchlist data</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b">
        <h3 className="text-sm font-medium">Council Scores ({states.length})</h3>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b bg-muted/50">
              <th className="text-left px-4 py-2 font-medium text-muted-foreground">Ticker</th>
              <th className="text-left px-3 py-2 font-medium text-muted-foreground">Sector</th>
              <th className="text-right px-3 py-2 font-medium text-muted-foreground">Price</th>
              <ThWithTooltip label="T" tooltip="Technical analyst score (1-5)" />
              <ThWithTooltip label="F" tooltip="Fundamental/domain analyst score (1-5)" />
              <ThWithTooltip label="S" tooltip="Sentiment analyst score (1-5)" />
              <ThWithTooltip label="N" tooltip="News/macro analyst score (1-5)" />
              <ThWithTooltip label="Score" tooltip="Weighted average of all analysts" />
              <th className="text-center px-3 py-2 font-medium text-muted-foreground">Signal</th>
              <ThWithTooltip label="Conf" tooltip="Council confidence in the signal" align="right" />
              <th className="text-right px-4 py-2 font-medium text-muted-foreground">Analyzed</th>
            </tr>
          </thead>
          <tbody>
            {states.map((s) => (
              <tr
                key={s.ticker}
                onClick={() => onSelectTicker(s.ticker)}
                className="border-b last:border-0 hover:bg-muted/30 cursor-pointer transition-colors"
              >
                <td className="px-4 py-2.5">
                  <div className="flex items-center gap-2">
                    <span className="font-medium font-mono">{s.ticker}</span>
                    {s.debate_triggered && (
                      <span className="text-[10px] px-1 py-0.5 rounded bg-yellow-50 text-yellow-700">Debate</span>
                    )}
                  </div>
                </td>
                <td className="px-3 py-2.5">
                  <span className={cn("text-[10px] px-1.5 py-0.5 rounded", SECTOR_COLORS[s.sector] || "bg-gray-50 text-gray-600")}>
                    {s.sector || s.asset_class}
                  </span>
                </td>
                <td className="text-right px-3 py-2.5 font-mono">${s.price.toFixed(2)}</td>
                <td className="text-center px-2 py-2.5">
                  <ScorePill value={s.technical} />
                </td>
                <td className="text-center px-2 py-2.5">
                  <ScorePill value={s.fundamental} />
                </td>
                <td className="text-center px-2 py-2.5">
                  <ScorePill value={s.sentiment} />
                </td>
                <td className="text-center px-2 py-2.5">
                  <ScorePill value={s.news} />
                </td>
                <td className="text-center px-3 py-2.5">
                  <span className={cn("font-mono font-medium px-2 py-0.5 rounded", scoreColor(s.weighted))}>
                    {s.weighted.toFixed(2)}
                  </span>
                </td>
                <td className="text-center px-3 py-2.5">
                  <span className={cn("px-2 py-0.5 rounded-full text-[10px] font-medium", signalColor(s.signal))}>
                    {s.signal}
                  </span>
                </td>
                <td className="text-right px-3 py-2.5 font-mono text-muted-foreground">
                  {(s.confidence * 100).toFixed(0)}%
                </td>
                <td className="text-right px-4 py-2.5 text-muted-foreground">
                  {timeAgo(s.analyzed_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function ScorePill({ value }: { value: number }) {
  return (
    <span className={cn("text-[10px] font-mono font-medium px-1.5 py-0.5 rounded", scoreColor(value))}>
      {value.toFixed(1)}
    </span>
  );
}

function ThWithTooltip({ label, tooltip, align = "center" }: { label: string; tooltip: string; align?: "center" | "right" }) {
  return (
    <th className={`text-${align} px-2 py-2 font-medium text-muted-foreground`}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="cursor-default">{label}</span>
        </TooltipTrigger>
        <TooltipContent>
          <p>{tooltip}</p>
        </TooltipContent>
      </Tooltip>
    </th>
  );
}
