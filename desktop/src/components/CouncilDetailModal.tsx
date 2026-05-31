import { useEffect } from "react";
import { X } from "lucide-react";
import { useCouncilDetail } from "@/hooks/use-council-detail";
import { cn, scoreColor, signalColor } from "@/lib/utils";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";

interface Props {
  ticker: string | null;
  onClose: () => void;
}

export default function CouncilDetailModal({ ticker, onClose }: Props) {
  const { data, isLoading } = useCouncilDetail(ticker);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [onClose]);

  if (!ticker) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-12 px-4">
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" onClick={onClose} />

      {/* Modal */}
      <div className="relative bg-card rounded-lg border shadow-xl w-full max-w-3xl max-h-[85vh] flex flex-col">
        {/* Header */}
        <div className="border-b px-5 py-3 flex items-center justify-between shrink-0">
          <div className="flex items-center gap-3">
            <span className="text-lg font-bold font-mono">{ticker}</span>
            {data?.detail?.detail && (
              <>
                <span className={cn("px-2 py-0.5 rounded-full text-xs font-medium", signalColor((data.detail.detail as any).signal || ""))}>
                  {(data.detail.detail as any).signal || "---"}
                </span>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <span className={cn("px-2 py-0.5 rounded text-xs font-mono cursor-default", scoreColor((data.detail.detail as any).weighted || 0))}>
                      {((data.detail.detail as any).weighted || 0).toFixed(2)}
                    </span>
                  </TooltipTrigger>
                  <TooltipContent>Weighted council score (1-5)</TooltipContent>
                </Tooltip>
                {(data.detail.detail as any).debate_triggered && (
                  <span className="text-[10px] px-1.5 py-0.5 rounded bg-yellow-50 text-yellow-700 font-medium">Debate</span>
                )}
              </>
            )}
          </div>
          <button onClick={onClose} className="p-1.5 rounded hover:bg-muted transition-colors">
            <X className="w-4 h-4" />
          </button>
        </div>

        {/* Scrollable body */}
        <div className="overflow-y-auto flex-1">
          <div className="p-5 space-y-5">
            {isLoading && <p className="text-xs text-muted-foreground py-8 text-center">Loading council data...</p>}

            {data && (
              <>
                {/* Score bars */}
                {data.detail?.detail && <ScoreBars detail={data.detail.detail as any} />}

                {/* Quant anchors */}
                {data.detail?.quant && Object.keys(data.detail.quant).length > 0 && (
                  <div className="rounded-md bg-muted/50 p-3">
                    <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Quant Anchors</h4>
                    <div className="flex gap-6 text-xs">
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-default">
                            <span className="text-muted-foreground">Fundamental:</span>{" "}
                            <span className="font-mono font-medium">{(data.detail.quant as any).fundamental}</span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Deterministic quant fundamental score (Altman-Z, FCF yield, etc.)</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-default">
                            <span className="text-muted-foreground">Technical:</span>{" "}
                            <span className="font-mono font-medium">{(data.detail.quant as any).technical}</span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>Deterministic quant technical score (regime-conditional)</TooltipContent>
                      </Tooltip>
                      <Tooltip>
                        <TooltipTrigger asChild>
                          <div className="cursor-default">
                            <span className="text-muted-foreground">Data Quality:</span>{" "}
                            <span className="font-mono font-medium">{((data.detail.quant as any).data_quality * 100).toFixed(0)}%</span>
                          </div>
                        </TooltipTrigger>
                        <TooltipContent>% of data fields available for scoring</TooltipContent>
                      </Tooltip>
                    </div>
                  </div>
                )}

                {/* Plan steps */}
                {data.plan && (
                  <div>
                    <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Active Plan Steps</h4>
                    <div className="space-y-1.5">
                      {data.plan.steps.map((step, i) => (
                        <div key={i} className="flex items-center gap-3 text-xs py-2 px-3 rounded-md border bg-muted/30">
                          <span className={cn("font-medium px-2 py-0.5 rounded-full text-[10px]", signalColor(step.action))}>
                            {step.action}
                          </span>
                          {step.entry && <span className="font-mono text-muted-foreground">Entry: ${step.entry}</span>}
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Score history */}
                {data.detail?.history && data.detail.history.length > 1 && (
                  <div>
                    <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Score History</h4>
                    <div className="overflow-x-auto">
                      <table className="w-full text-xs">
                        <thead>
                          <tr className="border-b">
                            <th className="text-left py-1.5 pr-3 font-medium text-muted-foreground">Time</th>
                            <th className="text-center py-1.5 px-2 font-medium text-muted-foreground">T</th>
                            <th className="text-center py-1.5 px-2 font-medium text-muted-foreground">F</th>
                            <th className="text-center py-1.5 px-2 font-medium text-muted-foreground">S</th>
                            <th className="text-center py-1.5 px-2 font-medium text-muted-foreground">N</th>
                            <th className="text-center py-1.5 px-2 font-medium text-muted-foreground">Score</th>
                            <th className="text-center py-1.5 px-2 font-medium text-muted-foreground">Signal</th>
                          </tr>
                        </thead>
                        <tbody>
                          {data.detail.history.map((h: any, i: number) => (
                            <tr key={i} className="border-b last:border-0">
                              <td className="py-2 pr-3 text-muted-foreground">{h.analyzed_at}</td>
                              <td className="text-center py-2 px-2"><span className={cn("px-1.5 py-0.5 rounded text-[10px] font-mono", scoreColor(h.technical))}>{h.technical}</span></td>
                              <td className="text-center py-2 px-2"><span className={cn("px-1.5 py-0.5 rounded text-[10px] font-mono", scoreColor(h.fundamental))}>{h.fundamental}</span></td>
                              <td className="text-center py-2 px-2"><span className={cn("px-1.5 py-0.5 rounded text-[10px] font-mono", scoreColor(h.sentiment))}>{h.sentiment}</span></td>
                              <td className="text-center py-2 px-2"><span className={cn("px-1.5 py-0.5 rounded text-[10px] font-mono", scoreColor(h.news))}>{h.news}</span></td>
                              <td className="text-center py-2 px-2 font-mono">{h.weighted?.toFixed(2)}</td>
                              <td className="text-center py-2 px-2"><span className={cn("px-1.5 py-0.5 rounded-full text-[10px]", signalColor(h.signal))}>{h.signal}</span></td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                )}

                {/* Analyst reports — accordion */}
                {data.analyst_reports && data.analyst_reports.length > 0 && (
                  <div>
                    <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Analyst Reports</h4>
                    <Accordion type="multiple" className="space-y-1">
                      {data.analyst_reports.map((report, i) => (
                        <AccordionItem key={i} value={`report-${i}`} className="border rounded-md px-3">
                          <AccordionTrigger className="text-xs py-2 hover:no-underline">
                            <div className="flex items-center gap-2">
                              <span className="text-muted-foreground">{report.analysis_date}</span>
                              <span className={cn("px-1.5 py-0.5 rounded-full text-[10px]", signalColor(report.council_signal))}>
                                {report.council_signal}
                              </span>
                              <span className="font-mono text-muted-foreground">{report.weighted_score?.toFixed(2)}</span>
                            </div>
                          </AccordionTrigger>
                          <AccordionContent className="text-xs space-y-3 pb-3">
                            {report.technical_report && <ReportSection title="Technical" content={report.technical_report} />}
                            {report.fundamental_report && <ReportSection title="Fundamental" content={report.fundamental_report} />}
                            {report.sentiment_report && <ReportSection title="Sentiment" content={report.sentiment_report} />}
                            {report.news_report && <ReportSection title="News" content={report.news_report} />}
                            {report.bull_case && <ReportSection title="Bull Case" content={report.bull_case} color="text-green-700" />}
                            {report.bear_case && <ReportSection title="Bear Case" content={report.bear_case} color="text-red-700" />}
                            {report.pm_decision && <ReportSection title="PM Decision" content={report.pm_decision} color="text-blue-700" />}
                          </AccordionContent>
                        </AccordionItem>
                      ))}
                    </Accordion>
                  </div>
                )}

                {/* Trade reports */}
                {data.trade_reports && data.trade_reports.length > 0 && (
                  <div>
                    <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Trade Reports</h4>
                    <Accordion type="multiple" className="space-y-1">
                      {data.trade_reports.map((report, i) => (
                        <AccordionItem key={i} value={`trade-report-${i}`} className="border rounded-md px-3">
                          <AccordionTrigger className="text-xs py-2 hover:no-underline">
                            <div className="flex items-center gap-2">
                              <span className="text-muted-foreground">{report.trade_date}</span>
                              <span className={cn("px-1.5 py-0.5 rounded-full text-[10px]", signalColor(report.signal))}>
                                {report.signal}
                              </span>
                              <span className="font-mono text-muted-foreground">{(report.confidence * 100).toFixed(0)}% conf</span>
                            </div>
                          </AccordionTrigger>
                          <AccordionContent className="text-xs space-y-2 pb-3">
                            {report.technicals && <ReportSection title="Technicals" content={report.technicals} />}
                            {report.fundamentals && <ReportSection title="Fundamentals" content={report.fundamentals} />}
                            {report.sentiment && <ReportSection title="Sentiment" content={report.sentiment} />}
                            {report.news_catalyst && <ReportSection title="News Catalyst" content={report.news_catalyst} />}
                            {report.risk_factors && <ReportSection title="Risk Factors" content={report.risk_factors} color="text-orange-700" />}
                            {report.reasoning && <ReportSection title="Reasoning" content={report.reasoning} />}
                          </AccordionContent>
                        </AccordionItem>
                      ))}
                    </Accordion>
                  </div>
                )}

                {/* Reflections */}
                {data.reflections && Object.keys(data.reflections).length > 0 && (
                  <div>
                    <h4 className="text-[10px] font-medium text-muted-foreground uppercase tracking-wider mb-2">Trade Reflections</h4>
                    <div className="space-y-2">
                      {Object.entries(data.reflections).map(([section, content]) => (
                        <div key={section} className="border rounded-md p-3">
                          <p className="text-xs font-medium mb-1">{section}</p>
                          <p className="text-xs text-muted-foreground whitespace-pre-wrap leading-relaxed">{content}</p>
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function ScoreBars({ detail }: { detail: any }) {
  const scores = [
    { label: "Technical", value: detail.technical, tip: "Price action, momentum, trend structure" },
    { label: "Fundamental", value: detail.fundamental, tip: "Domain-specific value assessment" },
    { label: "Sentiment", value: detail.sentiment, tip: "Social media, insider activity" },
    { label: "News", value: detail.news, tip: "News flow, macro catalysts" },
  ];

  return (
    <div className="space-y-2.5">
      {scores.map((s) => (
        <div key={s.label} className="flex items-center gap-3">
          <Tooltip>
            <TooltipTrigger asChild>
              <span className="text-xs text-muted-foreground w-24 cursor-default">{s.label}</span>
            </TooltipTrigger>
            <TooltipContent>{s.tip}</TooltipContent>
          </Tooltip>
          <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
            <div
              className={cn("h-full rounded-full transition-all", barColor(s.value))}
              style={{ width: `${(s.value / 5) * 100}%` }}
            />
          </div>
          <span className={cn("text-xs font-mono w-8 text-right font-medium", scoreColor(s.value))}>{s.value?.toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
}

function barColor(score: number): string {
  if (score >= 4) return "bg-green-500";
  if (score >= 3) return "bg-yellow-400";
  if (score >= 2) return "bg-orange-400";
  return "bg-red-500";
}

function ReportSection({ title, content, color }: { title: string; content: string; color?: string }) {
  return (
    <div>
      <p className={cn("text-[10px] font-medium uppercase tracking-wider mb-0.5", color || "text-muted-foreground")}>{title}</p>
      <p className="text-xs whitespace-pre-wrap leading-relaxed">{content}</p>
    </div>
  );
}
