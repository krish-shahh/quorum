"""Wiki page — browse run pages, daily digests, and ticker summaries."""

import reflex as rx

from ..state import DashboardState
from ..components import page_layout, section_label, panel, BG, SURFACE, TEXT, TEXT_MUTED, ACCENT, MONO, BORDER


def _wiki_row(item: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["ticker"], font_family=MONO, font_size="13px")),
        rx.table.cell(rx.text(item["trade_date"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(rx.text(item["signal"], font_size="13px")),
        rx.table.cell(rx.text(item["regime"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(
            rx.text(
                rx.cond(item["confidence"], item["confidence"], "0"),
                font_family=MONO,
                font_size="13px",
            )
        ),
        rx.table.cell(
            rx.button(
                "View",
                size="1",
                variant="ghost",
                color_scheme="blue",
                on_click=DashboardState.view_wiki_page(item["path"]),
            )
        ),
    )


def _digest_row(item: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["trade_date"], font_size="13px")),
        rx.table.cell(rx.text(item["regime"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(
            rx.button(
                "View",
                size="1",
                variant="ghost",
                color_scheme="blue",
                on_click=DashboardState.view_wiki_page(item["path"]),
            )
        ),
    )


def _ticker_row(item: dict) -> rx.Component:
    return rx.table.row(
        rx.table.cell(rx.text(item["ticker"], font_family=MONO, font_size="13px", font_weight="600")),
        rx.table.cell(rx.text(item["regime"], font_size="13px", color=TEXT_MUTED)),
        rx.table.cell(
            rx.button(
                "View",
                size="1",
                variant="ghost",
                color_scheme="blue",
                on_click=DashboardState.view_wiki_page(item["path"]),
            )
        ),
    )


def wiki_page() -> rx.Component:
    return page_layout(
        rx.heading("Wiki", size="5", font_weight="600", color=TEXT, margin_bottom="20px"),

        # Refresh button
        rx.button("Refresh Wiki", size="2", variant="outline", on_click=DashboardState.refresh_wiki, margin_bottom="20px"),

        # Page content viewer
        rx.cond(
            DashboardState.wiki_page_content != "",
            panel(
                rx.hstack(
                    rx.heading(DashboardState.wiki_page_title, size="4", color=TEXT),
                    rx.spacer(),
                    rx.button(
                        "Close",
                        size="1",
                        variant="ghost",
                        on_click=DashboardState.close_wiki_page,
                    ),
                ),
                rx.separator(margin_y="12px"),
                rx.code_block(
                    DashboardState.wiki_page_content,
                    language="markdown",
                    font_size="12px",
                    max_height="500px",
                    overflow_y="auto",
                ),
            ),
        ),

        # Recent run pages
        panel(
            section_label("Recent Run Pages"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Ticker"),
                        rx.table.column_header_cell("Date"),
                        rx.table.column_header_cell("Signal"),
                        rx.table.column_header_cell("Regime"),
                        rx.table.column_header_cell("Confidence"),
                        rx.table.column_header_cell(""),
                    ),
                ),
                rx.table.body(
                    rx.foreach(DashboardState.wiki_run_pages, _wiki_row),
                ),
                width="100%",
            ),
        ),

        # Daily digests
        panel(
            section_label("Daily Digests"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Date"),
                        rx.table.column_header_cell("Regime"),
                        rx.table.column_header_cell(""),
                    ),
                ),
                rx.table.body(
                    rx.foreach(DashboardState.wiki_daily_digests, _digest_row),
                ),
                width="100%",
            ),
        ),

        # Ticker summaries
        panel(
            section_label("Ticker Summaries"),
            rx.table.root(
                rx.table.header(
                    rx.table.row(
                        rx.table.column_header_cell("Ticker"),
                        rx.table.column_header_cell("Regime"),
                        rx.table.column_header_cell(""),
                    ),
                ),
                rx.table.body(
                    rx.foreach(DashboardState.wiki_ticker_summaries, _ticker_row),
                ),
                width="100%",
            ),
        ),
    )
