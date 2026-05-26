"""Congressional stock trade tracker using House clerk STOCK Act disclosures.

Fetches Periodic Transaction Reports (PTRs) from the official House clerk
XML index, downloads and parses the PDFs with pypdf, and caches structured
trade data as a local JSON file.  No API key required — this is public
government data.

Source: https://disclosures-clerk.house.gov/FinancialDisclosure
"""

from __future__ import annotations

import io
import json
import logging
import os
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

_TRADINGAGENTS_HOME = os.environ.get(
    "TRADINGAGENTS_HOME", os.path.join(os.path.expanduser("~"), ".tradingagents")
)
_CACHE_FILE = os.path.join(_TRADINGAGENTS_HOME, "congress_trades.json")
_SYNC_INTERVAL = 86400  # re-sync after 24 hours

_XML_URL = "https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.xml"
_PDF_URL = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf"
_UA = "tradingagents/0.2 (+https://github.com/TauricResearch/TradingAgents)"

# Regex to extract transactions from PTR PDF text
_TX_RE = re.compile(
    r'\((?P<ticker>[A-Z]{1,5})\)\s*\[(?:ST|OP|AB|OT|EF)\]\s*'
    r'(?P<tx_type>P|S \(partial\)|S|E)\s+'
    r'(?P<date>\d{2}/\d{2}/\d{4})'
    r'(?P<notif_date>\d{2}/\d{2}/\d{4})'
    r'(?P<amount>\$[\d,]+(?:\s*-\s*\$[\d,]+)?)',
)
_NAME_RE = re.compile(r'Name:\s*(.+)')


def _load_cache() -> dict:
    if os.path.exists(_CACHE_FILE):
        with open(_CACHE_FILE) as f:
            return json.load(f)
    return {"synced_at": None, "trades": [], "processed_docs": []}


