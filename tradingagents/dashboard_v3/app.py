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


def get_ticker_reflections(ticker):
    """Get trade reflections for a ticker (past outcome lessons)."""
    try:
        config = _cfg()
        from tradingagents.execution.learning import LearningEngine
        from tradingagents.execution.reflection import ReflectionEngine
        learner = LearningEngine(config)
        reflector = ReflectionEngine(learner, config)
        return reflector.get_reflections(ticker, include_sector=True, limit=5)
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


def get_activity_feed(recent_trades):
    feed = []
    for t in recent_trades[:5]:
        side = t.get("side", "")
        qty = t.get("qty", "")
        ticker = t.get("ticker", "")
        fill = t.get("fill")
        signal = t.get("signal", "")
        time_str = t.get("time", "")[:5]
        if side and fill:
            summary = f"{side} {qty} {ticker} @ ${fill:.2f}"
        else:
            summary = f"{signal} {ticker}"
        feed.append({"summary": summary, "time": time_str, "action": t.get("action", ""), "signal": signal})
    return feed


def get_cache_stats():
    try:
        from tradingagents.dataflows.cache import cache_stats
        s = cache_stats()
        per_func = [
            {
                "function": fn,
                "hits": fd.get("hits", 0),
                "misses": fd.get("misses", 0),
                "hit_rate": round(fd.get("hits", 0) / max(fd.get("hits", 0) + fd.get("misses", 0), 1) * 100),
            }
            for fn, fd in s.get("per_function", {}).items()
        ]
        return {"total": s.get("total_entries", 0), "active": s.get("active", 0),
                "expired": s.get("expired", 0), "per_function": per_func}
    except Exception:
        return {"total": 0, "active": 0, "expired": 0, "per_function": []}


def get_cycle_timeline():
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT ticker, council_signal, weighted_score, price_at_analysis, "
            "regime_at_analysis, analyzed_at "
            "FROM ticker_state ORDER BY analyzed_at DESC LIMIT 200"
        ).fetchall()

        cycles = {}
        for r in rows:
            key = r["analyzed_at"][:16]
            cycles.setdefault(key, []).append({
                "ticker": r["ticker"], "signal": r["council_signal"],
                "score": round(r["weighted_score"], 2),
            })

        return [
            {
                "time": k,
                "count": len(v),
                "tickers": ", ".join(t["ticker"] for t in v[:6]),
                "signals": ", ".join(f"{t['ticker']}={t['signal']}" for t in v[:4]),
                "buys": sum(1 for t in v if t["signal"] in ("Buy", "Overweight")),
                "sells": sum(1 for t in v if t["signal"] in ("Sell", "Underweight")),
                "holds": sum(1 for t in v if t["signal"] == "Hold"),
            }
            for k, v in list(cycles.items())[:20]
        ]
    except Exception:
        return []


def get_ticker_deltas():
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT ticker, technical_score, fundamental_score, sentiment_score, "
            "news_score, weighted_score, council_signal, price_at_analysis, analyzed_at "
            "FROM ticker_state ORDER BY analyzed_at DESC LIMIT 200"
        ).fetchall()

        by_ticker = {}
        for r in rows:
            tkr = r["ticker"]
            by_ticker.setdefault(tkr, [])
            if len(by_ticker[tkr]) < 2:
                by_ticker[tkr].append(dict(r))

        result = []
        for tkr, analyses in by_ticker.items():
            curr = analyses[0]
            if len(analyses) > 1:
                prev = analyses[1]
                score_delta = round(curr["weighted_score"] - prev["weighted_score"], 2)
                pn, pp = curr["price_at_analysis"] or 0, prev["price_at_analysis"] or 0
                price_delta = round((pn - pp) / max(pp, 0.01) * 100, 1) if pp else 0
                signal_changed = curr["council_signal"] != prev["council_signal"]
            else:
                score_delta = price_delta = 0.0
                signal_changed = False
            result.append({
                "ticker": tkr, "signal": curr["council_signal"],
                "score": round(curr["weighted_score"], 2),
                "score_delta": score_delta, "price_delta": price_delta,
                "signal_changed": signal_changed,
                "last_analyzed": curr["analyzed_at"][:16],
            })
        return result
    except Exception:
        return []


