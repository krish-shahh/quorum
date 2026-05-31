"""Flask dashboard v3 — light-mode Tailwind trading dashboard.

All data-fetching is ported from the Reflex v2 state.py into plain
functions.  Templates use Jinja2 + Tailwind CDN + Chart.js + htmx.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from flask import Flask, Blueprint, request, jsonify

# ── Make tradingagents importable ──────────────────────────────────────
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tradingagents.execution.db import get_db


def _cfg():
    from tradingagents.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.copy()



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_account_data():
    """Portfolio value, cash, P&L, positions, allocation."""
    try:
        config = _cfg()
        from tradingagents.execution.broker.paper_client import PaperBrokerClient
        from tradingagents.execution.safety import SafetyMonitor

        broker = PaperBrokerClient(config)
        safety = SafetyMonitor(config)
        account = broker.get_account_info()
        positions_raw = broker.get_positions()

        starting = float(config.get("paper_starting_balance", 100_000))
        dd_limit = float(config.get("max_drawdown_pct", 0.10))

        pv = round(account.account_value, 2)
        cash = round(account.cash_balance, 2)
        pnl = round(pv - starting, 2)
        pnl_pct = round(pnl / starting, 5) if starting else 0

        if safety._peak_value and account.account_value:
            dd = round((safety._peak_value - account.account_value) / safety._peak_value, 5)
        else:
            dd = 0.0

        from tradingagents.execution.ticker_utils import detect_asset_type, get_book
        from tradingagents.execution.contracts import get_contract_spec, days_to_expiry

        acct_val = account.account_value or 1
        positions = []
        for p in positions_raw:
            avg = round(p.avg_cost, 3)
            last = round(p.market_value / p.quantity, 3) if p.quantity else 0
            mv = round(p.market_value, 2)
            upnl = round(p.unrealized_pnl, 2)
            ret = round((p.market_value / (p.avg_cost * p.quantity) - 1) * 100, 2) if p.avg_cost * p.quantity > 0 else 0
            wt = round(p.market_value / acct_val * 100, 1)
            asset_info = detect_asset_type(p.ticker)
            spec = get_contract_spec(p.ticker)
            dte = days_to_expiry(p.ticker)
            positions.append({
                "ticker": p.ticker,
                "quantity": p.quantity,
                "avg_cost": avg,
                "last_price": last,
                "market_value": mv,
                "unrealized_pnl": upnl,
                "pct_return": ret,
                "weight": wt,
                "signal": "---",
                "asset_class": asset_info["asset_class"],
                "sector": asset_info["sector"],
                "multiplier": spec.multiplier if spec else 1,
                "contract_name": spec.name if spec else None,
                "margin": spec.margin if spec else None,
                "days_to_expiry": dte,
                "book": get_book(p.ticker),
            })

        # Overlay signals from council
        try:
            from tradingagents.execution.db import get_all_latest_states
            sig_map = {s["ticker"]: s["council_signal"] for s in get_all_latest_states(config)}
            for pos in positions:
                pos["signal"] = sig_map.get(pos["ticker"], "---")
        except Exception:
            pass

        # Notional exposure
        exposure = safety.check_notional_exposure(account, positions_raw)

        # Allocation
        allocation = [{"asset": p["ticker"], "value": p["weight"]} for p in positions]
        cash_pct = round((acct_val - sum(pp.market_value for pp in positions_raw)) / acct_val * 100, 1)
        if cash_pct > 0:
            allocation.append({"asset": "Cash", "value": cash_pct})

        # Treemap data: flat list of {sector, ticker, weight, pct_return, market_value, asset_class}
        _SECTOR_LABELS = {
            "tech": "Technology", "financials": "Financial", "healthcare": "Healthcare",
            "consumer": "Consumer", "cyclical": "Industrials",
            "etf_bond": "Fixed Income", "etf_commodity": "Commodities", "future": "Futures",
        }
        treemap_data = []
        for p in positions:
            ac = p.get("asset_class", "stock")
            sec = p.get("sector")
            if ac in ("etf_bond", "etf_commodity", "future"):
                group = _SECTOR_LABELS.get(ac, "Other")
            elif sec:
                group = _SECTOR_LABELS.get(sec, sec.title())
            else:
                group = "Other"
            treemap_data.append({
                "group": group,
                "ticker": p["ticker"],
                "weight": p["weight"],
                "pct_return": p["pct_return"],
                "market_value": p["market_value"],
            })
        if cash_pct > 0:
            treemap_data.append({
                "group": "Cash",
                "ticker": "Cash",
                "weight": cash_pct,
                "pct_return": 0,
                "market_value": round(cash, 2),
            })

        # Book view (portfolio hierarchy)
        from tradingagents.execution.portfolio import compute_book_view
        books_data = compute_book_view(positions, pv, cash)

        return {
            "portfolio_value": pv,
            "cash": cash,
            "pnl": pnl,
            "pnl_pct": pnl_pct,
            "drawdown": dd,
            "dd_limit": dd_limit,
            "kill_switch": safety.kill_switch_active,
            "execution_mode": config.get("execution_mode", "paper"),
            "positions": positions,
            "allocation": allocation,
            "treemap": treemap_data,
            "exposure": exposure,
            "books": books_data["books"],
        }
    except Exception as e:
        print(f"[v3] account error: {e}")
        return {
            "portfolio_value": 0, "cash": 0, "pnl": 0, "pnl_pct": 0,
            "drawdown": 0, "dd_limit": 0.10, "kill_switch": False,
            "execution_mode": "paper", "positions": [], "allocation": [],
        }


def get_trades_data():
    """Recent trades, stats, equity curve, analytics."""
    try:
        config = _cfg()
        from tradingagents.execution.trade_data import (
            load_recent_trades,
            compute_trade_stats,
            compute_equity_curve,
            compute_signal_distribution,
        )
        starting = float(config.get("paper_starting_balance", 100_000))
        trades = load_recent_trades(config, limit=500)
        stats = compute_trade_stats(trades, starting)

        from tradingagents.execution.ticker_utils import detect_asset_type
        from tradingagents.execution.contracts import get_multiplier

        recent = []
        for t in trades[:100]:
            req = t.get("order_request") or {}
            res = t.get("order_result") or {}
            tkr = t.get("ticker", "")
            ai = detect_asset_type(tkr)
            mult = get_multiplier(tkr)
            fill = res.get("filled_price")
            qty = req.get("quantity", 0)
            recent.append({
                "time": t.get("timestamp", "")[:16],
                "ticker": tkr,
                "signal": t.get("signal", ""),
                "action": t.get("action_taken", ""),
                "side": (req.get("side") or "").upper(),
                "qty": qty,
                "fill": fill,
                "reason": t.get("reason", ""),
                "account_before": t.get("account_value_before"),
                "account_after": t.get("account_value_after"),
                "asset_class": ai["asset_class"],
                "sector": ai["sector"],
                "multiplier": mult,
                "notional": round(float(fill or 0) * int(qty or 0) * mult, 2),
            })

        eq = compute_equity_curve(trades, starting)
        equity = [{"time": str(p.get("time_str", p.get("time", ""))), "value": p["value"]} for p in eq]
        sig_dist = compute_signal_distribution(trades)

        analytics = {}
        try:
            import logging as _lg
            _lg.getLogger("yfinance").setLevel(_lg.ERROR)
            from tradingagents.execution.analytics import (
                compute_sharpe_ratio, compute_sortino_ratio,
                compute_max_drawdown_series, compute_alpha_vs_benchmark,
                compute_win_rate_by_ticker, compute_win_rate_by_signal,
                compute_profit_factor, compute_expectancy, compute_sqn,
            )
            from tradingagents.execution.trade_data import compute_pnl_by_ticker

            analytics["sharpe"] = round(compute_sharpe_ratio(trades, starting), 3)
            analytics["sortino"] = round(compute_sortino_ratio(trades, starting), 3)
            dd_series = compute_max_drawdown_series(trades, starting)
            analytics["max_dd"] = round(min((d["drawdown"] for d in dd_series), default=0) * 100, 1)
            alpha_data = compute_alpha_vs_benchmark(trades, starting)
            analytics["alpha"] = round(alpha_data.get("alpha", 0) * 100, 2)
            analytics["wr_ticker"] = [
                {"ticker": k, "wins": v["wins"], "losses": v["losses"], "wr": round(v["win_rate"] * 100)}
                for k, v in compute_win_rate_by_ticker(trades).items()
            ]
            analytics["wr_signal"] = [
                {"signal": k, "wins": v["wins"], "losses": v["losses"], "wr": round(v["win_rate"] * 100)}
                for k, v in compute_win_rate_by_signal(trades).items()
            ]
            analytics["pnl_ticker"] = [
                {"ticker": d["ticker"], "pnl": round(d["pnl"], 2), "trades": d["trades"]}
                for d in compute_pnl_by_ticker(trades)
            ]
            analytics["profit_factor"] = round(compute_profit_factor(trades), 2)
            analytics["expectancy"] = round(compute_expectancy(trades), 2)
            analytics["sqn"] = round(compute_sqn(trades), 2)
        except Exception:
            pass

        return {
            "total": stats["total_trades"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": round(stats["win_rate"], 3),
            "recent": recent,
            "equity": equity,
            "signal_dist": dict(sig_dist),
            "analytics": analytics,
        }
    except Exception as e:
        print(f"[v3] trades error: {e}")
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "recent": [], "equity": [], "signal_dist": {}, "analytics": {}}


def get_market_status():
    try:
        from tradingagents.execution.market_calendar import is_market_open, is_trading_day
        if is_market_open():
            return {"open": True, "text": "MKT OPEN"}
        elif is_trading_day():
            return {"open": False, "text": "MKT CLOSED"}
        else:
            return {"open": False, "text": "NON-TRADING DAY"}
    except Exception:
        return {"open": False, "text": "UNKNOWN"}


def get_regime():
    try:
        from tradingagents.dataflows.regime import CrossAssetRegimeDetector
        det = CrossAssetRegimeDetector()
        r = det.detect(date.today().isoformat())
        vix = r.get("vix")
        dxy = r.get("dxy")
        yld = r.get("yield_10y")
        return {
            "regime": r.get("regime", "unknown").upper(),
            "confidence": f"{r.get('regime_confidence', 0):.0%}",
            "vix": f"{vix:.1f}" if vix is not None else "N/A",
            "dxy": f"{dxy:.2f}" if dxy is not None else "N/A",
            "yield_10y": f"{yld:.2f}%" if yld is not None else "N/A",
        }
    except Exception as e:
        print(f"[v3] regime error: {e}")
        return {"regime": "UNKNOWN", "confidence": "0%", "vix": "N/A", "dxy": "N/A", "yield_10y": "N/A"}


def get_ticker_states():
    try:
        config = _cfg()
        from tradingagents.execution.db import get_all_latest_states
        from tradingagents.execution.ticker_utils import detect_asset_type
        results = []
        for s in get_all_latest_states(config):
            asset_info = detect_asset_type(s["ticker"])
            results.append({
                "ticker": s["ticker"],
                "technical": round(s["technical_score"], 1),
                "fundamental": round(s["fundamental_score"], 1),
                "sentiment": round(s["sentiment_score"], 1),
                "news": round(s["news_score"], 1),
                "signal": s["council_signal"],
                "confidence": round(s["confidence"], 2),
                "weighted": round(s["weighted_score"], 2),
                "price": round(s["price_at_analysis"], 2) if s.get("price_at_analysis") else 0,
                "regime": s.get("regime_at_analysis", ""),
                "analyzed_at": s["analyzed_at"][:16],
                "asset_class": asset_info["asset_class"],
                "sector": asset_info["sector"],
                "debate_triggered": bool(s.get("debate_triggered", 0)),
            })
        return results
    except Exception as e:
        print(f"[v3] ticker states error: {e}")
        return []


def get_ticker_detail(ticker):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_ticker_state
        from tradingagents.execution.ticker_utils import detect_asset_type
        asset_info = detect_asset_type(ticker)
        history = get_ticker_state(config, ticker, limit=4)
        rows = [
            {
                "technical": round(h["technical_score"], 1),
                "fundamental": round(h["fundamental_score"], 1),
                "sentiment": round(h["sentiment_score"], 1),
                "news": round(h["news_score"], 1),
                "signal": h["council_signal"],
                "confidence": round(h["confidence"], 2),
                "weighted": round(h["weighted_score"], 2),
                "price": round(h["price_at_analysis"], 2) if h.get("price_at_analysis") else 0,
                "analyzed_at": h["analyzed_at"][:16],
                "asset_class": asset_info["asset_class"],
                "sector": asset_info["sector"],
                "debate_triggered": bool(h.get("debate_triggered", 0)),
            }
            for h in history
        ]
        # Fetch latest quant scores if available
        quant = {}
        try:
            conn = get_db(config)
            qrow = conn.execute(
                "SELECT * FROM quant_scores WHERE ticker = ? ORDER BY scored_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if qrow:
                quant = {
                    "fundamental": round(qrow["fundamental_score"], 2),
                    "technical": round(qrow["technical_score"], 2),
                    "data_quality": round(qrow["data_quality"], 2),
                    "scored_at": qrow["scored_at"][:16],
                }
        except Exception:
            pass

        return {"detail": rows[0] if rows else {}, "history": rows, "quant": quant}
    except Exception as e:
        print(f"[v3] ticker detail error: {e}")
        return {"detail": {}, "history": [], "quant": {}}


def get_analyst_reports(ticker):
    """Get persisted analyst reports from council cycles."""
    try:
        config = _cfg()
        from tradingagents.execution.db import get_council_analyst_reports
        return get_council_analyst_reports(config, ticker, limit=3)
    except Exception as e:
        print(f"[v3] analyst reports error: {e}")
        return []


def get_trade_reports_for_ticker(ticker):
    """Get pre-trade reports with analyst summaries for a ticker."""
    try:
        config = _cfg()
        conn = get_db(config)
        rows = conn.execute(
            """SELECT trade_date, report_type, signal, confidence,
                      technicals, fundamentals, sentiment, news_catalyst,
                      risk_factors, reasoning
               FROM trade_reports
               WHERE ticker = ? AND report_type = 'pre'
               ORDER BY created_at DESC LIMIT 5""",
            (ticker.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]
    except Exception as e:
        print(f"[v3] trade reports error: {e}")
        return []


def get_plan_steps_for_ticker(ticker):
    """Get active plan steps for a specific ticker."""
    try:
        from pathlib import Path
        import yaml
        plan_path = Path.home() / ".tradingagents" / "plans" / "active.md"
        if not plan_path.exists():
            return None
        text = plan_path.resolve().read_text()
        if not text.startswith("---"):
            return None
        yaml_end = text.index("---", 3)
        fm = yaml.safe_load(text[3:yaml_end])
        if not fm or "steps" not in fm:
            return None
        ticker_upper = ticker.upper()
        plan_info = {
            "plan_id": fm.get("plan_id", ""),
            "created_at": fm.get("created_at", ""),
            "regime": fm.get("regime", ""),
            "risk_level": fm.get("risk_level", ""),
            "expired": False,
        }
        # Check if plan is expired
        from datetime import date
        for step in fm.get("steps", []):
            expiry = step.get("expiry", "")
            if expiry and expiry < date.today().isoformat():
                plan_info["expired"] = True
                break
        # Find steps for this ticker
        steps = [s for s in fm.get("steps", []) if s.get("ticker", "").upper() == ticker_upper]
        if not steps:
            return None
        plan_info["steps"] = steps
        return plan_info
    except Exception as e:
        print(f"[v3] plan steps error: {e}")
        return None


def get_ticker_reflections(ticker):
    """Get trade reflections for a ticker, parsed into sections."""
    try:
        config = _cfg()
        from tradingagents.execution.learning import LearningEngine
        from tradingagents.execution.reflection import ReflectionEngine
        learner = LearningEngine(config)
        reflector = ReflectionEngine(learner, config)
        raw = reflector.get_reflections(ticker, include_sector=True, limit=5)
        if not raw:
            return None
        # Parse into sections
        sections = {}
        current_section = None
        current_lines = []
        for line in raw.strip().split("\n"):
            stripped = line.strip()
            if stripped.startswith("## "):
                if current_section:
                    sections[current_section] = "\n".join(current_lines).strip()
                current_section = stripped[3:].strip()
                current_lines = []
            elif stripped.startswith("# "):
                continue  # skip the title line
            else:
                current_lines.append(stripped)
        if current_section:
            sections[current_section] = "\n".join(current_lines).strip()
        return sections if sections else {"Raw": raw}
    except Exception as e:
        print(f"[v3] reflections error: {e}")
        return ""


def get_trade_reports(limit=30):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        from tradingagents.execution.ticker_utils import detect_asset_type
        conn = get_db(config)
        rows = conn.execute(
            "SELECT * FROM trade_reports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        results = []
        for r in rows:
            ai = detect_asset_type(r["ticker"])
            results.append({
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
                "asset_class": ai["asset_class"],
                "sector": ai["sector"],
            })
        return results
    except Exception as e:
        print(f"[v3] trade reports error: {e}")
        return []


def get_insider_clusters(positions, watchlist):
    try:
        from tradingagents.dataflows.insider_clustering import InsiderClusterDetector
        detector = InsiderClusterDetector(min_insiders=2)
        clusters = []
        seen = set()
        tickers = [p["ticker"] for p in positions] + watchlist[:10]
        for ticker in tickers:
            if ticker in seen:
                continue
            seen.add(ticker)
            try:
                r = detector.detect_clusters(ticker)
                if r.get("cluster_detected"):
                    clusters.append({
                        "ticker": ticker,
                        "direction": r.get("direction", ""),
                        "insider_count": r.get("insider_count", 0),
                        "window": f"{r.get('window_start', '')[:10]} — {r.get('window_end', '')[:10]}",
                    })
            except Exception:
                continue
        return clusters
    except Exception:
        return []


def get_plan_metrics_data():
    """Get plan adherence metrics with step-level detail for dashboard."""
    try:
        from tradingagents.execution.plan import get_plan_metrics, read_active_plan
        plan = read_active_plan()
        if plan is None:
            return {"active": False}
        metrics = get_plan_metrics(plan.get("plan_id"))
        metrics["active"] = True
        metrics["plan_type"] = plan.get("plan_type", "")
        metrics["regime"] = plan.get("regime", "")
        metrics["risk_level"] = plan.get("risk_level", "")
        metrics["created_at"] = plan.get("created_at", "")

        # Enrich with step-level detail
        steps = plan.get("steps", [])
        exec_log = _load_exec_log(plan.get("plan_id", ""))

        enriched_steps = []
        for s in steps:
            ticker = str(s.get("ticker", ""))
            action = str(s.get("action", "Hold"))
            entry = s.get("entry")
            log_entry = exec_log.get(ticker)
            enriched_steps.append({
                "ticker": ticker,
                "action": action,
                "entry": entry,
                "exec_status": log_entry["status"] if log_entry else "PENDING",
                "fill_price": log_entry.get("fill_price") if log_entry else None,
                "slippage_bps": log_entry.get("slippage_bps") if log_entry else None,
            })
        metrics["steps"] = enriched_steps
        return metrics
    except Exception:
        return {"active": False}


def get_plan_status_data():
    """Get active plan status for the trading page plan bar."""
    try:
        from tradingagents.execution.plan import read_active_plan, get_plan_metrics
        plan = read_active_plan()
        if plan is None:
            return {"active": False}

        steps = plan.get("steps", [])
        exec_log = _load_exec_log(plan.get("plan_id", ""))

        buy_actions = {"buy", "strong buy"}
        sell_actions = {"sell", "strong sell"}

        enriched_steps = []
        for s in steps:
            ticker = str(s.get("ticker", ""))
            action = str(s.get("action", "Hold"))
            entry = s.get("entry")
            log_entry = exec_log.get(ticker)
            enriched_steps.append({
                "ticker": ticker,
                "action": action,
                "entry": entry,
                "exec_status": log_entry["status"] if log_entry else "PENDING",
            })

        metrics = get_plan_metrics(plan.get("plan_id"))

        return {
            "active": True,
            "plan_id": plan.get("plan_id", ""),
            "plan_type": plan.get("plan_type", ""),
            "regime": plan.get("regime", ""),
            "risk_level": plan.get("risk_level", ""),
            "created_at": plan.get("created_at", ""),
            "steps": enriched_steps,
            "buy_count": sum(1 for s in steps if str(s.get("action", "")).lower() in buy_actions),
            "sell_count": sum(1 for s in steps if str(s.get("action", "")).lower() in sell_actions),
            "hold_count": sum(1 for s in steps if str(s.get("action", "")).lower() == "hold"),
            "adherence_rate": metrics.get("adherence_rate"),
        }
    except Exception:
        return {"active": False}


def _load_exec_log(plan_id: str) -> dict:
    """Load execution log entries keyed by ticker."""
    if not plan_id:
        return {}
    try:
        from pathlib import Path
        import os
        plans_dir = Path(os.environ.get("TRADINGAGENTS_HOME", Path.home() / ".tradingagents")) / "plans"
        log_path = plans_dir / f"{plan_id}.execlog.json"
        if not log_path.exists():
            return {}
        entries = json.loads(log_path.read_text())
        # Key by ticker (last entry wins if multiple)
        return {e["ticker"]: e for e in entries}
    except Exception:
        return {}


def get_trading_status_data():
    """Merged status strip: regime + plan + live risk in one call."""
    acct = get_account_data()
    return {
        "regime": get_regime(),
        "plan": get_plan_status_data(),
        "live_risk": get_live_risk_data(),
        "kill_switch": acct.get("kill_switch", False),
        "execution_mode": acct.get("execution_mode", "paper"),
        "exposure": acct.get("exposure"),
        "risk_level": get_live_risk_data().get("risk_level", "unknown"),
    }


def run_calibration():
    """Run conviction calibration and return formatted report."""
    try:
        from tradingagents.backtest.calibrate_conviction import calibrate, format_report
        result = calibrate(days=180)
        return format_report(result)
    except Exception as e:
        return f"Calibration error: {e}"


def get_congress_recent(positions, watchlist, days=30):
    """Get recent congressional trades for held + watchlist tickers."""
    try:
        from tradingagents.dataflows.congress import _load_cache
        from datetime import datetime, timedelta
        cache = _load_cache()
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        tickers = set(p["ticker"] for p in positions) | set(watchlist[:10])
        trades = [
            t for t in cache.get("trades", [])
            if t["ticker"] in tickers and t["date"] >= cutoff
        ]
        trades.sort(key=lambda t: t["date"], reverse=True)
        return trades[:20]
    except Exception:
        return []


def get_sector_rotation():
    try:
        from tradingagents.dataflows.sector_rotation import SectorRotationModel
        model = SectorRotationModel()
        r = model.analyze(date.today().isoformat())
        if "error" in r:
            return {"sectors": [], "direction": "neutral"}
        sectors = [
            {"name": s["name"], "etf": s["etf"],
             "return_1m": round(s["return_1m"] or 0, 1),
             "relative_1m": round(s["relative_1m"] or 0, 1)}
            for s in r.get("sectors", [])
        ]
        direction = r.get("rotation_direction", "neutral").replace("_", " ").title()
        return {"sectors": sectors, "direction": direction}
    except Exception:
        return {"sectors": [], "direction": "neutral"}


def get_kalshi_positions():
    """Get open Kalshi prediction market positions."""
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT * FROM kalshi_positions WHERE status = 'open' ORDER BY created_at DESC"
        ).fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "ticker": r["ticker"],
                "title": r["title"],
                "side": r["side"],
                "contracts": r["contracts"],
                "entry_price": r["entry_price"],
                "cost": r["cost"],
                "reasoning": r["reasoning"],
                "created_at": r["created_at"],
            })
        return results
    except Exception:
        return []


def get_live_risk_data():
    """Get live intraday risk status for the trading dashboard."""
    try:
        config = _cfg()
        from tradingagents.execution.safety import compute_live_risk
        return compute_live_risk(config)
    except Exception as exc:
        print(f"[v3] live risk error: {exc}")
        return {
            "risk_level": "unknown",
            "daily_pnl": 0, "daily_pnl_pct": 0,
            "intraday_drawdown": 0,
            "cash_reserve_pct": 0,
            "vix": 0,
            "consecutive_losses": 0,
            "position_stops": [],
            "stops_breached": [],
        }


def get_historical_data(date_str):
    if not date_str:
        return {}
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        d = date_str

        from tradingagents.execution.ticker_utils import detect_asset_type

        trade_rows = conn.execute(
            "SELECT * FROM trades WHERE substr(timestamp, 1, 10) = ? ORDER BY timestamp", (d,)
        ).fetchall()
        trades = []
        for r in trade_rows:
            ai = detect_asset_type(r["ticker"])
            trades.append({
                "time": r["timestamp"][:16], "ticker": r["ticker"],
                "signal": r["signal"], "action": r["action_taken"],
                "side": (r["side"] or "").upper(), "qty": r["quantity"],
                "fill": r["fill_price"], "reason": r["reason"] or "",
                "asset_class": ai["asset_class"], "sector": ai["sector"],
            })

        executed = [r for r in trade_rows if r["action_taken"] == "executed"]
        if executed and executed[0]["account_before"] and executed[-1]["account_after"]:
            hist_pnl = round(executed[-1]["account_after"] - executed[0]["account_before"], 2)
        else:
            hist_pnl = 0.0

        state_rows = conn.execute(
            "SELECT * FROM ticker_state WHERE substr(analyzed_at, 1, 10) = ? ORDER BY analyzed_at DESC", (d,)
        ).fetchall()
        states = []
        for s in state_rows:
            ai = detect_asset_type(s["ticker"])
            states.append({
                "ticker": s["ticker"],
                "technical": round(s["technical_score"], 1),
                "fundamental": round(s["fundamental_score"], 1),
                "sentiment": round(s["sentiment_score"], 1),
                "news": round(s["news_score"], 1),
                "signal": s["council_signal"],
                "weighted": round(s["weighted_score"], 2),
                "price": round(s["price_at_analysis"], 2) if s["price_at_analysis"] else 0,
                "analyzed_at": s["analyzed_at"][:16],
                "asset_class": ai["asset_class"],
                "sector": ai["sector"],
            })

        return {"trades": trades, "pnl": hist_pnl, "states": states}
    except Exception:
        return {"trades": [], "pnl": 0, "states": []}


def get_watchlist():
    try:
        config = _cfg()
        from tradingagents.execution.trade_data import load_watchlist
        saved = load_watchlist(config)
        return saved.get("tickers", [])
    except Exception:
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  JSON API (consumed by Electron desktop app)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

api_bp = Blueprint("api_json", __name__)


@api_bp.after_request
def api_cors(response):
    """Allow cross-origin requests from Electron/Vite dev server."""
    response.headers["Access-Control-Allow-Origin"] = "*"
    response.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    response.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return response


@api_bp.route("/api/v1/health")
def api_v1_health():
    """Lightweight health check — instant response, no data fetching."""
    return jsonify({"ok": True})


@api_bp.route("/api/v1/chart/<ticker>")
def api_v1_chart(ticker):
    """OHLCV price data for candlestick chart."""
    days = int(request.args.get("days", 90))
    try:
        from datetime import date, timedelta
        end = date.today().isoformat()
        start = (date.today() - timedelta(days=days)).isoformat()
        from tradingagents.dataflows.y_finance import get_YFin_data_online
        raw = get_YFin_data_online(ticker.upper(), start, end)
        candles = []
        for line in raw.strip().split("\n"):
            if not line or line.startswith("#") or not line[0].isdigit():
                continue
            parts = line.split(",")
            if len(parts) >= 6:
                candles.append({
                    "time": parts[0],
                    "open": round(float(parts[1]), 2),
                    "high": round(float(parts[2]), 2),
                    "low": round(float(parts[3]), 2),
                    "close": round(float(parts[4]), 2),
                    "volume": int(float(parts[5])),
                })
        return jsonify({"ticker": ticker.upper(), "candles": candles})
    except Exception as e:
        return jsonify({"ticker": ticker.upper(), "candles": [], "error": str(e)})


@api_bp.route("/api/v1/trades/<ticker>")
def api_v1_ticker_trades(ticker):
    """Get executed trades for a specific ticker (for chart markers)."""
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT timestamp, side, quantity, fill_price FROM trades "
            "WHERE ticker = ? AND action_taken = 'executed' ORDER BY timestamp",
            (ticker.upper(),),
        ).fetchall()
        trades = [
            {"time": r["timestamp"][:10], "side": r["side"], "qty": r["quantity"], "price": r["fill_price"]}
            for r in rows if r["fill_price"]
        ]
        return jsonify({"trades": trades})
    except Exception:
        return jsonify({"trades": []})


@api_bp.route("/api/v1/dashboard")
def api_v1_dashboard():
    """Aggregated dashboard data — single endpoint for 30s polling."""
    acct = get_account_data()
    trades = get_trades_data()
    regime = get_regime()
    market = get_market_status()
    states = get_ticker_states()
    status = get_trading_status_data()
    return jsonify({
        "account": acct,
        "trades": trades,
        "regime": regime,
        "market": market,
        "states": states,
        "status": status,
    })


@api_bp.route("/api/v1/council/<ticker>")
def api_v1_council_detail(ticker):
    """Full council detail for a ticker (on-demand)."""
    detail = get_ticker_detail(ticker)
    reflections = get_ticker_reflections(ticker)
    analyst_reports = get_analyst_reports(ticker)
    trade_reports = get_trade_reports_for_ticker(ticker)
    plan = get_plan_steps_for_ticker(ticker)
    return jsonify({
        "ticker": ticker,
        "detail": detail,
        "reflections": reflections,
        "analyst_reports": analyst_reports,
        "trade_reports": trade_reports,
        "plan": plan,
    })


@api_bp.route("/api/v1/scans/sectors")
def api_v1_sectors():
    return jsonify(get_sector_rotation())


@api_bp.route("/api/v1/scans/insiders")
def api_v1_insiders():
    acct = get_account_data()
    watchlist = get_watchlist()
    clusters = get_insider_clusters(acct["positions"], watchlist)
    return jsonify({"clusters": clusters})


@api_bp.route("/api/v1/scans/congress")
def api_v1_congress():
    acct = get_account_data()
    watchlist = get_watchlist()
    trades = get_congress_recent(acct["positions"], watchlist)
    return jsonify({"trades": trades})


@api_bp.route("/api/v1/plan")
def api_v1_plan():
    return jsonify(get_plan_metrics_data())


@api_bp.route("/api/v1/calibration")
def api_v1_calibration():
    return jsonify({"report": run_calibration()})


@api_bp.route("/api/v1/historical")
def api_v1_historical():
    date_str = request.args.get("date", "")
    if not date_str:
        return jsonify({"error": "date param required"}), 400
    return jsonify(get_historical_data(date_str))


@api_bp.route("/api/v1/reports")
def api_v1_reports():
    """All trade reports (pre + post trade analysis)."""
    return jsonify({"reports": get_trade_reports(limit=100)})


@api_bp.route("/api/v1/reports/<int:report_id>")
def api_v1_report(report_id):
    reports = get_trade_reports(limit=100)
    report = next((r for r in reports if r["id"] == report_id), None)
    if not report:
        return jsonify({"error": "not found"}), 404
    return jsonify(report)


@api_bp.route("/api/v1/kill-switch", methods=["POST"])
def api_v1_kill_switch():
    config = _cfg()
    from tradingagents.execution.safety import SafetyMonitor
    safety = SafetyMonitor(config)
    if safety.kill_switch_active:
        safety.reset_kill_switch()
    else:
        safety.kill_switch_active = True
        safety._save_state()
    return jsonify({"active": safety.kill_switch_active})


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  FLASK APP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_app():
    """Create Flask app with JSON API only (Electron desktop app is the UI)."""
    app = Flask(__name__)
    app.register_blueprint(api_bp)
    return app
