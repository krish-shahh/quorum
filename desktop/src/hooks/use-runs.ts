import { useQuery } from "@tanstack/react-query";
import { fetchRuns, type RunMode } from "@/lib/api";

export function useRuns(params?: { mode?: RunMode; strategy_id?: string; limit?: number }) {
  return useQuery({
    queryKey: ["runs", params],
    queryFn: () => fetchRuns(params),
    staleTime: 30_000,
  });
}