def get_slippage_data():
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT t.timestamp, t.ticker, t.side, t.quantity, t.fill_price, "
            "ts.price_at_analysis "
            "FROM trades t "
            "LEFT JOIN ticker_state ts ON t.ticker = ts.ticker "
            "AND ts.analyzed_at = ("
            "  SELECT MAX(ts2.analyzed_at) FROM ticker_state ts2 "
            "  WHERE ts2.ticker = t.ticker AND ts2.analyzed_at <= t.timestamp"
            ") "
            "WHERE t.fill_price IS NOT NULL AND t.fill_price > 0 "
            "AND t.action_taken = 'executed' "
            "ORDER BY t.timestamp DESC LIMIT 50"
        ).fetchall()

        total_slip = total_bps = 0.0
        count = 0
        data = []
        for r in rows:
            fill = r["fill_price"]
            ap = r["price_at_analysis"]
            if ap and ap > 0:
                slip_ps = abs(fill - ap)
                slip_pct = slip_ps / ap * 100
                slip_bps = slip_pct * 100
                qty = r["quantity"] or 0
                slip_total = slip_ps * qty
                total_slip += slip_total
                total_bps += slip_bps
                count += 1
                data.append({
                    "time": r["timestamp"][:16], "ticker": r["ticker"],
                    "side": (r["side"] or "").upper(), "qty": qty,
                    "analysis_price": ap, "fill_price": fill,
                    "slippage": round(slip_total, 2), "slippage_bps": round(slip_bps),
                })
        return {
            "data": data,
            "total_cost": round(total_slip, 2),
            "avg_bps": round(total_bps / max(count, 1)) if count else 0,
        }
    except Exception:
        return {"data": [], "total_cost": 0, "avg_bps": 0}


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


def get_kalshi_calibration():
    """Get Brier/Log scores for resolved Kalshi positions."""
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        from tradingagents.execution.analytics import compute_brier_score, compute_log_score
        conn = get_db(config)
        rows = conn.execute(
            "SELECT * FROM kalshi_positions WHERE status = 'settled' ORDER BY settled_at DESC"
        ).fetchall()
        if not rows:
            return None
        positions = [dict(r) for r in rows]
        brier = compute_brier_score(positions)
        log_score = compute_log_score(positions)
        return {
            "total_resolved": len(positions),
            "wins": sum(1 for p in positions if p.get("result") == "win"),
            "losses": sum(1 for p in positions if p.get("result") == "loss"),
            "brier_score": round(brier, 4) if brier is not None else None,
            "log_score": round(log_score, 4) if log_score is not None else None,
            "positions": positions[:10],
        }
    except Exception:
        return None


def get_kalshi_trending_events():
    """Get trending Kalshi events with volume."""
    try:
        from tradingagents.dataflows.kalshi import get_events
        events = get_events(limit=30, with_nested_markets=True)
        results = []
        for e in events:
            total_vol = sum(m.volume for m in e.markets)
            if total_vol < 10:
                continue
            top_markets = sorted(e.markets, key=lambda m: -m.volume)[:5]
            results.append({
                "event_ticker": e.event_ticker,
                "title": e.title,
                "sub_title": e.sub_title,
                "category": e.category,
                "total_volume": total_vol,
                "markets": [
                    {
                        "ticker": m.ticker,
                        "title": m.title[:80],
                        "yes_bid": m.yes_bid,
                        "yes_ask": m.yes_ask,
                        "last_price": m.last_price,
                        "implied_prob": m.implied_probability,
                        "volume": m.volume,
                        "time_to_close": m.time_to_close,
                    }
                    for m in top_markets
                ],
            })
        results.sort(key=lambda e: -e["total_volume"])
        return results[:15]
    except Exception as exc:
        print(f"[v3] kalshi events error: {exc}")
        return []


