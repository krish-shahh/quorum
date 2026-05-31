import os

_TRADINGAGENTS_HOME = os.path.join(os.path.expanduser("~"), ".tradingagents")

# Single source of truth for env-var → config-key overrides. To expose
# a new config key for environment-based override, add a row here — no
# entry-point script changes required. Coercion is driven by the type
# of the existing default, so users can keep writing plain strings in
# their .env file.
_ENV_OVERRIDES = {
    "TRADINGAGENTS_LLM_PROVIDER":         "llm_provider",
    "TRADINGAGENTS_DEEP_THINK_LLM":       "deep_think_llm",
    "TRADINGAGENTS_QUICK_THINK_LLM":      "quick_think_llm",
    "TRADINGAGENTS_LLM_BACKEND_URL":      "backend_url",
    "TRADINGAGENTS_OUTPUT_LANGUAGE":      "output_language",
    "TRADINGAGENTS_MAX_DEBATE_ROUNDS":    "max_debate_rounds",
    "TRADINGAGENTS_MAX_RISK_ROUNDS":      "max_risk_discuss_rounds",
    "TRADINGAGENTS_CHECKPOINT_ENABLED":   "checkpoint_enabled",
    "TRADINGAGENTS_BENCHMARK_TICKER":     "benchmark_ticker",
    # Execution layer overrides
    "TRADINGAGENTS_EXECUTION_MODE":       "execution_mode",
    "TRADINGAGENTS_PAPER_BALANCE":        "paper_starting_balance",
    "TRADINGAGENTS_MAX_POSITION_PCT":     "max_position_pct",
    "TRADINGAGENTS_MAX_SINGLE_TICKER_PCT": "max_single_ticker_pct",
    "TRADINGAGENTS_MAX_OPEN_POSITIONS":   "max_open_positions",
    "TRADINGAGENTS_MAX_DRAWDOWN_PCT":     "max_drawdown_pct",
    "TRADINGAGENTS_PAPER_SLIPPAGE":       "paper_slippage_enabled",
    "TRADINGAGENTS_PAPER_SPREAD_BPS":     "paper_spread_bps",
    "TRADINGAGENTS_STOP_LOSS_ENABLED":    "stop_loss_enabled",
    "TRADINGAGENTS_EXTENDED_HOURS":       "extended_hours",
    "TRADINGAGENTS_SCHEDULED_TICKERS":    "scheduled_tickers",
    "TRADINGAGENTS_SCHEDULE_TIME":        "schedule_time",
    "TRADINGAGENTS_SCHEDULE_TIMEZONE":    "schedule_timezone",
    "TRADINGAGENTS_INTRADAY_SNAPSHOTS":   "intraday_snapshots",
    # Email alerts
    "TRADINGAGENTS_ALERTS_ENABLED":       "alerts_enabled",
    "TRADINGAGENTS_ALERT_EMAIL_FROM":     "alert_email_from",
    "TRADINGAGENTS_ALERT_EMAIL_TO":       "alert_email_to",
    "TRADINGAGENTS_ALERT_SMTP_HOST":      "alert_smtp_host",
    "TRADINGAGENTS_ALERT_SMTP_PORT":      "alert_smtp_port",
    "TRADINGAGENTS_ALERT_SMTP_USER":      "alert_smtp_user",
    "TRADINGAGENTS_ALERT_SMTP_PASSWORD":  "alert_smtp_password",
    # Webhook / advanced alerts
    "TRADINGAGENTS_ALERT_SLACK_WEBHOOK":  "alert_slack_webhook",
    "TRADINGAGENTS_ALERT_MIN_TRADE_VALUE": "alert_min_trade_value",
    # alert_on_signals is a list; env var is comma-separated
    # (e.g. TRADINGAGENTS_ALERT_ON_SIGNALS=Buy,Sell)
    "TRADINGAGENTS_ALERT_ON_SIGNALS":     "alert_on_signals",
    "TRADINGAGENTS_ALERT_DAILY_SUMMARY":  "alert_daily_summary",
    # Discovery / autonomous scanning
    "TRADINGAGENTS_DISCOVERY_ENABLED":    "discovery_enabled",
    "TRADINGAGENTS_DISCOVERY_MODE":       "discovery_mode",
    "TRADINGAGENTS_DISCOVERY_SCAN_INTERVAL": "discovery_scan_interval_hours",
    "TRADINGAGENTS_DISCOVERY_MIN_SIGNAL": "discovery_min_signal_strength",
    "TRADINGAGENTS_DISCOVERY_MAX_CANDIDATES": "discovery_max_candidates",
    # Wiki / knowledge base
    "TRADINGAGENTS_WIKI_ENABLED":         "wiki_enabled",
    "TRADINGAGENTS_WIKI_DIR":             "wiki_dir",
    # Data edge features
    "TRADINGAGENTS_INSIDER_CLUSTERING":   "insider_clustering_enabled",
    "TRADINGAGENTS_SECTOR_ROTATION":      "sector_rotation_enabled",
    "TRADINGAGENTS_EARNINGS_AVOIDANCE":   "earnings_avoidance_enabled",
    "TRADINGAGENTS_MACRO_EVENT_ADJ":      "macro_event_adjustment_enabled",
    # Execution edge features
    "TRADINGAGENTS_KELLY_SIZING":         "kelly_sizing_enabled",
    "TRADINGAGENTS_CORRELATION_AWARE":    "correlation_aware_enabled",
    "TRADINGAGENTS_VWAP_ENABLED":         "vwap_enabled",
    # Push notifications
    "TRADINGAGENTS_PUSH_ENABLED":         "push_notifications_enabled",
    # Backtest
    "TRADINGAGENTS_BACKTEST_BALANCE":     "backtest_starting_balance",
}


