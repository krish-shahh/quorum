"""System page — monitoring only.

Kill switch status, execution mode, market status, portfolio rules,
watchlist display. No input controls — all trading is driven by
Claude Code via MCP tools.
"""

import reflex as rx

from ..state import DashboardState
from ..components import (
    page_layout, section_label, panel,
    MONO, TEXT, TEXT_MUTED, TEXT_DIM, GREEN, RED, AMBER, ACCENT, BORDER, SURFACE, SURFACE2,
)


def system_page() -> rx.Component:
    return page_layout(
        rx.heading("System", size="5", margin_bottom="16px", color=TEXT),

        # ── Row 1: Kill Switch + Mode + Market ──
        rx.grid(
            panel(
                section_label("KILL SWITCH"),
                rx.cond(
                    DashboardState.kill_switch_active,
                    rx.box(
                        rx.text("All trading is HALTED.", color=RED, font_weight="600"),
                        padding="8px 12px", background="#fee2e2", border_radius="6px",
                    ),
                    rx.box(
                        rx.text("Trading is active.", color=GREEN, font_weight="600"),
                        padding="8px 12px", background="#dcfce7", border_radius="6px",
                    ),
                ),
            ),
            panel(
                section_label("EXECUTION MODE"),
                rx.cond(
                    DashboardState.execution_mode == "paper",
                    rx.badge("PAPER MODE", color_scheme="green", size="2"),
                    rx.badge("LIVE MODE", color_scheme="red", size="2"),
                ),
            ),
            panel(
                section_label("MARKET STATUS"),
                rx.hstack(
                    rx.cond(
                        DashboardState.market_open,
                        rx.box(width="10px", height="10px", border_radius="50%", bg=GREEN),
                        rx.box(width="10px", height="10px", border_radius="50%", bg=TEXT_DIM),
                    ),
                    rx.text(DashboardState.market_status_text, font_weight="600", font_size="13px"),
                    spacing="2", align="center",
                ),
            ),
            columns=rx.breakpoints(initial="1", md="3"),
            spacing="3", width="100%", margin_bottom="16px",
        ),

        # ── Row 2: Watchlist (read-only display) ──
        panel(
            section_label("WATCHLIST"),
            rx.text("Managed via ~/.tradingagents/tickers.txt and Claude Code MCP tools.",
                    font_size="11px", color=TEXT_DIM, margin_bottom="8px"),
            rx.cond(
                DashboardState.watchlist_tickers.length() > 0,
                rx.flex(
                    rx.foreach(
                        DashboardState.watchlist_tickers,
                        lambda t: rx.badge(t, size="1", variant="surface", font_family=MONO),
                    ),
                    flex_wrap="wrap",
                    gap="6px",
                ),
                rx.text("No tickers in watchlist", color=TEXT_DIM, font_size="12px"),
            ),
        ),

        # ── Row 3: Risk Parameters (read-only) ──
        panel(
            section_label("RISK PARAMETERS"),
            rx.text("Set via environment variables or DEFAULT_CONFIG.",
                    font_size="11px", color=TEXT_DIM, margin_bottom="8px"),
            rx.grid(
                _param("Position Size", DashboardState.config_max_pos_pct, "%"),
                _param("Ticker Cap", DashboardState.config_max_ticker_pct, "%"),
                _param("Max Positions", DashboardState.config_max_open_pos, ""),
                _param("Drawdown Limit", DashboardState.config_max_drawdown, "%"),
                _param("Paper Balance", DashboardState.config_paper_balance, "$"),
                columns=rx.breakpoints(initial="2", md="5"),
                spacing="3", width="100%",
            ),
        ),

        # ── Row 4: How to Trade ──
        panel(
            section_label("HOW TO TRADE"),
            rx.vstack(
                rx.text("All trading is done through Claude Code or Claude Desktop via MCP tools.",
                        font_size="12px", color=TEXT),
                rx.code_block(
                    'In Claude Code:\n  /trading-council    — 4 parallel analyst subagents\n  /trading-cycle      — simpler single-agent mode\n\nOr just say:\n  "Run my autonomous trading cycle"\n  "Analyze AAPL for me"',
                    language="bash",
                    font_size="11px",
                ),
                rx.text("Tickers: edit ~/.tradingagents/tickers.txt",
                        font_size="11px", color=TEXT_MUTED),
                rx.text("Kill switch: tradingagents reset-kill-switch",
                        font_size="11px", color=TEXT_MUTED),
                spacing="3",
            ),
        ),
    )


def _param(label: str, value, unit: str) -> rx.Component:
    return rx.vstack(
        rx.text(label, font_size="10px", color=TEXT_DIM, font_weight="600"),
        rx.text(value, font_size="14px", font_family=MONO, font_weight="600"),
        spacing="1",
    )
