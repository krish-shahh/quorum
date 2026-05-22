"""Email, webhook, and unified alert manager for trading notifications.

Supports SMTP email alerts, Slack/Discord webhook alerts, configurable
thresholds, and daily portfolio summaries.
"""

from __future__ import annotations

import json
import logging
import smtplib
from datetime import date, datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from .schemas import ExecutionRecord, Position

logger = logging.getLogger(__name__)


class EmailAlerts:
    """Sends trading alerts via SMTP.

    Configuration (all via env vars or config dict):
        alert_email_from     – sender email address
        alert_email_to       – recipient email address (comma-separated for multiple)
        alert_smtp_host      – SMTP server hostname (default: smtp.gmail.com)
        alert_smtp_port      – SMTP port (default: 587)
        alert_smtp_user      – SMTP username
        alert_smtp_password  – SMTP password / app password
        alerts_enabled       – master toggle (default: False)
    """

    def __init__(self, config: Dict[str, Any]):
        self.enabled = bool(config.get("alerts_enabled", False))
        self.email_from = config.get("alert_email_from", "")
        self.email_to = config.get("alert_email_to", "")
        self.smtp_host = config.get("alert_smtp_host", "smtp.gmail.com")
        self.smtp_port = int(config.get("alert_smtp_port", 587))
        self.smtp_user = config.get("alert_smtp_user", "")
        self.smtp_password = config.get("alert_smtp_password", "")

    def send_pre_trade_alert(
        self,
        ticker: str,
        signal: str,
        final_decision: str,
        trade_date: str,
    ) -> None:
        """Send a summary of what the agents recommend before market open."""
        if not self.enabled:
            return

        subject = f"[TradingAgents] Pre-Trade Alert: {ticker} — {signal}"
        body = f"""Pre-Trade Analysis Summary
========================

Ticker: {ticker}
Date: {trade_date}
Signal: {signal}

Agent Decision:
{final_decision}

---
This is an automated alert from TradingAgents.
Review before market open. No orders have been placed yet.
"""
        self._send(subject, body)

    def send_post_trade_alert(
        self,
        ticker: str,
        record: ExecutionRecord,
    ) -> None:
        """Send a summary of what was executed and at what price."""
        if not self.enabled:
            return

        if record.order_request and record.order_result:
            order_detail = (
                f"Action: {record.order_request.side.value.upper()} "
                f"{record.order_request.quantity} shares\n"
                f"Fill Price: ${record.order_result.filled_price:.2f}\n"
                if record.order_result.filled_price
                else f"Action: {record.order_request.side.value.upper()} "
                     f"{record.order_request.quantity} shares\n"
                     f"Status: {record.order_result.status.value}\n"
            )
        else:
            order_detail = f"Action: {record.action_taken}\nReason: {record.reason or 'N/A'}\n"

        pnl_line = ""
        if record.account_value_before and record.account_value_after:
            diff = record.account_value_after - record.account_value_before
            pnl_line = f"Account Change: ${diff:+,.2f}\n"

        subject = f"[TradingAgents] Post-Trade: {ticker} — {record.action_taken.upper()}"
        body = f"""Post-Trade Execution Report
===========================

Ticker: {ticker}
Signal: {record.signal}
{order_detail}{pnl_line}
Account Value Before: ${record.account_value_before:,.2f}
Account Value After: ${record.account_value_after:,.2f}

---
This is an automated alert from TradingAgents.
"""
        self._send(subject, body)

    def send_intraday_snapshot(
        self,
        positions: List[Position],
        account_value: float,
        cash_balance: float,
    ) -> None:
        """Send an hourly snapshot of open positions."""
        if not self.enabled:
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        pos_lines = []
        for p in positions:
            pos_lines.append(
                f"  {p.ticker}: {p.quantity} shares @ ${p.avg_cost:.2f} "
                f"(MV: ${p.market_value:,.2f}, P&L: ${p.unrealized_pnl:+,.2f})"
            )
        pos_text = "\n".join(pos_lines) if pos_lines else "  No open positions"

        subject = f"[TradingAgents] Intra-Day Snapshot — {now}"
        body = f"""Intra-Day Position Snapshot
==========================

Time: {now}
Account Value: ${account_value:,.2f}
Cash Balance: ${cash_balance:,.2f}

Open Positions:
{pos_text}

---
This is an automated alert from TradingAgents.
"""
        self._send(subject, body)

    def send_kill_switch_alert(self, drawdown_pct: float, peak: float, current: float) -> None:
        """Send an urgent alert when the kill switch trips."""
        if not self.enabled:
            return

        subject = "[TradingAgents] KILL SWITCH ACTIVATED"
        body = f"""KILL SWITCH ACTIVATED
=====================

Drawdown: {drawdown_pct:.1f}%
Peak Account Value: ${peak:,.2f}
Current Account Value: ${current:,.2f}

ALL TRADING HAS BEEN HALTED.

To resume trading, manually reset the kill switch:
  tradingagents reset-kill-switch

---
This is an URGENT automated alert from TradingAgents.
"""
        self._send(subject, body)

    def _send(self, subject: str, body: str) -> None:
        if not self.email_from or not self.email_to:
            logger.warning("Email alerts enabled but from/to not configured — skipping")
            return

        recipients = [r.strip() for r in self.email_to.split(",")]

        msg = MIMEMultipart()
        msg["From"] = self.email_from
        msg["To"] = ", ".join(recipients)
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        try:
            with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
                server.starttls()
                if self.smtp_user and self.smtp_password:
                    server.login(self.smtp_user, self.smtp_password)
                server.sendmail(self.email_from, recipients, msg.as_string())
            logger.info("Email alert sent: %s", subject)
        except Exception as exc:
            logger.error("Failed to send email alert: %s", exc)


