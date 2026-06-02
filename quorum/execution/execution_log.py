"""Append-only trade audit log (JSON Lines)."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from .schemas import ExecutionRecord, OrderRequest, OrderResult

logger = logging.getLogger(__name__)


class ExecutionLog:
    """Writes one JSON object per line to an append-only log file.

    Every execution attempt — whether it results in a trade, a kill-switch
    block, or a no-action skip — gets recorded so there is a complete
    audit trail.

    Writes go to **both** the JSONL file (backward compat) and the
    ``trades`` table in the consolidated SQLite database.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._log_path = Path(
            config.get(
                "execution_log_path",
                "~/.quorum/execution/trades.jsonl",
            )
        ).expanduser()
        self._log_path.parent.mkdir(parents=True, exist_ok=True)

    # ── helpers ──

    def _get_db(self):
        """Lazily obtain the shared SQLite connection.

        When no explicit ``db_path`` is in config, derive it from the
        log path's grandparent so test fixtures using ``tmp_path``
        get an isolated database automatically.
        """
        from quorum.execution.db import get_db

        cfg = self._config
        if "db_path" not in cfg:
            # log_path is typically ~/.quorum/execution/trades.jsonl
            # so parent.parent gives ~/.quorum/
            cfg = dict(cfg, db_path=str(self._log_path.parent.parent / "quorum.db"))
        return get_db(cfg)

    # ── public interface ──

    def record_execution(self, record: ExecutionRecord) -> None:
        """Append a full execution record."""
        self._append(record.model_dump(mode="json"))

    def record_blocked(
        self, ticker: str, signal: str, reason: str,
        account_value: Optional[float] = None,
    ) -> None:
        """Record that a trade was blocked (e.g. kill switch)."""
        self._append(
            ExecutionRecord(
                timestamp=datetime.now(),
                ticker=ticker,
                signal=signal,
                action_taken="blocked",
                reason=reason,
                account_value_before=account_value,
            ).model_dump(mode="json")
        )

    def record_skipped(
        self, ticker: str, signal: str, reason: str,
        account_value: Optional[float] = None,
    ) -> None:
        """Record that no action was taken (Hold signal, no position to sell, etc.)."""
        self._append(
            ExecutionRecord(
                timestamp=datetime.now(),
                ticker=ticker,
                signal=signal,
                action_taken="skipped",
                reason=reason,
                account_value_before=account_value,
            ).model_dump(mode="json")
        )

    def query_trades(
        self,
        *,
        ticker: Optional[str] = None,
        action: Optional[str] = None,
        since: Optional[str] = None,
        limit: int = 200,
    ) -> list:
        """Return trade rows from SQLite matching the given filters (newest first).

        Falls back to reading the JSONL file if SQLite is unavailable.
        """
        try:
            from quorum.execution.db import query_trades
            return query_trades(
                self._config, ticker=ticker, action=action, since=since, limit=limit,
            )
        except Exception:  # noqa: BLE001
            logger.debug("SQLite query_trades unavailable; falling back to JSONL")

        # JSONL fallback
        if not self._log_path.exists():
            return []
        lines = self._log_path.read_text().strip().split("\n")
        results = []
        for line in reversed(lines):
            if not line.strip():
                continue
            try:
                t = json.loads(line)
            except json.JSONDecodeError:
                continue
            if ticker and t.get("ticker") != ticker:
                continue
            if action and t.get("action_taken") != action:
                continue
            if since and str(t.get("timestamp", "")) < since:
                continue
            results.append(t)
            if len(results) >= limit:
                break
        return results

    # ── internal ──

    def _append(self, data: dict) -> None:
        # ---- JSONL (backward compat) ----
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, default=str) + "\n")

        # ---- SQLite ----
        try:
            conn = self._get_db()
            req = data.get("order_request") or {}
            res = data.get("order_result") or {}
            with conn:
                conn.execute(
                    "INSERT INTO trades "
                    "(timestamp, ticker, signal, action_taken, side, quantity, "
                    " fill_price, account_before, account_after, reason, raw_json) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(data.get("timestamp", "")),
                        data.get("ticker", ""),
                        data.get("signal", ""),
                        data.get("action_taken", ""),
                        req.get("side", ""),
                        req.get("quantity", 0),
                        res.get("filled_price"),
                        data.get("account_value_before"),
                        data.get("account_value_after"),
                        data.get("reason") or "",
                        json.dumps(data, default=str),
                    ),
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("SQLite trade insert failed: %s", exc)
