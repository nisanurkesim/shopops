# MCP client for the shopops-orders server, used by the Support Agent
# The agent loop is synchronous, the MCP SDK is asynchronous. McpOrders runs an event loop
# in a background thread, keeps one server process and one MCP session open, and offers a
# plain call(name, args) -> dict to the agent.
import asyncio
import json
import os
import sys
import threading
import weakref
from pathlib import Path

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from config import DB_PATH, PROJECT_ROOT

CALL_TIMEOUT_S = 30   # one tool call; the tools only read or write a few SQLite rows
START_TIMEOUT_S = 30  # starting the server process and the MCP handshake


class McpOrders:
    """One shopops-orders server process for one customer."""

    def __init__(self, customer_unique_id: str, db_path: Path = DB_PATH):
        # The customer and the database are given on the command line, so the server knows
        # who is logged in before any tool is called. The server is started with this Python.
        self.params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "src.mcp_servers.shopops_orders",
                  "--customer", customer_unique_id, "--db", str(Path(db_path).resolve())],
            cwd=str(PROJECT_ROOT),
            env=dict(os.environ),   # our own code: same Python environment as the app
        )
        self.tool_names: set[str] = set()
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()
        self._session: ClientSession | None = None
        self._ready = threading.Event()
        self._stop: asyncio.Event | None = None
        self._error: BaseException | None = None
        self._main = asyncio.run_coroutine_threadsafe(self._serve(), self._loop)
        if not self._ready.wait(START_TIMEOUT_S) or self._error is not None:
            self.close()
            raise RuntimeError(f"shopops-orders MCP server did not start: {self._error}")
        # Stop the server process when the agent that owns this client is gone
        self._finalizer = weakref.finalize(self, McpOrders._shutdown, self._loop, self._stop, self._main,
                                           self._thread)

    async def _serve(self):
        """Hold the server process and the MCP session open until close()."""
        self._stop = asyncio.Event()
        try:
            async with stdio_client(self.params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    self.tool_names = {t.name for t in (await session.list_tools()).tools}
                    self._session = session
                    self._ready.set()
                    await self._stop.wait()
        except BaseException as e:   # report start-up errors to __init__
            self._error = e
            self._ready.set()
            raise

    def call(self, name: str, args: dict) -> dict:
        """Call one tool on the server. Always returns a dict, never raises."""
        if self._session is None:
            return {"error": "TOOL_FAILED", "message": "The order service is not running."}
        try:
            future = asyncio.run_coroutine_threadsafe(self._session.call_tool(name, args), self._loop)
            result = future.result(CALL_TIMEOUT_S)
        except Exception as e:
            return {"error": "TOOL_FAILED", "message": f"{type(e).__name__}: {e}"}
        text = "".join(getattr(c, "text", "") for c in result.content)
        if result.isError:
            return {"error": "TOOL_FAILED", "message": text}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return {"error": "TOOL_FAILED", "message": f"Unexpected answer: {text[:200]}"}

    def close(self):
        if hasattr(self, "_finalizer"):
            self._finalizer()
        else:
            McpOrders._shutdown(self._loop, self._stop, self._main, self._thread)
        self._session = None

    @staticmethod
    def _shutdown(loop, stop, main, thread):
        if stop is not None and loop.is_running():
            loop.call_soon_threadsafe(stop.set)
            try:
                main.result(10)   # leaves the MCP session and stops the server process
            except BaseException:
                pass
        if loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        thread.join(5)
        if not loop.is_running() and not loop.is_closed():
            loop.close()