def get_event_calendar():
    """Get Kalshi events grouped by resolution timeframe for the calendar view."""
    try:
        from tradingagents.dataflows.kalshi import get_events
        from datetime import datetime, timezone
        events = get_events(limit=30, with_nested_markets=True)
        now = datetime.now(timezone.utc)
        buckets = {"this_week": [], "this_month": [], "this_quarter": [], "this_year": [], "long_dated": []}
        for e in events:
            if not e.markets:
                continue
            # Use earliest close_time from nested markets
            close_times = []
            for m in e.markets:
                try:
                    ct = datetime.fromisoformat(m.close_time.replace("Z", "+00:00"))
                    close_times.append(ct)
                except Exception:
                    pass
            if not close_times:
                continue
            earliest = min(close_times)
            delta = earliest - now
            days = delta.days
            if days < 0:
                continue  # already closed
            total_vol = sum(m.volume for m in e.markets)
            if total_vol < 10:
                continue
            # Top market by volume for display
            top_market = max(e.markets, key=lambda m: m.volume)
            entry = {
                "event_ticker": e.event_ticker,
                "title": e.title,
                "sub_title": e.sub_title,
                "category": e.category,
                "num_markets": len(e.markets),
                "total_volume": total_vol,
                "close_date": earliest.strftime("%b %d, %Y"),
                "days_until": days,
                "can_close_early": any(m.can_close_early for m in e.markets),
                "top_prob": top_market.implied_probability,
                "top_market_title": top_market.title[:60],
            }
            if days <= 7:
                buckets["this_week"].append(entry)
            elif days <= 30:
                buckets["this_month"].append(entry)
            elif days <= 90:
                buckets["this_quarter"].append(entry)
            elif days <= 365:
                buckets["this_year"].append(entry)
            else:
                buckets["long_dated"].append(entry)
        # Sort each bucket by days_until
        for k in buckets:
            buckets[k].sort(key=lambda e: e["days_until"])
        return buckets
    except Exception as exc:
        print(f"[v3] event calendar error: {exc}")
        return {"this_week": [], "this_month": [], "this_quarter": [], "this_year": [], "long_dated": []}


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


def get_cross_platform_comparison():
    """Compare Kalshi vs Polymarket prices for matching markets."""
    try:
        from tradingagents.dataflows.kalshi import get_markets as kalshi_get_markets
        from tradingagents.dataflows.polymarket import list_markets as poly_list_markets, fuzzy_match_markets

        kalshi_markets = kalshi_get_markets(limit=100, status="open")
        poly_markets = poly_list_markets(limit=100, active=True)

        pairs = fuzzy_match_markets(kalshi_markets, poly_markets, threshold=0.45)

        results = []
        for p in pairs:
            results.append({
                "kalshi_ticker": p.kalshi_market.ticker[:35],
                "kalshi_title": p.kalshi_market.title[:60],
                "kalshi_yes": p.kalshi_yes_price,
                "kalshi_spread": p.kalshi_market.spread,
                "kalshi_volume": p.kalshi_market.volume,
                "poly_question": p.poly_market.question[:60],
                "poly_yes": p.poly_yes_price,
                "poly_volume": p.poly_market.volume,
                "similarity": p.similarity_score,
                "divergence": p.price_divergence,
                "potential_arb": p.potential_arb,
            })
        return results
    except Exception as exc:
        print(f"[v3] cross-platform comparison error: {exc}")
        return []


def get_polymarket_trending(limit=15):
    """Get top Polymarket markets by volume."""
    try:
        from tradingagents.dataflows.polymarket import list_markets
        markets = list_markets(limit=limit, active=True)
        results = []
        for m in markets:
            if not m.outcome_prices:
                continue
            results.append({
                "question": m.question[:80],
                "yes_price": m.outcome_prices[0] if m.outcome_prices else 0,
                "no_price": m.outcome_prices[1] if len(m.outcome_prices) > 1 else 0,
                "volume": m.volume,
                "liquidity": m.liquidity,
                "end_date": m.end_date[:10] if m.end_date else "",
                "category": m.category,
                "slug": m.slug,
            })
        return results
    except Exception as exc:
        print(f"[v3] polymarket error: {exc}")
        return []


def get_council_candidates_data():
    """Get prediction council candidate markets ranked by edge."""
    try:
        from tradingagents.dataflows.arb_scanner import get_council_candidates
        candidates = get_council_candidates(min_volume=500, top_n=10)
        return [
            {
                "ticker": c.ticker[:30],
                "title": c.title,
                "event_ticker": c.event_ticker,
                "implied_probability": c.implied_probability,
                "volume": c.volume,
                "spread": c.spread,
                "days_to_close": c.days_to_close,
                "bias_edge": c.bias_edge,
                "category": c.category,
                "reason": c.reason,
            }
            for c in candidates
        ]
    except Exception as exc:
        print(f"[v3] council candidates error: {exc}")
        return []


