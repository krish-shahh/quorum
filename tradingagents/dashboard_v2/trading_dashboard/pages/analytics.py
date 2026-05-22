"""Analytics page -- quant metrics.

Sharpe, Sortino, drawdown, win rate breakdowns, P&L by ticker, alpha.
"""

import reflex as rx

from ..state import DashboardState
from ..components import (
    page_layout, kpi_card, section_label, panel,
    MONO, TEXT, TEXT_MUTED, TEXT_DIM, GREEN, RED, ACCENT, BORDER,
)


def analytics_page() -> rx.Component:
    return page_layout(
        rx.heading("Analytics", size="5", margin_bottom="16px", color=TEXT),

        # Market Regime
        panel(
            section_label("MARKET REGIME"),
            rx.hstack(
                rx.button("Refresh Regime", size="1", variant="outline", on_click=DashboardState.refresh_regime),
                spacing="2",
                margin_bottom="8px",
            ),
            rx.grid(
                kpi_card("REGIME", DashboardState.current_regime),
                kpi_card("VIX", DashboardState.regime_vix),
                kpi_card("DXY", DashboardState.regime_dxy),
                kpi_card("10Y YIELD", DashboardState.regime_yield),
                kpi_card("CONFIDENCE", DashboardState.regime_confidence),
                columns="5",
                spacing="3",
                width="100%",
            ),
        ),

        # Top KPIs
        rx.grid(
            kpi_card("SHARPE", DashboardState.sharpe_ratio),
            kpi_card("SORTINO", DashboardState.sortino_ratio),
            kpi_card(
                "MAX DRAWDOWN",
                DashboardState.max_drawdown_ever.to(lambda d: f"{d:.1f}%"),
            ),
            kpi_card(
                "ALPHA vs SPY",
                DashboardState.alpha_vs_benchmark.to(lambda a: f"{a:+.2f}%"),
                color=rx.cond(DashboardState.alpha_vs_benchmark >= 0, GREEN, RED),
            ),
            columns="4",
            spacing="3",
            width="100%",
            margin_bottom="16px",
        ),

        # Drawdown over time
        panel(
            section_label("DRAWDOWN OVER TIME"),
            rx.cond(
                DashboardState.drawdown_series.length() > 0,  # type: ignore
                rx.recharts.area_chart(
                    rx.recharts.area(
                        data_key="dd",
                        stroke=RED,
                        fill=RED,
                        fill_opacity=0.1,
                        type_="monotone",
                    ),
                    rx.recharts.x_axis(data_key="time", font_size=10),
                    rx.recharts.y_axis(font_size=10),
                    rx.recharts.tooltip(),
                    data=DashboardState.drawdown_series,
                    width="100%",
                    height=200,
                ),
                rx.text("Not enough data", color=TEXT_DIM, padding="20px",
                         text_align="center"),
            ),
        ),

        # Win rate tables
        rx.grid(
            # By ticker
            panel(
                section_label("WIN RATE BY TICKER"),
                rx.cond(
                    DashboardState.win_rate_by_ticker.length() > 0,  # type: ignore
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("TICKER"),
                                rx.table.column_header_cell("W", text_align="right"),
                                rx.table.column_header_cell("L", text_align="right"),
                                rx.table.column_header_cell("WIN %", text_align="right"),
                            ),
                        ),
                        rx.table.body(
                            rx.foreach(
                                DashboardState.win_rate_by_ticker,
                                lambda r: rx.table.row(
                                    rx.table.cell(rx.text(r["ticker"], font_weight="600")),  # type: ignore
                                    rx.table.cell(rx.text(r["wins"], font_family=MONO, text_align="right")),  # type: ignore
                                    rx.table.cell(rx.text(r["losses"], font_family=MONO, text_align="right")),  # type: ignore
                                    rx.table.cell(rx.text(
                                        r["wr"].to(lambda w: f"{w}%"),  # type: ignore
                                        font_family=MONO, text_align="right",
                                        color=r["wr"].to(lambda w: GREEN if w >= 50 else RED),  # type: ignore
                                    )),
                                ),
                            ),
                        ),
                        variant="surface",
                        size="2",
                        width="100%",
                    ),
                    rx.text("No data", color=TEXT_DIM, text_align="center", padding="12px"),
                ),
            ),
            # By signal
            panel(
                section_label("WIN RATE BY SIGNAL"),
                rx.cond(
                    DashboardState.win_rate_by_signal.length() > 0,  # type: ignore
                    rx.table.root(
                        rx.table.header(
                            rx.table.row(
                                rx.table.column_header_cell("SIGNAL"),
                                rx.table.column_header_cell("W", text_align="right"),
                                rx.table.column_header_cell("L", text_align="right"),
                                rx.table.column_header_cell("WIN %", text_align="right"),
                            ),
                        ),
                        rx.table.body(
                            rx.foreach(
                                DashboardState.win_rate_by_signal,
                                lambda r: rx.table.row(
                                    rx.table.cell(rx.text(r["signal"], font_weight="600")),  # type: ignore
                                    rx.table.cell(rx.text(r["wins"], font_family=MONO, text_align="right")),  # type: ignore
                                    rx.table.cell(rx.text(r["losses"], font_family=MONO, text_align="right")),  # type: ignore
                                    rx.table.cell(rx.text(
                                        r["wr"].to(lambda w: f"{w}%"),  # type: ignore
                                        font_family=MONO, text_align="right",
                                        color=r["wr"].to(lambda w: GREEN if w >= 50 else RED),  # type: ignore
                                    )),
                                ),
                            ),
                        ),
                        variant="surface",
                        size="2",
                        width="100%",
                    ),
                    rx.text("No data", color=TEXT_DIM, text_align="center", padding="12px"),
                ),
            ),
            columns="2",
            spacing="3",
            width="100%",
            margin_bottom="16px",
        ),

        # P&L by ticker chart
        panel(
            section_label("P&L BY TICKER"),
            rx.cond(
                DashboardState.pnl_by_ticker.length() > 0,  # type: ignore
                rx.recharts.bar_chart(
                    rx.recharts.bar(
                        data_key="pnl",
                        fill=ACCENT,
                    ),
                    rx.recharts.x_axis(data_key="ticker", font_size=10),
                    rx.recharts.y_axis(font_size=10),
                    rx.recharts.tooltip(),
                    data=DashboardState.pnl_by_ticker,
                    width="100%",
                    height=220,
                ),
                rx.text("No data", color=TEXT_DIM, text_align="center", padding="20px"),
            ),
        ),
    )
