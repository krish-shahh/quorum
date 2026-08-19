"""Flask dashboard v3 — light-mode Tailwind trading dashboard.

All data-fetching is ported from the Reflex v2 state.py into plain
functions.  Templates use Jinja2 + Tailwind CDN + Chart.js + htmx.
"""

import json
import sys
from datetime import date, datetime
from pathlib import Path

from flask import Flask, Blueprint, request, jsonify

# ── Make quorum importable ──────────────────────────────────────
_project_root = str(Path(__file__).resolve().parents[2])
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from quorum.execution.db import get_db


def _cfg():
    from quorum.default_config import DEFAULT_CONFIG
    return DEFAULT_CONFIG.copy()



# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  DATA FUNCTIONS
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def get_account_data():
    """Portfolio value, cash, P&L, positions, allocation."""
    try:
        config = _cfg()
        from quorum.execution.broker.paper_client import PaperBrokerClient
        from quorum.execution.safety import SafetyMonitor

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

        from quorum.execution.ticker_utils import detect_asset_type, get_book
        from quorum.execution.contracts import get_contract_spec, days_to_expiry

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
            from quorum.execution.db import get_all_latest_states
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

        # Book view (portfolio hierarchy)
        from quorum.execution.portfolio import compute_book_view
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
        from quorum.execution.trade_data import (
            load_recent_trades,
            compute_trade_stats,
            compute_equity_curve,
            normalize_trade,
        )
        starting = float(config.get("paper_starting_balance", 100_000))
        trades = load_recent_trades(config, limit=500)
        stats = compute_trade_stats(trades, starting)

        from quorum.execution.ticker_utils import detect_asset_type
        from quorum.execution.contracts import get_multiplier

        recent = []
        for raw in trades[:100]:
            t = normalize_trade(raw)
            tkr = t.get("ticker", "")
            ai = detect_asset_type(tkr)
            mult = get_multiplier(tkr)
            fill = t.get("fill_price")
            qty = t.get("quantity", 0)
            recent.append({
                "time": str(t.get("timestamp", ""))[:16],
                "ticker": tkr,
                "signal": t.get("signal", ""),
                "action": t.get("action_taken", ""),
                "side": (t.get("side") or "").upper(),
                "qty": qty,
                "fill": fill,
                "reason": t.get("reason", ""),
                "account_before": t.get("account_before"),
                "account_after": t.get("account_after"),
                "realized_pnl": t.get("realized_pnl"),
                "asset_class": ai["asset_class"],
                "sector": ai["sector"],
                "multiplier": mult,
                "notional": round(float(fill or 0) * int(qty or 0) * mult, 2),
            })

        eq = compute_equity_curve(trades, starting)
        equity = [{"time": str(p.get("time_str", p.get("time", ""))), "value": p["value"]} for p in eq]

        return {
            "total": stats["total_trades"],
            "wins": stats["wins"],
            "losses": stats["losses"],
            "win_rate": round(stats["win_rate"], 3),
            "recent": recent,
            "equity": equity,
        }
    except Exception as e:
        print(f"[v3] trades error: {e}")
        return {"total": 0, "wins": 0, "losses": 0, "win_rate": 0,
                "recent": [], "equity": []}


def get_market_status():
    try:
        from quorum.execution.market_calendar import is_market_open, is_trading_day
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
        from quorum.dataflows.regime import CrossAssetRegimeDetector
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
        from quorum.execution.db import get_all_latest_states
        from quorum.execution.ticker_utils import detect_asset_type
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
        from quorum.execution.db import get_ticker_state
        from quorum.execution.ticker_utils import detect_asset_type
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
        from quorum.execution.db import get_council_analyst_reports
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
        plan_path = Path.home() / ".quorum" / "plans" / "active.md"
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
        from quorum.execution.learning import LearningEngine
        from quorum.execution.reflection import ReflectionEngine
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
        from quorum.execution.db import get_db
        from quorum.execution.ticker_utils import detect_asset_type
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
        from quorum.dataflows.insider_clustering import InsiderClusterDetector
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


def get_plan_status_data():
    """Get active plan status for the trading page plan bar."""
    try:
        from quorum.execution.plan import read_active_plan, get_plan_metrics
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
        plans_dir = Path(os.environ.get("QUORUM_HOME", Path.home() / ".quorum")) / "plans"
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
    live_risk = get_live_risk_data()
    return {
        "regime": get_regime(),
        "plan": get_plan_status_data(),
        "live_risk": live_risk,
        "kill_switch": acct.get("kill_switch", False),
        "execution_mode": acct.get("execution_mode", "paper"),
        "risk_level": live_risk.get("risk_level", "unknown"),
    }


