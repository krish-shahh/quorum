"""History page -- timeline of past trading days with drill-down modals.

Click any trade in the timeline to see full details: agent reports,
signal breakdown, execution info.
"""

import reflex as rx

from ..state import DashboardState
from ..components import (
    page_layout, section_label, panel,
    MONO, TEXT, TEXT_MUTED, TEXT_DIM, GREEN, RED, ACCENT, BORDER, SURFACE, SURFACE2,
)


def history_page() -> rx.Component:
    return page_layout(
        rx.heading("History", size="5", margin_bottom="16px", color=TEXT),

        # Equity curve (full history)
        panel(
            section_label("PORTFOLIO VALUE OVER TIME"),
            rx.cond(
                DashboardState.equity_data.length() > 0,
                rx.recharts.area_chart(
                    rx.recharts.area(
                        data_key="value",
                        stroke=ACCENT,
                        fill=ACCENT,
                        fill_opacity=0.08,
                        type_="monotone",
                    ),
                    rx.recharts.x_axis(data_key="time"),
                    rx.recharts.y_axis(),
                    rx.recharts.tooltip(),
                    rx.recharts.cartesian_grid(stroke_dasharray="3 3", opacity=0.3),
                    data=DashboardState.equity_data,
                    width="100%",
                    height=280,
                ),
                rx.text("No data yet", color=TEXT_DIM, padding="40px", text_align="center"),
            ),
        ),

        # Trade timeline
        panel(
            section_label("TRADE TIMELINE"),
            rx.text("Click a trade to see full details", font_size="11px",
                    color=TEXT_DIM, margin_bottom="8px"),
            rx.cond(
                DashboardState.recent_trades.length() > 0,
                rx.vstack(
                    rx.foreach(
                        DashboardState.recent_trades,
                        _timeline_entry,
                    ),
                    spacing="2",
                    width="100%",
                ),
                rx.text("No trade history yet.", color=TEXT_DIM, padding="20px",
                         text_align="center"),
            ),
        ),

        # Trade detail modal
        rx.dialog.root(
            rx.dialog.content(
                rx.dialog.title(
                    rx.hstack(
                        rx.text(DashboardState.modal_ticker, font_weight="700", font_size="18px"),
                        rx.badge(DashboardState.modal_signal, size="2", variant="soft"),
                        rx.badge(DashboardState.modal_action, size="2",
                                 color_scheme=DashboardState.modal_action_color),
                        spacing="2",
                        align="center",
                    ),
                ),
                rx.dialog.description(
                    DashboardState.modal_time,
                    font_family=MONO,
                    font_size="12px",
                    color=TEXT_MUTED,
                ),
                rx.separator(margin_y="12px"),

                # Execution details
                rx.vstack(
                    _detail_row("Side", DashboardState.modal_side),
                    _detail_row("Quantity", DashboardState.modal_qty),
                    _detail_row("Fill Price", DashboardState.modal_fill),
                    _detail_row("Account Before", DashboardState.modal_acct_before),
                    _detail_row("Account After", DashboardState.modal_acct_after),
                    _detail_row("Trade P&L", DashboardState.modal_trade_pnl),
                    _detail_row("Reason", DashboardState.modal_reason),
                    spacing="2",
                    width="100%",
                ),

                rx.dialog.close(
                    rx.button("Close", variant="soft", margin_top="16px"),
                ),
                max_width="500px",
            ),
            open=DashboardState.modal_open,
            on_open_change=DashboardState.set_modal_open,
        ),
    )


def _timeline_entry(trade: dict) -> rx.Component:
    return rx.box(
        rx.hstack(
            # Time
            rx.box(
                rx.text(trade["time"], font_size="10px", font_family=MONO, color=TEXT_DIM),
                min_width="120px",
            ),
            # Dot
            rx.box(
                rx.box(
                    width="8px", height="8px", border_radius="50%",
                    bg=trade["action"].to(
                        lambda a: GREEN if a == "executed" else (RED if a == "blocked" else TEXT_DIM)
                    ),
                ),
                padding_top="4px",
            ),
            # Content
            rx.box(
                rx.hstack(
                    rx.text(trade["ticker"], font_weight="600", font_size="13px"),
                    rx.badge(trade["signal"], size="1", variant="soft"),
                    rx.text(trade["side"], font_size="11px", font_family=MONO, color=TEXT_MUTED),
                    rx.text(trade["fill"], font_size="11px", font_family=MONO, color=TEXT_MUTED),
                    spacing="2",
                    align="center",
                ),
                flex="1",
                bg=SURFACE2,
                padding="8px 12px",
                border_radius="6px",
                border_left=trade["action"].to(
                    lambda a: f"3px solid {GREEN}" if a == "executed" else f"3px solid {TEXT_DIM}"
                ),
                cursor="pointer",
                _hover={"opacity": "0.8"},
                on_click=DashboardState.open_trade_modal(trade),
            ),
            spacing="3",
            align="start",
            width="100%",
            padding_y="2px",
        ),
    )


def _detail_row(label: str, value) -> rx.Component:
    return rx.hstack(
        rx.text(label, font_size="12px", color=TEXT_MUTED, min_width="120px", font_weight="500"),
        rx.text(value, font_size="12px", font_family=MONO, font_weight="600"),
        spacing="3",
        width="100%",
    )
