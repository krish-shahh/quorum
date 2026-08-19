import { useQuery } from "@tanstack/react-query";
import { fetchCycles, fetchCycleDetail } from "@/lib/api";

export function useCycles(limit = 50) {
  return useQuery({
    queryKey: ["cycles", limit],
    queryFn: () => fetchCycles(limit),
    staleTime: 30_000,
  });
}

export function useCycleDetail(cycleId: string | null) {
  return useQuery({
    queryKey: ["cycle", cycleId],
    queryFn: () => fetchCycleDetail(cycleId as string),
    enabled: cycleId != null,
    staleTime: 30_000,
  });
}
