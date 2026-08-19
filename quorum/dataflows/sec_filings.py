"""SEC filings via data.sec.gov's REST API directly — no edgartools needed.

data.sec.gov is free and keyless (just a descriptive User-Agent header,
per SEC's own request), so there's no dependency to install and nothing
that can silently be missing. 13F/institutional-holdings data comes from
yfinance instead of real 13F-HR filing XML (that requires parsing every
institutional filer's own filing, a much bigger undertaking than a ticker-
keyed lookup supports) — this was already true before, just gated behind
a since-removed edgartools import that made it dead code.

Follows congress.py's pattern: file-based cache, lazy sync, direct MCP
import.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

import requests

logger = logging.getLogger(__name__)

_QUORUM_HOME = Path(os.environ.get("QUORUM_HOME", Path.home() / ".quorum"))
_CACHE_DIR = _QUORUM_HOME / "sec_cache"
_CACHE_TTL = 86400  # 1 day

_TICKER_MAP_PATH = _CACHE_DIR / "_ticker_cik_map.json"
_TICKER_MAP_TTL = 7 * 86400  # CIK assignments change rarely
_TICKER_MAP_URL = "https://www.sec.gov/files/company_tickers.json"
_SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik:010d}.json"


def _headers() -> dict:
    # SEC asks every data.sec.gov caller to identify itself in the
    # User-Agent (name + contact) — set QUORUM_SEC_IDENTITY in your .env.
    return {"User-Agent": os.environ.get("QUORUM_SEC_IDENTITY", "quorum-research research@example.com")}


def _cache_path(ticker: str, suffix: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Strip path separators / unexpected chars so a ticker can't escape the cache dir.
    safe = "".join(c for c in ticker.upper() if c.isalnum() or c in ".-=")[:15] or "UNKNOWN"
    return _CACHE_DIR / f"{safe}_{suffix}.json"


def _load_cache(path: Path, ttl: int = _CACHE_TTL) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = data.get("cached_at", "")
        if cached_at:
            age = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds()
            if age < ttl:
                return data
    except Exception:
        pass
    return None


def _save_cache(path: Path, data: dict) -> None:
    try:
        data["cached_at"] = datetime.now().isoformat()
        path.write_text(json.dumps(data, default=str))
    except Exception as e:
        logger.warning(f"SEC cache save failed: {e}")


def _ticker_to_cik(ticker: str) -> Optional[int]:
    """Resolve a ticker to its SEC CIK via the bulk company_tickers.json
    map, cached locally since it rarely changes."""
    cache = _load_cache(_TICKER_MAP_PATH, ttl=_TICKER_MAP_TTL)
    mapping = cache.get("map") if cache else None

    if mapping is None:
        try:
            resp = requests.get(_TICKER_MAP_URL, headers=_headers(), timeout=15.0)
            resp.raise_for_status()
            raw = resp.json()  # {"0": {"cik_str": 320193, "ticker": "AAPL", ...}, ...}
            mapping = {row["ticker"].upper(): row["cik_str"] for row in raw.values()}
            _save_cache(_TICKER_MAP_PATH, {"map": mapping})
        except Exception as e:
            logger.warning("Failed to fetch SEC ticker->CIK map: %s", e)
            return None

    return mapping.get(ticker.upper())


def get_sec_filings(ticker: str, filing_type: str = "all", limit: int = 5) -> str:
    """Get recent SEC filings (10-K, 10-Q, 8-K) for a ticker via data.sec.gov."""
    cache = _load_cache(_cache_path(ticker, "filings"))
    if cache and cache.get("filings"):
        filings = cache["filings"]
        if filing_type != "all":
            filings = [f for f in filings if f.get("form") == filing_type]
        return _format_filings(ticker, filings[:limit])

    cik = _ticker_to_cik(ticker)
    if cik is None:
        return f"No SEC CIK found for ticker '{ticker}' — may not be a US-listed filer"

    try:
        resp = requests.get(_SUBMISSIONS_URL.format(cik=cik), headers=_headers(), timeout=15.0)
        resp.raise_for_status()
        recent = resp.json().get("filings", {}).get("recent", {})

        forms = recent.get("form", [])
        dates = recent.get("filingDate", [])
        descriptions = recent.get("primaryDocDescription", [])
        accessions = recent.get("accessionNumber", [])

        filings = [
            {
                "form": forms[i],
                "filed": dates[i] if i < len(dates) else "",
                "description": descriptions[i] if i < len(descriptions) and descriptions[i] else forms[i],
                "accession": accessions[i] if i < len(accessions) else "",
            }
            for i in range(len(forms))
            if forms[i] in ("10-K", "10-Q", "8-K")
        ][:20]

        _save_cache(_cache_path(ticker, "filings"), {"filings": filings})

        if filing_type != "all":
            filings = [f for f in filings if f.get("form") == filing_type]
        return _format_filings(ticker, filings[:limit])

    except Exception as e:
        return f"Error fetching SEC filings for {ticker}: {e}"


def _format_filings(ticker: str, filings: list) -> str:
    if not filings:
        return f"No SEC filings found for {ticker.upper()}"

    lines = [f"SEC Filings — {ticker.upper()} (last {len(filings)})"]
    lines.append("-" * 50)
    for f in filings:
        lines.append(f"{f['filed']}  {f['form']:6s}  {f['description']}")
    return "\n".join(lines)


def get_13f_holdings(ticker: str, limit: int = 10) -> str:
    """Get institutional holders for a ticker.

    Sourced from yfinance's institutional_holders (a snapshot derived from
    13F aggregation), not raw 13F-HR filing XML — see module docstring.
    """
    cache = _load_cache(_cache_path(ticker, "13f"))
    if cache and cache.get("holders"):
        return _format_holders(ticker, cache["holders"][:limit])

    try:
        import yfinance as yf
        t = yf.Ticker(ticker.upper())
        inst = t.institutional_holders
        holders = []
        if inst is not None and not inst.empty:
            for _, row in inst.head(limit).iterrows():
                holders.append({
                    "holder": str(row.get("Holder", "")),
                    "shares": int(row.get("Shares", 0)),
                    "value": float(row.get("Value", 0)),
                    "pct_held": float(row.get("pctHeld", 0)) if "pctHeld" in row else None,
                    "date": str(row.get("Date Reported", "")),
                })

        if holders:
            _save_cache(_cache_path(ticker, "13f"), {"holders": holders})
            return _format_holders(ticker, holders[:limit])

        return f"No institutional holder data found for {ticker.upper()}"

    except Exception as e:
        return f"Error fetching 13F data for {ticker}: {e}"


def _format_holders(ticker: str, holders: list) -> str:
    if not holders:
        return f"No institutional holders found for {ticker.upper()}"

    lines = [f"Institutional Holdings — {ticker.upper()} (top {len(holders)})"]
    lines.append("-" * 60)
    for h in holders:
        shares_str = f"{h['shares']:>12,}" if h.get("shares") else "N/A"
        value_str = f"${h['value']:>14,.0f}" if h.get("value") else "N/A"
        pct_str = f"{h['pct_held']:.2%}" if h.get("pct_held") else ""
        lines.append(f"  {h['holder'][:35]:<35s}  {shares_str} shares  {value_str}  {pct_str}")
    return "\n".join(lines)
