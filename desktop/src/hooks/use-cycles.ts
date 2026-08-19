import { useQuery } from "@tanstack/react-query";
import { fetchCycleDetail } from "@/lib/api";

export function useCycleDetail(cycleId: string | null) {
  return useQuery({
    queryKey: ["cycle", cycleId],
    queryFn: () => fetchCycleDetail(cycleId as string),
    enabled: cycleId != null,
    staleTime: 30_000,
  });
}
