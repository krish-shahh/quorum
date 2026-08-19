import { useQuery } from "@tanstack/react-query";
import { fetchAnnotations, type AnchorType } from "@/lib/api";

export function useAnnotations(anchorType: AnchorType, anchor: Record<string, unknown>) {
  return useQuery({
    queryKey: ["annotations", anchorType, anchor],
    queryFn: () => fetchAnnotations({ anchor_type: anchorType, anchor }),
    staleTime: 15_000,
  });
}

export function useOpenAnnotationCount() {
  return useQuery({
    queryKey: ["annotations", "open-count"],
    queryFn: () => fetchAnnotations({ status: "open" }),
    staleTime: 30_000,
    select: (data) => data.annotations.length,
  });
}
