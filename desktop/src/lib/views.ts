export type View = "portfolio" | "performance" | "activity" | "research";

export const VIEWS: { id: View; label: string }[] = [
  { id: "portfolio", label: "Portfolio" },
  { id: "performance", label: "Performance" },
  { id: "activity", label: "Activity" },
  { id: "research", label: "Research" },
];
