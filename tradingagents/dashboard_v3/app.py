"""Flask dashboard v3 — light-mode Tailwind trading dashboard.

All data-fetching is ported from the Reflex v2 state.py into plain
functions.  Templates use Jinja2 + Tailwind CDN + Chart.js + htmx.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify

# ── Make tradingagents importable ──────────────────────────────────────
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tradingagents.execution.db import get_db


def _cfg():
    from tradingagents.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.copy()


def _md_to_html(content: str) -> str:
    if not content or not content.strip():
        return ""
    text = content.strip()
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) >= 3:
            text = parts[2].strip()
    if not text:
        return ""
    try:
        import markdown
        return markdown.markdown(text, extensions=["tables", "fenced_code"])
    except ImportError:
        return f"<pre>{text}</pre>"


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

        from tradingagents.execution.ticker_utils import detect_asset_type
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
#  FLASK APP
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def create_app():
    app = Flask(__name__, template_folder="templates")

    # ── Jinja helpers ──

    @app.template_filter("usd")
    def usd_filter(v):
        if v is None:
            return "---"
        return f"${v:,.2f}"

    @app.template_filter("pct")
    def pct_filter(v):
        if v is None:
            return "---"
        return f"{v:.3%}"

    @app.template_filter("signed_usd")
    def signed_usd_filter(v):
        if v is None:
            return "---"
        sign = "+" if v >= 0 else ""
        return f"{sign}${v:,.2f}"

    @app.template_filter("signed_pct")
    def signed_pct_filter(v):
        if v is None:
            return "---"
        return f"{v:+.1f}%"

    @app.template_filter("domain_label")
    def domain_label_filter(item):
        """Derive the domain analyst label from asset_class/sector."""
        ac = item.get("asset_class", "stock") if isinstance(item, dict) else "stock"
        sec = item.get("sector", "") if isinstance(item, dict) else ""
        return _domain_label(ac, sec)

    @app.template_filter("domain_abbr")
    def domain_abbr_filter(item):
        """Short abbreviation for domain analyst (for mini score displays)."""
        ac = item.get("asset_class", "stock") if isinstance(item, dict) else "stock"
        sec = item.get("sector", "") if isinstance(item, dict) else ""
        labels = {
            "etf_bond": "Bnd", "etf_commodity": "Cmd",
        }
        sector_labels = {
            "tech": "Tch", "financials": "Fin", "healthcare": "HC",
            "consumer": "Con", "cyclical": "Cyc",
        }
        return labels.get(ac) or sector_labels.get(sec or "") or "F"

    @app.template_filter("qty_label")
    def qty_label_filter(asset_class):
        """Return 'contracts' for futures, 'shares' for everything else."""
        return "contracts" if asset_class == "future" else "shares"

    @app.template_filter("usd_int")
    def usd_int_filter(v):
        """Format as $1,234 (no decimals)."""
        if v is None:
            return "---"
        return f"${v:,.0f}"

    def _domain_label(asset_class, sector):
        labels = {
            "etf_bond": "Bond", "etf_commodity": "Commodity",
        }
        sector_labels = {
            "tech": "Tech", "financials": "Financials", "healthcare": "Healthcare",
            "consumer": "Consumer", "cyclical": "Cyclical",
        }
        return labels.get(asset_class) or sector_labels.get(sector or "") or "Fund"

    @app.context_processor
    def inject_globals():
        """Minimal globals for API partials (kill switch toggle)."""
        try:
            from tradingagents.execution.safety import SafetyMonitor
            ks = SafetyMonitor(_cfg()).kill_switch_active
        except Exception:
            ks = False
        return {"kill_switch": ks}

    # ── Single page route ──

    @app.route("/")
    def index():
        hist_date = request.args.get("date")
        acct = get_account_data()
        trades = get_trades_data()
        regime = get_regime()
        market = get_market_status()
        states = get_ticker_states()
        predictions = get_kalshi_positions()
        historical = get_historical_data(hist_date) if hist_date else None
        status = get_trading_status_data() if not hist_date else None
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return render_template("index.html",
                               acct=acct, trades=trades,
                               regime=regime, market=market,
                               states=states,
                               predictions=predictions,
                               hist_date=hist_date, historical=historical,
                               status=status,
                               now=now)

    # ── API / htmx partials ──

    @app.route("/api/scan-sectors")
    def api_scan_sectors():
        sectors = get_sector_rotation()
        return render_template("_sectors.html", sectors=sectors)

    @app.route("/api/scan-insiders")
    def api_scan_insiders():
        acct = get_account_data()
        watchlist = get_watchlist()
        clusters = get_insider_clusters(acct["positions"], watchlist)
        return render_template("_insiders.html", clusters=clusters)

    @app.route("/api/scan-congress")
    def api_scan_congress():
        acct = get_account_data()
        watchlist = get_watchlist()
        trades = get_congress_recent(acct["positions"], watchlist)
        return render_template("_congress.html", congress_trades=trades)

    @app.route("/api/council-detail")
    def api_council_detail():
        ticker = request.args.get("ticker", "")
        if not ticker:
            return "<p class='text-gray-400 text-sm'>No ticker specified</p>"
        detail = get_ticker_detail(ticker)
        reflections = get_ticker_reflections(ticker)
        analyst_reports = get_analyst_reports(ticker)
        trade_reports = get_trade_reports_for_ticker(ticker)
        plan = get_plan_steps_for_ticker(ticker)
        return render_template("_council_detail.html",
                               ticker=ticker, detail=detail, reflections=reflections,
                               analyst_reports=analyst_reports, trade_reports=trade_reports,
                               plan=plan)

    @app.route("/api/plan-metrics")
    def api_plan_metrics():
        metrics = get_plan_metrics_data()
        return render_template("_plan_metrics.html", plan=metrics)

    @app.route("/api/trading-kpis")
    def api_trading_kpis():
        acct = get_account_data()
        trades = get_trades_data()
        return render_template("_trading_kpis.html", acct=acct, trades=trades)

    @app.route("/api/trading-risk")
    def api_trading_risk():
        live_risk = get_live_risk_data()
        return render_template("_trading_risk.html", live_risk=live_risk)

    @app.route("/api/trading-positions")
    def api_trading_positions():
        acct = get_account_data()
        return render_template("_trading_positions.html", acct=acct)

    @app.route("/api/trading-status")
    def api_trading_status():
        status = get_trading_status_data()
        return render_template("_trading_status.html", status=status)

    @app.route("/api/kill-switch", methods=["POST"])
    def api_kill_switch_toggle():
        config = _cfg()
        from tradingagents.execution.safety import SafetyMonitor
        safety = SafetyMonitor(config)
        if safety.kill_switch_active:
            safety.reset_kill_switch()
        else:
            safety.kill_switch_active = True
            safety._save_state()
        active = safety.kill_switch_active
        return render_template("_kill_switch_btn.html", kill_switch=active)

    @app.route("/api/run-calibration")
    def api_run_calibration():
        report = run_calibration()
        return f"<pre class='text-xs font-mono text-gray-700 whitespace-pre-wrap'>{report}</pre>"

    @app.route("/api/report/<int:report_id>")
    def api_report_detail(report_id):
        reports = get_trade_reports(limit=100)
        report = next((r for r in reports if r["id"] == report_id), None)
        if not report:
            return "<p class='text-gray-400 text-sm'>Report not found</p>"
        return render_template("_report_detail.html", r=report)

    @app.route("/api/trade-detail")
    def api_trade_detail():
        ticker = request.args.get("ticker", "")
        time = request.args.get("time", "")
        try:
            config = _cfg()
            from tradingagents.execution.trade_data import load_recent_trades
            all_trades = load_recent_trades(config, limit=500)
            for t in all_trades:
                ts = t.get("timestamp", "")[:16]
                if ts == time and t.get("ticker") == ticker:
                    req = t.get("order_request") or {}
                    res = t.get("order_result") or {}
                    return render_template("_trade_detail.html", t={
                        "ticker": ticker, "time": time,
                        "signal": t.get("signal", ""), "action": t.get("action_taken", ""),
                        "side": (req.get("side") or "").upper(),
                        "qty": req.get("quantity", ""),
                        "fill": res.get("filled_price"),
                        "before": t.get("account_value_before"),
                        "after": t.get("account_value_after"),
                        "reason": t.get("reason", "---"),
                    })
        except Exception:
            pass
        return "<p class='text-gray-400 text-sm'>Trade not found</p>"

    return app
