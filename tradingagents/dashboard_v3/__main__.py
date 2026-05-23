"""Entry point: python -m tradingagents.dashboard_v3"""

from .app import create_app

app = create_app()
app.run(debug=True, port=5050)
