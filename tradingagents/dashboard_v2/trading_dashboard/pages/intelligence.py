"""Intelligence page -- alternative data and edge finding.

Politician trades, discovery scanner, ETF analytics.
"""

import reflex as rx

from ..state import DashboardState
from ..components import (
    page_layout, section_label, panel,
    MONO, TEXT, TEXT_MUTED, TEXT_DIM, GREEN, RED, AMBER, ACCENT, BORDER, SURFACE2,
)


def intelligence_page() -> rx.Component:
    return page_layout(
        rx.heading("Intelligence", size="5", margin_bottom="16px", color=TEXT),

        # Politician trades
        panel(
            rx.hstack(
                section_label("CONGRESSIONAL TRADES"),
                rx.spacer(),
                rx.button(
                    "Refresh",
                    on_click=DashboardState.refresh_politicians,
                    size="1",
                    variant="outline",
                    color_scheme="gray",
                ),
                align="center",
                margin_bottom="8px",
            ),
            rx.cond(
                DashboardState.politician_trades.length() > 0,  # type: ignore
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("POLITICIAN"),
                            rx.table.column_header_cell("TICKER"),
                            rx.table.column_header_cell("TYPE"),
                            rx.table.column_header_cell("AMOUNT"),
                            rx.table.column_header_cell("DATE"),
                            rx.table.column_header_cell("CHAMBER"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            DashboardState.politician_trades,
                            lambda t: rx.table.row(
                                rx.table.cell(rx.text(t["politician"], font_weight="500")),  # type: ignore
                                rx.table.cell(rx.text(t["ticker"], font_weight="600",  # type: ignore
                                                       font_family=MONO)),
                                rx.table.cell(
                                    rx.badge(
                                        t["type"].to(lambda v: "BUY" if v == "purchase" else "SELL"),  # type: ignore
                                        color_scheme=t["type"].to(lambda v: "green" if v == "purchase" else "red"),  # type: ignore
                                        size="1",
                                    ),
                                ),
                                rx.table.cell(rx.text(t["amount"], font_size="11px")),  # type: ignore
                                rx.table.cell(rx.text(t["date"], font_family=MONO,  # type: ignore
                                                       font_size="11px")),
                                rx.table.cell(rx.text(t["chamber"], font_size="11px",  # type: ignore
                                                       color=TEXT_MUTED)),
                            ),
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
                rx.text(
                    "Click Refresh to fetch congressional trades from Capitol Trades.",
                    color=TEXT_DIM, padding="20px", text_align="center",
                ),
            ),
        ),

        # Hot tickers (convergence)
        rx.cond(
            DashboardState.hot_tickers.length() > 0,  # type: ignore
            panel(
                section_label("CONVERGENCE SIGNALS"),
                rx.text("Tickers where multiple politicians traded the same direction",
                         font_size="11px", color=TEXT_MUTED, margin_bottom="8px"),
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("TICKER"),
                            rx.table.column_header_cell("DIRECTION"),
                            rx.table.column_header_cell("POLITICIANS"),
                            rx.table.column_header_cell("STRENGTH"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            DashboardState.hot_tickers,
                            lambda s: rx.table.row(
                                rx.table.cell(rx.text(s["ticker"], font_weight="600",  # type: ignore
                                                       font_family=MONO)),
                                rx.table.cell(
                                    rx.badge(
                                        s["direction"].to(lambda d: d.upper()),  # type: ignore
                                        color_scheme=s["direction"].to(  # type: ignore
                                            lambda d: "green" if d == "bullish" else ("red" if d == "bearish" else "gray")
                                        ),
                                        size="1",
                                    ),
                                ),
                                rx.table.cell(rx.text(s["politicians"], font_family=MONO)),  # type: ignore
                                rx.table.cell(rx.text(
                                    s["strength"],  # type: ignore
                                    font_family=MONO,
                                    color=s["strength"].to(lambda v: GREEN if v >= 0.6 else TEXT_MUTED),  # type: ignore
                                )),
                            ),
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
            ),
            rx.fragment(),
        ),

        # Sector Rotation
        panel(
            rx.hstack(
                section_label("SECTOR ROTATION"),
                rx.spacer(),
                rx.button(
                    "Refresh",
                    on_click=DashboardState.refresh_sectors,
                    size="1",
                    variant="outline",
                    color_scheme="gray",
                ),
                align="center",
                margin_bottom="8px",
            ),
            rx.text(
                rx.text.strong("Rotation: "),
                DashboardState.rotation_direction,
                font_size="13px",
                margin_bottom="8px",
            ),
            rx.cond(
                DashboardState.sector_rotation.length() > 0,  # type: ignore
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("SECTOR"),
                            rx.table.column_header_cell("ETF"),
                            rx.table.column_header_cell("1M RETURN"),
                            rx.table.column_header_cell("vs SPY"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            DashboardState.sector_rotation,
                            lambda s: rx.table.row(
                                rx.table.cell(rx.text(s["name"], font_size="13px")),  # type: ignore
                                rx.table.cell(rx.text(s["etf"], font_family=MONO, font_size="13px")),  # type: ignore
                                rx.table.cell(rx.text(
                                    s["return_1m"].to(lambda v: f"{v}%"),  # type: ignore
                                    font_family=MONO, font_size="13px",
                                )),
                                rx.table.cell(rx.text(
                                    s["relative_1m"].to(lambda v: f"{v:+}%"),  # type: ignore
                                    font_family=MONO, font_size="13px",
                                    color=s["relative_1m"].to(lambda v: GREEN if v > 0 else RED),  # type: ignore
                                )),
                            ),
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
                rx.text(
                    "Click Refresh to load sector rotation data.",
                    color=TEXT_DIM, padding="20px", text_align="center",
                ),
            ),
        ),

        # Discovery scanner
        panel(
            rx.hstack(
                section_label("DISCOVERY SCANNER"),
                rx.spacer(),
                rx.button(
                    "Run Scan",
                    on_click=DashboardState.refresh_discovery,
                    size="1",
                    variant="outline",
                    color_scheme="gray",
                ),
                align="center",
                margin_bottom="8px",
            ),
            rx.cond(
                DashboardState.discovered_candidates.length() > 0,  # type: ignore
                rx.table.root(
                    rx.table.header(
                        rx.table.row(
                            rx.table.column_header_cell("TICKER"),
                            rx.table.column_header_cell("SOURCE"),
                            rx.table.column_header_cell("STRENGTH"),
                            rx.table.column_header_cell("REASON"),
                        ),
                    ),
                    rx.table.body(
                        rx.foreach(
                            DashboardState.discovered_candidates,
                            lambda c: rx.table.row(
                                rx.table.cell(rx.text(c["ticker"], font_weight="600",  # type: ignore
                                                       font_family=MONO)),
                                rx.table.cell(rx.text(c["source"], font_size="11px")),  # type: ignore
                                rx.table.cell(rx.text(c["strength"], font_family=MONO)),  # type: ignore
                                rx.table.cell(rx.text(c["reason"], font_size="11px",  # type: ignore
                                                       color=TEXT_MUTED,
                                                       max_width="300px",
                                                       overflow="hidden",
                                                       text_overflow="ellipsis",
                                                       white_space="nowrap")),
                            ),
                        ),
                    ),
                    variant="surface",
                    size="2",
                    width="100%",
                ),
                rx.text(
                    "Click Run Scan to find opportunities beyond your watchlist.",
                    color=TEXT_DIM, padding="20px", text_align="center",
                ),
            ),
        ),
    )
