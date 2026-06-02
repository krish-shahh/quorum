"""Allow `python -m quorum.mcp` to start the MCP server."""
import asyncio
from quorum.mcp.server import main

asyncio.run(main())
