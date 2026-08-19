import { useEffect, useState } from "react";
import { useCycles, useCycleDetail } from "@/hooks/use-cycles";
import { cn } from "@/lib/utils";
import type { CycleSummary, TraceEvent } from "@/lib/api";
import { Badge } from "@/components/ui/badge";

const STATUS_STYLE: Record<CycleSummary["status"], string> = {
  running: "text-gate-skip bg-muted",
  ok: "text-gate-pass bg-gate-pass/10",
  error: "text-gate-fail bg-gate-fail/10",
  unknown: "text-muted-foreground bg-muted",
};

export default function LogsView({ initialCycleId }: { initialCycleId?: string | null }) {
  const [cycleId, setCycleId] = useState<string | null>(initialCycleId ?? null);
  const { data: cyclesData, isLoading: cyclesLoading } = useCycles();

  useEffect(() => {
    if (initialCycleId) setCycleId(initialCycleId);
  }, [initialCycleId]);

  useEffect(() => {
    if (!cycleId && cyclesData?.cycles.length) setCycleId(cyclesData.cycles[0].cycle_id);
  }, [cycleId, cyclesData]);

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[280px_1fr] gap-4">
      <div className="rounded-lg border bg-card overflow-hidden">
        <div className="px-3 py-2 border-b bg-muted/50">
          <h3 className="text-xs font-medium">Cycles</h3>
        </div>
        <div className="divide-y max-h-[70vh] overflow-y-auto">
          {cyclesLoading ? (
            <p className="text-xs text-muted-foreground text-center py-8">Loading cycles...</p>
          ) : !cyclesData || cyclesData.cycles.length === 0 ? (
            <p className="text-xs text-muted-foreground text-center py-8 px-3">
              No traced cycles yet — runs launched via `quorum cycle` will appear here.
            </p>
          ) : (
            cyclesData.cycles.map((c) => (
              <button
                key={c.cycle_id}
                onClick={() => setCycleId(c.cycle_id)}
                className={cn(
                  "w-full text-left px-3 py-2 hover:bg-muted/30 transition-colors",
                  cycleId === c.cycle_id && "bg-muted/50"
                )}
              >
                <div className="flex items-center justify-between mb-1">
                  <span className="font-mono text-[11px] truncate">{c.cycle_id.slice(0, 12)}</span>
                  <span className={cn("px-1.5 py-0.5 rounded text-[9px] font-medium uppercase", STATUS_STYLE[c.status])}>
                    {c.status}
                  </span>
                </div>
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>{c.started_at}</span>
                  <span>{c.n_trace_events} events</span>
                </div>
              </button>
            ))
          )}
        </div>
      </div>

      <TraceTimeline cycleId={cycleId} />
    </div>
  );
}

function TraceTimeline({ cycleId }: { cycleId: string | null }) {
  const { data, isLoading } = useCycleDetail(cycleId);

  if (!cycleId) {
    return (
      <div className="rounded-lg border bg-card p-8 text-center text-sm text-muted-foreground">
        Select a cycle to view its trace.
      </div>
    );
  }
  if (isLoading || !data) {
    return <p className="text-sm text-muted-foreground py-12 text-center">Loading trace...</p>;
  }

  return (
    <div className="space-y-3">
      <div className="rounded-lg border bg-card p-3 flex items-center gap-2 flex-wrap">
        <span className="text-[10px] text-muted-foreground uppercase tracking-wider mr-1">Runs touched</span>
        {data.runs.length === 0 ? (
          <span className="text-xs text-muted-foreground">none</span>
        ) : (
          data.runs.map((r) => (
            <Badge key={r.run_id} variant="secondary" className="font-mono font-normal text-[10px]">
              {r.strategy_id} · {r.mode} · {r.status}
            </Badge>
          ))
        )}
      </div>

      <div className="rounded-lg border bg-card p-3 max-h-[65vh] overflow-y-auto space-y-1.5">
        {data.trace_events.length === 0 ? (
          <p className="text-xs text-muted-foreground text-center py-8">No events in this cycle.</p>
        ) : (
          data.trace_events.map((e) => <TraceEventRow key={e.event_id} event={e} />)
        )}
      </div>
    </div>
  );
}

function TraceEventRow({ event }: { event: TraceEvent }) {
  const nested = event.parent_tool_use_id != null;

  return (
    <div className={cn("rounded px-2 py-1.5 text-xs", nested ? "ml-5 border-l-2 border-accent bg-muted/30" : "bg-muted/40")}>
      <div className="flex items-center gap-2 mb-0.5">
        <span className="text-[9px] font-mono text-muted-foreground">{event.ts}</span>
        <span className={cn("text-[9px] uppercase tracking-wider font-medium", eventTypeColor(event.event_type))}>
          {event.event_type}
        </span>
        {nested && <span className="text-[9px] text-muted-foreground">(subagent)</span>}
      </div>

      {event.event_type === "tool_use" ? (
        <div>
          <span className="font-mono font-medium">{event.tool_name}</span>
          {event.tool_input && Object.keys(event.tool_input).length > 0 && (
            <pre className="mt-1 text-[10px] text-muted-foreground whitespace-pre-wrap break-all">
              {JSON.stringify(event.tool_input)}
            </pre>
          )}
        </div>
      ) : event.event_type === "tool_result" ? (
        <p className="text-muted-foreground whitespace-pre-wrap break-words">{event.tool_output_summary}</p>
      ) : (
        <p className={cn("whitespace-pre-wrap break-words", event.event_type === "thinking" && "text-muted-foreground italic")}>
          {event.text}
        </p>
      )}
    </div>
  );
}

function eventTypeColor(type: TraceEvent["event_type"]): string {
  switch (type) {
    case "tool_use": return "text-accent-foreground";
    case "tool_result": return "text-muted-foreground";
    case "thinking": return "text-muted-foreground";
    default: return "text-foreground";
  }
}