class WebhookAlerts:
    """Sends trading alerts via Slack-format webhooks.

    Also works with Discord's ``/slack`` compatibility endpoint.  Messages
    are formatted using Slack Block Kit JSON (sections, dividers, fields).

    Configuration:
        alert_slack_webhook  -- Slack or Discord webhook URL
        alerts_enabled       -- master toggle (default: False)
    """

    def __init__(self, config: Dict[str, Any]):
        self.enabled = bool(config.get("alerts_enabled", False))
        self.webhook_url: str = config.get("alert_slack_webhook", "")

    # ------------------------------------------------------------------
    # Public methods mirror EmailAlerts
    # ------------------------------------------------------------------

    def send_pre_trade_alert(
        self,
        ticker: str,
        signal: str,
        final_decision: str,
        trade_date: str,
    ) -> None:
        if not self.enabled:
            return

        blocks = [
            self._header(f":chart_with_upwards_trend: Pre-Trade Alert: {ticker} — {signal}"),
            self._divider(),
            self._fields([
                ("Ticker", ticker),
                ("Date", trade_date),
                ("Signal", signal),
            ]),
            self._section(f"*Agent Decision:*\n{self._truncate(final_decision)}"),
            self._context("Automated alert from TradingAgents. Review before market open."),
        ]
        self._send(blocks)

    def send_post_trade_alert(
        self,
        ticker: str,
        record: ExecutionRecord,
    ) -> None:
        if not self.enabled:
            return

        if record.order_request and record.order_result:
            action = record.order_request.side.value.upper()
            qty = record.order_request.quantity
            price = record.order_result.filled_price
            detail = f"{action} {qty} shares"
            if price:
                detail += f" @ ${price:.2f}"
            else:
                detail += f" — status: {record.order_result.status.value}"
        else:
            detail = f"{record.action_taken} — {record.reason or 'N/A'}"

        fields = [
            ("Ticker", ticker),
            ("Signal", record.signal),
            ("Execution", detail),
        ]
        if record.account_value_before is not None and record.account_value_after is not None:
            diff = record.account_value_after - record.account_value_before
            fields.append(("Account Change", f"${diff:+,.2f}"))
            fields.append(("Account Before", f"${record.account_value_before:,.2f}"))
            fields.append(("Account After", f"${record.account_value_after:,.2f}"))

        blocks = [
            self._header(f":white_check_mark: Post-Trade: {ticker} — {record.action_taken.upper()}"),
            self._divider(),
            self._fields(fields),
            self._context("Automated alert from TradingAgents."),
        ]
        self._send(blocks)

    def send_intraday_snapshot(
        self,
        positions: List[Position],
        account_value: float,
        cash_balance: float,
    ) -> None:
        if not self.enabled:
            return

        now = datetime.now().strftime("%Y-%m-%d %H:%M")
        pos_lines = []
        for p in positions:
            pos_lines.append(
                f"`{p.ticker}` {p.quantity} shares @ ${p.avg_cost:.2f}  "
                f"MV: ${p.market_value:,.2f}  P&L: ${p.unrealized_pnl:+,.2f}"
            )
        pos_text = "\n".join(pos_lines) if pos_lines else "_No open positions_"

        blocks = [
            self._header(f":bar_chart: Intra-Day Snapshot — {now}"),
            self._divider(),
            self._fields([
                ("Account Value", f"${account_value:,.2f}"),
                ("Cash Balance", f"${cash_balance:,.2f}"),
            ]),
            self._section(f"*Open Positions:*\n{pos_text}"),
            self._context("Automated alert from TradingAgents."),
        ]
        self._send(blocks)

    def send_kill_switch_alert(self, drawdown_pct: float, peak: float, current: float) -> None:
        if not self.enabled:
            return

        blocks = [
            self._header(":rotating_light: KILL SWITCH ACTIVATED"),
            self._divider(),
            self._fields([
                ("Drawdown", f"{drawdown_pct:.1f}%"),
                ("Peak Value", f"${peak:,.2f}"),
                ("Current Value", f"${current:,.2f}"),
            ]),
            self._section(
                "*ALL TRADING HAS BEEN HALTED.*\n"
                "Run `tradingagents reset-kill-switch` to resume."
            ),
            self._context("URGENT automated alert from TradingAgents."),
        ]
        self._send(blocks)

    # ------------------------------------------------------------------
    # Block Kit helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _header(text: str) -> Dict[str, Any]:
        return {"type": "header", "text": {"type": "plain_text", "text": text, "emoji": True}}

    @staticmethod
    def _divider() -> Dict[str, Any]:
        return {"type": "divider"}

    @staticmethod
    def _section(text: str) -> Dict[str, Any]:
        return {"type": "section", "text": {"type": "mrkdwn", "text": text}}

    @staticmethod
    def _fields(pairs: List[tuple]) -> Dict[str, Any]:
        fields = []
        for label, value in pairs:
            fields.append({"type": "mrkdwn", "text": f"*{label}:*\n{value}"})
        return {"type": "section", "fields": fields}

    @staticmethod
    def _context(text: str) -> Dict[str, Any]:
        return {"type": "context", "elements": [{"type": "mrkdwn", "text": text}]}

    @staticmethod
    def _truncate(text: str, max_len: int = 2800) -> str:
        """Slack blocks have a ~3000 char limit per text field."""
        if len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _send(self, blocks: List[Dict[str, Any]]) -> None:
        if not self.webhook_url:
            logger.warning("Webhook alerts enabled but no URL configured — skipping")
            return

        payload = {"blocks": blocks}
        try:
            resp = requests.post(
                self.webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
                timeout=10,
            )
            if resp.status_code not in (200, 204):
                logger.error(
                    "Webhook alert failed (HTTP %d): %s", resp.status_code, resp.text[:200],
                )
            else:
                logger.info("Webhook alert sent")
        except Exception as exc:
            logger.error("Failed to send webhook alert: %s", exc)


