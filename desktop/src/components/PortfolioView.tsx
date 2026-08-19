import PortfolioHero from "@/components/PortfolioHero";
import StatusStrip from "@/components/StatusStrip";
import EquityCurve from "@/components/EquityCurve";
import PositionsTable from "@/components/PositionsTable";
import WatchlistTable from "@/components/WatchlistTable";
import RecentTrades from "@/components/RecentTrades";
import { OverviewKpiStrip } from "@/components/PerformanceView";
import type { DashboardData } from "@/lib/api";

/** The PM's one-screen view — merges the old Overview + Positions & Trades
 * tabs: account state, risk/regime, current book, and the trade blotter,
 * all in one scroll instead of two separate tabs for what is really one
 * "where do things stand" question. */
export default function PortfolioView({ data }: { data: DashboardData }) {
  return (
    <div className="space-y-4">
      <PortfolioHero account={data.account} trades={data.trades} />
      <StatusStrip status={data.status} />
      <OverviewKpiStrip />
      <EquityCurve
        equity={data.trades.equity}
        books={data.account.books || []}
      />
      <PositionsTable
        positions={data.account.positions}
        books={data.account.books || []}
      />
      <WatchlistTable watchlist={data.watchlist} />
      <RecentTrades trades={data.trades.recent} />
    </div>
  );
}
