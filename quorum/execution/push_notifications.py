"""Browser push notifications via VAPID web push.

Sends push notifications on trade execution, kill switch activation,
stop-loss triggers, and discovery scan results.

Requires ``pywebpush`` and VAPID keys configured in DEFAULT_CONFIG.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class PushNotificationService:
    """Send browser push notifications to subscribed clients.

    Subscriptions are stored in the execution SQLite database.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.config = config
        self._enabled = bool(config.get("push_notifications_enabled", False))
        self._vapid_private = config.get("vapid_private_key", "")
        self._vapid_public = config.get("vapid_public_key", "")
        self._vapid_email = config.get("vapid_claims_email", "")

    def _get_db(self):
        from quorum.execution.db import get_db
        return get_db(self.config)

    def subscribe(self, subscription_info: Dict[str, Any]) -> None:
        """Register a push subscription."""
        conn = self._get_db()
        endpoint = subscription_info.get("endpoint", "")
        keys = subscription_info.get("keys", {})
        conn.execute(
            "INSERT OR REPLACE INTO push_subscriptions (endpoint, keys_json) VALUES (?, ?)",
            (endpoint, json.dumps(keys)),
        )
        # Default preferences
        conn.execute(
            "INSERT OR IGNORE INTO notification_preferences "
            "(endpoint, on_trade, on_kill_switch, on_discovery, on_stop_loss) "
            "VALUES (?, 1, 1, 0, 1)",
            (endpoint,),
        )
        conn.commit()
        logger.info("Push subscription registered: %s", endpoint[:50])

    def unsubscribe(self, endpoint: str) -> None:
        """Remove a push subscription."""
        conn = self._get_db()
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))
        conn.execute("DELETE FROM notification_preferences WHERE endpoint = ?", (endpoint,))
        conn.commit()

    def update_preferences(self, endpoint: str, prefs: Dict[str, bool]) -> None:
        """Update notification preferences for a subscription."""
        conn = self._get_db()
        for key in ("on_trade", "on_kill_switch", "on_discovery", "on_stop_loss"):
            if key in prefs:
                conn.execute(
                    f"UPDATE notification_preferences SET {key} = ? WHERE endpoint = ?",
                    (int(prefs[key]), endpoint),
                )
        conn.commit()

    def send(self, title: str, body: str, tag: str = "trade") -> int:
        """Send a push notification to all subscribed clients.

        Only sends to clients whose preferences include the given tag.
        Returns the number of notifications sent.

        Tag mapping:
          - "trade" -> on_trade
          - "kill_switch" -> on_kill_switch
          - "discovery" -> on_discovery
          - "stop_loss" -> on_stop_loss
        """
        if not self._enabled:
            return 0

        if not self._vapid_private or not self._vapid_public:
            logger.debug("Push notifications enabled but VAPID keys not configured")
            return 0

        try:
            from pywebpush import webpush, WebPushException
        except ImportError:
            logger.debug("pywebpush not installed — push notifications unavailable")
            return 0

        pref_col = {
            "trade": "on_trade",
            "kill_switch": "on_kill_switch",
            "discovery": "on_discovery",
            "stop_loss": "on_stop_loss",
        }.get(tag, "on_trade")

        conn = self._get_db()
        rows = conn.execute(
            f"""SELECT s.endpoint, s.keys_json
                FROM push_subscriptions s
                JOIN notification_preferences p ON s.endpoint = p.endpoint
                WHERE p.{pref_col} = 1""",
        ).fetchall()

        payload = json.dumps({"title": title, "body": body, "tag": tag})
        vapid_claims = {"sub": f"mailto:{self._vapid_email}"}
        sent = 0

        for row in rows:
            try:
                keys = json.loads(row["keys_json"])
                subscription_info = {
                    "endpoint": row["endpoint"],
                    "keys": keys,
                }
                webpush(
                    subscription_info=subscription_info,
                    data=payload,
                    vapid_private_key=self._vapid_private,
                    vapid_claims=vapid_claims,
                )
                sent += 1
            except Exception as e:
                logger.debug("Push failed for %s: %s", row["endpoint"][:30], e)
                # Remove stale subscriptions
                if "410" in str(e) or "404" in str(e):
                    self.unsubscribe(row["endpoint"])

        logger.info("Push notifications sent: %d/%d (%s)", sent, len(rows), tag)
        return sent

    def notify_trade(self, ticker: str, signal: str, side: str, quantity: int, price: float) -> int:
        """Send a trade execution notification."""
        return self.send(
            title=f"Trade Executed: {ticker}",
            body=f"{side.upper()} {quantity} {ticker} @ ${price:,.2f} (Signal: {signal})",
            tag="trade",
        )

    def notify_kill_switch(self, reason: str = "") -> int:
        """Send a kill switch activation notification."""
        return self.send(
            title="KILL SWITCH ACTIVATED",
            body=f"All trading halted. {reason}".strip(),
            tag="kill_switch",
        )

    def notify_stop_loss(self, ticker: str, price: float, quantity: int) -> int:
        """Send a stop-loss trigger notification."""
        return self.send(
            title=f"Stop-Loss Triggered: {ticker}",
            body=f"SELL {quantity} {ticker} @ ${price:,.2f}",
            tag="stop_loss",
        )

    def notify_discovery(self, ticker: str, reason: str) -> int:
        """Send a discovery scan notification."""
        return self.send(
            title=f"New Opportunity: {ticker}",
            body=reason,
            tag="discovery",
        )
