"""Shared UI components: sidebar navigation, header, KPI cards."""

import reflex as rx

from .state import DashboardState

# ── Color tokens (light mode only) ──
BG = "#f4f5f7"
SURFACE = "#ffffff"
SURFACE2 = "#f9fafb"
BORDER = "#e2e5ea"
TEXT = "#1a1d23"
TEXT_MUTED = "#6b7280"
TEXT_DIM = "#9ca3af"
GREEN = "#16a34a"
RED = "#dc2626"
AMBER = "#d97706"
ACCENT = "#2563eb"
ACCENT_BG = "#eff6ff"

MONO = "'SF Mono', 'Cascadia Code', 'JetBrains Mono', monospace"


def sidebar() -> rx.Component:
    """Left sidebar with navigation tabs."""
    return rx.box(
        rx.vstack(
            # Logo
            rx.hstack(
                rx.text(
                    "TradingAgents",
                    font_weight="700",
                    font_size="15px",
                    color=TEXT,
                    letter_spacing="-0.3px",
                ),
                padding="20px 16px 16px",
            ),
            # Mode badge
            rx.box(
                rx.cond(
                    DashboardState.execution_mode == "paper",
                    rx.badge("PAPER", color_scheme="green", size="1"),
                    rx.badge("LIVE", color_scheme="red", size="1"),
                ),
                padding_x="16px",
                padding_bottom="16px",
            ),
            # Nav items
            _nav_item("Overview", "/", "bar-chart-2"),
            _nav_item("Activity", "/activity", "activity"),
            _nav_item("History", "/history", "clock"),
            _nav_item("Analytics", "/analytics", "trending-up"),
            _nav_item("Intelligence", "/intelligence", "search"),
            _nav_item("Wiki", "/wiki", "book-open"),
            _nav_item("Backtest", "/backtest", "rewind"),
            _nav_item("System", "/system", "settings"),
            rx.spacer(),
            # Market status
            rx.box(
                rx.hstack(
                    rx.cond(
                        DashboardState.market_open,
                        rx.box(width="6px", height="6px", border_radius="50%",
                               bg=GREEN),
                        rx.box(width="6px", height="6px", border_radius="50%",
                               bg=TEXT_DIM),
                    ),
                    rx.text(
                        DashboardState.market_status_text,
                        font_size="10px",
                        color=TEXT_MUTED,
                        font_weight="600",
                        letter_spacing="0.5px",
                    ),
                    spacing="2",
                    align="center",
                ),
                padding="12px 16px",
            ),
            # Kill switch
            rx.box(
                rx.vstack(
                    rx.cond(
                        DashboardState.kill_switch_active,
                        rx.text("HALTED", color=RED, font_weight="700",
                                font_size="11px", letter_spacing="1px"),
                        rx.text("TRADING ACTIVE", color=GREEN, font_weight="600",
                                font_size="10px", letter_spacing="0.5px"),
                    ),
                    rx.hstack(
                        rx.button(
                            "KILL ALL",
                            on_click=DashboardState.activate_kill_switch,
                            color_scheme="red",
                            size="1",
                            variant="solid",
                        ),
                        rx.button(
                            "RESET",
                            on_click=DashboardState.reset_kill_switch,
                            color_scheme="gray",
                            size="1",
                            variant="outline",
                        ),
                        spacing="2",
                    ),
                    spacing="2",
                ),
                padding="12px 16px",
                border_top=f"1px solid {BORDER}",
            ),
            # Last refresh
            rx.text(
                DashboardState.last_refresh,
                font_size="9px",
                color=TEXT_DIM,
                padding="8px 16px",
            ),
            spacing="1",
            height="100%",
        ),
        width="200px",
        min_width="200px",
        height="100vh",
        bg=SURFACE,
        border_right=f"1px solid {BORDER}",
        position="fixed",
        left="0",
        top="0",
        overflow_y="auto",
    )


def _nav_item(label: str, href: str, icon: str) -> rx.Component:
    """Single sidebar navigation item."""
    return rx.link(
        rx.hstack(
            rx.text(label, font_size="13px", color=TEXT, font_weight="500"),
            spacing="3",
            align="center",
            padding="8px 16px",
            border_radius="6px",
            _hover={"background": ACCENT_BG},
            width="100%",
        ),
        href=href,
        text_decoration="none",
        width="100%",
    )


def page_layout(*children) -> rx.Component:
    """Standard page layout: sidebar + main content area."""
    return rx.hstack(
        sidebar(),
        rx.box(
            *children,
            margin_left="200px",
            padding="24px",
            width="100%",
            min_height="100vh",
            bg=BG,
        ),
        spacing="0",
        width="100%",
    )


def kpi_card(label: str, value, sub=None, color: str = TEXT) -> rx.Component:
    """Single KPI metric card."""
    children = [
        rx.text(label, font_size="9px", color=TEXT_DIM, font_weight="600",
                letter_spacing="1px"),
        rx.text(value, font_size="22px", font_weight="700", font_family=MONO,
                color=color, line_height="1.2"),
    ]
    if sub is not None:
        children.append(
            rx.text(sub, font_size="11px", font_family=MONO, color=TEXT_MUTED)
        )
    return rx.box(
        rx.vstack(*children, spacing="1"),
        bg=SURFACE,
        border=f"1px solid {BORDER}",
        border_radius="6px",
        padding="12px 14px",
    )


def section_label(text: str) -> rx.Component:
    """Section header label."""
    return rx.text(
        text,
        font_size="9px",
        color=TEXT_DIM,
        font_weight="600",
        letter_spacing="1.5px",
        margin_bottom="10px",
    )


def panel(*children) -> rx.Component:
    """Card-style panel container."""
    return rx.box(
        *children,
        bg=SURFACE,
        border=f"1px solid {BORDER}",
        border_radius="6px",
        padding="16px",
        margin_bottom="12px",
    )
