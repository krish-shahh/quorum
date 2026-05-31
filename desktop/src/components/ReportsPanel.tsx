import { useState, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, ChevronDown, FileText } from "lucide-react";
import { fetchReports, type FullTradeReport } from "@/lib/api";
import { cn, formatUsd, signalColor } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

const PAGE_SIZE = 5; // dates per page

export default function ReportsPanel() {
  const [expandedDates, setExpandedDates] = useState<Set<string>>(new Set());
  const [expandedReport, setExpandedReport] = useState<number | null>(null);
  const [page, setPage] = useState(0);

  const { data, isLoading } = useQuery({
    queryKey: ["reports"],
    queryFn: fetchReports,
    staleTime: 60_000,
  });

  const reports = data?.reports || [];

  // Group by date
  const grouped = useMemo(() => {
    const map = new Map<string, FullTradeReport[]>();
    for (const r of reports) {
      const date = r.trade_date;
      if (!map.has(date)) map.set(date, []);
      map.get(date)!.push(r);
    }
    return Array.from(map.entries());
  }, [reports]);

  const totalPages = Math.ceil(grouped.length / PAGE_SIZE);
  const visibleDates = grouped.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  const toggleDate = (date: string) => {
    setExpandedDates((prev) => {
      const next = new Set(prev);
      if (next.has(date)) next.delete(date);
      else next.add(date);
      return next;
    });
  };

  if (isLoading) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Trade Reports</h3>
        <p className="text-xs text-muted-foreground">Loading...</p>
      </div>
    );
  }

  if (reports.length === 0) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Trade Reports</h3>
        <p className="text-xs text-muted-foreground">No reports yet</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card overflow-hidden">
      <div className="px-4 py-3 border-b flex items-center justify-between">
        <h3 className="text-sm font-medium">Trade Reports ({reports.length})</h3>
        {totalPages > 1 && (
          <div className="flex items-center gap-2 text-xs">
            <button
              onClick={() => setPage((p) => Math.max(0, p - 1))}
              disabled={page === 0}
              className="px-2 py-0.5 rounded bg-muted text-muted-foreground disabled:opacity-30"
            >
              Prev
            </button>
            <span className="text-muted-foreground">
              {page + 1} / {totalPages}
            </span>
            <button
              onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
              disabled={page >= totalPages - 1}
              className="px-2 py-0.5 rounded bg-muted text-muted-foreground disabled:opacity-30"
            >
              Next
            </button>
          </div>
        )}
      </div>

      <div className="divide-y">
        {visibleDates.map(([date, dateReports]) => {
          const isOpen = expandedDates.has(date);
          const preCount = dateReports.filter((r) => r.report_type === "pre").length;
          const postCount = dateReports.filter((r) => r.report_type === "post").length;
          const tickers = [...new Set(dateReports.map((r) => r.ticker))];

          return (
            <div key={date}>
              {/* Date row — tree parent */}
              <button
                onClick={() => toggleDate(date)}
                className="w-full flex items-center gap-2 px-4 py-2.5 text-xs hover:bg-muted/30 transition-colors text-left"
              >
                {isOpen ? (
                  <ChevronDown className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                ) : (
                  <ChevronRight className="w-3.5 h-3.5 text-muted-foreground shrink-0" />
                )}
                <span className="font-medium">{date}</span>
                <span className="text-muted-foreground">
                  {dateReports.length} report{dateReports.length > 1 ? "s" : ""}
                </span>
                <div className="flex gap-1 ml-1">
                  {preCount > 0 && (
                    <span className="px-1.5 py-0.5 rounded bg-gray-100 text-gray-600 text-[10px]">
                      {preCount} pre
                    </span>
                  )}
                  {postCount > 0 && (
                    <span className="px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 text-[10px]">
                      {postCount} post
                    </span>
                  )}
                </div>
                <div className="flex gap-1.5 ml-auto">
                  {tickers.map((t) => (
                    <span key={t} className="font-mono text-muted-foreground">{t}</span>
                  ))}
                </div>
              </button>

              {/* Expanded: report rows — tree children */}
              {isOpen && (
                <div className="border-t bg-muted/5">
                  {dateReports.map((r) => (
                    <ReportRow
                      key={r.id}
                      report={r}
                      isExpanded={expandedReport === r.id}
                      onToggle={() => setExpandedReport(expandedReport === r.id ? null : r.id)}
                    />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ReportRow({ report: r, isExpanded, onToggle }: { report: FullTradeReport; isExpanded: boolean; onToggle: () => void }) {
  const hasDetail = r.technicals || r.fundamentals || r.sentiment || r.reasoning;

  return (
    <>
      <button
        onClick={hasDetail ? onToggle : undefined}
        className={cn(
          "w-full flex items-center gap-3 px-4 pl-10 py-2 text-xs text-left transition-colors",
          hasDetail && "hover:bg-muted/30 cursor-pointer",
          isExpanded && "bg-muted/20"
        )}
      >
        <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
        <span className="font-mono font-medium w-14">{r.ticker}</span>
        <Tooltip>
          <TooltipTrigger asChild>
            <span className={cn(
              "px-1.5 py-0.5 rounded text-[10px] font-medium",
              r.report_type === "post" ? "bg-blue-50 text-blue-700" : "bg-gray-100 text-gray-600"
            )}>
              {r.report_type === "post" ? "POST" : "PRE"}
            </span>
          </TooltipTrigger>
          <TooltipContent>{r.report_type === "post" ? "Post-trade analysis" : "Pre-trade analysis"}</TooltipContent>
        </Tooltip>
        <span className={cn("px-1.5 py-0.5 rounded-full text-[10px] font-medium", signalColor(r.signal))}>
          {r.signal}
        </span>
        {r.side && (
          <span className={cn(
            "px-1.5 py-0.5 rounded-full text-[10px] font-medium",
            r.side.toLowerCase() === "buy" ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
          )}>
            {r.side.toUpperCase()}
          </span>
        )}
        <span className="text-muted-foreground font-mono ml-auto">
          {r.fill_price ? formatUsd(r.fill_price) : ""}
          {r.quantity ? ` x${r.quantity}` : ""}
        </span>
        {r.pnl != null && r.pnl !== 0 && (
          <span className={cn("font-mono font-medium", r.pnl >= 0 ? "text-green-600" : "text-red-600")}>
            {r.pnl >= 0 ? "+" : ""}${r.pnl.toFixed(2)}
          </span>
        )}
        {r.confidence > 0 && (
          <span className="text-muted-foreground font-mono">{(r.confidence * 100).toFixed(0)}%</span>
        )}
      </button>

      {isExpanded && hasDetail && (
        <div className="px-4 pl-14 py-3 bg-muted/10 border-t border-b text-xs">
          <div className="grid grid-cols-2 gap-x-6 gap-y-2 max-w-4xl">
            {r.technicals && <Detail label="Technicals" content={r.technicals} />}
            {r.fundamentals && <Detail label="Fundamentals" content={r.fundamentals} />}
            {r.sentiment && <Detail label="Sentiment" content={r.sentiment} />}
            {r.news_catalyst && <Detail label="Catalyst" content={r.news_catalyst} />}
            {r.risk_factors && <Detail label="Risk Factors" content={r.risk_factors} />}
            {r.reasoning && <Detail label="Reasoning" content={r.reasoning} />}
          </div>
        </div>
      )}
    </>
  );
}

function Detail({ label, content }: { label: string; content: string }) {
  return (
    <div>
      <span className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider">{label}</span>
      <p className="text-muted-foreground mt-0.5 leading-relaxed">{content}</p>
    </div>
  );
}
