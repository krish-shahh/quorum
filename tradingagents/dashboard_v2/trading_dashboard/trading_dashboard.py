"""TradingAgents Dashboard v2 — Reflex-based monitoring terminal.

Light mode only. 6-tab monitoring-first layout.
"""

import reflex as rx

from .state import DashboardState
from .pages.overview import overview_page
from .pages.activity import activity_page
from .pages.history import history_page
from .pages.analytics import analytics_page
from .pages.intelligence import intelligence_page
from .pages.system import system_page
from .pages.wiki import wiki_page
from .pages.backtest import backtest_page


app = rx.App(
    theme=rx.theme(
        appearance="light",
        accent_color="blue",
        radius="medium",
    ),
)

app.add_page(
    overview_page,
    route="/",
    title="TradingAgents - Overview",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    activity_page,
    route="/activity",
    title="TradingAgents - Activity",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    history_page,
    route="/history",
    title="TradingAgents - History",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    analytics_page,
    route="/analytics",
    title="TradingAgents - Analytics",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    intelligence_page,
    route="/intelligence",
    title="TradingAgents - Intelligence",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    system_page,
    route="/system",
    title="TradingAgents - System",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    wiki_page,
    route="/wiki",
    title="TradingAgents - Wiki",
    on_load=DashboardState.refresh_all,
)
app.add_page(
    backtest_page,
    route="/backtest",
    title="TradingAgents - Backtest",
    on_load=DashboardState.refresh_all,
)
