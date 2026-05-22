"""Overview page -- the 5-second glance.

KPIs, equity curve, positions table, allocation chart.
"""

import reflex as rx

from ..state import DashboardState
from ..components import (
    page_layout, section_label, panel,
    MONO, TEXT, TEXT_MUTED, TEXT_DIM, GREEN, RED, ACCENT, BORDER, SURFACE, SURFACE2,
)


def overview_page() -> rx.Component:
    return page_layout(
        # KPI row
        rx.grid(
            _kpi("PORTFOLIO", DashboardState.portfolio_display, DashboardState.pnl_display),
            _kpi("CASH", DashboardState.cash_display),
            _kpi("P&L", DashboardState.pnl_display, DashboardState.pnl_pct_display),
            _kpi("DRAWDOWN", DashboardState.drawdown_display, DashboardState.dd_limit_display),
            _kpi("WIN RATE", DashboardState.win_rate_display, DashboardState.trade_count_display),
            columns="5",
            spacing="3",
            width="100%",
            margin_bottom="16px",
        ),

        # Charts row
        rx.grid(
            # Equity curve
            panel(
                section_label("EQUITY CURVE"),
                rx.cond(
                    DashboardState.equity_data.length() > 0,
                    rx.recharts.area_chart(
                        rx.recharts.area(
                            data_key="value",
                            stroke=ACCENT,
                            fill=ACCENT,
                            fill_opacity=0.08,
                        ),
                        rx.recharts.x_axis(data_key="time"),
                        rx.recharts.y_axis(),
                        rx.recharts.tooltip(),
                        data=DashboardState.equity_data,
                        width="100%",
                        height=220,
                    ),
                    rx.text("No data yet", color=TEXT_DIM, padding="40px",
                            text_align="center"),
                ),
            ),
            # Allocation
            panel(
                section_label("ALLOCATION"),
                rx.cond(
                    DashboardState.allocation_data.length() > 0,
                    rx.recharts.bar_chart(
                        rx.recharts.bar(
                            data_key="value",
                            fill=ACCENT,
                        ),
                        rx.recharts.x_axis(data_key="asset"),
                        rx.recharts.y_axis(),
                        rx.recharts.tooltip(),
                        data=DashboardState.allocation_data,
                        width="100%",
                        height=220,
                    ),
                    rx.text("No positions", color=TEXT_DIM, padding="40px",
                            text_align="center"),
                ),
            ),
            columns=rx.breakpoints(initial="1", md="2"),
            spacing="3",
            width="100%",
            margin_bottom="16px",
        ),

        # Positions table
        panel(
            section_label("POSITIONS"),
            rx.cond(
                DashboardState.positions.length() > 0,
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("TICKER"),
                            rx.table.column_header_cell("QTY"),
                            rx.table.column_header_cell("AVG COST"),
                            rx.table.column_header_cell("MKT VAL"),
                            rx.table.column_header_cell("P&L"),
                            rx.table.column_header_cell("RETURN"),
                            rx.table.column_header_cell("WEIGHT"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            DashboardState.positions,
                            _position_row,
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
                rx.text("No open positions", color=TEXT_DIM, padding="20px",
                         text_align="center"),
            ),
        ),
    )


def _kpi(label: str, value, sub=None) -> rx.Component:
    """Simple KPI card with optional sub-label."""
    children = [
        rx.text(label, font_size="9px", color=TEXT_DIM, font_weight="600",
                letter_spacing="1px"),
        rx.text(value, font_size="22px", font_weight="700",
                font_family=MONO, line_height="1.2"),
    ]
    if sub is not None:
        children.append(rx.text(sub, font_size="11px", font_family=MONO, color=TEXT_MUTED))
    return rx.box(
        rx.vstack(*children, spacing="1"),
        background=SURFACE,
        border=f"1px solid {BORDER}",
        border_radius="6px",
        padding="12px 14px",
    )


def _position_row(pos: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(pos["ticker"], font_weight="600")),  # type: ignore
        rx.table.cell(rx.text(pos["quantity"], font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(pos["avg_cost"], font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(pos["last_price"], font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(pos["market_value"], font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(pos["unrealized_pnl"], font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(pos["pct_return"], font_family=MONO)),  # type: ignore
        rx.table.cell(rx.text(pos["weight"], font_family=MONO)),  # type: ignore
    )