def _save_cache(cache: dict) -> None:
    os.makedirs(os.path.dirname(_CACHE_FILE), exist_ok=True)
    with open(_CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def _fetch_url(url: str, timeout: float = 15.0, retries: int = 3) -> bytes:
    req = Request(url, headers={"User-Agent": _UA})
    for attempt in range(retries):
        try:
            with urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except (HTTPError, URLError, TimeoutError, ConnectionError, OSError) as exc:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            logger.debug("Retry %d for %s after %s (wait %ds)", attempt + 1, url, exc, wait)
            time.sleep(wait)
    raise RuntimeError("unreachable")


def _parse_ptr_pdf(doc_id: str, year: int) -> list[dict]:
    """Download and parse a single PTR PDF.  Returns list of trade dicts."""
    from pypdf import PdfReader

    url = _PDF_URL.format(year=year, doc_id=doc_id)
    try:
        pdf_bytes = _fetch_url(url, timeout=20.0)
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("Failed to download PTR %s: %s", doc_id, exc)
        return []

    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        full_text = "\n".join(page.extract_text() or "" for page in reader.pages)
    except Exception as exc:
        logger.warning("Failed to parse PDF %s: %s", doc_id, exc)
        return []

    # Extract member name
    name_match = _NAME_RE.search(full_text)
    member = name_match.group(1).strip() if name_match else "Unknown"

    # Extract state/district
    state_match = re.search(r'State/District:\s*(\S+)', full_text)
    state = state_match.group(1).strip() if state_match else ""

    trades = []
    for m in _TX_RE.finditer(full_text):
        # Parse amount range
        amount_str = m.group("amount").replace("\n", "").strip()
        amounts = re.findall(r'\$([\d,]+)', amount_str)
        amount_low = int(amounts[0].replace(",", "")) if amounts else 0
        amount_high = int(amounts[1].replace(",", "")) if len(amounts) > 1 else amount_low

        tx_raw = m.group("tx_type").strip()
        tx_label = {
            "P": "Purchase", "S": "Sale",
            "S (partial)": "Partial Sale", "E": "Exchange",
        }.get(tx_raw, tx_raw)

        # Parse date to ISO format
        date_str = m.group("date")
        try:
            date_iso = datetime.strptime(date_str, "%m/%d/%Y").strftime("%Y-%m-%d")
        except ValueError:
            date_iso = date_str

        trades.append({
            "member": member,
            "state": state,
            "ticker": m.group("ticker"),
            "tx_type": tx_label,
            "date": date_iso,
            "amount_low": amount_low,
            "amount_high": amount_high,
            "amount_str": amount_str,
            "doc_id": doc_id,
        })

    return trades


def sync_house_trades(year: int | None = None) -> int:
    """Fetch the House clerk XML index and parse new PTR filings.

    Returns the number of new trades added.
    """
    if year is None:
        year = datetime.now().year

    cache = _load_cache()
    processed = set(cache.get("processed_docs", []))

    # Fetch XML index
    try:
        xml_bytes = _fetch_url(_XML_URL.format(year=year))
    except (HTTPError, URLError, TimeoutError) as exc:
        logger.warning("Failed to fetch House clerk XML: %s", exc)
        return 0

    root = ET.fromstring(xml_bytes)
    ptrs = [
        m for m in root.findall("Member")
        if (m.find("FilingType") is not None and m.find("FilingType").text == "P")
    ]

    new_trades = 0
    for member_el in ptrs:
        doc_id = member_el.find("DocID").text
        if doc_id in processed:
            continue

        trades = _parse_ptr_pdf(doc_id, year)
        cache["trades"].extend(trades)
        processed.add(doc_id)
        new_trades += len(trades)

        # Rate limit: 1s between PDF downloads (gov server drops fast requests)
        time.sleep(1.0)

    cache["processed_docs"] = list(processed)
    cache["synced_at"] = datetime.now().isoformat()
    _save_cache(cache)

    logger.info("Congress sync: %d new trades from %d new filings", new_trades, len(ptrs) - len(processed - set(cache["processed_docs"])))
    return new_trades


def _ensure_synced() -> dict:
    """Load cache and trigger sync if stale (>24h)."""
    cache = _load_cache()
    synced_at = cache.get("synced_at")

    if synced_at:
        try:
            last_sync = datetime.fromisoformat(synced_at)
            if (datetime.now() - last_sync).total_seconds() < _SYNC_INTERVAL:
                return cache
        except ValueError:
            pass

    sync_house_trades()
    return _load_cache()


def get_congress_trades(ticker: str, days: int = 90) -> str:
    """Get congressional trades for a ticker.  Returns formatted plaintext."""
    ticker = ticker.upper()
    try:
        cache = _ensure_synced()
    except Exception as exc:
        logger.warning("Congress sync failed: %s", exc)
        return f"<congressional trade data unavailable: {type(exc).__name__}>"

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    trades = [
        t for t in cache.get("trades", [])
        if t["ticker"] == ticker and t["date"] >= cutoff
    ]

    if not trades:
        return (
            f"<no congressional trades found for {ticker} in the past {days} days>\n"
            f"Source: House Clerk STOCK Act disclosures (disclosures-clerk.house.gov)"
        )

    trades.sort(key=lambda t: t["date"], reverse=True)

    # Count unique members and trade directions
    members = set(t["member"] for t in trades)
    purchases = sum(1 for t in trades if "Purchase" in t["tx_type"])
    sales = sum(1 for t in trades if "Sale" in t["tx_type"])

    lines = [
        f"Congressional Trades — {ticker} (last {days} days)",
        f"{len(trades)} transactions by {len(members)} member(s):",
        "",
    ]
    for t in trades:
        lines.append(
            f"  {t['date']}  {t['tx_type']:15} {t['member'][:30]:30} {t['amount_str']}"
        )

    lines.append("")
    lines.append(f"Summary: {purchases} purchase(s), {sales} sale(s) by {len(members)} member(s)")
    lines.append("Source: House Clerk STOCK Act disclosures")

    return "\n".join(lines)


def get_congress_summary(days: int = 30) -> str:
    """Overview of congressional trading activity.  Returns formatted plaintext."""
    try:
        cache = _ensure_synced()
    except Exception as exc:
        logger.warning("Congress sync failed: %s", exc)
        return f"<congressional trade data unavailable: {type(exc).__name__}>"

    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    recent = [t for t in cache.get("trades", []) if t["date"] >= cutoff]

    if not recent:
        return f"<no congressional trades in the past {days} days>"

    # Most traded tickers by member count
    ticker_members: dict[str, set] = {}
    ticker_counts: dict[str, int] = {}
    member_counts: dict[str, int] = {}

    for t in recent:
        tk = t["ticker"]
        ticker_members.setdefault(tk, set()).add(t["member"])
        ticker_counts[tk] = ticker_counts.get(tk, 0) + 1
        member_counts[t["member"]] = member_counts.get(t["member"], 0) + 1

    # Sort tickers by number of distinct members trading them
    top_tickers = sorted(
        ticker_members.items(), key=lambda x: len(x[1]), reverse=True
    )[:15]

    top_members = sorted(member_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    lines = [
        f"Congressional Trading Summary (last {days} days)",
        f"Total: {len(recent)} transactions by {len(member_counts)} members",
        "",
        "Most traded tickers (by # of members):",
    ]
    for tk, members in top_tickers:
        count = ticker_counts[tk]
        lines.append(f"  {tk:6} — {len(members)} member(s), {count} transaction(s)")

    lines.append("")
    lines.append("Most active members:")
    for member, count in top_members:
        lines.append(f"  {member[:35]:35} — {count} transaction(s)")

    lines.append("")
    lines.append("Source: House Clerk STOCK Act disclosures")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    if "--sync" in sys.argv:
        n = sync_house_trades()
        print(f"Synced {n} new trades")
    elif len(sys.argv) > 1:
        print(get_congress_trades(sys.argv[1]))
    else:
        print(get_congress_summary())