def _coerce(value: str, reference):
    """Coerce env-var string to the type of the existing default value."""
    if isinstance(reference, bool):
        return value.strip().lower() in ("true", "1", "yes", "on")
    if isinstance(reference, list):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(reference, int) and not isinstance(reference, bool):
        return int(value)
    if isinstance(reference, float):
        return float(value)
    return value


def _apply_env_overrides(config: dict) -> dict:
    """Apply TRADINGAGENTS_* env vars to the config dict in-place."""
    for env_var, key in _ENV_OVERRIDES.items():
        raw = os.environ.get(env_var)
        if raw is None or raw == "":
            continue
        config[key] = _coerce(raw, config.get(key))
    return config


DEFAULT_CONFIG = _apply_env_overrides({
    "project_dir": os.path.abspath(os.path.join(os.path.dirname(__file__), ".")),
    "results_dir": os.getenv("TRADINGAGENTS_RESULTS_DIR", os.path.join(_TRADINGAGENTS_HOME, "logs")),
    "data_cache_dir": os.getenv("TRADINGAGENTS_CACHE_DIR", os.path.join(_TRADINGAGENTS_HOME, "cache")),
    "memory_log_path": os.getenv("TRADINGAGENTS_MEMORY_LOG_PATH", os.path.join(_TRADINGAGENTS_HOME, "memory", "trading_memory.md")),
    # Optional cap on the number of resolved memory log entries. When set,
    # the oldest resolved entries are pruned once this limit is exceeded.
    # Pending entries are never pruned. None disables rotation entirely.
    "memory_log_max_entries": None,
    # LLM settings
    "llm_provider": "anthropic",
    "deep_think_llm": "claude-opus-4-7",
    "quick_think_llm": "claude-sonnet-4-6",
    # When None, each provider's client falls back to its own default endpoint
    # (api.openai.com for OpenAI, generativelanguage.googleapis.com for Gemini, ...).
    # The CLI overrides this per provider when the user picks one. Keeping a
    # provider-specific URL here would leak (e.g. OpenAI's /v1 was previously
    # being forwarded to Gemini, producing malformed request URLs).
    "backend_url": None,
    # Provider-specific thinking configuration
    "google_thinking_level": None,      # "high", "minimal", etc.
    "openai_reasoning_effort": None,    # "medium", "high", "low"
    "anthropic_effort": None,           # "high", "medium", "low"
    # Checkpoint/resume: when True, LangGraph saves state after each node
    # so a crashed run can resume from the last successful step.
    "checkpoint_enabled": False,
    # Computation cache (Gromit-style): caches analyst/researcher outputs and
    # only recomputes nodes whose inputs changed. Dramatically reduces LLM calls
    # on intra-day re-analysis and sequential ticker runs.
    "computation_cache_enabled": True,
    # Output language for analyst reports and final decision
    # Internal agent debate stays in English for reasoning quality
    "output_language": "English",
    # Debate and discussion settings
    "max_debate_rounds": 1,
    "max_risk_discuss_rounds": 1,
    "max_recur_limit": 100,
    "analyst_concurrency_limit": 4,  # run all 4 analysts in parallel (was 1 = sequential)
    # News / data fetching parameters
    # Increase for longer lookback strategies or to broaden macro coverage;
    # decrease to reduce token usage in agent prompts.
    "news_article_limit": 20,             # max articles per ticker (ticker-news)
    "global_news_article_limit": 10,      # max articles for global/macro news
    "global_news_lookback_days": 7,       # macro news lookback window
    # Search queries used by get_global_news for macro headlines. Extend or
    # replace to broaden geographic / sector coverage.
    "global_news_queries": [
        "Federal Reserve interest rates inflation",
        "S&P 500 earnings GDP economic outlook",
        "geopolitical risk trade war sanctions",
        "ECB Bank of England BOJ central bank policy",
        "oil commodities supply chain energy",
    ],
    # Data vendor configuration
    # Category-level configuration (default for all tools in category)
    "data_vendors": {
        "core_stock_apis": "yfinance",       # Options: alpha_vantage, yfinance
        "technical_indicators": "yfinance",  # Options: alpha_vantage, yfinance
        "fundamental_data": "yfinance",      # Options: alpha_vantage, yfinance
        "news_data": "yfinance",             # Options: alpha_vantage, yfinance
    },
    # Tool-level configuration (takes precedence over category-level)
    "tool_vendors": {
        # Example: "get_stock_data": "alpha_vantage",  # Override category default
    },
    # Benchmark for alpha calculation in the reflection layer.
    # ``benchmark_ticker`` (when set) overrides the suffix map for all
    # tickers; leave it None to use ``benchmark_map`` for auto-detection
    # based on the ticker's exchange suffix. SPY remains the US default
    # so the reflection label keeps reading "Alpha vs SPY" for US tickers
    # while non-US tickers get their regional index automatically.
    # ------------------------------------------------------------------
    # Execution layer
    # ------------------------------------------------------------------
    # Mode: "paper" (in-memory simulation) or "schwab" (live Schwab API)
    "execution_mode": "paper",
    # Paper-trading starting cash balance
    "paper_starting_balance": 5000.0,
    # Position sizing
    "max_position_pct": 0.25,           # 25% of portfolio per new trade (matches single-ticker cap)
    "max_single_ticker_pct": 0.25,      # 25% cap in any single ticker
    "max_open_positions": 6,
    # Safety / kill switch
    "max_drawdown_pct": 0.10,           # halt trading if drawdown exceeds 10%
    # Stop-loss monitoring
    "stop_loss_enabled": True,          # auto-register stop-losses from trader proposals
    # Extended hours (pre-market 4:00-9:30 ET, after-hours 16:00-20:00 ET)
    "extended_hours": False,
    # Schwab API (credentials read from env vars SCHWAB_API_KEY, SCHWAB_API_SECRET,
    # SCHWAB_ACCOUNT_HASH — not stored in DEFAULT_CONFIG for security)
    "schwab_token_path": os.path.join(_TRADINGAGENTS_HOME, "schwab_token.json"),
    # Scheduler / parallelization
    "parallel_max_workers": 3,          # concurrent tickers (1 = sequential)
    "parallel_stagger_seconds": 60,     # delay between parallel ticker starts (avoids API rate limits)
    "scheduled_tickers": [],            # e.g. ["AAPL", "MSFT", "NVDA"]
    "schedule_time": "09:00",           # 24h format, in schedule_timezone
    "schedule_timezone": "US/Eastern",
    "intraday_snapshots": False,        # hourly position snapshots during market hours
    # Email alerts (pre-trade, post-trade, intra-day, kill switch)
    "alerts_enabled": False,
    "alert_email_from": "",
    "alert_email_to": "",               # comma-separated for multiple recipients
    "alert_smtp_host": "smtp.gmail.com",
    "alert_smtp_port": 587,
    "alert_smtp_user": "",
    "alert_smtp_password": "",
    # Slack/Discord webhook alerts (also works with Discord's /slack endpoint)
    "alert_slack_webhook": "",          # webhook URL
    # Alert thresholds
    "alert_min_trade_value": 0,         # only alert on trades > $X (0 = all)
    "alert_on_signals": [],             # empty = all signals; e.g. ["Buy", "Sell"]
    # Daily portfolio summary at market close
    "alert_daily_summary": False,
    # ------------------------------------------------------------------
    # Discovery / autonomous scanning
    # ------------------------------------------------------------------
    "discovery_enabled": False,
    "discovery_mode": "advisory",                # "advisory" or "autonomous"
    "discovery_scan_interval_hours": 4,
    "discovery_min_signal_strength": 0.6,        # 0-1 threshold
    "discovery_max_candidates": 20,              # max pending candidates
    # ------------------------------------------------------------------
    # Wiki / knowledge base
    # ------------------------------------------------------------------
    "wiki_enabled": True,
    "wiki_dir": os.path.join(_TRADINGAGENTS_HOME, "wiki"),
    # ------------------------------------------------------------------
    # Data cache TTLs (seconds per category)
    # ------------------------------------------------------------------
    "cache_ttls": {
        "price": 60,            # OHLCV refreshes every minute
        "technicals": 60,       # RSI/MACD/SMA derived from price
        "fundamentals": 86400,  # PE/EPS/margins change quarterly
        "news": 3600,           # news refreshes hourly
        "sentiment": 900,       # StockTwits shifts every 15 min
        "insiders": 86400,      # insider txns change daily at most
        "congressional": 86400, # STOCK Act filings, daily sync
        "earnings": 86400,      # earnings dates change rarely
        "regime": 300,          # VIX/DXY/yields shift intraday
        "sector_rotation": 3600,
    },
    # ------------------------------------------------------------------
    # Paper broker realism
    # ------------------------------------------------------------------
    "paper_slippage_enabled": False,    # simulate spread + market impact
    "paper_spread_bps": 10,             # default spread in basis points
    "paper_impact_bps_per_pct": 1,      # market impact: 1bp per 1% of portfolio
    # ------------------------------------------------------------------
    # Data edge features
    # ------------------------------------------------------------------
    "insider_clustering_enabled": True,
    "insider_cluster_window_days": 14,
    "insider_cluster_min_insiders": 3,
    "sector_rotation_enabled": True,
    "earnings_avoidance_enabled": True,
    "earnings_avoidance_days": 3,          # reduce size within N days of earnings
    "macro_event_adjustment_enabled": True,
    # ------------------------------------------------------------------
    # Execution edge features
    # ------------------------------------------------------------------
    "kelly_sizing_enabled": False,          # opt-in: uses historical win rate
    "correlation_aware_enabled": True,      # reduces allocation when correlated with holdings (>0.7)
    "correlation_threshold": 0.7,
    # Regime-conditional strategy thresholds
    # Minimum holding period (trading days) before a position can be sold.
    # Prevents buy-then-sell-4-days-later whipsaw. Stop-loss (priority 1) overrides.
    "min_holding_days": 7,
    # Max sector concentration — blocks buys if sector would exceed this %
    "max_sector_concentration_pct": 0.50,
    "regime_strategy": {
        "risk_on":    {"buy_threshold": 3.5, "sell_threshold": 2.5, "cash_target": 0.20, "size_mult": 1.0},
        "risk_off":   {"buy_threshold": 3.8, "sell_threshold": 2.8, "cash_target": 0.30, "size_mult": 0.8},
        "volatile":   {"buy_threshold": 3.6, "sell_threshold": 2.5, "cash_target": 0.25, "size_mult": 0.7},
        "transition": {"buy_threshold": 3.5, "sell_threshold": 2.5, "cash_target": 0.20, "size_mult": 1.0},
    },
    "vwap_enabled": False,                  # opt-in: split large orders
    "vwap_slice_threshold": 100,            # shares above which VWAP is used
    # ------------------------------------------------------------------
    # Debate architecture (bull/bear + risk debate layers)
    # ------------------------------------------------------------------
    "debate_enabled": True,
    "debate_trigger_score_min": 2.8,        # lower bound of ambiguous zone
    "debate_trigger_score_max": 4.2,        # upper bound of ambiguous zone
    "debate_trigger_spread": 2.0,           # analyst spread threshold
    "debate_force_on_new_position": True,   # always debate before first entry
    "debate_force_on_earnings": True,       # always debate near-earnings decisions
    # ------------------------------------------------------------------
    # Push notifications (VAPID web push)
    # ------------------------------------------------------------------
    "push_notifications_enabled": False,
    "vapid_private_key": "",
    "vapid_public_key": "",
    "vapid_claims_email": "",
    # ------------------------------------------------------------------
    # Backtest
    # ------------------------------------------------------------------
    "backtest_starting_balance": 100000.0,
    # ------------------------------------------------------------------
    "benchmark_ticker": None,
    "benchmark_map": {
        ".NS":  "^NSEI",    # NSE India (Nifty 50)
        ".BO":  "^BSESN",   # BSE India (Sensex)
        ".T":   "^N225",    # Tokyo (Nikkei 225)
        ".HK":  "^HSI",     # Hong Kong (Hang Seng)
        ".L":   "^FTSE",    # London (FTSE 100)
        ".TO":  "^GSPTSE",  # Toronto (TSX Composite)
        ".AX":  "^AXJO",    # Australia (ASX 200)
        "":     "SPY",      # default for US-listed tickers (no suffix)
    },
    # Asset-type benchmarks — used instead of benchmark_map when the ticker
    # is a known bond or commodity ETF. Stock tickers still use benchmark_map.
    "asset_type_benchmarks": {
        "etf_bond":      "AGG",   # iShares Core U.S. Aggregate Bond ETF
        "etf_commodity":  "DBC",   # Invesco DB Commodity Index Tracking Fund
    },
})
