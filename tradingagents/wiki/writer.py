"""WikiWriter — writes and manages the trading knowledge base.

Produces markdown pages for every pipeline run, daily digests,
rolling per-ticker summaries, regime pages, and interactive reports.
All pages are written to ``~/.tradingagents/wiki/`` and indexed in SQLite
for fast lookup.
"""

from __future__ import annotations

import json
import logging
import os
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from .models import (
    WikiFrontmatter,
    WikiPageIndex,
    extract_narratives,
    extract_related_tickers,
    extract_tags,
)
from .regime import RegimeClassifier

logger = logging.getLogger(__name__)


def _safe_float(v: Any) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


class WikiWriter:
    """Persistent, structured knowledge base for pipeline runs.

    Pages are written as markdown files to disk (human-readable source
    of truth) and indexed in the SQLite execution database for fast
    querying from the dashboard and future agent prompts.
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        config = config or {}
        self.wiki_dir = Path(
            config.get("wiki_dir", os.path.join(os.path.expanduser("~"), ".tradingagents", "wiki"))
        )
        self.config = config
        self._regime = RegimeClassifier()

        # Ensure directory structure
        for subdir in ("runs", "daily", "tickers", "regimes", "reports"):
            (self.wiki_dir / subdir).mkdir(parents=True, exist_ok=True)

    # ── helpers ──────────────────────────────────────────────────────

    def _get_db(self):
        """Lazy import to avoid circular dependency."""
        from tradingagents.execution.db import get_db
        return get_db(self.config)

    def _index_page(self, page: WikiPageIndex) -> None:
        """Insert or update the SQLite index for a wiki page."""
        conn = self._get_db()
        conn.execute(
            """INSERT OR REPLACE INTO wiki_pages
               (path, ticker, trade_date, signal, regime, confidence, tags, page_type)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                page.path,
                page.ticker,
                page.trade_date,
                page.signal,
                page.regime,
                page.confidence,
                json.dumps(page.tags),
                page.page_type,
            ),
        )
        conn.commit()

    @staticmethod
    def _render_yaml_frontmatter(fm: WikiFrontmatter) -> str:
        """Render YAML frontmatter block."""
        lines = ["---"]
        lines.append(f"ticker: {fm.ticker}")
        lines.append(f"date: {fm.date}")
        lines.append(f"signal: {fm.signal}")
        lines.append(f"confidence: {fm.confidence:.2f}")
        if fm.regime:
            lines.append(f"regime: {fm.regime}")
        if fm.fill_price is not None:
            lines.append(f"fill_price: {fm.fill_price:.2f}")
        if fm.quantity is not None:
            lines.append(f"quantity: {fm.quantity}")
        if fm.account_after is not None:
            lines.append(f"account_after: {fm.account_after:.2f}")
        lines.append(f"realized_pnl: {fm.realized_pnl}")
        if fm.narratives:
            lines.append(f"narratives: {json.dumps(fm.narratives)}")
        if fm.related_tickers:
            lines.append(f"related_tickers: {json.dumps(fm.related_tickers)}")
        if fm.tags:
            lines.append(f"tags: {json.dumps(fm.tags)}")
        lines.append("---")
        return "\n".join(lines)

    # ── Phase 1: Run Pages ───────────────────────────────────────────

    def write_run_page(
        self,
        ticker: str,
        trade_date: str,
        final_state: Dict[str, Any],
        signal: str,
        execution_record: Optional[Any] = None,
    ) -> Path:
        """Write a wiki page for a single pipeline run.

        Called after execution (or after propagate for Hold signals).
        """
        # Gather all analyst reports
        market_report = final_state.get("market_report", "")
        sentiment_report = final_state.get("sentiment_report", "")
        news_report = final_state.get("news_report", "")
        fundamentals_report = final_state.get("fundamentals_report", "")

        all_text = " ".join([market_report, sentiment_report, news_report, fundamentals_report])

        # Extract metadata
        tags = extract_tags(all_text)
        narratives = extract_narratives(all_text)
        related = extract_related_tickers(all_text, exclude=ticker)

        # Confidence
        confidence = 0.0
        try:
            from tradingagents.execution.confidence import compute_confidence_score
            confidence = compute_confidence_score(final_state)
        except Exception:
            pass

        # Regime
        regime = self._regime.classify(trade_date)

        # Execution details
        fill_price = None
        quantity = None
        account_after = None
        if execution_record is not None:
            if hasattr(execution_record, "order_result") and execution_record.order_result:
                fill_price = _safe_float(execution_record.order_result.filled_price)
                quantity = getattr(execution_record.order_result, "filled_quantity", None)
            account_after = _safe_float(
                getattr(execution_record, "account_value_after", None)
            )

        # Debate summaries
        invest_state = final_state.get("investment_debate_state", {})
        risk_state = final_state.get("risk_debate_state", {})

        bull_args = invest_state.get("bull_history", "")
        bear_args = invest_state.get("bear_history", "")
        research_plan = final_state.get("investment_plan", "")
        trader_proposal = final_state.get("trader_investment_plan", "")
        risk_debate = risk_state.get("history", "")
        final_decision = final_state.get("final_trade_decision", "")

        # Build frontmatter
        fm = WikiFrontmatter(
            ticker=ticker,
            date=trade_date,
            signal=signal,
            confidence=confidence,
            regime=regime,
            fill_price=fill_price,
            quantity=quantity,
            account_after=account_after,
            realized_pnl=None,
            narratives=narratives,
            related_tickers=related,
            tags=tags,
        )

        # Build page body
        body_parts = [
            self._render_yaml_frontmatter(fm),
            "",
            f"# {ticker} — {trade_date}",
            "",
            f"**Signal:** {signal} | **Confidence:** {confidence:.2f} | **Regime:** {regime}",
            "",
        ]

        # Cross-references
        if related:
            links = ", ".join(f"[[{t}]]" for t in related)
            body_parts.append(f"**Related:** {links}")
            body_parts.append("")

        # Analyst reports
        for label, content in [
            ("Market Analysis", market_report),
            ("Sentiment Analysis", sentiment_report),
            ("News Analysis", news_report),
            ("Fundamentals Analysis", fundamentals_report),
        ]:
            body_parts.append(f"## {label}")
            body_parts.append("")
            body_parts.append(content.strip() if content else "*No report available.*")
            body_parts.append("")

        # Debate
        body_parts.append("## Bull Arguments")
        body_parts.append("")
        body_parts.append(bull_args.strip() if bull_args else "*No arguments recorded.*")
        body_parts.append("")

        body_parts.append("## Bear Arguments")
        body_parts.append("")
        body_parts.append(bear_args.strip() if bear_args else "*No arguments recorded.*")
        body_parts.append("")

        body_parts.append("## Research Plan")
        body_parts.append("")
        body_parts.append(research_plan.strip() if research_plan else "*Not available.*")
        body_parts.append("")

        body_parts.append("## Trader Proposal")
        body_parts.append("")
        body_parts.append(trader_proposal.strip() if trader_proposal else "*Not available.*")
        body_parts.append("")

        body_parts.append("## Risk Debate Summary")
        body_parts.append("")
        body_parts.append(risk_debate.strip() if risk_debate else "*Not available.*")
        body_parts.append("")

        body_parts.append("## Final Decision")
        body_parts.append("")
        body_parts.append(final_decision.strip() if final_decision else "*Not available.*")
        body_parts.append("")

        # Execution details
        if execution_record is not None:
            body_parts.append("## Execution")
            body_parts.append("")
            body_parts.append(f"- **Fill Price:** ${fill_price:,.2f}" if fill_price else "- **Fill Price:** N/A")
            body_parts.append(f"- **Quantity:** {quantity}" if quantity else "- **Quantity:** N/A")
            body_parts.append(f"- **Account After:** ${account_after:,.2f}" if account_after else "- **Account After:** N/A")
            body_parts.append("")

        # Write file
        date_dir = self.wiki_dir / "runs" / trade_date
        date_dir.mkdir(parents=True, exist_ok=True)
        page_path = date_dir / f"{ticker}.md"
        page_path.write_text("\n".join(body_parts), encoding="utf-8")

        # Index in SQLite
        rel_path = str(page_path.relative_to(self.wiki_dir))
        self._index_page(WikiPageIndex(
            path=rel_path,
            ticker=ticker,
            trade_date=trade_date,
            signal=signal,
            regime=regime,
            confidence=confidence,
            tags=tags,
            page_type="run",
        ))

        logger.info("Wiki run page written: %s", page_path)

        # Update ticker page as side-effect
        try:
            self.update_ticker_page(ticker)
        except Exception:
            logger.debug("Ticker page update failed for %s", ticker, exc_info=True)

        return page_path

    # ── Phase 1: Daily Digests ───────────────────────────────────────

    def write_daily_digest(self, date_str: str) -> Path:
        """Generate a rule-based daily digest (no LLM) for the given date.

        Reads all run pages for the date, computes signal distribution,
        clusters narratives by tag frequency, detects analyst conflicts,
        and stamps the macro regime.
        """
        conn = self._get_db()
        rows = conn.execute(
            "SELECT path, ticker, signal, regime, confidence, tags FROM wiki_pages "
            "WHERE trade_date = ? AND page_type = 'run' ORDER BY ticker",
            (date_str,),
        ).fetchall()

        total = len(rows)
        if total == 0:
            logger.info("No run pages for %s — skipping digest", date_str)
            digest_path = self.wiki_dir / "daily" / f"{date_str}.md"
            digest_path.write_text(
                f"# Daily Digest — {date_str}\n\nNo pipeline runs recorded.\n",
                encoding="utf-8",
            )
            return digest_path

        # Signal distribution
        signal_counts: Counter = Counter()
        all_tags: Counter = Counter()
        tickers_by_signal: Dict[str, List[str]] = defaultdict(list)
        ticker_signals: Dict[str, str] = {}
        regimes: Counter = Counter()

        for row in rows:
            sig = row["signal"]
            tkr = row["ticker"]
            signal_counts[sig] += 1
            tickers_by_signal[sig].append(tkr)
            ticker_signals[tkr] = sig
            regimes[row["regime"]] += 1
            try:
                tags = json.loads(row["tags"]) if row["tags"] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            for tag in tags:
                all_tags[tag] += 1

        # Dominant regime
        regime_today = regimes.most_common(1)[0][0] if regimes else "unknown"

        # Regime data
        regime_data = self._regime.get_regime_data(date_str)

        # Narrative clusters (group tickers by shared top tags)
        tag_tickers: Dict[str, List[str]] = defaultdict(list)
        for row in rows:
            tkr = row["ticker"]
            try:
                tags = json.loads(row["tags"]) if row["tags"] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            for tag in tags:
                tag_tickers[tag].append(tkr)

        # Conflict detection: same tag but opposing signals
        conflicts: List[str] = []
        for tag, tickers in tag_tickers.items():
            if len(tickers) < 2:
                continue
            sigs_for_tag = {t: ticker_signals.get(t, "") for t in tickers}
            has_buy = any(s in ("Buy", "Overweight") for s in sigs_for_tag.values())
            has_sell = any(s in ("Sell", "Underweight") for s in sigs_for_tag.values())
            if has_buy and has_sell:
                bulls = [t for t, s in sigs_for_tag.items() if s in ("Buy", "Overweight")]
                bears = [t for t, s in sigs_for_tag.items() if s in ("Sell", "Underweight")]
                conflicts.append(
                    f"**{tag}**: bullish on {', '.join(bulls)} vs bearish on {', '.join(bears)}"
                )

        # Build digest
        parts = [
            f"# Daily Digest — {date_str}",
            "",
            f"**Total Runs:** {total} | **Regime:** {regime_today}",
            "",
        ]

        # Regime data
        if regime_data:
            parts.append("## Market Indicators")
            parts.append("")
            if regime_data.get("vix") is not None:
                parts.append(f"- **VIX:** {regime_data['vix']:.1f} ({regime_data.get('vix_change_pct', 0):.1f}% 5d)")
            if regime_data.get("dxy") is not None:
                parts.append(f"- **DXY:** {regime_data['dxy']:.2f} ({regime_data.get('dxy_change_pct', 0):.1f}% 5d)")
            if regime_data.get("yield_10y") is not None:
                parts.append(f"- **10Y Yield:** {regime_data['yield_10y']:.2f}% ({regime_data.get('yield_change_pct', 0):.1f}% 5d)")
            parts.append("")

        # Signal summary
        parts.append("## Signal Distribution")
        parts.append("")
        for sig, count in signal_counts.most_common():
            tickers_str = ", ".join(tickers_by_signal[sig])
            parts.append(f"- **{sig}:** {count} ({tickers_str})")
        parts.append("")

        # Tag clusters
        if all_tags:
            parts.append("## Narrative Clusters")
            parts.append("")
            for tag, count in all_tags.most_common(10):
                tickers_str = ", ".join(sorted(set(tag_tickers[tag])))
                parts.append(f"- **{tag}** ({count}): {tickers_str}")
            parts.append("")

        # Conflicts
        if conflicts:
            parts.append("## Analyst Conflicts")
            parts.append("")
            for c in conflicts:
                parts.append(f"- {c}")
            parts.append("")

        # Ticker details
        parts.append("## Tickers Analyzed")
        parts.append("")
        parts.append("| Ticker | Signal | Confidence | Regime |")
        parts.append("|--------|--------|------------|--------|")
        for row in rows:
            parts.append(
                f"| {row['ticker']} | {row['signal']} | {row['confidence']:.2f} | {row['regime']} |"
            )
        parts.append("")

        # Write file
        digest_path = self.wiki_dir / "daily" / f"{date_str}.md"
        digest_path.write_text("\n".join(parts), encoding="utf-8")

        # Index
        self._index_page(WikiPageIndex(
            path=str(digest_path.relative_to(self.wiki_dir)),
            ticker="*",
            trade_date=date_str,
            signal="digest",
            regime=regime_today,
            confidence=0.0,
            tags=list(all_tags.keys())[:20],
            page_type="daily",
        ))

        logger.info("Wiki daily digest written: %s", digest_path)
        return digest_path

    # ── Phase 1: Ticker Pages ────────────────────────────────────────

    def update_ticker_page(self, ticker: str) -> Path:
        """Update the rolling per-ticker summary page.

        Reads all run pages for this ticker from the index and computes
        aggregated stats, narrative timeline, and analyst accuracy.
        """
        conn = self._get_db()
        rows = conn.execute(
            "SELECT path, trade_date, signal, regime, confidence, tags "
            "FROM wiki_pages WHERE ticker = ? AND page_type = 'run' "
            "ORDER BY trade_date DESC",
            (ticker,),
        ).fetchall()

        total = len(rows)
        if total == 0:
            page_path = self.wiki_dir / "tickers" / f"{ticker}.md"
            page_path.write_text(
                f"# {ticker}\n\nNo pipeline runs recorded yet.\n", encoding="utf-8"
            )
            return page_path

        # Stats
        signal_counts: Counter = Counter()
        regime_counts: Counter = Counter()
        confidences: List[float] = []
        all_tags: Counter = Counter()

        for row in rows:
            signal_counts[row["signal"]] += 1
            regime_counts[row["regime"]] += 1
            confidences.append(row["confidence"])
            try:
                tags = json.loads(row["tags"]) if row["tags"] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            for tag in tags:
                all_tags[tag] += 1

        avg_confidence = sum(confidences) / len(confidences) if confidences else 0.0
        most_common_signal = signal_counts.most_common(1)[0][0] if signal_counts else "N/A"
        most_common_regime = regime_counts.most_common(1)[0][0] if regime_counts else "N/A"

        # Try to get P&L data from trade log
        wins = 0
        losses = 0
        total_pnl = 0.0
        best_trade = 0.0
        worst_trade = 0.0
        try:
            from tradingagents.execution.trade_data import load_recent_trades
            trades = load_recent_trades(self.config, limit=500)
            ticker_trades = [t for t in trades if t.get("ticker") == ticker and t.get("action_taken") == "executed"]
            for t in ticker_trades:
                before = t.get("account_value_before") or t.get("account_before", 0)
                after = t.get("account_value_after") or t.get("account_after", 0)
                pnl = (after or 0) - (before or 0)
                total_pnl += pnl
                if pnl > 0:
                    wins += 1
                    best_trade = max(best_trade, pnl)
                elif pnl < 0:
                    losses += 1
                    worst_trade = min(worst_trade, pnl)
        except Exception:
            pass

        win_rate = (wins / (wins + losses) * 100) if (wins + losses) > 0 else 0.0

        # Build page
        parts = [
            f"# {ticker}",
            "",
            f"*Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            "",
            "## Summary",
            "",
            f"| Metric | Value |",
            f"|--------|-------|",
            f"| Total Runs | {total} |",
            f"| Win Rate | {win_rate:.1f}% ({wins}W / {losses}L) |",
            f"| Total P&L | ${total_pnl:,.2f} |",
            f"| Best Trade | ${best_trade:,.2f} |",
            f"| Worst Trade | ${worst_trade:,.2f} |",
            f"| Avg Confidence | {avg_confidence:.2f} |",
            f"| Most Common Signal | {most_common_signal} |",
            f"| Most Common Regime | {most_common_regime} |",
            "",
        ]

        # Signal breakdown
        parts.append("## Signal History")
        parts.append("")
        for sig, count in signal_counts.most_common():
            pct = count / total * 100
            parts.append(f"- **{sig}:** {count} ({pct:.0f}%)")
        parts.append("")

        # Tag profile
        if all_tags:
            parts.append("## Key Themes")
            parts.append("")
            for tag, count in all_tags.most_common(10):
                parts.append(f"- {tag} ({count})")
            parts.append("")

        # Trade reflections (lessons from past outcomes)
        try:
            from tradingagents.execution.learning import LearningEngine
            from tradingagents.execution.reflection import ReflectionEngine
            learner = LearningEngine(self.config)
            reflector = ReflectionEngine(learner, self.config)
            reflections = reflector.get_reflections(ticker, include_sector=False, limit=5)
            # Only add section if there are actual resolved trades
            if "No resolved trades yet" not in reflections:
                parts.append("## Trade Reflections")
                parts.append("")
                # Strip the title line (already have a section header)
                refl_lines = reflections.split("\n")
                for line in refl_lines:
                    if not line.startswith("# Trade Reflections"):
                        parts.append(line)
                parts.append("")
        except Exception:
            pass

        # Recent run timeline (last 20)
        parts.append("## Recent Runs")
        parts.append("")
        parts.append("| Date | Signal | Confidence | Regime |")
        parts.append("|------|--------|------------|--------|")
        for row in rows[:20]:
            parts.append(
                f"| {row['trade_date']} | {row['signal']} | {row['confidence']:.2f} | {row['regime']} |"
            )
        parts.append("")

        # Write
        page_path = self.wiki_dir / "tickers" / f"{ticker}.md"
        page_path.write_text("\n".join(parts), encoding="utf-8")

        # Index
        self._index_page(WikiPageIndex(
            path=str(page_path.relative_to(self.wiki_dir)),
            ticker=ticker,
            trade_date=rows[0]["trade_date"] if rows else "",
            signal="summary",
            regime=most_common_regime,
            confidence=avg_confidence,
            tags=list(all_tags.keys())[:20],
            page_type="ticker",
        ))

        logger.info("Wiki ticker page updated: %s", page_path)
        return page_path

    # ── Phase 2: Regime Pages ────────────────────────────────────────

    def update_regime_page(self, regime: str) -> Path:
        """Update the rolling regime summary page."""
        conn = self._get_db()
        rows = conn.execute(
            "SELECT path, ticker, trade_date, signal, confidence, tags "
            "FROM wiki_pages WHERE regime = ? AND page_type = 'run' "
            "ORDER BY trade_date DESC",
            (regime,),
        ).fetchall()

        total = len(rows)
        signal_counts: Counter = Counter()
        ticker_counts: Counter = Counter()
        all_tags: Counter = Counter()

        for row in rows:
            signal_counts[row["signal"]] += 1
            ticker_counts[row["ticker"]] += 1
            try:
                tags = json.loads(row["tags"]) if row["tags"] else []
            except (json.JSONDecodeError, TypeError):
                tags = []
            for tag in tags:
                all_tags[tag] += 1

        parts = [
            f"# Regime: {regime}",
            "",
            f"*{total} runs recorded in this regime.*",
            "",
            "## Signal Distribution",
            "",
        ]
        for sig, count in signal_counts.most_common():
            parts.append(f"- **{sig}:** {count} ({count / total * 100:.0f}%)")
        parts.append("")

        parts.append("## Top Tickers")
        parts.append("")
        for tkr, count in ticker_counts.most_common(15):
            parts.append(f"- {tkr}: {count} runs")
        parts.append("")

        if all_tags:
            parts.append("## Common Themes")
            parts.append("")
            for tag, count in all_tags.most_common(10):
                parts.append(f"- {tag} ({count})")
            parts.append("")

        # Recent runs
        parts.append("## Recent Runs")
        parts.append("")
        parts.append("| Date | Ticker | Signal | Confidence |")
        parts.append("|------|--------|--------|------------|")
        for row in rows[:30]:
            parts.append(
                f"| {row['trade_date']} | {row['ticker']} | {row['signal']} | {row['confidence']:.2f} |"
            )
        parts.append("")

        page_path = self.wiki_dir / "regimes" / f"{regime}.md"
        page_path.write_text("\n".join(parts), encoding="utf-8")

        self._index_page(WikiPageIndex(
            path=str(page_path.relative_to(self.wiki_dir)),
            ticker="*",
            trade_date=rows[0]["trade_date"] if rows else "",
            signal="regime",
            regime=regime,
            confidence=0.0,
            tags=list(all_tags.keys())[:20],
            page_type="regime",
        ))

        logger.info("Wiki regime page updated: %s (%d runs)", regime, total)
        return page_path

    # ── Phase 2: Context Injection ───────────────────────────────────

    def get_relevant_context(
        self,
        ticker: str,
        trade_date: str,
        regime: str = "",
        limit: int = 3,
    ) -> str:
        """Find the most relevant past wiki pages for prompt injection.

        Scoring: same ticker +3, same regime +2, recency (last 30d) +1.
        Returns a formatted markdown snippet for the PM prompt.
        """
        conn = self._get_db()
        rows = conn.execute(
            "SELECT path, ticker, trade_date, signal, regime, confidence, tags "
            "FROM wiki_pages WHERE page_type = 'run' "
            "ORDER BY trade_date DESC LIMIT 100",
        ).fetchall()

        if not rows:
            return ""

        try:
            ref_date = datetime.strptime(trade_date, "%Y-%m-%d")
        except (ValueError, TypeError):
            ref_date = datetime.now()

        scored: List[tuple] = []
        for row in rows:
            score = 0
            if row["ticker"] == ticker:
                score += 3
            if regime and row["regime"] == regime:
                score += 2
            try:
                rd = datetime.strptime(row["trade_date"], "%Y-%m-%d")
                if (ref_date - rd).days <= 30:
                    score += 1
            except (ValueError, TypeError):
                pass
            if score > 0:
                scored.append((score, row))

        scored.sort(key=lambda x: (-x[0], x[1]["trade_date"]))
        top = scored[:limit]

        if not top:
            return ""

        parts = ["## Relevant Past Analysis (from wiki)", ""]
        for score, row in top:
            parts.append(
                f"- **{row['ticker']}** ({row['trade_date']}): Signal={row['signal']}, "
                f"Regime={row['regime']}, Confidence={row['confidence']:.2f}"
            )

            # Read the page for a brief summary (first 10 lines after frontmatter)
            page_path = self.wiki_dir / row["path"]
            if page_path.exists():
                try:
                    content = page_path.read_text(encoding="utf-8")
                    # Skip frontmatter
                    in_fm = False
                    summary_lines = []
                    for line in content.split("\n"):
                        if line.strip() == "---":
                            in_fm = not in_fm
                            continue
                        if not in_fm and line.strip():
                            summary_lines.append(line)
                            if len(summary_lines) >= 3:
                                break
                    if summary_lines:
                        parts.append(f"  > {' '.join(summary_lines)}")
                except Exception:
                    pass
        parts.append("")

        # Overexposure detection
        active_buys = conn.execute(
            "SELECT DISTINCT ticker FROM wiki_pages "
            "WHERE page_type = 'run' AND signal IN ('Buy', 'Overweight') "
            "AND trade_date >= ? ORDER BY trade_date DESC LIMIT 20",
            ((ref_date - timedelta(days=14)).strftime("%Y-%m-%d"),),
        ).fetchall()

        if len(active_buys) > 3:
            recent_buy_tickers = [r["ticker"] for r in active_buys]
            # Check tag overlap for correlation proxy
            tag_overlap: Counter = Counter()
            for bt in recent_buy_tickers:
                tag_rows = conn.execute(
                    "SELECT tags FROM wiki_pages WHERE ticker = ? AND page_type = 'run' "
                    "ORDER BY trade_date DESC LIMIT 1",
                    (bt,),
                ).fetchall()
                for tr in tag_rows:
                    try:
                        tags = json.loads(tr["tags"]) if tr["tags"] else []
                    except (json.JSONDecodeError, TypeError):
                        tags = []
                    for tag in tags:
                        tag_overlap[tag] += 1

            shared = [(tag, cnt) for tag, cnt in tag_overlap.most_common(5) if cnt >= 3]
            if shared:
                shared_str = ", ".join(f"{tag}({cnt})" for tag, cnt in shared)
                parts.append(
                    f"**OVEREXPOSURE WARNING:** {len(recent_buy_tickers)} recent buy signals "
                    f"in last 14 days. Shared themes: {shared_str}. "
                    "Consider reducing position size."
                )
                parts.append("")

        return "\n".join(parts)

    # ── Phase 2: Reports ─────────────────────────────────────────────

    def generate_report(self, period: str, output_path: Optional[str] = None) -> Path:
        """Generate a performance report for a given period.

        ``period`` can be: "2026-05" (monthly), "2026-Q1" (quarterly),
        or "2026" (annual).  This is designed to be called interactively
        from Claude Code or the CLI, not autonomously.
        """
        conn = self._get_db()

        # Parse period into date range
        if re.match(r"^\d{4}-Q[1-4]$", period):
            year = int(period[:4])
            quarter = int(period[-1])
            month_start = (quarter - 1) * 3 + 1
            start = f"{year}-{month_start:02d}-01"
            end_month = month_start + 2
            end = f"{year}-{end_month:02d}-31"
        elif re.match(r"^\d{4}-\d{2}$", period):
            start = f"{period}-01"
            end = f"{period}-31"
        elif re.match(r"^\d{4}$", period):
            start = f"{period}-01-01"
            end = f"{period}-12-31"
        else:
            raise ValueError(f"Invalid period format: {period}. Use YYYY, YYYY-MM, or YYYY-QN")

        rows = conn.execute(
            "SELECT path, ticker, trade_date, signal, regime, confidence, tags "
            "FROM wiki_pages WHERE page_type = 'run' "
            "AND trade_date >= ? AND trade_date <= ? "
            "ORDER BY trade_date",
            (start, end),
        ).fetchall()

        total = len(rows)
        signal_counts: Counter = Counter()
        ticker_counts: Counter = Counter()
        regime_counts: Counter = Counter()

        for row in rows:
            signal_counts[row["signal"]] += 1
            ticker_counts[row["ticker"]] += 1
            regime_counts[row["regime"]] += 1

        parts = [
            f"# Performance Report — {period}",
            "",
            f"*Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}*",
            "",
            f"**Total Pipeline Runs:** {total}",
            "",
            "## Signal Summary",
            "",
        ]
        for sig, count in signal_counts.most_common():
            parts.append(f"- **{sig}:** {count}")
        parts.append("")

        parts.append("## Tickers Analyzed")
        parts.append("")
        for tkr, count in ticker_counts.most_common():
            parts.append(f"- {tkr}: {count} runs")
        parts.append("")

        parts.append("## Regime Breakdown")
        parts.append("")
        for reg, count in regime_counts.most_common():
            parts.append(f"- **{reg}:** {count} runs ({count / total * 100:.0f}%)")
        parts.append("")

        parts.append("## Run Details")
        parts.append("")
        parts.append("| Date | Ticker | Signal | Confidence | Regime |")
        parts.append("|------|--------|--------|------------|--------|")
        for row in rows:
            parts.append(
                f"| {row['trade_date']} | {row['ticker']} | {row['signal']} "
                f"| {row['confidence']:.2f} | {row['regime']} |"
            )
        parts.append("")

        # Write
        if output_path:
            report_path = Path(output_path)
        else:
            report_path = self.wiki_dir / "reports" / f"{period}.md"
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text("\n".join(parts), encoding="utf-8")

        self._index_page(WikiPageIndex(
            path=str(report_path.relative_to(self.wiki_dir)) if report_path.is_relative_to(self.wiki_dir) else str(report_path),
            ticker="*",
            trade_date=start,
            signal="report",
            regime="",
            confidence=0.0,
            tags=[],
            page_type="report",
        ))

        logger.info("Wiki report generated: %s (%d runs)", report_path, total)
        return report_path

    # ── Search ───────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search wiki pages by ticker, tag, or signal."""
        conn = self._get_db()
        q = f"%{query}%"
        rows = conn.execute(
            "SELECT path, ticker, trade_date, signal, regime, confidence, tags, page_type "
            "FROM wiki_pages "
            "WHERE ticker LIKE ? OR tags LIKE ? OR signal LIKE ? OR regime LIKE ? "
            "ORDER BY trade_date DESC LIMIT ?",
            (q, q, q, q, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def get_recent_pages(
        self, ticker: Optional[str] = None, page_type: str = "run", limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Get recent wiki pages, optionally filtered by ticker and type."""
        conn = self._get_db()
        if ticker:
            rows = conn.execute(
                "SELECT path, ticker, trade_date, signal, regime, confidence, tags, page_type "
                "FROM wiki_pages WHERE ticker = ? AND page_type = ? "
                "ORDER BY trade_date DESC LIMIT ?",
                (ticker, page_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT path, ticker, trade_date, signal, regime, confidence, tags, page_type "
                "FROM wiki_pages WHERE page_type = ? "
                "ORDER BY trade_date DESC LIMIT ?",
                (page_type, limit),
            ).fetchall()
        return [dict(row) for row in rows]

    def get_page_content(self, path: str) -> str:
        """Read the content of a wiki page by its relative path."""
        full_path = self.wiki_dir / path
        if full_path.exists():
            return full_path.read_text(encoding="utf-8")
        return ""
