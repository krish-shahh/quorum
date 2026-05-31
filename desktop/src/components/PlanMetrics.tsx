import { cn, signalColor } from "@/lib/utils";
import type { PlanStatus } from "@/lib/api";

interface Props {
  status: PlanStatus;
}

export default function PlanMetrics({ status }: Props) {
  if (!status.active) {
    return (
      <div className="rounded-lg border bg-card p-4">
        <h3 className="text-sm font-medium mb-2">Trading Plan</h3>
        <p className="text-xs text-muted-foreground">No active plan</p>
      </div>
    );
  }

  return (
    <div className="rounded-lg border bg-card p-4">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium">Trading Plan</h3>
        <span className="text-[10px] text-muted-foreground font-mono">{status.plan_id}</span>
      </div>

      {/* Plan meta */}
      <div className="flex items-center gap-3 text-xs mb-3">
        {status.plan_type && (
          <span className="px-2 py-0.5 bg-muted rounded text-muted-foreground">{status.plan_type}</span>
        )}
        {status.regime && (
          <span className="px-2 py-0.5 bg-muted rounded text-muted-foreground">{status.regime}</span>
        )}
        {status.adherence_rate != null && (
          <span className="font-mono">
            Adherence: {(status.adherence_rate * 100).toFixed(0)}%
          </span>
        )}
      </div>

      {/* Steps */}
      {status.steps && status.steps.length > 0 && (
        <div className="space-y-1.5">
          {status.steps.map((step, i) => (
            <div key={i} className="flex items-center justify-between text-xs py-1.5 px-2 rounded bg-muted/50">
              <div className="flex items-center gap-2">
                <span className="font-mono font-medium">{step.ticker}</span>
                <span className={cn("px-1.5 py-0.5 rounded-full text-[10px] font-medium", signalColor(step.action))}>
                  {step.action}
                </span>
              </div>
              <div className="flex items-center gap-2">
                {step.entry && <span className="text-muted-foreground font-mono">${step.entry}</span>}
                <StatusBadge status={step.exec_status} />
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    FILLED: "bg-green-100 text-green-700",
    SKIPPED: "bg-gray-100 text-gray-500",
    PENDING: "bg-yellow-50 text-yellow-700",
  };

  return (
    <span className={cn("px-1.5 py-0.5 rounded text-[10px] font-medium", styles[status] || styles.PENDING)}>
      {status}
    </span>
  );
}
