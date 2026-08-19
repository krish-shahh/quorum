const BASE_URL = `http://localhost:${window.electronAPI?.flaskPort ?? 5050}`;

async function fetchJson<T>(path: string): Promise<T> {
  const res = await fetch(`${BASE_URL}${path}`);
  if (!res.ok) {
    throw new Error(`API error: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

export interface DashboardData {
  account: AccountData;
  trades: TradesData;
  regime: RegimeData;
  market: MarketStatus;
  watchlist: WatchlistEntry[];
  status: StatusData;
}

export interface AccountData {
  portfolio_value: number;
  cash: number;
  pnl: number;
  pnl_pct: number;
  drawdown: number;
  dd_limit: number;
  kill_switch: boolean;
  execution_mode: string;
  positions: Position[];
  allocation: { asset: string; value: number }[];
  books: BookData[];
}

export interface BookData {
  name: string;
  market_value: number;
  unrealized_pnl: number;
  allocation_pct: number;
  position_count: number;
  positions: Position[];
}

export interface Position {
  ticker: string;
  quantity: number;
  avg_cost: number;
  last_price: number;
  market_value: number;
  unrealized_pnl: number;
  pct_return: number;
  weight: number;
  signal: string;
  asset_class: string;
  sector: string;
  multiplier: number;
  contract_name: string | null;
  margin: number | null;
  days_to_expiry: number | null;
  book: string;
}

export interface TradesData {
  total: number;
  wins: number;
  losses: number;
  win_rate: number;
  recent: RecentTrade[];
  equity: { time: string; value: number }[];
}

export interface RecentTrade {
  time: string;
  ticker: string;
  signal: string;
  action: string;
  side: string;
  qty: number;
  fill: number | null;
  reason: string;
  account_before: number | null;
  account_after: number | null;
  asset_class: string;
  sector: string;
  multiplier: number;
  notional: number;
}

export interface RegimeData {
  regime: string;
  confidence: string;
  vix: string;
  dxy: string;
  yield_10y: string;
}

export interface MarketStatus {
  open: boolean;
  text: string;
}

export interface WatchlistEntry {
  ticker: string;
  asset_class: string;
  sector: string;
}

export interface StatusData {
  regime: RegimeData;
  plan: PlanStatus;
  live_risk: LiveRisk;
  kill_switch: boolean;
  execution_mode: string;
  risk_level: string;
}

export interface PlanStatus {
  active: boolean;
  plan_id?: string;
  plan_type?: string;
  regime?: string;
  risk_level?: string;
  created_at?: string;
  steps?: PlanStep[];
  buy_count?: number;
  sell_count?: number;
  hold_count?: number;
  adherence_rate?: number | null;
}

export interface PlanStep {
  ticker: string;
  action: string;
  entry: number | null;
  exec_status: string;
  fill_price?: number | null;
  slippage_bps?: number | null;
}

export interface LiveRisk {
  risk_level: string;
  daily_pnl: number;
  daily_pnl_pct: number;
  intraday_drawdown: number;
  cash_reserve_pct: number;
  vix: number;
  consecutive_losses: number;
  position_stops: unknown[];
  stops_breached: unknown[];
}

// ── API Functions ──

export function fetchDashboard(): Promise<DashboardData> {
  return fetchJson("/api/v1/dashboard");
}

export function fetchSectors(): Promise<{ sectors: unknown[]; direction: string }> {
  return fetchJson("/api/v1/scans/sectors");
}

export function fetchInsiders(): Promise<{ clusters: unknown[] }> {
  return fetchJson("/api/v1/scans/insiders");
}

export function fetchCongress(): Promise<{ trades: unknown[] }> {
  return fetchJson("/api/v1/scans/congress");
}

export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export function fetchChart(ticker: string, days = 90): Promise<{ ticker: string; candles: CandleData[] }> {
  return fetchJson(`/api/v1/chart/${ticker}?days=${days}`);
}

export async function refreshRegime(): Promise<{ cleared: number }> {
  const res = await fetch(`${BASE_URL}/api/v1/refresh`, { method: "POST" });
  if (!res.ok) throw new Error("Refresh failed");
  return res.json();
}

export async function toggleKillSwitch(): Promise<{ active: boolean }> {
  const res = await fetch(`${BASE_URL}/api/v1/kill-switch`, { method: "POST" });
  if (!res.ok) throw new Error("Kill switch toggle failed");
  return res.json();
}

// ── Performance ──

export interface WinRateBucket {
  wins: number;
  losses: number;
  win_rate: number;
}

export interface RollingMetricPoint {
  trade_index: number;
  time: string;
  rolling_sharpe: number;
  rolling_sortino: number;
}

export interface PerformanceSummary {
  total_trades: number;
  wins: number;
  losses: number;
  win_rate: number;
  cumulative_return: number;
  best_trade: number;
  worst_trade: number;
  avg_trade_pnl: number;
  total_realized_pnl: number;
  sharpe_ratio: number;
  sortino_ratio: number;
  max_drawdown: number;
  win_rate_by_ticker: Record<string, WinRateBucket>;
  win_rate_by_signal: Record<string, WinRateBucket>;
  win_rate_by_day_of_week: Record<string, WinRateBucket>;
  alpha_vs_benchmark: { portfolio_return: number; benchmark_return: number; alpha: number };
  rolling_metrics: RollingMetricPoint[];
  profit_factor: number;
  expectancy: number;
  sqn: number;
}

export function fetchPerformance(): Promise<PerformanceSummary> {
  return fetchJson("/api/v1/performance");
}

export function fetchRunPerformance(runId: string): Promise<PerformanceSummary> {
  return fetchJson(`/api/v1/runs/${runId}/performance`);
}

// ── Runs ──

export type RunMode = "backtest" | "walkforward" | "paper" | "shadow" | "live";
export type RunStatus = "running" | "ok" | "error" | "killed";

export interface RunSummary {
  run_id: string;
  strategy_id: string;
  strategy_version: string;
  mode: RunMode;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  gate_passed: boolean | null;
  metrics: Record<string, unknown>;
}

export interface GateCheck {
  name: string;
  passed: boolean;
  value: number | null;
  threshold: string;
  detail: string;
}

export interface GateResult {
  passed: boolean | null;
  checks: GateCheck[] | null;
}

export interface RunSignal {
  symbol: string;
  direction: number;
  score: number | null;
  rationale: string;
  suppressed: number;
  suppressed_reason: string | null;
}

export interface RunTarget {
  symbol: string;
  target_weight: number | null;
  target_shares: number | null;
  sizing_method: string;
}

export interface RunOrder {
  symbol: string;
  side: "buy" | "sell";
  qty: number;
  status: string;
  ts_submitted: string;
  price: number | null;
  fill_ts: string | null;
  commission: number | null;
  slippage_bps: number | null;
}

export interface RunDecision {
  ts: string;
  kind: string;
  author: string;
  body: string;
  tags: string[];
}

export interface RunClosedTrade {
  symbol: string;
  qty: number;
  entry_price: number;
  exit_price: number;
  pnl: number;
  entry_ts: string;
  exit_ts: string;
}

export interface RunDetail {
  run_id: string;
  strategy_id: string;
  strategy_version: string;
  mode: RunMode;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  error: string | null;
  cycle_id: string | null;
  metrics: Record<string, unknown>;
  gate: GateResult;
  candidates: RunSignal[];
  n_signals_suppressed: number;
  targets: RunTarget[];
  orders: RunOrder[];
  decisions: RunDecision[];
  closed_trades: RunClosedTrade[];
}

export function fetchRuns(params?: { mode?: RunMode; strategy_id?: string; limit?: number }): Promise<{ runs: RunSummary[] }> {
  const qs = new URLSearchParams();
  if (params?.mode) qs.set("mode", params.mode);
  if (params?.strategy_id) qs.set("strategy_id", params.strategy_id);
  if (params?.limit) qs.set("limit", String(params.limit));
  const suffix = qs.toString() ? `?${qs}` : "";
  return fetchJson(`/api/v1/runs${suffix}`);
}

export function fetchRunDetail(runId: string): Promise<RunDetail> {
  return fetchJson(`/api/v1/runs/${runId}`);
}

// ── Daily recap ──

export interface DailyRecapSummary {
  d: string;
  computed_at: string;
  n_runs: number;
  n_candidates: number;
  n_decisions: number;
  n_orders: number;
  n_fills: number;
  realized_pnl: number | null;
}

export interface DailyRecapRun {
  run_id: string;
  strategy_id: string;
  strategy_version: string;
  mode: RunMode;
  status: RunStatus;
  started_at: string;
  finished_at: string | null;
  metrics: Record<string, unknown>;
  candidates: RunSignal[];
  n_signals_suppressed: number;
  decisions: RunDecision[];
  orders: RunOrder[];
}

export interface DailyRecap {
  date: string;
  runs: DailyRecapRun[];
  closed_trades: (RunClosedTrade & { run_id: string })[];
  summary: {
    n_runs: number;
    n_candidates: number;
    n_decisions: number;
    n_orders: number;
    n_fills: number;
    n_closed_trades: number;
    realized_pnl: number | null;
  };
}

export function fetchDailyRecaps(limit = 30): Promise<{ recaps: DailyRecapSummary[] }> {
  return fetchJson(`/api/v1/daily-recap?limit=${limit}`);
}

export function fetchDailyRecap(date: string): Promise<DailyRecap> {
  return fetchJson(`/api/v1/daily-recap/${date}`);
}

// ── Cycles / trace ──

export interface TraceEvent {
  event_id: string;
  ts: string;
  session_id: string;
  parent_tool_use_id: string | null;
  role: "assistant" | "user";
  event_type: "text" | "thinking" | "tool_use" | "tool_result";
  tool_name: string | null;
  tool_input: Record<string, unknown> | null;
  tool_output_summary: string | null;
  text: string | null;
}

export interface CycleRun {
  run_id: string;
  strategy_id: string;
  mode: RunMode;
  status: RunStatus;
}

export interface CycleDetail {
  cycle_id: string;
  started_at: string;
  runs: CycleRun[];
  trace_events: TraceEvent[];
}

export function fetchCycleDetail(cycleId: string): Promise<CycleDetail> {
  return fetchJson(`/api/v1/cycles/${cycleId}`);
}

// ── Annotations ──

export type AnchorType = "kpi" | "run" | "table_row" | "chart_series";

export interface AnnotationComment {
  author: "user" | "claude";
  body: string;
  ts: string;
}

export interface Annotation {
  id: string;
  anchor_type: AnchorType;
  anchor: Record<string, unknown>;
  status: "open" | "resolved";
  created_at: string;
  thread: AnnotationComment[];
}

export function fetchAnnotations(params?: {
  anchor_type?: AnchorType;
  anchor?: Record<string, unknown>;
  status?: "open" | "resolved";
}): Promise<{ annotations: Annotation[] }> {
  const qs = new URLSearchParams();
  if (params?.anchor_type) qs.set("anchor_type", params.anchor_type);
  if (params?.anchor) qs.set("anchor", JSON.stringify(params.anchor));
  if (params?.status) qs.set("status", params.status);
  const suffix = qs.toString() ? `?${qs}` : "";
  return fetchJson(`/api/v1/annotations${suffix}`);
}

export async function createAnnotation(anchor_type: AnchorType, anchor: Record<string, unknown>, body: string): Promise<Annotation> {
  const res = await fetch(`${BASE_URL}/api/v1/annotations`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ anchor_type, anchor, body, author: "user" }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export async function replyToAnnotation(id: string, body: string, author: "user" | "claude" = "user"): Promise<Annotation> {
  const res = await fetch(`${BASE_URL}/api/v1/annotations/${id}/reply`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ body, author }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export async function resolveAnnotation(id: string): Promise<Annotation> {
  const res = await fetch(`${BASE_URL}/api/v1/annotations/${id}/resolve`, { method: "POST" });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}

export interface ValidateSpecResult {
  ok: boolean;
  cleaned_text?: string;
  errors?: string[];
}

/** Validate a generated spec YAML against its closed-grammar schema —
 * always resolves (never throws for an invalid spec, only for a bad
 * request); check `.ok`. Used by the generate -> validate -> retry loop
 * (lib/codegen.ts) after every codegen attempt. */
export async function validateSpec(kind: "strategy", text: string, expectedId?: string): Promise<ValidateSpecResult> {
  const res = await fetch(`${BASE_URL}/api/v1/validate-spec`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ kind, text, expected_id: expectedId }),
  });
  if (!res.ok) throw new Error(`API error: ${res.status} ${res.statusText}`);
  return res.json();
}
