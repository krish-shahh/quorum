import { Activity, Pause, Power } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { toggleKillSwitch, type MarketStatus } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

interface HeaderProps {
  market: MarketStatus;
  killSwitch: boolean;
  live: boolean;
  onToggleLive: () => void;
  lastUpdated: number;
}

export default function Header({ market, killSwitch, live, onToggleLive, lastUpdated }: HeaderProps) {
  const queryClient = useQueryClient();

  const handleKillSwitch = async () => {
    await toggleKillSwitch();
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  return (
    <header className="sticky top-0 z-50 bg-background/95 backdrop-blur border-b px-6 drag-region">
      <div className="flex items-center h-12 max-w-[1600px] mx-auto">
        {/* Left: branding + market status (pl-[72px] clears macOS traffic lights) */}
        <div className="flex items-center gap-2.5 pl-[72px]">
          <span className="font-semibold text-sm tracking-tight">TradingAgents</span>
          <span
            className={cn(
              "text-[11px] font-medium px-2 py-0.5 rounded-full no-drag",
              market.open ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
            )}
          >
            {market.text}
          </span>
        </div>

        {/* Spacer */}
        <div className="flex-1" />

        {/* Right: staleness + controls */}
        <div className="flex items-center gap-2 no-drag">
          <span className="text-[11px] text-muted-foreground mr-1">
            {lastUpdated ? timeAgo(new Date(lastUpdated).toISOString()) : "---"}
          </span>

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={onToggleLive}
                className={cn(
                  "flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded",
                  live ? "bg-green-100 text-green-700" : "bg-gray-100 text-gray-500"
                )}
              >
                {live ? <Activity className="w-3 h-3" /> : <Pause className="w-3 h-3" />}
                {live ? "Live" : "Paused"}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{live ? "Auto-refreshing every 30s" : "Polling paused"}</p>
            </TooltipContent>
          </Tooltip>

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={handleKillSwitch}
                className={cn(
                  "flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded",
                  killSwitch ? "bg-red-600 text-white" : "bg-gray-100 text-gray-600 hover:bg-red-50 hover:text-red-600"
                )}
              >
                <Power className="w-3 h-3" />
                {killSwitch ? "HALTED" : "Kill"}
              </button>
            </TooltipTrigger>
            <TooltipContent>
              <p>{killSwitch ? "Trading halted — click to resume" : "Emergency halt all trading"}</p>
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
    </header>
  );
}
