import { useQuery } from "@tanstack/react-query";
import { fetchRunDetail } from "@/lib/api";

export function useRunDetail(runId: string | null) {
  return useQuery({
    queryKey: ["run-detail", runId],
    queryFn: () => fetchRunDetail(runId as string),
    enabled: runId != null,
    staleTime: 30_000,
  });
}
