import { useQuery } from "@tanstack/react-query";
import { fetchDailyRecap, fetchDailyRecaps } from "@/lib/api";

export function useDailyRecaps(limit = 30) {
  return useQuery({
    queryKey: ["daily-recaps", limit],
    queryFn: () => fetchDailyRecaps(limit),
    staleTime: 60_000,
  });
}

export function useDailyRecap(date: string) {
  return useQuery({
    queryKey: ["daily-recap", date],
    queryFn: () => fetchDailyRecap(date),
    staleTime: 30_000,
    retry: false,
  });
}
