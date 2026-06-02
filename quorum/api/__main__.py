"""Entry point: python -m quorum.api"""

from .app import create_app

app = create_app()
# Bind to localhost only; debug=False (the Werkzeug debugger is an RCE vector).
app.run(host="127.0.0.1", port=5050, debug=False)