def get_congress_recent(positions, watchlist, days=30):
    """Get recent congressional trades for held + watchlist tickers."""
    try:
        from quorum.dataflows.congress import _load_cache
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
        from quorum.dataflows.sector_rotation import SectorRotationModel
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


def get_live_risk_data():
    """Get live intraday risk status for the trading dashboard."""
    try:
        config = _cfg()
        from quorum.execution.safety import compute_live_risk
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


def get_watchlist():
    try:
        config = _cfg()
        from quorum.execution.trade_data import load_watchlist
        saved = load_watchlist(config)
        return saved.get("tickers", [])
    except Exception:
        return []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  JSON API (consumed by Electron desktop app)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

api_bp = Blueprint("api_json", __name__)


_ALLOWED_ORIGIN_HOSTS = {"localhost", "127.0.0.1", "::1"}


def _origin_allowed(origin: str) -> bool:
    """Allow only the Electron app (file:// → 'null') and localhost dev origins."""
    if not origin:
        return False
    if origin == "null":  # packaged Electron renderer loads via file://
        return True
    from urllib.parse import urlparse
    return urlparse(origin).hostname in _ALLOWED_ORIGIN_HOSTS


@api_bp.after_request
def api_cors(response):
    """Reflect CORS only for the Electron app / localhost dev — never a wildcard.

    A wildcard would let any website the user visits issue cross-origin
    requests to this localhost API (e.g. flipping the kill switch).
    """
    origin = request.headers.get("Origin", "")
    if _origin_allowed(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Vary"] = "Origin"
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
        from quorum.dataflows.y_finance import get_YFin_data_online
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


@api_bp.route("/api/v1/refresh", methods=["POST"])
def api_v1_refresh():
    """Manually bust the regime cache (the status strip's only TTL-cached
    field — P&L and plan status are already computed live on every
    request) so a user-triggered refresh doesn't have to wait out the
    5-minute cache_ttls.regime window."""
    from quorum.dataflows.cache import invalidate

    return jsonify({"cleared": invalidate("detect")})


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


@api_bp.route("/api/v1/performance")
def api_v1_performance():
    """Full performance summary — rolling Sharpe/Sortino, win-rate by
    ticker/signal/day-of-week, best/worst trade — computed but never
    exposed by any route until now. Reads the legacy `trades` table,
    which is real fills only (both legacy-council and pod-cycle trades
    land there via ExecutionEngine.record_execution), so this is safe
    without a mode filter."""
    try:
        config = _cfg()
        from quorum.execution.analytics import generate_performance_summary
        from quorum.execution.trade_data import load_recent_trades

        starting = float(config.get("paper_starting_balance", 100_000))
        trades = load_recent_trades(config, limit=500)
        return jsonify(generate_performance_summary(trades, starting))
    except Exception as e:
        print(f"[v3] performance error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/v1/runs")
def api_v1_runs():
    """Run browser listing — filterable by mode/strategy_id."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.decision_log import list_runs

    mode = request.args.get("mode") or None
    strategy_id = request.args.get("strategy_id") or None
    limit = request.args.get("limit", default=50, type=int)
    return jsonify({"runs": list_runs(DEFAULT_CONFIG, mode=mode, strategy_id=strategy_id, limit=limit)})


@api_bp.route("/api/v1/runs/<run_id>")
def api_v1_run_detail(run_id):
    """One run's full decision chain: candidates, targets, orders/fills,
    journal decisions, closed trades, and its gate result. Prefers the
    saved run_recap (fast, kept current by save_run_recap's auto-save
    hooks) and falls back to a live query + opportunistic save for any
    run that predates this feature or hasn't finished yet."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.decision_log import get_run_detail, get_run_recap, save_run_recap

    detail = get_run_recap(DEFAULT_CONFIG, run_id)
    if detail is None:
        detail = get_run_detail(DEFAULT_CONFIG, run_id)
        if detail is not None:
            save_run_recap(DEFAULT_CONFIG, run_id)
    if detail is None:
        return jsonify({"error": f"no run {run_id}"}), 404
    return jsonify(detail)


@api_bp.route("/api/v1/runs/<run_id>/performance")
def api_v1_run_performance(run_id):
    """Same shape as /api/v1/performance, scoped to one run's own closed
    trades instead of the whole live book — lets the Performance view
    work for a specific backtest or pod-cycle run."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.decision_log import get_run_detail

    if get_run_detail(DEFAULT_CONFIG, run_id) is None:
        return jsonify({"error": f"no run {run_id}"}), 404
    try:
        from quorum.execution.analytics import generate_run_performance_summary
        return jsonify(generate_run_performance_summary(DEFAULT_CONFIG, run_id))
    except Exception as e:
        print(f"[v3] run-performance error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/v1/cycles/<cycle_id>")
def api_v1_cycle_detail(cycle_id):
    """Full ordered trace-event stream for one cycle, plus the run_ids it
    touched — the Opik-style reasoning/tool-call trace behind a run."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.decision_log import get_cycle

    detail = get_cycle(DEFAULT_CONFIG, cycle_id)
    if detail is None:
        return jsonify({"error": f"no cycle {cycle_id}"}), 404
    return jsonify(detail)


@api_bp.route("/api/v1/annotations", methods=["GET", "POST"])
def api_v1_annotations():
    """GET lists threads (optionally filtered by anchor_type, anchor as a
    JSON string, and/or status). POST starts a new thread on an anchor."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.annotations import create_annotation, list_annotations

    if request.method == "POST":
        payload = request.get_json(force=True) or {}
        anchor_type = payload.get("anchor_type")
        anchor = payload.get("anchor")
        body = payload.get("body")
        author = payload.get("author", "user")
        if not anchor_type or anchor is None or not body:
            return jsonify({"error": "anchor_type, anchor, and body are required"}), 400
        return jsonify(create_annotation(DEFAULT_CONFIG, anchor_type=anchor_type, anchor=anchor, author=author, body=body)), 201

    anchor_type = request.args.get("anchor_type") or None
    status = request.args.get("status") or None
    anchor_raw = request.args.get("anchor")
    anchor = json.loads(anchor_raw) if anchor_raw else None
    return jsonify({"annotations": list_annotations(DEFAULT_CONFIG, anchor_type=anchor_type, anchor=anchor, status=status)})


@api_bp.route("/api/v1/annotations/<annotation_id>/reply", methods=["POST"])
def api_v1_annotation_reply(annotation_id):
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.annotations import add_reply

    payload = request.get_json(force=True) or {}
    body = payload.get("body")
    author = payload.get("author", "user")
    if not body:
        return jsonify({"error": "body is required"}), 400
    annotation = add_reply(DEFAULT_CONFIG, annotation_id, author=author, body=body)
    if annotation is None:
        return jsonify({"error": f"no annotation {annotation_id}"}), 404
    return jsonify(annotation)


@api_bp.route("/api/v1/annotations/<annotation_id>/resolve", methods=["POST"])
def api_v1_annotation_resolve(annotation_id):
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.annotations import resolve_annotation

    annotation = resolve_annotation(DEFAULT_CONFIG, annotation_id)
    if annotation is None:
        return jsonify({"error": f"no annotation {annotation_id}"}), 404
    return jsonify(annotation)


@api_bp.route("/api/v1/analyst-accuracy")
def api_v1_analyst_accuracy():
    """Legacy council per-analyst IC/directional accuracy."""
    try:
        config = _cfg()
        from quorum.execution.db import compute_analyst_accuracy
        return jsonify(compute_analyst_accuracy(config))
    except Exception as e:
        print(f"[v3] analyst-accuracy error: {e}")
        return jsonify({"error": str(e)}), 500


@api_bp.route("/api/v1/daily-recap")
def api_v1_daily_recap_list():
    """Recent daily-recap summaries, newest first — backs the Activity
    view's daily-recap list."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.decision_log import list_daily_recaps

    limit = request.args.get("limit", default=30, type=int)
    return jsonify({"recaps": list_daily_recaps(DEFAULT_CONFIG, limit=limit)})


@api_bp.route("/api/v1/daily-recap/<recap_date>")
def api_v1_daily_recap_detail(recap_date):
    """Full play-by-play for one day: every run (any mode), its candidates,
    pod-PM decisions, orders/fills, and trades closed that day."""
    from quorum.default_config import DEFAULT_CONFIG
    from quorum.execution.decision_log import get_daily_recap

    recap = get_daily_recap(DEFAULT_CONFIG, recap_date)
    if recap is None:
        return jsonify({"error": f"no recap saved for {recap_date}"}), 404
    return jsonify(recap)


@api_bp.route("/api/v1/reports")
def api_v1_reports():
    """All trade reports (pre + post trade analysis)."""
    return jsonify({"reports": get_trade_reports(limit=100)})


@api_bp.route("/api/v1/kill-switch", methods=["POST"])
def api_v1_kill_switch():
    # Block drive-by CSRF: reject a cross-site Origin (a website the user is
    # browsing). Electron ('null'), localhost dev, and non-browser callers
    # (curl, no Origin header) are allowed.
    origin = request.headers.get("Origin", "")
    if origin and not _origin_allowed(origin):
        return jsonify({"error": "cross-site request forbidden"}), 403
    config = _cfg()
    from quorum.execution.safety import SafetyMonitor
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