def get_arb_scans(limit=20):
    """Get recent arbitrage scan results."""
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT * FROM arb_scans ORDER BY scanned_at DESC LIMIT ?", (limit,)
        ).fetchall()
        results = []
        for r in rows:
            results.append({
                "id": r["id"],
                "scan_type": r["scan_type"],
                "event_ticker": r["event_ticker"] or "",
                "market_ticker": r["market_ticker"] or "",
                "implied_prob_sum": r["implied_prob_sum"],
                "overround_pct": r["overround_pct"],
                "profit_pct": r["profit_pct"],
                "price_bucket": r["price_bucket"] or "",
                "bucket_edge": r["bucket_edge"],
                "num_markets": r["num_markets"],
                "scanned_at": r["scanned_at"],
            })
        return results
    except Exception:
        return []


def get_arb_executions():
    """Get arb execution bundles."""
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        import json
        conn = get_db(config)
        rows = conn.execute(
            "SELECT * FROM arb_executions ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
        results = []
        for r in rows:
            markets = []
            try:
                markets = json.loads(r["markets_json"])
            except Exception:
                pass
            results.append({
                "id": r["id"],
                "event_ticker": r["event_ticker"],
                "strategy": r["strategy"],
                "markets": markets,
                "num_legs": len(markets),
                "total_cost": r["total_cost"],
                "expected_profit": r["expected_profit"],
                "status": r["status"],
                "result_pnl": r["result_pnl"],
                "created_at": r["created_at"],
                "settled_at": r["settled_at"],
            })
        return results
    except Exception:
        return []


def get_dag_data(ticker):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db, get_ticker_state
        from tradingagents.execution.ticker_utils import detect_asset_type
        conn = get_db(config)

        asset_info = detect_asset_type(ticker)
        states = get_ticker_state(config, ticker, limit=1)
        scores = {}
        if states:
            s = states[0]
            scores = {
                "technical": round(s["technical_score"], 1),
                "fundamental": round(s["fundamental_score"], 1),
                "sentiment": round(s["sentiment_score"], 1),
                "news": round(s["news_score"], 1),
                "weighted": round(s["weighted_score"], 2),
                "signal": s["council_signal"],
                "confidence": round(s["confidence"], 2),
                "regime": s.get("regime_at_analysis", ""),
                "price": round(s["price_at_analysis"], 2) if s.get("price_at_analysis") else 0,
                "time": s["analyzed_at"][:16],
                "asset_class": asset_info["asset_class"],
                "sector": asset_info["sector"],
            }

        rows = conn.execute(
            "SELECT * FROM trade_reports WHERE ticker = ? ORDER BY created_at DESC LIMIT 1",
            (ticker,),
        ).fetchall()
        report = {}
        if rows:
            r = rows[0]
            report = {
                "type": r["report_type"], "technicals": r["technicals"],
                "fundamentals": r["fundamentals"], "sentiment": r["sentiment"],
                "news_catalyst": r["news_catalyst"], "risk_factors": r["risk_factors"],
                "reasoning": r["reasoning"],
            }

        trade_rows = conn.execute(
            "SELECT * FROM trades WHERE ticker = ? AND action_taken = 'executed' "
            "ORDER BY timestamp DESC LIMIT 1",
            (ticker,),
        ).fetchall()
        trade = {}
        if trade_rows:
            t = trade_rows[0]
            trade = {
                "side": (t["side"] or "").upper(), "qty": t["quantity"],
                "fill": t["fill_price"], "time": t["timestamp"][:16],
                "before": t["account_before"], "after": t["account_after"],
                "asset_class": asset_info["asset_class"],
            }

        # Quant pre-screen scores
        quant = {}
        try:
            qrow = conn.execute(
                "SELECT * FROM quant_scores WHERE ticker = ? ORDER BY scored_at DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if qrow:
                quant = {
                    "fundamental": round(qrow["fundamental_score"], 2),
                    "technical": round(qrow["technical_score"], 2),
                    "data_quality": round(qrow["data_quality"], 2),
                    "asset_class": qrow["asset_class"],
                    "sector": qrow["sector"] or "",
                    "scored_at": qrow["scored_at"][:16],
                    "vetoes": json.loads(qrow["vetoes_json"]) if qrow["vetoes_json"] else [],
                    "components": json.loads(qrow["components_json"]) if qrow["components_json"] else {},
                }
        except Exception:
            pass

        return {"scores": scores, "report": report, "trade": trade, "quant": quant}
    except Exception:
        return {"scores": {}, "report": {}, "trade": {}, "quant": {}}


def get_wiki_pages(filter_type="all"):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        if filter_type == "all":
            rows = conn.execute(
                "SELECT path, ticker, trade_date, signal, regime, confidence, page_type "
                "FROM wiki_pages ORDER BY trade_date DESC, created_at DESC LIMIT 50"
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT path, ticker, trade_date, signal, regime, confidence, page_type "
                "FROM wiki_pages WHERE page_type = ? "
                "ORDER BY trade_date DESC, created_at DESC LIMIT 50",
                (filter_type,),
            ).fetchall()
        from tradingagents.execution.ticker_utils import detect_asset_type
        results = []
        for r in rows:
            ai = detect_asset_type(r["ticker"]) if r["ticker"] else {"asset_class": "stock", "sector": None}
            results.append({
                "path": r["path"], "ticker": r["ticker"],
                "trade_date": r["trade_date"], "signal": r["signal"],
                "regime": r["regime"] or "", "confidence": round(r["confidence"] or 0, 2),
                "page_type": r["page_type"],
                "asset_class": ai["asset_class"], "sector": ai["sector"],
            })
        return results
    except Exception:
        return []


def search_wiki_pages(query):
    if not query or not query.strip():
        return []
    try:
        config = _cfg()
        from tradingagents.wiki import WikiWriter
        wiki = WikiWriter(config)
        return [
            {
                "path": r["path"], "ticker": r["ticker"],
                "trade_date": r["trade_date"], "signal": r["signal"],
                "regime": r.get("regime", ""), "confidence": round(r.get("confidence", 0), 2),
                "page_type": r.get("page_type", "run"),
            }
            for r in wiki.search(query.strip(), limit=20)
        ]
    except Exception:
        return []


def get_wiki_content(path):
    try:
        config = _cfg()
        from tradingagents.wiki import WikiWriter
        wiki = WikiWriter(config)
        content = wiki.get_page_content(path)
        return _md_to_html(content)
    except Exception:
        return ""


def get_daily_digest_dates():
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        d1 = conn.execute(
            "SELECT DISTINCT trade_date FROM wiki_pages WHERE page_type = 'daily' ORDER BY trade_date DESC LIMIT 30"
        ).fetchall()
        d2 = conn.execute(
            "SELECT DISTINCT trade_date FROM wiki_pages WHERE page_type = 'run' ORDER BY trade_date DESC LIMIT 30"
        ).fetchall()
        return sorted(set(r["trade_date"] for r in d1) | set(r["trade_date"] for r in d2), reverse=True)[:30]
    except Exception:
        return []


def get_daily_digest_html(date_str):
    if not date_str:
        return ""
    try:
        config = _cfg()
        from tradingagents.wiki import WikiWriter
        wiki = WikiWriter(config)
        path = f"daily/{date_str}.md"
        content = wiki.get_page_content(path)
        if not content:
            wiki.write_daily_digest(date_str)
            content = wiki.get_page_content(path)
        return _md_to_html(content)
    except Exception as e:
        return f"<p>Error: {e}</p>"


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


def get_available_dates():
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        d1 = conn.execute("SELECT DISTINCT substr(timestamp, 1, 10) as d FROM trades ORDER BY d DESC LIMIT 90").fetchall()
        d2 = conn.execute("SELECT DISTINCT substr(analyzed_at, 1, 10) as d FROM ticker_state ORDER BY d DESC LIMIT 90").fetchall()
        return sorted(set(r["d"] for r in d1) | set(r["d"] for r in d2), reverse=True)[:60]
    except Exception:
        return []


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
    def inject_nav():
        """Common data for the nav bar on every page."""
        mkt = get_market_status()
        regime = get_regime()
        dates = get_available_dates()
        hist_date = request.args.get("date")
        return {
            "market_status": mkt,
            "regime": regime,
            "now": datetime.now().strftime("%H:%M:%S"),
            "nav_dates": dates,
            "nav_hist_date": hist_date,
        }

    # ── Page routes ──

    @app.route("/")
    def trading():
        hist_date = request.args.get("date")
        acct = get_account_data()
        trades = get_trades_data()
        regime = get_regime()
        activity = get_activity_feed(trades["recent"])
        dates = get_available_dates()
        historical = get_historical_data(hist_date) if hist_date else None
        live_risk = get_live_risk_data() if not hist_date else None
        return render_template("trading.html",
                               acct=acct, trades=trades, regime=regime,
                               activity=activity, dates=dates,
                               hist_date=hist_date, historical=historical,
                               live_risk=live_risk,
                               page="trading")

    @app.route("/council")
    def council():
        ticker = request.args.get("ticker")
        states = get_ticker_states()
        detail = get_ticker_detail(ticker) if ticker else None
        reports = get_trade_reports(limit=30)
        reflections = get_ticker_reflections(ticker) if ticker else ""
        return render_template("council.html",
                               states=states, ticker=ticker, detail=detail,
                               reports=reports, reflections=reflections,
                               page="council")

    @app.route("/performance")
    def performance():
        acct = get_account_data()
        trades = get_trades_data()
        slippage = get_slippage_data()
        return render_template("performance.html",
                               acct=acct, trades=trades, slippage=slippage,
                               page="performance")

    @app.route("/research")
    def research():
        query = request.args.get("q", "")
        filter_type = request.args.get("filter", "all")
        wiki_path = request.args.get("page")
        report_ticker = request.args.get("rt", "")
        report_type = request.args.get("rtype", "all")
        digest_date = request.args.get("digest")

        search_results = search_wiki_pages(query) if query else []
        pages = get_wiki_pages(filter_type)
        wiki_html = get_wiki_content(wiki_path) if wiki_path else ""
        wiki_title = wiki_path.split("/")[-1].replace(".md", "") if wiki_path else ""

        reports = get_trade_reports(limit=30)
        if report_ticker:
            reports = [r for r in reports if report_ticker.upper() in r["ticker"].upper()]
        if report_type != "all":
            reports = [r for r in reports if r["report_type"] == report_type]

        digest_dates = get_daily_digest_dates()
        digest_html = get_daily_digest_html(digest_date) if digest_date else ""

        return render_template("research.html",
                               query=query, search_results=search_results,
                               filter_type=filter_type, pages=pages,
                               wiki_html=wiki_html, wiki_title=wiki_title,
                               wiki_path=wiki_path,
                               reports=reports, report_ticker=report_ticker,
                               report_type=report_type,
                               digest_dates=digest_dates, digest_date=digest_date,
                               digest_html=digest_html,
                               page="research")

    @app.route("/predictions")
    def predictions():
        kalshi_positions = get_kalshi_positions()
        kalshi_events = get_kalshi_trending_events()
        arb_scans = get_arb_scans()
        arb_executions = get_arb_executions()
        council_candidates = get_council_candidates_data()
        poly_markets = get_polymarket_trending()
        cross_platform = get_cross_platform_comparison()
        event_calendar = get_event_calendar()
        calibration = get_kalshi_calibration()
        return render_template("predictions.html",
                               positions=kalshi_positions,
                               events=kalshi_events,
                               arb_scans=arb_scans,
                               arb_executions=arb_executions,
                               council_candidates=council_candidates,
                               poly_markets=poly_markets,
                               cross_platform=cross_platform,
                               event_calendar=event_calendar,
                               calibration=calibration,
                               page="predictions")

    @app.route("/pipeline")
    def pipeline():
        dag_ticker = request.args.get("dag")
        acct = get_account_data()
        cache = get_cache_stats()
        timeline = get_cycle_timeline()
        deltas = get_ticker_deltas()
        slippage = get_slippage_data()
        dag = get_dag_data(dag_ticker) if dag_ticker else None
        sectors = get_sector_rotation()
        watchlist = get_watchlist()
        clusters = get_insider_clusters(acct["positions"], watchlist)
        congress = get_congress_recent(acct["positions"], watchlist)
        return render_template("pipeline.html",
                               cache=cache, timeline=timeline, deltas=deltas,
                               slippage=slippage, dag_ticker=dag_ticker, dag=dag,
                               sectors=sectors, clusters=clusters,
                               congress_trades=congress,
                               page="pipeline")

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
