"""Drawdown monitor, kill switch, and notional exposure tracking."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List

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
                "~/.tradingagents/safety_state.json",
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
        from tradingagents.execution.contracts import get_multiplier

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
        from tradingagents.execution.db import get_db

        cfg = self._config
        if "db_path" not in cfg:
            cfg = dict(cfg, db_path=str(self._state_path.parent / "tradingagents.db"))
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
