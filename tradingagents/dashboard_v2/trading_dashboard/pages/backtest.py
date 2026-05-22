"""Backtest page — view past backtest results (monitoring only)."""

import reflex as rx

from ..state import DashboardState
from ..components import page_layout, section_label, panel, kpi_card, BG, SURFACE, TEXT, TEXT_MUTED, ACCENT, GREEN, RED, MONO, BORDER


def _bt_run_row(item: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["run_id"], font_family=MONO, font_size="12px")),
        rx.table.cell(rx.text(item["tickers"], font_size="13px")),
        rx.table.cell(rx.text(item["start_date"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(rx.text(item["end_date"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(rx.text(f"{item['total_return']:.1f}%", font_family=MONO, font_size="13px")),
        rx.table.cell(rx.text(f"{item['win_rate']:.0f}%", font_family=MONO, font_size="13px")),
        rx.table.cell(rx.text(str(item["total_trades"]), font_family=MONO, font_size="13px")),
        rx.table.cell(
            rx.button(
                "Load",
                size="1",
                variant="ghost",
                color_scheme="blue",
                on_click=DashboardState.load_backtest_result(item["run_id"]),
            )
        ),
    )


def _bt_trade_row(item: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["date"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(rx.text(item["ticker"], font_family=MONO, font_size="13px")),
        rx.table.cell(rx.text(item["signal"], font_size="13px")),
        rx.table.cell(rx.text(item["side"], font_size="13px")),
        rx.table.cell(rx.text(str(item["quantity"]), font_family=MONO, font_size="13px")),
    )


def backtest_page() -> rx.Component:
    return page_layout(
        rx.heading("Backtest", size="5", font_weight="600", color=TEXT, margin_bottom="20px"),


        # Equity curve for selected backtest
        rx.cond(
            DashboardState.bt_selected_equity.length() > 0,
            panel(
                section_label("Equity Curve"),
                rx.recharts.area_chart(
                    rx.recharts.area(
                        data_key="value",
                        stroke=ACCENT,
                        fill=ACCENT,
                        fill_opacity=0.1,
                    ),
                    rx.recharts.x_axis(data_key="date", font_size=11),
                    rx.recharts.y_axis(font_size=11),
                    rx.recharts.tooltip(),
                    data=DashboardState.bt_selected_equity,
                    width="100%",
                    height=250,
                ),
            ),
        ),

        # Selected backtest trades
        rx.cond(
            DashboardState.bt_selected_trades.length() > 0,
            panel(
                section_label("Backtest Trades"),
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("Date"),
                            rx.table.column_header_cell("Ticker"),
                            rx.table.column_header_cell("Signal"),
                            rx.table.column_header_cell("Side"),
                            rx.table.column_header_cell("Qty"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(DashboardState.bt_selected_trades, _bt_trade_row),
                    ),
                    width="100%",
                ),
            ),
        ),

        # Past runs
        panel(
            rx.hstack(
                section_label("Past Backtest Runs"),
                rx.spacer(),
                rx.button("Refresh", size="1", variant="ghost", on_click=DashboardState.refresh_backtest_runs),
            ),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Run ID"),
                        rx.table.column_header_cell("Tickers"),
                        rx.table.column_header_cell("Start"),
                        rx.table.column_header_cell("End"),
                        rx.table.column_header_cell("Return"),
                        rx.table.column_header_cell("Win Rate"),
                        rx.table.column_header_cell("Trades"),
                        rx.table.column_header_cell(""),
                    ),
                ),
                rx.table.body(
                    rx.foreach(DashboardState.bt_runs, _bt_run_row),
                ),
                width="100%",
            ),
        ),
    )
