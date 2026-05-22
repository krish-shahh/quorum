"""Activity page -- what happened today.

Trade log, trade reports (pre/post analysis), signal distribution.
"""

import reflex as rx

from ..state import DashboardState
from ..components import (
    page_layout, section_label, panel,
    MONO, TEXT, TEXT_MUTED, TEXT_DIM, GREEN, RED, ACCENT, ACCENT_BG, BORDER,
)


def activity_page() -> rx.Component:
    return page_layout(
        rx.heading("Activity", size="5", margin_bottom="16px", color=TEXT),

        # Signal summary
        rx.grid(
            panel(
                section_label("TODAY'S SIGNALS"),
                rx.hstack(
                    _signal_badge("Total", DashboardState.total_trades, TEXT_MUTED),
                    _signal_badge("Wins", DashboardState.wins, GREEN),
                    _signal_badge("Losses", DashboardState.losses, RED),
                    spacing="4",
                ),
            ),
            columns="1",
            width="100%",
            margin_bottom="16px",
        ),

        # Signal distribution
        rx.cond(
            DashboardState.signal_distribution.length() > 0,
            panel(
                section_label("SIGNAL DISTRIBUTION"),
                rx.recharts.bar_chart(
                    rx.recharts.bar(data_key="count", fill=ACCENT),
                    rx.recharts.x_axis(data_key="signal"),
                    rx.recharts.y_axis(),
                    rx.recharts.tooltip(),
                    data=DashboardState.signal_distribution,
                    width="100%",
                    height=150,
                ),
            ),
            rx.fragment(),
        ),

        # Trade reports (pre/post analysis)
        panel(
            rx.hstack(
                section_label("TRADE REPORTS"),
                rx.spacer(),
                rx.button("Refresh", on_click=DashboardState.refresh_trade_reports,
                          size="1", variant="outline", color_scheme="gray"),
                justify="between",
                align="center",
                margin_bottom="8px",
            ),
            rx.cond(
                DashboardState.trade_reports.length() > 0,
                rx.vstack(
                    rx.foreach(DashboardState.trade_reports, _report_card),
                    spacing="2",
                    width="100%",
                ),
                rx.text("No trade reports yet. Run the trading cycle to generate analyses.",
                         color=TEXT_DIM, padding="20px", text_align="center"),
            ),
        ),

        # Trade log
        panel(
            rx.hstack(
                section_label("TRADE LOG"),
                rx.spacer(),
                rx.button("Export CSV", on_click=DashboardState.export_csv,
                          size="1", variant="outline", color_scheme="blue"),
                justify="between",
                align="center",
                margin_bottom="8px",
            ),
            rx.cond(
                DashboardState.recent_trades.length() > 0,  # type: ignore
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("TIME"),
                            rx.table.column_header_cell("TICKER"),
                            rx.table.column_header_cell("SIGNAL"),
                            rx.table.column_header_cell("ACTION"),
                            rx.table.column_header_cell("SIDE"),
                            rx.table.column_header_cell("QTY", text_align="right"),
                            rx.table.column_header_cell("FILL", text_align="right"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            DashboardState.recent_trades,
                            _trade_row,
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
                rx.text("No trades yet. Start autonomous mode from the System tab.",
                         color=TEXT_DIM, padding="20px", text_align="center"),
            ),
        ),

        # Report detail modal
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.hstack(
                        rx.text(
                            DashboardState.report_detail["ticker"],  # type: ignore
                            font_weight="700", font_size="18px",
                        ),
                        rx.badge(
                            DashboardState.report_detail["report_type"].to(  # type: ignore
                                lambda t: "PRE-TRADE" if t == "pre" else "POST-TRADE"
                            ),
                            color_scheme=DashboardState.report_detail["report_type"].to(  # type: ignore
                                lambda t: "blue" if t == "pre" else "green"
                            ),
                            size="2",
                        ),
                        rx.badge(
                            DashboardState.report_detail["signal"],  # type: ignore
                            color_scheme=DashboardState.report_detail["signal"].to(  # type: ignore
                                lambda s: "green" if s == "Buy" else ("red" if s == "Sell" else "gray")
                            ),
                            size="2",
                        ),
                        spacing="2",
                        align="center",
                    ),
                ),
                rx.dialog.description(
                    rx.text(
                        DashboardState.report_detail["trade_date"],  # type: ignore
                        font_family=MONO, font_size="12px", color=TEXT_MUTED,
                    ),
                ),
                rx.separator(margin_y="12px"),

                rx.vstack(
                    _report_section("Reasoning", DashboardState.report_detail["reasoning"]),  # type: ignore
                    _report_section("Technicals", DashboardState.report_detail["technicals"]),  # type: ignore
                    _report_section("Fundamentals", DashboardState.report_detail["fundamentals"]),  # type: ignore
                    _report_section("Sentiment", DashboardState.report_detail["sentiment"]),  # type: ignore
                    _report_section("Catalyst", DashboardState.report_detail["news_catalyst"]),  # type: ignore
                    _report_section("Risk Factors", DashboardState.report_detail["risk_factors"]),  # type: ignore
                    spacing="3",
                    width="100%",
                ),

                # Post-trade execution details
                rx.cond(
                    DashboardState.report_detail["report_type"].to(lambda t: t == "post"),  # type: ignore
                    rx.box(
                        rx.separator(margin_y="12px"),
                        rx.hstack(
                            rx.text("Execution", font_weight="600", font_size="13px"),
                            spacing="2",
                        ),
                        rx.hstack(
                            rx.text("Fill:", font_size="12px", color=TEXT_MUTED),
                            rx.text(
                                DashboardState.report_detail["fill_price"].to(  # type: ignore
                                    lambda p: f"${p:,.2f}" if p else "N/A"
                                ),
                                font_family=MONO, font_size="12px",
                            ),
                            rx.text("Qty:", font_size="12px", color=TEXT_MUTED),
                            rx.text(
                                DashboardState.report_detail["quantity"],  # type: ignore
                                font_family=MONO, font_size="12px",
                            ),
                            spacing="3",
                        ),
                        margin_top="8px",
                    ),
                ),

                rx.dialog.close(
                    rx.button("Close", variant="soft", margin_top="16px"),
                ),
                max_width="600px",
            ),
            open=DashboardState.report_detail_open,
            on_open_change=lambda v: DashboardState.close_report_detail(),
        ),
    )