class AlertManager:
    """Unified alert router that dispatches to email and/or webhook channels.

    Also supports:
        - Minimum trade-value threshold (skip small alerts)
        - Signal allow-list (only alert on specific signals)
        - Daily portfolio summary
    """

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.email = EmailAlerts(config)
        self.webhook = WebhookAlerts(config)

        # Threshold: minimum trade dollar value to alert on (0 = alert on all)
        self.min_trade_value: float = float(config.get("alert_min_trade_value", 0))

        # Signal allow-list: empty list means alert on every signal
        self.alert_on_signals: List[str] = list(config.get("alert_on_signals", []))

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_alert_signal(self, signal: str) -> bool:
        """Return True if *signal* passes the allow-list filter."""
        if not self.alert_on_signals:
            return True  # empty list = all signals
        return signal in self.alert_on_signals

    def _should_alert_value(self, record: Optional[ExecutionRecord] = None) -> bool:
        """Return True if the trade value exceeds the minimum threshold."""
        if self.min_trade_value <= 0:
            return True
        if record is None:
            return True  # no record to check — let it through
        if record.order_request and record.order_result and record.order_result.filled_price:
            trade_value = record.order_request.quantity * record.order_result.filled_price
            return trade_value >= self.min_trade_value
        return True  # can't compute — let it through

    # ------------------------------------------------------------------
    # Public methods (same signatures as EmailAlerts)
    # ------------------------------------------------------------------

    def send_pre_trade_alert(
        self,
        ticker: str,
        signal: str,
        final_decision: str,
        trade_date: str,
    ) -> None:
        if not self._should_alert_signal(signal):
            logger.debug("Pre-trade alert skipped: signal %r not in allow-list", signal)
            return

        self.email.send_pre_trade_alert(ticker, signal, final_decision, trade_date)
        self.webhook.send_pre_trade_alert(ticker, signal, final_decision, trade_date)

    def send_post_trade_alert(
        self,
        ticker: str,
        record: ExecutionRecord,
    ) -> None:
        if not self._should_alert_signal(record.signal):
            logger.debug("Post-trade alert skipped: signal %r not in allow-list", record.signal)
            return
        if not self._should_alert_value(record):
            logger.debug("Post-trade alert skipped: trade value below threshold")
            return

        self.email.send_post_trade_alert(ticker, record)
        self.webhook.send_post_trade_alert(ticker, record)

    def send_intraday_snapshot(
        self,
        positions: List[Position],
        account_value: float,
        cash_balance: float,
    ) -> None:
        self.email.send_intraday_snapshot(positions, account_value, cash_balance)
        self.webhook.send_intraday_snapshot(positions, account_value, cash_balance)

    def send_kill_switch_alert(self, drawdown_pct: float, peak: float, current: float) -> None:
        # Kill-switch alerts bypass all filters — always send.
        self.email.send_kill_switch_alert(drawdown_pct, peak, current)
        self.webhook.send_kill_switch_alert(drawdown_pct, peak, current)

    # ------------------------------------------------------------------
    # Daily summary
    # ------------------------------------------------------------------

    def send_daily_summary(
        self,
        positions: List[Position],
        account_value: float,
        cash_balance: float,
    ) -> None:
        """Compile today's trades from the JSONL log and send a portfolio summary.

        This reads the execution log, filters to today's entries, and sends
        a combined summary via all enabled channels.
        """
        today_str = date.today().isoformat()
        today_trades = self._load_todays_trades(today_str)

        # Compute day P&L from executed trades
        day_pnl = 0.0
        for t in today_trades:
            before = t.get("account_value_before")
            after = t.get("account_value_after")
            if before is not None and after is not None:
                day_pnl += after - before

        # Position summary
        pos_lines = []
        for p in positions:
            pos_lines.append(
                f"  {p.ticker}: {p.quantity} shares @ ${p.avg_cost:.2f} "
                f"(MV: ${p.market_value:,.2f}, P&L: ${p.unrealized_pnl:+,.2f})"
            )
        pos_text = "\n".join(pos_lines) if pos_lines else "  No open positions"

        # Trade summary
        trade_lines = []
        for t in today_trades:
            action = t.get("action_taken", "unknown")
            ticker = t.get("ticker", "?")
            signal = t.get("signal", "?")
            trade_lines.append(f"  {ticker}: {action.upper()} (signal: {signal})")
        trade_text = "\n".join(trade_lines) if trade_lines else "  No trades today"

        # --- Email ---
        if self.email.enabled:
            subject = f"[TradingAgents] Daily Summary — {today_str}"
            body = (
                f"Daily Portfolio Summary\n"
                f"======================\n\n"
                f"Date: {today_str}\n"
                f"Account Value: ${account_value:,.2f}\n"
                f"Cash Balance: ${cash_balance:,.2f}\n"
                f"Day P&L: ${day_pnl:+,.2f}\n\n"
                f"Open Positions:\n{pos_text}\n\n"
                f"Today's Trades ({len(today_trades)}):\n{trade_text}\n\n"
                f"---\n"
                f"This is an automated daily summary from TradingAgents.\n"
            )
            self.email._send(subject, body)

        # --- Webhook ---
        if self.webhook.enabled and self.webhook.webhook_url:
            # Slack-formatted position lines
            slack_pos = []
            for p in positions:
                slack_pos.append(
                    f"`{p.ticker}` {p.quantity} shares @ ${p.avg_cost:.2f}  "
                    f"MV: ${p.market_value:,.2f}  P&L: ${p.unrealized_pnl:+,.2f}"
                )
            slack_pos_text = "\n".join(slack_pos) if slack_pos else "_No open positions_"

            slack_trade = []
            for t in today_trades:
                action = t.get("action_taken", "unknown")
                ticker = t.get("ticker", "?")
                signal = t.get("signal", "?")
                slack_trade.append(f"`{ticker}` {action.upper()} (signal: {signal})")
            slack_trade_text = "\n".join(slack_trade) if slack_trade else "_No trades today_"

            blocks = [
                WebhookAlerts._header(f":ledger: Daily Summary — {today_str}"),
                WebhookAlerts._divider(),
                WebhookAlerts._fields([
                    ("Account Value", f"${account_value:,.2f}"),
                    ("Cash Balance", f"${cash_balance:,.2f}"),
                    ("Day P&L", f"${day_pnl:+,.2f}"),
                    ("Trades Today", str(len(today_trades))),
                ]),
                WebhookAlerts._divider(),
                WebhookAlerts._section(f"*Open Positions:*\n{slack_pos_text}"),
                WebhookAlerts._divider(),
                WebhookAlerts._section(f"*Today's Trades:*\n{slack_trade_text}"),
                WebhookAlerts._context("Automated daily summary from TradingAgents."),
            ]
            self.webhook._send(blocks)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_todays_trades(self, today_iso: str) -> List[Dict[str, Any]]:
        """Read the JSONL trade log and return entries whose timestamp matches *today_iso*."""
        log_path = Path(
            self.config.get(
                "execution_log_path",
                "~/.tradingagents/execution/trades.jsonl",
            )
        ).expanduser()

        if not log_path.exists():
            return []

        trades: List[Dict[str, Any]] = []
        try:
            with open(log_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = entry.get("timestamp", "")
                    # Timestamp may be ISO datetime string: "2026-01-15T09:30:00"
                    if isinstance(ts, str) and ts.startswith(today_iso):
                        trades.append(entry)
        except Exception as exc:
            logger.error("Failed to read trade log for daily summary: %s", exc)

        return trades
