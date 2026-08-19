import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatUsd(v: number | null | undefined): string {
  if (v == null) return "---";
  return `$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatPct(v: number | null | undefined): string {
  if (v == null) return "---";
  return `${(v * 100).toFixed(1)}%`;
}

export function formatSignedUsd(v: number | null | undefined): string {
  if (v == null) return "---";
  const sign = v >= 0 ? "+" : "";
  return `${sign}$${v.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

export function formatSignedPct(v: number | null | undefined): string {
  if (v == null) return "---";
  const sign = v >= 0 ? "+" : "";
  return `${sign}${v.toFixed(1)}%`;
}

export function scoreColor(score: number): string {
  if (score >= 3.5) return "text-profit bg-profit/10";
  if (score >= 2.5) return "text-muted-foreground bg-muted";
  return "text-loss bg-loss/10";
}

export function signalColor(signal: string): string {
  const s = signal?.toLowerCase() || "";
  if (s.includes("buy") || s.includes("overweight")) return "text-profit bg-profit/10";
  if (s.includes("sell") || s.includes("underweight")) return "text-loss bg-loss/10";
  return "text-neutral-signal bg-muted";
}

export function riskColor(level: string): string {
  switch (level?.toLowerCase()) {
    case "green": return "text-risk-green bg-risk-green/10";
    case "yellow": return "text-risk-yellow bg-risk-yellow/10";
    case "orange": return "text-risk-orange bg-risk-orange/10";
    case "red": return "text-risk-red bg-risk-red/10";
    default: return "text-muted-foreground bg-muted";
  }
}

export function regimeColor(regime: string): string {
  switch (regime?.toUpperCase()) {
    case "RISK_ON": return "text-regime-calm bg-regime-calm/10";
    case "RISK_OFF": return "text-regime-risk-off bg-regime-risk-off/10";
    case "VOLATILE": return "text-regime-volatile bg-regime-volatile/10";
    default: return "text-regime-neutral bg-muted";
  }
}

export function gateColor(passed: boolean | null): string {
  if (passed === null) return "text-gate-skip bg-muted";
  return passed ? "text-gate-pass bg-gate-pass/10" : "text-gate-fail bg-gate-fail/10";
}

/** Text-only P&L color — for numbers inline in a table/KPI, not a pill. */
export function pnlTextColor(v: number | null | undefined): string {
  if (v == null || v === 0) return "text-muted-foreground";
  return v > 0 ? "text-profit" : "text-loss";
}

/** Resolve a token like "--profit" to a real `hsl(...)` string, for canvas
 * libraries (lightweight-charts) that can't consume Tailwind classes or
 * CSS variables directly. Re-read whenever the theme toggles. */
export function themeColor(varName: string, alpha = 1): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
  return alpha === 1 ? `hsl(${value})` : `hsl(${value} / ${alpha})`;
}

export function timeAgo(timestamp: string): string {
  const diff = Date.now() - new Date(timestamp).getTime();
  const seconds = Math.floor(diff / 1000);
  if (seconds < 10) return "just now";
  if (seconds < 60) return `${seconds}s ago`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ago`;
}
