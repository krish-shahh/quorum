const BASE_URL = "http://localhost:5050";

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
  states: TickerState[];
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
  treemap: TreenmapItem[];
  exposure: Record<string, unknown>;
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

export interface TreenmapItem {
  group: string;
  ticker: string;
  weight: number;
  pct_return: number;
  market_value: number;
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
  signal_dist: Record<string, number>;
  analytics: Analytics;
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

export interface Analytics {
  sharpe?: number;
  sortino?: number;
  max_dd?: number;
  alpha?: number;
  profit_factor?: number;
  expectancy?: number;
  sqn?: number;
  wr_signal?: { signal: string; wins: number; losses: number; wr: number }[];
  wr_ticker?: { ticker: string; wins: number; losses: number; wr: number }[];
  pnl_ticker?: { ticker: string; pnl: number; trades: number }[];
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

export interface TickerState {
  ticker: string;
  technical: number;
  fundamental: number;
  sentiment: number;
  news: number;
  signal: string;
  confidence: number;
  weighted: number;
  price: number;
  regime: string;
  analyzed_at: string;
  asset_class: string;
  sector: string;
  debate_triggered: boolean;
}

export interface StatusData {
  regime: RegimeData;
  plan: PlanStatus;
  live_risk: LiveRisk;
  kill_switch: boolean;
  execution_mode: string;
  exposure: Record<string, unknown> | null;
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

export interface CouncilDetail {
  ticker: string;
  detail: {
    detail: Record<string, unknown>;
    history: Record<string, unknown>[];
    quant: Record<string, unknown>;
  };
  reflections: Record<string, string> | null;
  analyst_reports: AnalystReport[];
  trade_reports: TradeReport[];
  plan: PlanInfo | null;
}

export interface AnalystReport {
  ticker: string;
  analysis_date: string;
  council_signal: string;
  weighted_score: number;
  debate_triggered: boolean;
  technical_report: string;
  fundamental_report: string;
  sentiment_report: string;
  news_report: string;
  bull_case: string | null;
  bear_case: string | null;
  pm_decision: string | null;
}

export interface TradeReport {
  trade_date: string;
  report_type: string;
  signal: string;
  confidence: number;
  technicals: string;
  fundamentals: string;
  sentiment: string;
  news_catalyst: string;
  risk_factors: string;
  reasoning: string;
}

export interface PlanInfo {
  plan_id: string;
  created_at: string;
  regime: string;
  risk_level: string;
  expired: boolean;
  steps: { ticker: string; action: string; entry: number | null }[];
}

// ── API Functions ──

export function fetchDashboard(): Promise<DashboardData> {
  return fetchJson("/api/v1/dashboard");
}

export function fetchCouncilDetail(ticker: string): Promise<CouncilDetail> {
  return fetchJson(`/api/v1/council/${ticker}`);
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

export function fetchPlan(): Promise<Record<string, unknown>> {
  return fetchJson("/api/v1/plan");
}

export function fetchCalibration(): Promise<{ report: string }> {
  return fetchJson("/api/v1/calibration");
}

export function fetchHistorical(date: string): Promise<Record<string, unknown>> {
  return fetchJson(`/api/v1/historical?date=${date}`);
}

export interface FullTradeReport {
  id: number;
  ticker: string;
  trade_date: string;
  report_type: string;
  signal: string;
  confidence: number;
  technicals: string;
  fundamentals: string;
  sentiment: string;
  news_catalyst: string;
  risk_factors: string;
  reasoning: string;
  fill_price: number | null;
  quantity: number | null;
  side: string;
  pnl: number | null;
  created_at: string;
  asset_class: string;
  sector: string;
}

export function fetchReports(): Promise<{ reports: FullTradeReport[] }> {
  return fetchJson("/api/v1/reports");
}

export interface CandleData {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface TradeMarker {
  time: string;
  side: string;
  qty: number;
  price: number;
}

export function fetchTickerTrades(ticker: string): Promise<{ trades: TradeMarker[] }> {
  return fetchJson(`/api/v1/trades/${ticker}`);
}

export function fetchChart(ticker: string, days = 90): Promise<{ ticker: string; candles: CandleData[] }> {
  return fetchJson(`/api/v1/chart/${ticker}?days=${days}`);
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

export function fetchGate(runId: string): Promise<GateResult> {
  return fetchJson(`/api/v1/gate/${runId}`);
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

// ── Portfolio risk ──

export interface PortfolioRisk {
  account_value: number;
  cash: number;
  n_positions: number;
  exposure: {
    total_notional: number;
    futures_notional: number;
    equity_notional: number;
    leverage: number;
    max_leverage: number;
    within_limits: boolean;
  };
  var: {
    var_95_pct: number;
    var_95_dollars: number;
    threshold_pct: number;
    threshold_dollars: number;
    within_limits: boolean;
  };
}

export function fetchPortfolioRisk(): Promise<PortfolioRisk> {
  return fetchJson("/api/v1/portfolio-risk");
}

// ── Analyst accuracy ──

export function fetchAnalystAccuracy(): Promise<Record<string, unknown>> {
  return fetchJson("/api/v1/analyst-accuracy");
}
