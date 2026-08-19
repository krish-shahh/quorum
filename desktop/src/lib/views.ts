export type View = "overview" | "performance" | "runs" | "today" | "positions" | "scans";

export const VIEWS: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "performance", label: "Performance" },
  { id: "runs", label: "Runs" },
  { id: "today", label: "Today" },
  { id: "positions", label: "Positions & Trades" },
  { id: "scans", label: "Scans & Reports" },
];
