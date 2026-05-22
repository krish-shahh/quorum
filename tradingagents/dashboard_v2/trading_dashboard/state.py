"""Global state for the TradingAgents dashboard.

All pages read from this shared state. Background tasks periodically
refresh market data, positions, and trade history.
"""

import asyncio
import json
import sys
import os
from datetime import datetime, date
from pathlib import Path
from typing import Any

import reflex as rx

# Add project root to path so we can import tradingagents
_project_root = str(Path(__file__).resolve().parents[3])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


def _get_config():
    """Load TradingAgents config (deferred to avoid import issues at module level)."""
    from tradingagents.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.copy()


class DashboardState(rx.State):
    """Central state shared across all dashboard pages."""

    # ── KPIs (raw) ──
    portfolio_value: float = 0.0
    cash_balance: float = 0.0
    pnl: float = 0.0
    pnl_pct: float = 0.0
    drawdown: float = 0.0
    max_drawdown_limit: float = 0.10
    win_rate: float = 0.0
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    starting_balance: float = 100_000.0

    # ── KPIs (formatted for display) ──
    portfolio_display: str = "$0"
    cash_display: str = "$0"
    pnl_display: str = "$0"
    pnl_pct_display: str = "0.000%"
    drawdown_display: str = "0.000%"
    dd_limit_display: str = "Limit: 10%"
    win_rate_display: str = "0%"
    trade_count_display: str = "No trades"

    # ── Status ──
    kill_switch_active: bool = False
    market_open: bool = False
    market_status_text: str = "CHECKING..."
    execution_mode: str = "paper"
    is_autonomous_running: bool = False
    last_refresh: str = ""

    # ── Positions ──
    positions: list[dict[str, Any]] = []

    # ── Trades ──
    recent_trades: list[dict[str, Any]] = []

    # ── Equity curve data ──
    equity_data: list[dict[str, Any]] = []

    # ── Allocation ──
    allocation_data: list[dict[str, Any]] = []

    # ── Autonomous config ──
    watchlist_tickers: list[str] = []
    schedule_time: str = "09:00"
    ticker_input: str = ""
    available_tickers: list[str] = []
    autonomous_status: str = "Stopped"

    # ── Pipeline config ──
    llm_provider: str = "anthropic"
    quick_think_model: str = "claude-sonnet-4-6"
    deep_think_model: str = "claude-opus-4-7"
    research_depth_display: str = "1 - Quick"
    output_language: str = "English"
    analyst_market: bool = True
    analyst_sentiment: bool = True
    analyst_news: bool = True
    analyst_fundamentals: bool = True

    # ── Risk config ──
    config_max_pos_pct: str = "0.05"
    config_max_ticker_pct: str = "0.25"
    config_max_open_pos: str = "6"
    config_max_drawdown: str = "0.10"
    config_paper_balance: str = "100000"
    config_save_status: str = ""

    # ── History timeline ──
    history_entries: list[dict[str, Any]] = []

    # ── Trade detail modal ──
    modal_open: bool = False
    modal_ticker: str = ""
    modal_signal: str = ""
    modal_action: str = ""
    modal_action_color: str = "gray"
    modal_time: str = ""
    modal_side: str = ""
    modal_qty: str = ""
    modal_fill: str = ""
    modal_acct_before: str = ""
    modal_acct_after: str = ""
    modal_trade_pnl: str = ""
    modal_reason: str = ""

    # ── Analytics ──
    sharpe_ratio: float = 0.0
    sortino_ratio: float = 0.0
    max_drawdown_ever: float = 0.0
    alpha_vs_benchmark: float = 0.0
    win_rate_by_ticker: list[dict[str, Any]] = []
    win_rate_by_signal: list[dict[str, Any]] = []
    pnl_by_ticker: list[dict[str, Any]] = []
    drawdown_series: list[dict[str, Any]] = []

    # ── Politician trades ──
    politician_trades: list[dict[str, Any]] = []
    hot_tickers: list[dict[str, Any]] = []

    # ── Signal distribution ──
    signal_distribution: list[dict[str, Any]] = []

    # ── Discovery ──
    discovered_candidates: list[dict[str, Any]] = []

    # ── Trade Reports ──
    trade_reports: list[dict[str, Any]] = []
    report_detail_open: bool = False
    report_detail: dict[str, Any] = {}

    # ── Wiki ──
    wiki_run_pages: list[dict[str, Any]] = []
    wiki_daily_digests: list[dict[str, Any]] = []
    wiki_ticker_summaries: list[dict[str, Any]] = []
    wiki_page_content: str = ""
    wiki_page_title: str = ""

    # ── Backtest ──
    bt_ticker: str = ""
    bt_start_date: str = ""
    bt_end_date: str = ""
    bt_status: str = ""
    bt_runs: list[dict[str, Any]] = []
    bt_selected_equity: list[dict[str, Any]] = []
    bt_selected_trades: list[dict[str, Any]] = []

    # ── Regime ──
    current_regime: str = "---"
    regime_vix: str = "---"
    regime_dxy: str = "---"
    regime_yield: str = "---"
    regime_confidence: str = "---"

    # ── Insider clusters ──
    insider_clusters: list[dict[str, Any]] = []

    # ── Sector rotation ──
    sector_rotation: list[dict[str, Any]] = []
    rotation_direction: str = "---"

    def refresh_all(self):
        """Full data refresh -- called on page load and periodically."""
        self._refresh_account()
        self._refresh_trades()
        self._refresh_market_status()
        self._load_config()
        self.last_refresh = datetime.now().strftime("%H:%M:%S")

    def _refresh_account(self):
        """Refresh account info, positions, and derived KPIs."""
        try:
            config = _get_config()
            from tradingagents.execution.broker.paper_client import PaperBrokerClient
            from tradingagents.execution.safety import SafetyMonitor

            broker = PaperBrokerClient(config)
            safety = SafetyMonitor(config)
            account = broker.get_account_info()
            positions = broker.get_positions()

            self.starting_balance = float(config.get("paper_starting_balance", 100_000))
            self.max_drawdown_limit = float(config.get("max_drawdown_pct", 0.10))
            self.execution_mode = config.get("execution_mode", "paper")

            self.portfolio_value = round(account.account_value, 3)
            self.cash_balance = round(account.cash_balance, 3)
            self.pnl = round(account.account_value - self.starting_balance, 3)
            self.pnl_pct = round(self.pnl / self.starting_balance, 5) if self.starting_balance else 0

            # Formatted display strings
            self.portfolio_display = f"${self.portfolio_value:,.2f}"
            self.cash_display = f"${self.cash_balance:,.2f}"
            sign = "+" if self.pnl >= 0 else ""
            self.pnl_display = f"{sign}${self.pnl:,.2f}"
            self.pnl_pct_display = f"{self.pnl_pct:+.3%}"
            self.dd_limit_display = f"Limit: {self.max_drawdown_limit:.0%}"

            self.kill_switch_active = safety.kill_switch_active
            if safety._peak_value and account.account_value:
                self.drawdown = round((safety._peak_value - account.account_value) / safety._peak_value, 5)
            else:
                self.drawdown = 0.0
            self.drawdown_display = f"{self.drawdown:.3%}"

            acct_val = account.account_value or 1
            self.positions = []
            for p in positions:
                avg = round(p.avg_cost, 3)
                last = round(p.market_value / p.quantity, 3) if p.quantity else 0
                mv = round(p.market_value, 2)
                upnl = round(p.unrealized_pnl, 2)
                ret = round((p.market_value / (p.avg_cost * p.quantity) - 1) * 100, 3) if p.avg_cost * p.quantity > 0 else 0
                wt = round(p.market_value / acct_val * 100, 3)
                self.positions.append({
                    "ticker": p.ticker,
                    "quantity": f"{p.quantity:,}",
                    "avg_cost": f"${avg:,.3f}",
                    "last_price": f"${last:,.3f}",
                    "market_value": f"${mv:,.2f}",
                    "unrealized_pnl": f"${upnl:+,.2f}",
                    "pct_return": f"{ret:+.3f}%",
                    "weight": f"{wt:.3f}%",
                })

            # Allocation
            pos_total = sum(p.market_value for p in positions)
            self.allocation_data = [
                {"asset": p.ticker, "value": round(p.market_value / acct_val * 100, 1)}
                for p in positions
            ]
            cash_pct = round((acct_val - pos_total) / acct_val * 100, 1)
            if cash_pct > 0:
                self.allocation_data.append({"asset": "Cash", "value": cash_pct})

        except Exception as e:
            print(f"Account refresh error: {e}")

    def _refresh_trades(self):
        """Refresh trade history and derived stats."""
        try:
            config = _get_config()
            from tradingagents.execution.trade_data import (
                load_recent_trades,
                compute_trade_stats,
                compute_equity_curve,
                compute_signal_distribution,
            )

            trades = load_recent_trades(config, limit=500)
            stats = compute_trade_stats(trades, self.starting_balance)

            self.total_trades = stats["total_trades"]
            self.wins = stats["wins"]
            self.losses = stats["losses"]
            self.win_rate = round(stats["win_rate"], 3)
            self.win_rate_display = f"{self.win_rate:.1%}" if self.total_trades > 0 else "---"
            self.trade_count_display = (
                f"{self.wins}W {self.losses}L / {self.total_trades}"
                if self.total_trades > 0 else "No trades"
            )

            # Format trades for display
            self.recent_trades = []
            for t in trades[:100]:
                req = t.get("order_request") or {}
                res = t.get("order_result") or {}
                self.recent_trades.append({
                    "time": t.get("timestamp", "")[:16],
                    "ticker": t.get("ticker", ""),
                    "signal": t.get("signal", ""),
                    "action": t.get("action_taken", ""),
                    "side": (req.get("side") or "").upper(),
                    "qty": req.get("quantity", ""),
                    "fill": f"${res['filled_price']:.2f}" if res.get("filled_price") else "",
                    "pnl": "",
                })

            # Equity curve
            eq = compute_equity_curve(trades, self.starting_balance)
            self.equity_data = [
                {"time": str(p.get("time_str", p.get("time", ""))), "value": p["value"]}
                for p in eq
            ]

            # Signal distribution
            dist = compute_signal_distribution(trades)
            self.signal_distribution = [
                {"signal": sig, "count": count}
                for sig, count in dist.items()
            ]

            # Analytics (suppress yfinance download noise)
            try:
                import logging as _logging
                _logging.getLogger("yfinance").setLevel(_logging.ERROR)

                from tradingagents.execution.analytics import (
                    compute_sharpe_ratio,
                    compute_sortino_ratio,
                    compute_max_drawdown_series,
                    compute_alpha_vs_benchmark,
                    compute_win_rate_by_ticker,
                    compute_win_rate_by_signal,
                )
                from tradingagents.execution.trade_data import compute_pnl_by_ticker

                self.sharpe_ratio = round(compute_sharpe_ratio(trades, self.starting_balance), 3)
                self.sortino_ratio = round(compute_sortino_ratio(trades, self.starting_balance), 3)

                dd_series = compute_max_drawdown_series(trades, self.starting_balance)
                self.drawdown_series = [{"time": d["time"], "dd": round(d["drawdown"] * 100, 1)} for d in dd_series]
                self.max_drawdown_ever = round(min((d["drawdown"] for d in dd_series), default=0) * 100, 1)

                alpha_data = compute_alpha_vs_benchmark(trades, self.starting_balance)
                self.alpha_vs_benchmark = round(alpha_data.get("alpha", 0) * 100, 2)

                wr_ticker = compute_win_rate_by_ticker(trades)
                self.win_rate_by_ticker = [
                    {"ticker": k, "wins": v["wins"], "losses": v["losses"],
                     "wr": round(v["win_rate"] * 100)}
                    for k, v in wr_ticker.items()
                ]

                wr_signal = compute_win_rate_by_signal(trades)
                self.win_rate_by_signal = [
                    {"signal": k, "wins": v["wins"], "losses": v["losses"],
                     "wr": round(v["win_rate"] * 100)}
                    for k, v in wr_signal.items()
                ]

                pnl_ticker = compute_pnl_by_ticker(trades)
                self.pnl_by_ticker = [
                    {"ticker": d["ticker"], "pnl": round(d["pnl"], 2), "trades": d["trades"]}
                    for d in pnl_ticker
                ]
            except Exception:
                pass

        except Exception as e:
            print(f"Trade refresh error: {e}")

    def _refresh_market_status(self):
        """Check market open/close status."""
        try:
            from tradingagents.execution.market_calendar import is_market_open, is_trading_day
            self.market_open = is_market_open()
            if self.market_open:
                self.market_status_text = "MKT OPEN"
            elif is_trading_day():
                self.market_status_text = "MKT CLOSED"
            else:
                self.market_status_text = "NON-TRADING DAY"
        except Exception:
            self.market_status_text = "UNKNOWN"

    def _load_config(self):
        """Load config values for display on the System page."""
        try:
            config = _get_config()
            self.llm_provider = config.get("llm_provider", "anthropic")
            self.quick_think_model = config.get("quick_think_llm", "claude-sonnet-4-6")
            self.deep_think_model = config.get("deep_think_llm", "claude-opus-4-7")
            depth = config.get("max_debate_rounds", 1)
            self.research_depth_display = {1: "1 - Quick", 2: "2 - Standard", 3: "3 - Deep"}.get(depth, "1 - Quick")
            self.output_language = config.get("output_language", "English")
            self.config_max_pos_pct = str(config.get("max_position_pct", 0.05))
            self.config_max_ticker_pct = str(config.get("max_single_ticker_pct", 0.25))
            self.config_max_open_pos = str(config.get("max_open_positions", 6))
            self.config_max_drawdown = str(config.get("max_drawdown_pct", 0.10))
            self.config_paper_balance = str(config.get("paper_starting_balance", 100000))

            # Load available tickers for dropdown
            try:
                from tradingagents.execution.ticker_utils import COMMON_TICKERS
                self.available_tickers = list(COMMON_TICKERS)[:200]
            except Exception:
                self.available_tickers = ["AAPL", "MSFT", "NVDA", "GOOG", "AMZN", "META",
                                          "TSLA", "JPM", "V", "SPY", "QQQ", "TLT", "GLD"]

            # Load saved watchlist
            try:
                from tradingagents.execution.trade_data import load_watchlist as _load_watchlist
                saved = _load_watchlist(config)
                if saved.get("tickers") and not self.watchlist_tickers:
                    self.watchlist_tickers = saved["tickers"]
                if saved.get("schedule_time"):
                    self.schedule_time = saved["schedule_time"]
            except Exception:
                pass
        except Exception:
            pass

    # ── Watchlist management ──

    def set_ticker_input(self, value: str):
        self.ticker_input = value

    def add_ticker_from_dropdown(self, ticker: str):
        if ticker and ticker not in self.watchlist_tickers:
            self.watchlist_tickers = self.watchlist_tickers + [ticker.upper()]

    def add_tickers_from_input(self):
        if not self.ticker_input:
            return
        new = [t.strip().upper() for t in self.ticker_input.split(",") if t.strip()]
        existing = set(self.watchlist_tickers)
        added = [t for t in new if t not in existing]
        self.watchlist_tickers = self.watchlist_tickers + added
        self.ticker_input = ""

    def remove_ticker(self, ticker: str):
        self.watchlist_tickers = [t for t in self.watchlist_tickers if t != ticker]

    def clear_watchlist(self):
        self.watchlist_tickers = []

    def save_watchlist_to_disk(self):
        try:
            config = _get_config()
            from tradingagents.execution.trade_data import save_watchlist as _save_watchlist
            _save_watchlist(config, self.watchlist_tickers, self.schedule_time)
        except Exception:
            pass

    def set_schedule_time(self, value: str):
        self.schedule_time = value

    # ── Pipeline config setters ──

    def set_llm_provider(self, value: str):
        self.llm_provider = value

    def set_quick_think_model(self, value: str):
        self.quick_think_model = value

    def set_deep_think_model(self, value: str):
        self.deep_think_model = value

    def set_research_depth(self, value: str):
        self.research_depth_display = value

    def set_output_language(self, value: str):
        self.output_language = value

    def set_analyst_market(self, value: bool):
        self.analyst_market = value

    def set_analyst_sentiment(self, value: bool):
        self.analyst_sentiment = value

    def set_analyst_news(self, value: bool):
        self.analyst_news = value

    def set_analyst_fundamentals(self, value: bool):
        self.analyst_fundamentals = value

    # ── Risk config setters ──

    def set_config_max_pos_pct(self, value: str):
        self.config_max_pos_pct = value

    def set_config_max_ticker_pct(self, value: str):
        self.config_max_ticker_pct = value

    def set_config_max_open_pos(self, value: str):
        self.config_max_open_pos = value

    def set_config_max_drawdown(self, value: str):
        self.config_max_drawdown = value

    def set_config_paper_balance(self, value: str):
        self.config_paper_balance = value

    def save_config(self):
        """Save config changes to the runtime config."""
        try:
            config = _get_config()
            config["max_position_pct"] = float(self.config_max_pos_pct)
            config["max_single_ticker_pct"] = float(self.config_max_ticker_pct)
            config["max_open_positions"] = int(self.config_max_open_pos)
            config["max_drawdown_pct"] = float(self.config_max_drawdown)
            config["paper_starting_balance"] = float(self.config_paper_balance)
            self.config_save_status = "Saved"
        except (ValueError, TypeError) as exc:
            self.config_save_status = f"Error: {exc}"

    # ── Autonomous start/stop ──

    _scheduler_thread = None

    def start_autonomous(self):
        if not self.watchlist_tickers:
            self.autonomous_status = "Add tickers first"
            return
        self.save_watchlist_to_disk()
        try:
            import threading
            config = _get_config()
            config["scheduled_tickers"] = list(self.watchlist_tickers)
            config["schedule_time"] = self.schedule_time
            config["llm_provider"] = self.llm_provider
            config["quick_think_llm"] = self.quick_think_model
            config["deep_think_llm"] = self.deep_think_model

            def _run():
                from tradingagents.execution.scheduler import TradingScheduler
                try:
                    TradingScheduler(config).start()
                except Exception:
                    pass

            DashboardState._scheduler_thread = threading.Thread(target=_run, daemon=True)
            DashboardState._scheduler_thread.start()
            self.is_autonomous_running = True
            self.autonomous_status = f"Running: {len(self.watchlist_tickers)} tickers at {self.schedule_time} ET"
        except Exception as e:
            self.autonomous_status = f"Error: {e}"

    def stop_autonomous(self):
        self.is_autonomous_running = False
        self.autonomous_status = "Stopped"
        DashboardState._scheduler_thread = None

    def open_trade_modal(self, trade: dict):
        """Open the trade detail modal with data from the clicked trade."""
        self.modal_ticker = trade.get("ticker", "")
        self.modal_signal = trade.get("signal", "")
        self.modal_action = trade.get("action", "")
        action = trade.get("action", "")
        self.modal_action_color = "green" if action == "executed" else ("red" if action == "blocked" else "gray")
        self.modal_time = trade.get("time", "")
        self.modal_side = trade.get("side", "---")
        self.modal_qty = str(trade.get("qty", "---"))
        self.modal_fill = trade.get("fill", "---") or "---"

        # Look up the full trade record for account values
        try:
            config = _get_config()
            from tradingagents.execution.trade_data import load_recent_trades
            all_trades = load_recent_trades(config, limit=500)
            # Find matching trade by ticker + timestamp prefix
            for t in all_trades:
                ts = t.get("timestamp", "")[:16]
                if ts == self.modal_time and t.get("ticker") == self.modal_ticker:
                    before = t.get("account_value_before")
                    after = t.get("account_value_after")
                    self.modal_acct_before = f"${before:,.2f}" if before else "---"
                    self.modal_acct_after = f"${after:,.2f}" if after else "---"
                    if before and after:
                        pnl = after - before
                        self.modal_trade_pnl = f"${pnl:+,.2f}"
                    else:
                        self.modal_trade_pnl = "---"
                    self.modal_reason = t.get("reason") or "---"
                    break
            else:
                self.modal_acct_before = "---"
                self.modal_acct_after = "---"
                self.modal_trade_pnl = "---"
                self.modal_reason = "---"
        except Exception:
            self.modal_acct_before = "---"
            self.modal_acct_after = "---"
            self.modal_trade_pnl = "---"
            self.modal_reason = "---"

        self.modal_open = True

    def set_modal_open(self, value: bool):
        self.modal_open = value

    def export_csv(self):
        """Export trade log to CSV and trigger download."""
        try:
            import csv
            import io
            config = _get_config()
            from tradingagents.execution.trade_data import load_recent_trades, format_trades_for_table
            trades = load_recent_trades(config, limit=1000)
            rows = format_trades_for_table(trades)
            if not rows:
                return

            output = io.StringIO()
            writer = csv.DictWriter(output, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

            # Write to a file in the project for download
            csv_path = Path("~/.tradingagents/export/trades.csv").expanduser()
            csv_path.parent.mkdir(parents=True, exist_ok=True)
            csv_path.write_text(output.getvalue())
        except Exception as e:
            print(f"CSV export error: {e}")

    def activate_kill_switch(self):
        """Trip the kill switch."""
        try:
            config = _get_config()
            from tradingagents.execution.safety import SafetyMonitor
            safety = SafetyMonitor(config)
            safety.kill_switch_active = True
            safety._save_state()
            self.kill_switch_active = True
        except Exception:
            pass

    def reset_kill_switch(self):
        """Reset the kill switch."""
        try:
            config = _get_config()
            from tradingagents.execution.safety import SafetyMonitor
            safety = SafetyMonitor(config)
            safety.reset_kill_switch()
            self.kill_switch_active = False
        except Exception:
            pass

    def refresh_politicians(self):
        """Fetch latest politician trades."""
        try:
            from tradingagents.execution.politician_tracker import (
                PoliticianTradesFetcher,
                PoliticianSignalLayer,
            )
            fetcher = PoliticianTradesFetcher(max_pages=5)
            trades = fetcher.fetch_recent_trades(days=60)
            self.politician_trades = [
                {
                    "politician": t.politician,
                    "ticker": t.ticker,
                    "type": t.transaction_type,
                    "amount": t.amount_range,
                    "date": t.transaction_date.strftime("%Y-%m-%d"),
                    "chamber": t.chamber,
                }
                for t in trades[:50]
            ]

            signals = PoliticianSignalLayer(fetcher)
            hot = signals.get_hot_tickers(min_politicians=1, days=60)
            self.hot_tickers = [
                {
                    "ticker": s.ticker,
                    "direction": s.direction,
                    "politicians": s.politician_count,
                    "strength": round(s.signal_strength, 2),
                }
                for s in hot[:20]
            ]
        except Exception as e:
            print(f"Politician refresh error: {e}")

    def refresh_discovery(self):
        """Run discovery scanner."""
        try:
            config = _get_config()
            from tradingagents.execution.discovery import DiscoveryEngine
            engine = DiscoveryEngine(config)
            engine.run_scan()
            candidates = engine.candidates.get_pending()
            self.discovered_candidates = [
                {
                    "ticker": c.ticker,
                    "source": c.source,
                    "reason": c.reason,
                    "strength": round(c.signal_strength, 2),
                }
                for c in candidates[:20]
            ]
        except Exception as e:
            print(f"Discovery refresh error: {e}")

    def refresh_trade_reports(self):
        """Load recent trade reports from SQLite."""
        try:
            config = _get_config()
            from tradingagents.execution.db import get_db
            conn = get_db(config)
            rows = conn.execute(
                "SELECT * FROM trade_reports ORDER BY created_at DESC LIMIT 30"
            ).fetchall()
            self.trade_reports = [
                {
                    "id": r["id"],
                    "ticker": r["ticker"],
                    "trade_date": r["trade_date"],
                    "report_type": r["report_type"],
                    "signal": r["signal"],
                    "confidence": round(r["confidence"], 2),
                    "technicals": r["technicals"],
                    "fundamentals": r["fundamentals"],
                    "sentiment": r["sentiment"],
                    "news_catalyst": r["news_catalyst"],
                    "risk_factors": r["risk_factors"],
                    "reasoning": r["reasoning"],
                    "fill_price": r["fill_price"],
                    "quantity": r["quantity"],
                    "side": r["side"] or "",
                    "pnl": r["pnl"],
                    "created_at": r["created_at"],
                }
                for r in rows
            ]
        except Exception as e:
            print(f"Trade reports refresh error: {e}")

    def open_report_detail(self, report: dict):
        """Open the report detail modal."""
        self.report_detail = report
        self.report_detail_open = True

    def close_report_detail(self):
        """Close the report detail modal."""
        self.report_detail_open = False

    def refresh_wiki(self):
        """Load recent wiki pages."""
        try:
            config = _get_config()
            from tradingagents.wiki import WikiWriter
            wiki = WikiWriter(config)
            self.wiki_run_pages = wiki.get_recent_pages(page_type="run", limit=20)
            self.wiki_daily_digests = wiki.get_recent_pages(page_type="daily", limit=10)
            self.wiki_ticker_summaries = wiki.get_recent_pages(page_type="ticker", limit=15)
        except Exception as e:
            print(f"Wiki refresh error: {e}")

    def view_wiki_page(self, path: str):
        """Load a wiki page's content for display."""
        try:
            config = _get_config()
            from tradingagents.wiki import WikiWriter
            wiki = WikiWriter(config)
            self.wiki_page_content = wiki.get_page_content(path)
            self.wiki_page_title = path.split("/")[-1].replace(".md", "")
        except Exception as e:
            print(f"Wiki page load error: {e}")

    def close_wiki_page(self):
        """Close the wiki page viewer."""
        self.wiki_page_content = ""
        self.wiki_page_title = ""

    def refresh_regime(self):
        """Load current market regime data."""
        try:
            from tradingagents.dataflows.regime import CrossAssetRegimeDetector
            detector = CrossAssetRegimeDetector()
            today = date.today().isoformat()
            result = detector.detect(today)
            self.current_regime = result.get("regime", "unknown").upper()
            self.regime_confidence = f"{result.get('regime_confidence', 0):.0%}"
            vix = result.get("vix")
            self.regime_vix = f"{vix:.1f}" if vix is not None else "N/A"
            dxy = result.get("dxy")
            self.regime_dxy = f"{dxy:.2f}" if dxy is not None else "N/A"
            yld = result.get("yield_10y")
            self.regime_yield = f"{yld:.2f}%" if yld is not None else "N/A"
        except Exception as e:
            print(f"Regime refresh error: {e}")

    def refresh_backtest_runs(self):
        """Load list of past backtest runs."""
        try:
            config = _get_config()
            from tradingagents.backtest.results import BacktestResult
            self.bt_runs = BacktestResult.list_runs(config, limit=20)
        except Exception as e:
            print(f"Backtest runs refresh error: {e}")

    def load_backtest_result(self, run_id: str):
        """Load a specific backtest result for display."""
        try:
            config = _get_config()
            from tradingagents.backtest.results import BacktestResult
            result = BacktestResult.load(run_id, config)
            if result:
                self.bt_selected_equity = result.equity_curve
                self.bt_selected_trades = result.trades
                self.bt_status = f"Loaded: {result.total_return:.1f}% return, {result.total_trades} trades"
        except Exception as e:
            print(f"Backtest load error: {e}")

    def set_bt_ticker(self, val: str):
        self.bt_ticker = val

    def set_bt_start_date(self, val: str):
        self.bt_start_date = val

    def set_bt_end_date(self, val: str):
        self.bt_end_date = val

    @rx.event(background=True)
    async def run_backtest(self):
        """Run a backtest in the background."""
        async with self:
            self.bt_status = "Running..."

        try:
            config = _get_config()
            from tradingagents.backtest import BacktestEngine
            engine = BacktestEngine(config)
            result = engine.run(self.bt_ticker, self.bt_start_date, self.bt_end_date)

            async with self:
                self.bt_status = f"Complete: {result.total_return:.1f}% return, {result.total_trades} trades"
                self.bt_selected_equity = result.equity_curve
                self.bt_selected_trades = result.trades
                self.refresh_backtest_runs()
        except Exception as e:
            async with self:
                self.bt_status = f"Error: {e}"

    def refresh_sectors(self):
        """Load sector rotation data."""
        try:
            from tradingagents.dataflows.sector_rotation import SectorRotationModel
            model = SectorRotationModel()
            today = date.today().isoformat()
            result = model.analyze(today)
            if "error" not in result:
                self.sector_rotation = [
                    {
                        "name": s["name"],
                        "etf": s["etf"],
                        "return_1m": round(s["return_1m"] or 0, 1),
                        "relative_1m": round(s["relative_1m"] or 0, 1),
                    }
                    for s in result.get("sectors", [])
                ]
                self.rotation_direction = result.get("rotation_direction", "neutral").replace("_", " ").title()
        except Exception as e:
            print(f"Sector rotation error: {e}")

    @rx.event(background=True)
    async def periodic_refresh(self):
        """Background task: refresh data every 10 seconds."""
        while True:
            async with self:
                self.refresh_all()
            await asyncio.sleep(10)
