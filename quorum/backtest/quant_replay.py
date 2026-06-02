"""Quant score historical replay for backtesting signal quality.

Replays technical + fundamental scores over a historical date range,
then computes Information Coefficient (IC) vs actual forward returns.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


def _compute_indicators_at(ohlcv: pd.DataFrame, idx: int) -> Dict[str, float]:
    """Compute technical indicators using data up to index `idx`.

    Uses the same indicator set as integration._fetch_indicators() but
    from a pre-downloaded DataFrame instead of live yfinance calls.
    """
    window = ohlcv.iloc[: idx + 1]
    if len(window) < 20:
        return {}

    close = window["Close"].values
    high = window["High"].values
    low = window["Low"].values
    volume = window["Volume"].values

    # RSI (14)
    deltas = np.diff(close[-15:])
    gains = np.where(deltas > 0, deltas, 0)
    losses = np.where(deltas < 0, -deltas, 0)
    avg_gain = np.mean(gains) if len(gains) > 0 else 0
    avg_loss = np.mean(losses) if len(losses) > 0 else 1e-9
    rs = avg_gain / avg_loss if avg_loss > 0 else 100
    rsi = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    if len(close) >= 26:
        ema12 = pd.Series(close).ewm(span=12).mean().iloc[-1]
        ema26 = pd.Series(close).ewm(span=26).mean().iloc[-1]
        macd_line = ema12 - ema26
        signal_line = pd.Series(close).ewm(span=12).mean().ewm(span=9).mean().iloc[-1]
        # Simplified: compute MACD histogram
        macd_series = pd.Series(close).ewm(span=12).mean() - pd.Series(close).ewm(span=26).mean()
        signal_series = macd_series.ewm(span=9).mean()
        macd_hist = float(macd_series.iloc[-1] - signal_series.iloc[-1])
    else:
        macd_line = 0
        signal_line = 0
        macd_hist = 0

    # SMA 50, 200
    sma50 = float(np.mean(close[-50:])) if len(close) >= 50 else float(np.mean(close))
    sma200 = float(np.mean(close[-200:])) if len(close) >= 200 else float(np.mean(close))

    # Bollinger Bands (20, 2)
    bb_window = close[-20:] if len(close) >= 20 else close
    bb_mean = float(np.mean(bb_window))
    bb_std = float(np.std(bb_window))
    bb_upper = bb_mean + 2 * bb_std
    bb_lower = bb_mean - 2 * bb_std
    bb_pctb = (close[-1] - bb_lower) / (bb_upper - bb_lower) if (bb_upper - bb_lower) > 0 else 0.5

    # ATR (14)
    if len(high) >= 15:
        tr = np.maximum(
            high[1:] - low[1:],
            np.maximum(np.abs(high[1:] - close[:-1]), np.abs(low[1:] - close[:-1])),
        )
        atr = float(np.mean(tr[-14:]))
    else:
        atr = 0

    # Volume
    avg_vol_20 = float(np.mean(volume[-20:])) if len(volume) >= 20 else float(np.mean(volume))
    vol_ratio = float(volume[-1] / avg_vol_20) if avg_vol_20 > 0 else 1.0

    return {
        "rsi": float(rsi),
        "macd": float(macd_line),
        "macd_signal": float(signal_line),
        "macd_histogram": float(macd_hist),
        "sma50": sma50,
        "sma200": sma200,
        "bb_upper": bb_upper,
        "bb_lower": bb_lower,
        "bb_pctb": float(bb_pctb),
        "atr": atr,
        "close": float(close[-1]),
        "volume": float(volume[-1]),
        "avg_volume_20d": avg_vol_20,
        "volume_ratio": vol_ratio,
        "price_vs_sma50": float((close[-1] - sma50) / sma50) if sma50 > 0 else 0,
        "price_vs_sma200": float((close[-1] - sma200) / sma200) if sma200 > 0 else 0,
    }


def replay_quant_scores(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    regime: str = "risk_on",
) -> Dict[str, Any]:
    """Replay quant technical scores over a historical date range.

    Downloads historical OHLCV, computes technical indicators at each date,
    runs the technical scorer, and compares with actual forward returns.

    Returns dict with:
        - scores: List of {date, score, close} per trading day
        - forward_returns: {1d, 5d, 20d} actual returns after each score
        - ic: {1d, 5d, 20d} Information Coefficient (Spearman rank correlation)
        - summary: {mean_score, std_score, n_days, ticker}
    """
    import yfinance as yf
    from quorum.quant.technical import score_technical

    today = date.today()
    if end_date is None:
        end_date = today.isoformat()
    if start_date is None:
        start_date = (today - timedelta(days=365)).isoformat()

    # Download with extra buffer for SMA200 + 20d forward returns
    buffer_start = (date.fromisoformat(start_date) - timedelta(days=250)).isoformat()
    buffer_end = (date.fromisoformat(end_date) + timedelta(days=25)).isoformat()

    hist = yf.Ticker(ticker).history(start=buffer_start, end=buffer_end)
    if hist is None or len(hist) < 50:
        return {"error": f"Insufficient data for {ticker}", "scores": [], "ic": {}}

    # Flatten MultiIndex columns if present
    if hasattr(hist.columns, "levels"):
        hist.columns = [c[0] if isinstance(c, tuple) else c for c in hist.columns]

    hist = hist.reset_index()
    hist["Date"] = pd.to_datetime(hist["Date"]).dt.date

    # Find the scoring range indices
    start_dt = date.fromisoformat(start_date)
    end_dt = date.fromisoformat(end_date)

    scores_list = []
    regime_data = {"regime": regime.upper(), "vix": 16, "confidence": 50}

    for i in range(len(hist)):
        d = hist.iloc[i]["Date"]
        if d < start_dt or d > end_dt:
            continue

        indicators = _compute_indicators_at(hist, i)
        if not indicators:
            continue

        try:
            result = score_technical(ticker, indicators, regime_data)
            score = result.score
        except Exception:
            score = 3.0

        close_price = float(hist.iloc[i]["Close"])

        # Forward returns (raw — kept for backward compat)
        fwd_1d = fwd_5d = fwd_20d = None
        if i + 1 < len(hist):
            fwd_1d = float((hist.iloc[min(i + 1, len(hist) - 1)]["Close"] - close_price) / close_price)
        if i + 5 < len(hist):
            fwd_5d = float((hist.iloc[min(i + 5, len(hist) - 1)]["Close"] - close_price) / close_price)
        if i + 20 < len(hist):
            fwd_20d = float((hist.iloc[min(i + 20, len(hist) - 1)]["Close"] - close_price) / close_price)

        # Multi-horizon volatility-normalized labels
        # 3d/7d/15d with weights 0.3/0.5/0.2, normalized by 20-period rolling vol
        pct_returns = hist["Close"].pct_change()
        rolling_vol_20 = float(pct_returns.iloc[max(0, i - 19):i + 1].std()) if i >= 19 else None

        fwd_3d_norm = fwd_7d_norm = fwd_15d_norm = composite_label = None
        if rolling_vol_20 and rolling_vol_20 > 0:
            for horizon, attr in [(3, "fwd_3d_norm"), (7, "fwd_7d_norm"), (15, "fwd_15d_norm")]:
                if i + horizon < len(hist):
                    raw = float((hist.iloc[i + horizon]["Close"] - close_price) / close_price)
                    normed = raw / (rolling_vol_20 * np.sqrt(horizon))
                    if attr == "fwd_3d_norm":
                        fwd_3d_norm = normed
                    elif attr == "fwd_7d_norm":
                        fwd_7d_norm = normed
                    else:
                        fwd_15d_norm = normed

            # Composite: 0.3 * 3d + 0.5 * 7d + 0.2 * 15d
            parts = []
            if fwd_3d_norm is not None:
                parts.append((0.3, fwd_3d_norm))
            if fwd_7d_norm is not None:
                parts.append((0.5, fwd_7d_norm))
            if fwd_15d_norm is not None:
                parts.append((0.2, fwd_15d_norm))
            if parts:
                total_w = sum(w for w, _ in parts)
                composite_label = sum(w * v for w, v in parts) / total_w

        scores_list.append({
            "date": d.isoformat(),
            "score": round(score, 4),
            "close": round(close_price, 2),
            "fwd_1d": round(fwd_1d, 6) if fwd_1d is not None else None,
            "fwd_5d": round(fwd_5d, 6) if fwd_5d is not None else None,
            "fwd_20d": round(fwd_20d, 6) if fwd_20d is not None else None,
            "fwd_3d_norm": round(fwd_3d_norm, 6) if fwd_3d_norm is not None else None,
            "fwd_7d_norm": round(fwd_7d_norm, 6) if fwd_7d_norm is not None else None,
            "fwd_15d_norm": round(fwd_15d_norm, 6) if fwd_15d_norm is not None else None,
            "composite_label": round(composite_label, 6) if composite_label is not None else None,
            "rolling_vol_20": round(rolling_vol_20, 6) if rolling_vol_20 is not None else None,
        })

    if not scores_list:
        return {"error": "No scores computed", "scores": [], "ic": {}}

    # Compute IC (Spearman rank correlation) for each horizon
    from scipy.stats import spearmanr

    ic = {}
    scores_arr = np.array([s["score"] for s in scores_list])

    # Raw forward returns (backward compat)
    for horizon, key in [(1, "1d"), (5, "5d"), (20, "20d")]:
        fwd = [s[f"fwd_{key}"] for s in scores_list]
        valid = [(sc, fw) for sc, fw in zip(scores_arr, fwd) if fw is not None]
        if len(valid) >= 10:
            sc_v, fw_v = zip(*valid)
            corr, pval = spearmanr(sc_v, fw_v)
            ic[key] = {"ic": round(float(corr), 4), "pval": round(float(pval), 4), "n": len(valid)}
        else:
            ic[key] = {"ic": None, "pval": None, "n": len(valid)}

    # Vol-normalized horizons + composite
    for key in ["3d_norm", "7d_norm", "15d_norm", "composite"]:
        field = f"fwd_{key}" if key != "composite" else "composite_label"
        fwd = [s.get(field) for s in scores_list]
        valid = [(sc, fw) for sc, fw in zip(scores_arr, fwd) if fw is not None]
        if len(valid) >= 10:
            sc_v, fw_v = zip(*valid)
            corr, pval = spearmanr(sc_v, fw_v)
            ic[key] = {"ic": round(float(corr), 4), "pval": round(float(pval), 4), "n": len(valid)}
        else:
            ic[key] = {"ic": None, "pval": None, "n": len(valid)}

    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "regime": regime,
        "n_days": len(scores_list),
        "mean_score": round(float(np.mean(scores_arr)), 4),
        "std_score": round(float(np.std(scores_arr)), 4),
        "scores": scores_list,
        "ic": ic,
    }
