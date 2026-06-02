"""Entry point: python -m quorum.api"""

from .app import create_app

app = create_app()
app.run(debug=True, port=5050)
