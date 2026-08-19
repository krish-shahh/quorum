export type View = "overview" | "performance" | "runs" | "today" | "logs" | "positions" | "scans";

export const VIEWS: { id: View; label: string }[] = [
  { id: "overview", label: "Overview" },
  { id: "performance", label: "Performance" },
  { id: "runs", label: "Runs" },
  { id: "today", label: "Today" },
  { id: "logs", label: "Logs" },
  { id: "positions", label: "Positions & Trades" },
  { id: "scans", label: "Scans & Reports" },
];