def _report_card(report: dict) -> rx.Component:
    """Compact card for a trade report in the list."""
    return rx.box(
        rx.hstack(
            # Type badge
            rx.badge(
                report["report_type"].to(lambda t: "PRE" if t == "pre" else "POST"),  # type: ignore
                color_scheme=report["report_type"].to(lambda t: "blue" if t == "pre" else "green"),  # type: ignore
                size="1",
                min_width="40px",
            ),
            # Ticker
            rx.text(report["ticker"], font_weight="600", font_family=MONO, min_width="50px"),  # type: ignore
            # Signal
            rx.badge(
                report["signal"],  # type: ignore
                color_scheme=report["signal"].to(  # type: ignore
                    lambda s: "green" if s == "Buy" else ("red" if s == "Sell" else "gray")
                ),
                size="1",
            ),
            # Confidence
            rx.text(
                report["confidence"].to(lambda c: f"{c:.0%}"),  # type: ignore
                font_family=MONO, font_size="11px", color=TEXT_MUTED,
            ),
            # Reasoning (truncated)
            rx.text(
                report["reasoning"],  # type: ignore
                font_size="11px", color=TEXT_MUTED,
                max_width="400px", overflow="hidden",
                text_overflow="ellipsis", white_space="nowrap",
            ),
            rx.spacer(),
            # Date
            rx.text(report["trade_date"], font_size="10px", font_family=MONO, color=TEXT_DIM),  # type: ignore
            spacing="3",
            align="center",
            width="100%",
        ),
        padding="8px 12px",
        border_radius="6px",
        border_left=report["report_type"].to(  # type: ignore
            lambda t: f"3px solid {ACCENT}" if t == "pre" else f"3px solid {GREEN}"
        ),
        bg=ACCENT_BG,
        cursor="pointer",
        _hover={"opacity": "0.8"},
        on_click=DashboardState.open_report_detail(report),
    )


def _report_section(label: str, value) -> rx.Component:
    """Expandable section in the report detail modal."""
    return rx.cond(
        value != "",
        rx.box(
            rx.text(label, font_size="11px", font_weight="600", color=TEXT_MUTED,
                    letter_spacing="0.5px", margin_bottom="2px"),
            rx.text(value, font_size="12px", color=TEXT, line_height="1.5"),
        ),
    )


def _trade_row(trade: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(trade["time"], font_size="11px", font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(trade["ticker"], font_weight="600")),  # type: ignore
        rx.table.cell(rx.text(trade["signal"], font_size="12px")),  # type: ignore
        rx.table.cell(
            rx.badge(
                trade["action"],  # type: ignore
                color_scheme=trade["action"].to(  # type: ignore
                    lambda a: "green" if a == "executed" else ("red" if a == "blocked" else "gray")
                ),
                size="1",
            ),
        ),
        rx.table.cell(rx.text(trade["side"], font_family=MONO, font_size="11px")),  # type: ignore
        rx.table.cell(rx.text(trade["qty"], font_family=MONO, text_align="right")),  # type: ignore
        rx.table.cell(rx.text(trade["fill"], font_family=MONO, text_align="right")),  # type: ignore
    )


def _signal_badge(label: str, value, color: str) -> rx.Component:
    return rx.vstack(
        rx.text(label, font_size="10px", color=TEXT_DIM, font_weight="600"),
        rx.text(value, font_size="20px", font_weight="700", font_family=MONO,
                color=color),
        spacing="1",
        align="center",
    )
