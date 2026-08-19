import { useQuery } from "@tanstack/react-query";
import { fetchPerformance, fetchRunPerformance } from "@/lib/api";

export function usePerformance(runId?: string | null) {
  return useQuery({
    queryKey: runId ? ["performance", "run", runId] : ["performance"],
    queryFn: () => (runId ? fetchRunPerformance(runId) : fetchPerformance()),
    staleTime: 60_000,
  });
}
