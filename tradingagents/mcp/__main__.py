"""Allow `python -m tradingagents.mcp` to start the MCP server."""
import asyncio
from tradingagents.mcp.server import main

asyncio.run(main())
