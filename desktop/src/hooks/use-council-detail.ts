import { useQuery } from "@tanstack/react-query";
import { fetchCouncilDetail, type CouncilDetail } from "@/lib/api";

export function useCouncilDetail(ticker: string | null) {
  return useQuery<CouncilDetail>({
    queryKey: ["council-detail", ticker],
    queryFn: () => fetchCouncilDetail(ticker!),
    enabled: !!ticker,
    staleTime: 60_000,
  });
}
