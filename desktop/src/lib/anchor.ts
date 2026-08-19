import type { AnchorType } from "@/lib/api";
import type { View } from "@/lib/views";

/** Stable DOM id for the element a CommentButton is attached to, so the
 * comments drawer can scroll straight to it. Doesn't need to match the
 * backend's anchor_key canonicalization — just needs to be the same string
 * on both the CommentButton that renders the element and the drawer link
 * that navigates to it. */
export function anchorElementId(anchorType: AnchorType, anchor: Record<string, unknown>): string {
  const sorted = Object.keys(anchor)
    .sort()
    .map((k) => `${k}:${String(anchor[k])}`)
    .join("|");
  return `anno-${anchorType}-${sorted}`.replace(/[^a-zA-Z0-9_:|-]/g, "_");
}

const VIEW_LABELS: Record<View, string> = {
  portfolio: "Portfolio",
  performance: "Performance",
  activity: "Activity",
  research: "Research",
};

// Anchors created before the 7-tab -> 4-tab consolidation carry the old tab
// names ("overview", "positions", "runs", "today", "logs", "scans") in their
// `view` field. Those anchor_key values are stable identifiers in the DB
// (including on real historical threads) so they're never rewritten —
// this map just translates them to where that content now lives for
// navigation/display purposes.
const LEGACY_VIEW_TO_TAB: Record<string, View> = {
  overview: "portfolio",
  positions: "portfolio",
  runs: "activity",
  today: "activity",
  logs: "activity",
  performance: "performance",
  scans: "research",
};

/** Which top-level tab a thread's anchor lives on. `run` anchors have no
 * `view` field (they're only ever created from the run blotter), everything
 * else carries one explicitly (current or legacy). */
export function anchorView(anchorType: AnchorType, anchor: Record<string, unknown>): View {
  if (typeof anchor.view === "string" && anchor.view in LEGACY_VIEW_TO_TAB) {
    return LEGACY_VIEW_TO_TAB[anchor.view];
  }
  if (anchorType === "run") return "activity";
  return "portfolio";
}

export function describeAnchor(anchorType: AnchorType, anchor: Record<string, unknown>): string {
  const view = VIEW_LABELS[anchorView(anchorType, anchor)];
  switch (anchorType) {
    case "kpi":
      return `${view} · ${anchor.metric ?? "KPI"}`;
    case "run":
      return `Run ${String(anchor.run_id ?? "").slice(0, 8)}`;
    case "table_row": {
      const table = String(anchor.table ?? "table").replace(/_/g, " ");
      const row = anchor.ticker ?? anchor.time ?? "";
      return `${view} · ${table}${row ? ` · ${row}` : ""}`;
    }
    case "chart_series": {
      const chart = String(anchor.chart ?? "chart").replace(/_/g, " ");
      const scope = anchor.scope ? ` (${anchor.scope})` : "";
      return `${view} · ${chart} chart${scope}`;
    }
    default:
      return view;
  }
}
