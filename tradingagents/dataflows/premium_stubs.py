"""Stub interfaces for premium/paid data sources.

These classes define the API surface for data sources that require
paid subscriptions.  Each stub raises ``NotImplementedError`` with
instructions on which provider and API key to use.

To implement a stub:
1. Create a new module (e.g., ``unusual_whales.py``)
2. Implement the same interface as the stub class
3. Register it in ``interface.py`` under the ``premium_data`` category
4. Add vendor routing so it falls back gracefully
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class OptionsFlowProvider:
    """Unusual options activity as a smart money signal.

    Recommended providers:
    - Unusual Whales (unusualwhales.com) — REST API
    - CBOE DataShop (datashop.cboe.com) — historical options data

    Expected return format: plaintext summary of unusual options activity
    including strike, expiry, volume, open interest, and premium.
    """

    def get_options_flow(self, ticker: str, min_premium: float = 100_000) -> str:
        raise NotImplementedError(
            "Options flow data requires a paid subscription. "
            "Set UNUSUAL_WHALES_API_KEY and implement unusual_whales.py, "
            "then register in interface.py under 'premium_data'."
        )


class DarkPoolProvider:
    """Institutional accumulation/distribution via dark pool prints.

    Recommended providers:
    - FINRA ADF (Alternative Display Facility) — delayed feed
    - Quandl / Nasdaq — FINRA short volume

    Expected return format: plaintext with dark pool volume,
    percentage of total volume, and large block prints.
    """

    def get_dark_pool_volume(self, ticker: str) -> str:
        raise NotImplementedError(
            "Dark pool data requires a FINRA data subscription. "
            "Implement finra_dark_pool.py and register in interface.py."
        )


class ShortInterestProvider:
    """Short interest and borrow rates for squeeze detection.

    Recommended providers:
    - ORTEX (ortex.com) — real-time short interest
    - S3 Partners — institutional short analytics

    Expected return format: plaintext with short interest %,
    days to cover, borrow rate, and utilization rate.
    """

    def get_short_interest(self, ticker: str) -> str:
        raise NotImplementedError(
            "Short interest data requires an ORTEX or S3 Partners subscription. "
            "Set ORTEX_API_KEY and implement ortex_short.py."
        )


class EarningsWhispersProvider:
    """Buy-side earnings expectations vs street consensus.

    Recommended providers:
    - EstimateHub — whisper numbers
    - Estimize — crowdsourced estimates

    Expected return format: plaintext with whisper EPS, consensus EPS,
    difference, and historical beat/miss rate.
    """

    def get_whisper_number(self, ticker: str) -> str:
        raise NotImplementedError(
            "Earnings whisper data requires an EstimateHub subscription. "
            "Set ESTIMATEHUB_API_KEY and implement estimatehub.py."
        )


class FundFlowProvider:
    """ETF and mutual fund inflow/outflow data for sector rotation.

    Recommended providers:
    - ICI (Investment Company Institute) — weekly fund flows
    - EPFR Global — daily fund flows

    Expected return format: plaintext with net flows by sector,
    weekly/monthly trends, and largest inflow/outflow funds.
    """

    def get_fund_flows(self, sector: str = "", period: str = "weekly") -> str:
        raise NotImplementedError(
            "Fund flow data requires an ICI or EPFR subscription. "
            "Implement fund_flows.py and register in interface.py."
        )


class CDSSpreadsProvider:
    """Credit default swap spreads as distress signal.

    Recommended providers:
    - Bloomberg Terminal — CDS pricing
    - Markit (IHS Markit) — CDS data via API

    Expected return format: plaintext with 5Y CDS spread,
    change over time, and distress threshold comparison.
    """

    def get_cds_spread(self, entity: str) -> str:
        raise NotImplementedError(
            "CDS spread data requires a Bloomberg or Markit subscription. "
            "Implement cds_data.py and register in interface.py."
        )
