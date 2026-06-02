"""SEC filings and 13F institutional holdings via edgartools.

Follows the congress.py pattern: file-based cache, lazy sync, direct MCP import.
Degrades gracefully if edgartools is not installed.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_QUORUM_HOME = Path(os.environ.get("QUORUM_HOME", Path.home() / ".quorum"))
_CACHE_DIR = _QUORUM_HOME / "sec_cache"
_CACHE_TTL = 86400  # 1 day


def _cache_path(ticker: str, suffix: str) -> Path:
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    # Strip path separators / unexpected chars so a ticker can't escape the cache dir.
    safe = "".join(c for c in ticker.upper() if c.isalnum() or c in ".-=")[:15] or "UNKNOWN"
    return _CACHE_DIR / f"{safe}_{suffix}.json"


def _load_cache(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        cached_at = data.get("cached_at", "")
        if cached_at:
            age = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds()
            if age < _CACHE_TTL:
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


def get_sec_filings(ticker: str, filing_type: str = "all", limit: int = 5) -> str:
    """Get recent SEC filings (10-K, 10-Q, 8-K) for a ticker.

    Requires: pip install edgartools
    """
    cache = _load_cache(_cache_path(ticker, "filings"))
    if cache and cache.get("filings"):
        filings = cache["filings"]
        if filing_type != "all":
            filings = [f for f in filings if f.get("form") == filing_type]
        return _format_filings(ticker, filings[:limit])

    try:
        from edgar import Company, set_identity
    except ImportError:
        return f"SEC filings unavailable — install edgartools: pip install edgartools"

    try:
        # SEC EDGAR asks for a contact identity in the request header. Set
        # QUORUM_SEC_IDENTITY in your .env (e.g. "your-name you@example.com").
        set_identity(os.environ.get("QUORUM_SEC_IDENTITY", "quorum-research research@example.com"))
        company = Company(ticker.upper())
        filings_obj = company.get_filings(form=["10-K", "10-Q", "8-K"]).latest(20)

        filings = []
        for f in filings_obj:
            filings.append({
                "form": f.form,
                "filed": str(f.filing_date),
                "description": getattr(f, "description", "") or f.form,
                "accession": getattr(f, "accession_no", ""),
            })

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
    """Get institutional holders from SEC 13F filings.

    Requires: pip install edgartools
    """
    cache = _load_cache(_cache_path(ticker, "13f"))
    if cache and cache.get("holders"):
        return _format_holders(ticker, cache["holders"][:limit])

    try:
        from edgar import Company
    except ImportError:
        return f"13F data unavailable — install edgartools: pip install edgartools"

    try:
        company = Company(ticker.upper())
        holders = []

        # Get institutional holders from yfinance as primary source
        # (edgartools 13F search by held-ticker is complex; yfinance is simpler)
        try:
            import yfinance as yf
            t = yf.Ticker(ticker.upper())
            inst = t.institutional_holders
            if inst is not None and not inst.empty:
                for _, row in inst.head(limit).iterrows():
                    holders.append({
                        "holder": str(row.get("Holder", "")),
                        "shares": int(row.get("Shares", 0)),
                        "value": float(row.get("Value", 0)),
                        "pct_held": float(row.get("pctHeld", 0)) if "pctHeld" in row else None,
                        "date": str(row.get("Date Reported", "")),
                    })
        except Exception:
            pass

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
