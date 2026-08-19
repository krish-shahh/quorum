import { useState } from "react";
import { useDashboard } from "@/hooks/use-dashboard";
import Header from "@/components/Header";
import PortfolioHero from "@/components/PortfolioHero";
import StatusStrip from "@/components/StatusStrip";
import PositionsTable from "@/components/PositionsTable";
import WatchlistTable from "@/components/WatchlistTable";
import RecentTrades from "@/components/RecentTrades";
import EquityCurve from "@/components/EquityCurve";
import CouncilDetailModal from "@/components/CouncilDetailModal";
import PlanMetrics from "@/components/PlanMetrics";
import ScansPanel from "@/components/ScansPanel";
import ReportsPanel from "@/components/ReportsPanel";
import PerformanceView, { OverviewKpiStrip } from "@/components/PerformanceView";
import RunsView from "@/components/RunsView";
import TodayView from "@/components/TodayView";
import LogsView from "@/components/LogsView";
import CommentsDrawer from "@/components/CommentsDrawer";
import type { Annotation } from "@/lib/api";
import { anchorElementId, anchorView } from "@/lib/anchor";
import type { View } from "@/lib/views";

export default function App() {
  const [live, setLive] = useState(true);
  const [view, setView] = useState<View>("overview");
  const [selectedTicker, setSelectedTicker] = useState<string | null>(null);
  const [logsCycleId, setLogsCycleId] = useState<string | null>(null);
  const [commentsOpen, setCommentsOpen] = useState(false);
  const { data, dataUpdatedAt, isLoading, error } = useDashboard(live);

  function viewTrace(cycleId: string) {
    setLogsCycleId(cycleId);
    setView("logs");
  }

  // Comments drawer "jump to" — switch view, then poll for the target
  // element (the view it lives on may still be fetching its own data) and
  // scroll + flash it once it mounts.
  function jumpToThread(thread: Annotation) {
    const targetId = anchorElementId(thread.anchor_type, thread.anchor);
    setView(anchorView(thread.anchor_type, thread.anchor));

    let attempts = 0;
    const tryScroll = () => {
      const el = document.getElementById(targetId);
      if (el) {
        el.scrollIntoView({ behavior: "smooth", block: "center" });
        el.classList.add("annotation-highlight");
        window.setTimeout(() => el.classList.remove("annotation-highlight"), 1600);
        window.dispatchEvent(new CustomEvent("quorum:open-thread", { detail: { id: targetId } }));
      } else if (attempts++ < 20) {
        window.setTimeout(tryScroll, 100);
      }
    };
    window.setTimeout(tryScroll, 50);
  }

  if (isLoading && !data) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-muted-foreground text-sm">Connecting to trading system...</div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-destructive text-sm">
          Failed to connect. Ensure Flask is running on port 5050.
        </div>
      </div>
    );
  }

  if (!data) return null;

  return (
    <div className="min-h-screen bg-background">
      <Header
        market={data.market}
        killSwitch={data.account.kill_switch}
        live={live}
        onToggleLive={() => setLive(!live)}
        lastUpdated={dataUpdatedAt}
        view={view}
        onChangeView={setView}
        onOpenComments={() => setCommentsOpen(true)}
      />

      <main className="px-6 pb-8 pt-4 space-y-4 max-w-[1600px] mx-auto">
        {view === "overview" && (
          <>
            <PortfolioHero account={data.account} trades={data.trades} />
            <StatusStrip status={data.status} />
            <OverviewKpiStrip />
            <EquityCurve
              equity={data.trades.equity}
              positions={data.account.positions}
              books={data.account.books || []}
            />
          </>
        )}

        {view === "performance" && <PerformanceView />}

        {view === "runs" && <RunsView onViewTrace={viewTrace} />}

        {view === "today" && <TodayView />}

        {view === "logs" && <LogsView initialCycleId={logsCycleId} />}

        {view === "positions" && (
          <>
            <PositionsTable
              positions={data.account.positions}
              books={data.account.books || []}
              onSelectTicker={setSelectedTicker}
            />
            <WatchlistTable
              states={data.states}
              onSelectTicker={setSelectedTicker}
            />
            <RecentTrades trades={data.trades.recent} />
          </>
        )}

        {view === "scans" && (
          <>
            <ReportsPanel />
            <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
              <PlanMetrics status={data.status.plan} />
              <ScansPanel />
            </div>
          </>
        )}
      </main>

      <CouncilDetailModal
        ticker={selectedTicker}
        onClose={() => setSelectedTicker(null)}
      />

      <CommentsDrawer
        open={commentsOpen}
        onOpenChange={setCommentsOpen}
        onNavigate={jumpToThread}
      />
    </div>
  );
}
