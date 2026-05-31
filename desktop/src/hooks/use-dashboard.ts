import { useQuery } from "@tanstack/react-query";
import { fetchDashboard, type DashboardData } from "@/lib/api";

const POLL_INTERVAL = 30_000;

export function useDashboard(live: boolean = true) {
  return useQuery<DashboardData>({
    queryKey: ["dashboard"],
    queryFn: fetchDashboard,
    refetchInterval: live ? POLL_INTERVAL : false,
    staleTime: 10_000,
  });
}
