"""Flask dashboard v3 — light-mode Tailwind trading dashboard.

All data-fetching is ported from the Reflex v2 state.py into plain
functions.  Templates use Jinja2 + Tailwind CDN + Chart.js + htmx.
"""

import sys
from datetime import date, datetime
from pathlib import Path

from flask import Flask, render_template, request, jsonify

# ── Make tradingagents importable ──────────────────────────────────────
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)


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

        acct_val = account.account_value or 1
        positions = []
        for p in positions_raw:
            avg = round(p.avg_cost, 3)
            last = round(p.market_value / p.quantity, 3) if p.quantity else 0
            mv = round(p.market_value, 2)
            upnl = round(p.unrealized_pnl, 2)
            ret = round((p.market_value / (p.avg_cost * p.quantity) - 1) * 100, 2) if p.avg_cost * p.quantity > 0 else 0
            wt = round(p.market_value / acct_val * 100, 1)
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
            })

        # Overlay signals from council
        try:
            from tradingagents.execution.db import get_all_latest_states
            sig_map = {s["ticker"]: s["council_signal"] for s in get_all_latest_states(config)}
            for pos in positions:
                pos["signal"] = sig_map.get(pos["ticker"], "---")
        except Exception:
            pass

        # Allocation
        allocation = [{"asset": p["ticker"], "value": p["weight"]} for p in positions]
        cash_pct = round((acct_val - sum(pp.market_value for pp in positions_raw)) / acct_val * 100, 1)
        if cash_pct > 0:
            allocation.append({"asset": "Cash", "value": cash_pct})

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

        recent = []
        for t in trades[:100]:
            req = t.get("order_request") or {}
            res = t.get("order_result") or {}
            recent.append({
                "time": t.get("timestamp", "")[:16],
                "ticker": t.get("ticker", ""),
                "signal": t.get("signal", ""),
                "action": t.get("action_taken", ""),
                "side": (req.get("side") or "").upper(),
                "qty": req.get("quantity", ""),
                "fill": res.get("filled_price"),
                "reason": t.get("reason", ""),
                "account_before": t.get("account_value_before"),
                "account_after": t.get("account_value_after"),
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
        return [
            {
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
            }
            for s in get_all_latest_states(config)
        ]
    except Exception as e:
        print(f"[v3] ticker states error: {e}")
        return []


def get_ticker_detail(ticker):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_ticker_state
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
            }
            for h in history
        ]
        return {"detail": rows[0] if rows else {}, "history": rows}
    except Exception as e:
        print(f"[v3] ticker detail error: {e}")
        return {"detail": {}, "history": []}


def get_trade_reports(limit=30):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db
        conn = get_db(config)
        rows = conn.execute(
            "SELECT * FROM trade_reports ORDER BY created_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [
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


def get_dag_data(ticker):
    try:
        config = _cfg()
        from tradingagents.execution.db import get_db, get_ticker_state
        conn = get_db(config)

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
            }

        return {"scores": scores, "report": report, "trade": trade}
    except Exception:
        return {"scores": {}, "report": {}, "trade": {}}


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
        return [
            {
                "path": r["path"], "ticker": r["ticker"],
                "trade_date": r["trade_date"], "signal": r["signal"],
                "regime": r["regime"] or "", "confidence": round(r["confidence"] or 0, 2),
                "page_type": r["page_type"],
            }
            for r in rows
        ]
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

        trade_rows = conn.execute(
            "SELECT * FROM trades WHERE substr(timestamp, 1, 10) = ? ORDER BY timestamp", (d,)
        ).fetchall()
        trades = [
            {
                "time": r["timestamp"][:16], "ticker": r["ticker"],
                "signal": r["signal"], "action": r["action_taken"],
                "side": (r["side"] or "").upper(), "qty": r["quantity"],
                "fill": r["fill_price"], "reason": r["reason"] or "",
            }
            for r in trade_rows
        ]
        executed = [r for r in trade_rows if r["action_taken"] == "executed"]
        if executed and executed[0]["account_before"] and executed[-1]["account_after"]:
            hist_pnl = round(executed[-1]["account_after"] - executed[0]["account_before"], 2)
        else:
            hist_pnl = 0.0

        state_rows = conn.execute(
            "SELECT * FROM ticker_state WHERE substr(analyzed_at, 1, 10) = ? ORDER BY analyzed_at DESC", (d,)
        ).fetchall()
        states = [
            {
                "ticker": s["ticker"],
                "technical": round(s["technical_score"], 1),
                "fundamental": round(s["fundamental_score"], 1),
                "sentiment": round(s["sentiment_score"], 1),
                "news": round(s["news_score"], 1),
                "signal": s["council_signal"],
                "weighted": round(s["weighted_score"], 2),
                "price": round(s["price_at_analysis"], 2) if s["price_at_analysis"] else 0,
                "analyzed_at": s["analyzed_at"][:16],
            }
            for s in state_rows
        ]

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
        return render_template("trading.html",
                               acct=acct, trades=trades, regime=regime,
                               activity=activity, dates=dates,
                               hist_date=hist_date, historical=historical,
                               page="trading")

    @app.route("/council")
    def council():
        ticker = request.args.get("ticker")
        states = get_ticker_states()
        detail = get_ticker_detail(ticker) if ticker else None
        reports = get_trade_reports(limit=30)
        return render_template("council.html",
                               states=states, ticker=ticker, detail=detail,
                               reports=reports, page="council")

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
        return render_template("pipeline.html",
                               cache=cache, timeline=timeline, deltas=deltas,
                               slippage=slippage, dag_ticker=dag_ticker, dag=dag,
                               sectors=sectors, clusters=clusters,
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
