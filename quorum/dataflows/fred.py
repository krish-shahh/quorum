"""FRED (Federal Reserve Economic Data) — free, keyed via FRED_API_KEY.

Supplies the macro series regime_gate.yaml's design comment flagged as
wanted (VXN/DFII10) but never wired up because "the engine's DataFeed
can't pull FRED series yet." This closes that gap at the data layer —
CrossAssetRegimeDetector exposes the values, but its _classify() decision
logic is untouched; wiring these into an actual regime decision is a
strategy-design call for later, not a data-availability one.

Best-effort: no FRED_API_KEY (free, instant signup at
fredaccount.stlouisfed.org) or a failed request returns None rather than
raising — every caller here treats this as optional enrichment.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import requests

from .cache import cached_config

logger = logging.getLogger(__name__)

_FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"


@cached_config("regime")
def get_fred_series_latest(series_id: str) -> Optional[Dict[str, Any]]:
    """Latest value + %change vs. ~20 observations back for one FRED
    series. Returns None (never raises) if FRED_API_KEY is unset or the
    request fails, so callers can unconditionally check truthiness."""
    key = os.environ.get("FRED_API_KEY")
    if not key:
        return None

    try:
        resp = requests.get(
            _FRED_BASE,
            params={
                "series_id": series_id, "api_key": key, "file_type": "json",
                "sort_order": "desc", "limit": 25,
            },
            timeout=8.0,
        )
        resp.raise_for_status()
        obs = [o for o in resp.json().get("observations", []) if o.get("value") not in (None, ".")]
        if not obs:
            return None

        latest = float(obs[0]["value"])
        change_20d = None
        if len(obs) > 20:
            prior = float(obs[20]["value"])
            change_20d = ((latest - prior) / prior * 100) if prior else None

        return {"value": latest, "date": obs[0]["date"], "change_20d_pct": change_20d}
    except Exception as e:
        logger.debug("FRED fetch failed for %s: %s", series_id, e)
        return None
