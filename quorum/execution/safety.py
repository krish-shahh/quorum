"""Drawdown monitor, kill switch, and notional exposure tracking."""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .schemas import AccountInfo

logger = logging.getLogger(__name__)


class SafetyMonitor:
    """Tracks peak account value and halts trading if drawdown exceeds threshold.

    The kill switch is persistent — once tripped it stays active across restarts
    until explicitly reset by the user.

    Futures-aware: tracks notional exposure vs account value and enforces
    max notional leverage limits.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self.max_drawdown_pct = float(config.get("max_drawdown_pct", 0.10))
        self.max_notional_leverage = float(config.get("max_notional_leverage", 3.0))
        self._state_path = Path(
            config.get(
                "safety_state_path",
                "~/.quorum/safety_state.json",
            )
        ).expanduser()

        self.kill_switch_active: bool = False
        self._peak_value: float | None = None
        self._load_state()

    def check_drawdown(self, account: AccountInfo) -> bool:
        """Return True if trading is allowed, False if the kill switch trips.

        Must be called before every order submission.
        """
        if self.kill_switch_active:
            logger.warning("Kill switch already active — all trading halted")
            return False

        current = account.account_value
        if self._peak_value is None or current > self._peak_value:
            self._peak_value = current
            self._save_state()

        if self._peak_value <= 0:
            return True

        drawdown = (self._peak_value - current) / self._peak_value
        if drawdown >= self.max_drawdown_pct:
            self.kill_switch_active = True
            self._save_state()
            logger.critical(
                "KILL SWITCH ACTIVATED: drawdown %.1f%% exceeds max %.1f%%. "
                "Peak: $%.2f, Current: $%.2f. All trading halted.",
                drawdown * 100,
                self.max_drawdown_pct * 100,
                self._peak_value,
                current,
            )
            return False

        return True

    def check_notional_exposure(
        self, account: AccountInfo, positions: List[Any],
    ) -> Dict[str, Any]:
        """Calculate total notional exposure including futures multipliers.

        Returns a dict with exposure metrics and whether it's within limits.
        """
        from quorum.execution.contracts import get_multiplier

        total_notional = 0.0
        futures_notional = 0.0
        equity_notional = 0.0

        for p in positions:
            qty = p.quantity if hasattr(p, "quantity") else p.get("quantity", 0)
            ticker = p.ticker if hasattr(p, "ticker") else p.get("ticker", "")
            mv = p.market_value if hasattr(p, "market_value") else p.get("market_value", 0)

            mult = get_multiplier(ticker)
            if mult > 1:
                futures_notional += abs(mv)
            else:
                equity_notional += abs(mv)
            total_notional += abs(mv)

        acct_value = account.account_value or 1
        leverage = total_notional / acct_value
        within_limits = leverage <= self.max_notional_leverage

        if not within_limits:
            logger.warning(
                "Notional exposure $%.0f (%.1fx leverage) exceeds max %.1fx. "
                "Futures: $%.0f, Equity: $%.0f, Account: $%.0f",
                total_notional, leverage, self.max_notional_leverage,
                futures_notional, equity_notional, acct_value,
            )

        return {
            "total_notional": round(total_notional, 2),
            "futures_notional": round(futures_notional, 2),
            "equity_notional": round(equity_notional, 2),
            "leverage": round(leverage, 2),
            "max_leverage": self.max_notional_leverage,
            "within_limits": within_limits,
        }

    def reset_kill_switch(self) -> None:
        """Manually reset the kill switch and clear peak tracking.

        This is an intentional, user-initiated action — never call it
        automatically.
        """
        self.kill_switch_active = False
        self._peak_value = None
        self._save_state()
        logger.info("Kill switch reset — trading re-enabled")

    # ------------------------------------------------------------------
    # Persistence  (SQLite primary, JSON fallback)
    # ------------------------------------------------------------------

    def _get_db(self):
        """Lazily obtain the shared SQLite connection.

        When no explicit ``db_path`` is in config, derive it from the
        safety state path's parent so test fixtures using ``tmp_path``
        get an isolated database automatically.
        """
        from quorum.execution.db import get_db

        cfg = self._config
        if "db_path" not in cfg:
            cfg = dict(cfg, db_path=str(self._state_path.parent / "quorum.db"))
        return get_db(cfg)

    def _save_state(self) -> None:
        data = {
            "kill_switch_active": self.kill_switch_active,
            "peak_value": self._peak_value,
        }

        # ---- SQLite (primary) ----
        try:
            conn = self._get_db()
            with conn:
                for key, value in data.items():
                    conn.execute(
                        "INSERT OR REPLACE INTO safety_state (key, value) VALUES (?, ?)",
                        (key, json.dumps(value)),
                    )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQLite safety save failed (%s); JSON only", exc)

        # ---- JSON (backward compat) ----
        self._state_path.parent.mkdir(parents=True, exist_ok=True)
        self._state_path.write_text(json.dumps(data, indent=2))

    def _load_state(self) -> None:
        loaded_from = None

        # ---- Try SQLite first ----
        try:
            conn = self._get_db()
            row = conn.execute(
                "SELECT value FROM safety_state WHERE key = 'kill_switch_active'"
            ).fetchone()
            if row is not None:
                self.kill_switch_active = bool(json.loads(row[0]))
                pv_row = conn.execute(
                    "SELECT value FROM safety_state WHERE key = 'peak_value'"
                ).fetchone()
                if pv_row is not None:
                    pv = json.loads(pv_row[0])
                    self._peak_value = float(pv) if pv is not None else None
                loaded_from = "sqlite"
                if self.kill_switch_active:
                    logger.warning("Kill switch is ACTIVE from previous session (SQLite)")
        except Exception as exc:  # noqa: BLE001
            logger.debug("SQLite safety load unavailable (%s); trying JSON", exc)

        # ---- Fall back to JSON ----
        if loaded_from is None:
            if not self._state_path.exists():
                return
            try:
                data = json.loads(self._state_path.read_text())
                self.kill_switch_active = bool(data.get("kill_switch_active", False))
                pv = data.get("peak_value")
                self._peak_value = float(pv) if pv is not None else None
                loaded_from = "json"
                if self.kill_switch_active:
                    logger.warning("Kill switch is ACTIVE from previous session")
            except (json.JSONDecodeError, KeyError, ValueError) as exc:
                logger.warning("Could not load safety state (%s); starting fresh", exc)
                return

        # ---- If loaded from JSON, migrate into SQLite ----
        if loaded_from == "json":
            try:
                self._save_state()
                logger.info("Migrated safety state from JSON to SQLite")
            except Exception as exc:  # noqa: BLE001
                logger.debug("Post-load migration to SQLite failed: %s", exc)


# ---------------------------------------------------------------------------
# Live intraday risk monitoring
# ---------------------------------------------------------------------------

_atr_cache: Dict[str, tuple] = {}  # ticker -> (atr_value, timestamp)
_ATR_CACHE_TTL = 3600  # 1 hour


def _get_cached_atr(ticker: str) -> Optional[float]:
    """Get ATR(14) for a ticker with 1-hour cache."""
    cached = _atr_cache.get(ticker)
    if cached and (time.time() - cached[1]) < _ATR_CACHE_TTL:
        return cached[0]
    try:
        import yfinance as yf
        import numpy as np
        hist = yf.Ticker(ticker).history(period="30d")
        if hist is None or len(hist) < 15:
            return None
        high = hist["High"].values
        low = hist["Low"].values
        close = hist["Close"].values
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(
                np.abs(high[1:] - close[:-1]),
                np.abs(low[1:] - close[:-1]),
            ),
        )
        atr = float(np.mean(tr[-14:]))
        _atr_cache[ticker] = (atr, time.time())
        return atr
    except Exception:
        return None


def _classify_risk_level(
    daily_pnl_pct: float,
    cash_reserve_pct: float,
    vix: float,
    consecutive_losses: int,
) -> str:
    """Pure function: classify circuit breaker tier from metrics."""
    if daily_pnl_pct <= -0.03 or vix > 30:
        return "red"
    if daily_pnl_pct <= -0.02 or consecutive_losses >= 3:
        return "orange"
    if daily_pnl_pct <= -0.01 or cash_reserve_pct < 0.20:
        return "yellow"
    return "green"


def compute_live_risk(config: Dict[str, Any]) -> Dict[str, Any]:
    """Compute all intraday risk metrics in one call (<2 seconds).

    Returns dict with: risk_level (green/yellow/orange/red), daily_pnl,
    daily_pnl_pct, intraday_drawdown, cash_reserve_pct, per-position stop
    distances, consecutive_losses, vix.
    """
    import sqlite3
    from quorum.execution.broker.paper_client import PaperBrokerClient
    from quorum.execution.db import get_db

    broker = PaperBrokerClient(config)
    account = broker.get_account_info()
    positions = broker.get_positions()
    current_value = account.account_value
    cash = account.cash_balance
    today = date.today().isoformat()

    # --- Daily P&L from intraday_risk table ---
    conn = get_db(config)
    row = None
    try:
        row = conn.execute(
            "SELECT * FROM intraday_risk WHERE date = ?", (today,)
        ).fetchone()
    except sqlite3.OperationalError:
        pass

    if row:
        open_value = row["open_value"]
        high_value = max(row["high_value"], current_value)
        low_value = min(row["low_value"], current_value)
    else:
        open_value = current_value
        high_value = current_value
        low_value = current_value

    daily_pnl = current_value - open_value
    daily_pnl_pct = daily_pnl / open_value if open_value > 0 else 0.0
    intraday_drawdown = (high_value - current_value) / high_value if high_value > 0 else 0.0

    # --- Cash reserve ---
    cash_reserve_pct = cash / current_value if current_value > 0 else 0.0

    # --- Per-position stops ---
    position_stops = []
    for p in positions:
        ticker = p.ticker if hasattr(p, "ticker") else p.get("ticker", "")
        qty = p.quantity if hasattr(p, "quantity") else p.get("quantity", 0)
        avg_cost = p.avg_cost if hasattr(p, "avg_cost") else p.get("avg_cost", 0)
        market_value = p.market_value if hasattr(p, "market_value") else p.get("market_value", 0)
        current_price = market_value / qty if qty > 0 else 0
        atr = _get_cached_atr(ticker)
        if atr and atr > 0:
            stop_price = avg_cost - (2 * atr)
            distance_pct = (current_price - stop_price) / current_price if current_price > 0 else 0
            breached = current_price <= stop_price
        else:
            stop_price = None
            distance_pct = None
            breached = False
        position_stops.append({
            "ticker": ticker,
            "current_price": round(current_price, 2),
            "avg_cost": round(avg_cost, 2),
            "atr": round(atr, 2) if atr else None,
            "stop_price": round(stop_price, 2) if stop_price else None,
            "distance_pct": round(distance_pct, 4) if distance_pct is not None else None,
            "breached": breached,
        })

    # --- Consecutive losses ---
    consecutive_losses = 0
    try:
        recent_trades = conn.execute(
            """SELECT account_value_before, account_value_after FROM trades
               WHERE action_taken = 'executed' AND date(timestamp) = ?
               ORDER BY timestamp DESC LIMIT 10""",
            (today,),
        ).fetchall()
        for t in recent_trades:
            if t["account_value_after"] < t["account_value_before"]:
                consecutive_losses += 1
            else:
                break
    except (sqlite3.OperationalError, KeyError):
        pass

    # --- VIX ---
    vix = 16.0  # default
    try:
        from quorum.dataflows.regime import CrossAssetRegimeDetector
        regime = CrossAssetRegimeDetector().detect()
        vix = regime.get("vix", 16.0) if isinstance(regime, dict) else 16.0
    except Exception:
        pass

    # --- Circuit breaker ---
    risk_level = _classify_risk_level(daily_pnl_pct, cash_reserve_pct, vix, consecutive_losses)

    # --- Persist intraday_risk ---
    try:
        now = datetime.now().isoformat()
        conn.execute(
            """INSERT OR REPLACE INTO intraday_risk
               (date, open_value, high_value, low_value, current_value,
                daily_pnl, daily_pnl_pct, risk_level, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (today, open_value, high_value, low_value, current_value,
             round(daily_pnl, 2), round(daily_pnl_pct, 6), risk_level, now),
        )
        conn.commit()
    except Exception as exc:
        logger.warning("Failed to persist intraday_risk: %s", exc)

    # --- Auto kill switch if RED ---
    if risk_level == "red":
        try:
            safety = SafetyMonitor(config)
            if not safety.kill_switch_active:
                safety.kill_switch_active = True
                safety._save_state()
                logger.critical(
                    "LIVE RISK: RED level triggered auto kill switch. "
                    "Daily P&L: $%.2f (%.2f%%), VIX: %.1f",
                    daily_pnl, daily_pnl_pct * 100, vix,
                )
        except Exception:
            pass

    # --- Exit signals (trailing stops, profit targets, time decay) ---
    exit_signals = check_exit_conditions(config, positions, position_stops)

    # --- Sell recommendations (stops breached = actionable sells) ---
    sell_recommendations = []
    for s in position_stops:
        if s["breached"]:
            sell_recommendations.append({
                "ticker": s["ticker"],
                "reason": f"ATR stop breached: ${s['current_price']} < stop ${s['stop_price']}",
                "urgency": "immediate",
            })
    for ex in exit_signals:
        if ex["urgency"] == "immediate":
            sell_recommendations.append(ex)

    return {
        "risk_level": risk_level,
        "daily_pnl": round(daily_pnl, 2),
        "daily_pnl_pct": round(daily_pnl_pct, 6),
        "intraday_drawdown": round(intraday_drawdown, 6),
        "open_value": round(open_value, 2),
        "high_value": round(high_value, 2),
        "low_value": round(low_value, 2),
        "current_value": round(current_value, 2),
        "cash_reserve_pct": round(cash_reserve_pct, 4),
        "consecutive_losses": consecutive_losses,
        "vix": vix,
        "position_stops": position_stops,
        "stops_breached": [s for s in position_stops if s["breached"]],
        "exit_signals": exit_signals,
        "sell_recommendations": sell_recommendations,
    }


