import { useQuery } from "@tanstack/react-query";
import { fetchPerformance } from "@/lib/api";

export function usePerformance() {
  return useQuery({
    queryKey: ["performance"],
    queryFn: fetchPerformance,
    staleTime: 60_000,
  });
}
