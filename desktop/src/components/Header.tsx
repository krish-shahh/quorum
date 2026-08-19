import { Activity, Pause, Power, MessageCircle } from "lucide-react";
import { cn, timeAgo } from "@/lib/utils";
import { toggleKillSwitch, type MarketStatus } from "@/lib/api";
import { useQueryClient } from "@tanstack/react-query";
import { useOpenAnnotationCount } from "@/hooks/use-annotations";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { View } from "@/lib/views";
import { VIEWS } from "@/lib/views";

interface HeaderProps {
  market: MarketStatus;
  killSwitch: boolean;
  live: boolean;
  onToggleLive: () => void;
  lastUpdated: number;
  view: View;
  onChangeView: (v: View) => void;
}

export default function Header({
  market, killSwitch, live, onToggleLive, lastUpdated,
  view, onChangeView,
}: HeaderProps) {
  const queryClient = useQueryClient();
  const { data: openCommentCount } = useOpenAnnotationCount();

  const handleKillSwitch = async () => {
    await toggleKillSwitch();
    queryClient.invalidateQueries({ queryKey: ["dashboard"] });
  };

  return (
    <header className="sticky top-0 z-50 bg-background/95 backdrop-blur border-b px-6 drag-region">
      <div className="flex items-center h-12 max-w-[1600px] mx-auto">
        {/* Left: branding + market status (pl-[72px] clears macOS traffic lights) */}
        <div className="flex items-center gap-2.5 pl-[72px]">
          <span className="font-semibold text-sm tracking-tight">quorum</span>
          <span
            className={cn(
              "text-[11px] font-medium px-2 py-0.5 rounded-full no-drag",
              market.open ? "bg-profit/10 text-profit" : "bg-muted text-muted-foreground"
            )}
          >
            {market.text}
          </span>
        </div>

        {/* Center: top-level view nav */}
        <nav className="flex items-center gap-0.5 mx-auto no-drag">
          {VIEWS.map((v) => (
            <button
              key={v.id}
              onClick={() => onChangeView(v.id)}
              className={cn(
                "text-[12px] font-medium px-3 py-1.5 rounded-md transition-colors duration-fast",
                view === v.id
                  ? "bg-accent text-accent-foreground"
                  : "text-muted-foreground hover:text-foreground hover:bg-accent/50"
              )}
            >
              {v.label}
            </button>
          ))}
        </nav>

        {/* Right: staleness + controls */}
        <div className="flex items-center gap-2 no-drag">
          <span className="text-[11px] text-muted-foreground mr-1">
            {lastUpdated ? timeAgo(new Date(lastUpdated).toISOString()) : "---"}
          </span>

          {!!openCommentCount && (
            <Tooltip>
              <TooltipTrigger asChild>
                <span className="flex items-center gap-1 text-[11px] font-medium px-2 py-1 rounded bg-muted text-muted-foreground">
                  <MessageCircle className="w-3 h-3" />
                  {openCommentCount}
                </span>
              </TooltipTrigger>
              <TooltipContent>
                <p>{openCommentCount} open comment thread{openCommentCount === 1 ? "" : "s"}</p>
              </TooltipContent>
            </Tooltip>
          )}

          <Tooltip>
            <TooltipTrigger asChild>
              <button
                onClick={onToggleLive}
                className={cn(
                  "flex items-center gap-1 text-[11px] font-medium px-2.5 py-1 rounded",
                  live ? "bg-profit/10 text-profit" : "bg-muted text-muted-foreground"
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
                  killSwitch ? "bg-risk-red text-risk-red-foreground" : "bg-muted text-muted-foreground hover:bg-risk-red/10 hover:text-risk-red"
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