# ---------------------------------------------------------------------------
# Exit condition checks (trailing stops, profit targets, time decay)
# ---------------------------------------------------------------------------


def check_exit_conditions(
    config: Dict[str, Any],
    positions: list,
    position_stops: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Check positions for exit signals beyond basic ATR stops.

    Returns list of exit signals with ticker, reason, and urgency.
    """
    from quorum.execution.db import get_db

    signals: List[Dict[str, Any]] = []
    conn = get_db(config)

    for p in positions:
        ticker = p.ticker if hasattr(p, "ticker") else p.get("ticker", "")
        qty = p.quantity if hasattr(p, "quantity") else p.get("quantity", 0)
        avg_cost = p.avg_cost if hasattr(p, "avg_cost") else p.get("avg_cost", 0)
        market_value = p.market_value if hasattr(p, "market_value") else p.get("market_value", 0)
        if qty <= 0 or avg_cost <= 0:
            continue
        current_price = market_value / qty

        # --- Trailing stop (ratchet up after 5% gain) ---
        pnl_pct = (current_price - avg_cost) / avg_cost
        atr = None
        for ps in position_stops:
            if ps["ticker"] == ticker:
                atr = ps.get("atr")
                break

        try:
            row = conn.execute(
                "SELECT trailing_high FROM paper_positions WHERE ticker = ?",
                (ticker,),
            ).fetchone()
            trailing_high = float(row["trailing_high"]) if row and row["trailing_high"] else avg_cost
        except Exception:
            trailing_high = avg_cost

        if current_price > trailing_high:
            trailing_high = current_price
            try:
                conn.execute(
                    "UPDATE paper_positions SET trailing_high = ? WHERE ticker = ?",
                    (trailing_high, ticker),
                )
                conn.commit()
            except Exception:
                pass

        if pnl_pct > 0.05 and atr and atr > 0:
            trailing_stop = trailing_high - (2 * atr)
            if current_price <= trailing_stop:
                signals.append({
                    "ticker": ticker,
                    "reason": f"Trailing stop hit: ${current_price:.2f} < ${trailing_stop:.2f} (high: ${trailing_high:.2f})",
                    "urgency": "immediate",
                })

        # --- Profit target review (at +15%, flag for re-analysis) ---
        if pnl_pct >= 0.15:
            signals.append({
                "ticker": ticker,
                "reason": f"Profit target +{pnl_pct:.0%} reached — review for take-profit",
                "urgency": "review",
            })

        # --- Time decay (flat for 15+ trading days) ---
        try:
            trade_row = conn.execute(
                "SELECT timestamp FROM trades WHERE ticker = ? AND action_taken = 'executed' "
                "ORDER BY timestamp DESC LIMIT 1",
                (ticker,),
            ).fetchone()
            if trade_row:
                from datetime import datetime as _dt
                trade_date = _dt.fromisoformat(trade_row["timestamp"][:19])
                days_held = (datetime.now() - trade_date).days
                if days_held >= 15 and abs(pnl_pct) < 0.02:
                    signals.append({
                        "ticker": ticker,
                        "reason": f"Time decay: held {days_held} days, only {pnl_pct:+.1%} — thesis may be stale",
                        "urgency": "review",
                    })
        except Exception:
            pass

    return signals
