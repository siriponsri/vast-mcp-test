import os
from pathlib import Path
import sys
import unittest

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from vast_mcp import BLOCKED


class StdioTest(unittest.TestCase):
    def test_original_entrypoint_serves_the_same_mock_tools(self):
        async def scenario():
            env = {k: v for k, v in os.environ.items() if "VAST_" not in k}
            root = Path(__file__).resolve().parents[1]
            params = StdioServerParameters(command=sys.executable, args=["-m", "ptp_vast_mcp.mcp_server"],
                                           env=env, cwd=str(root))
            async with stdio_client(params) as (reader, writer):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    tools = (await session.list_tools()).tools
                    self.assertEqual({t.name for t in tools},
                                     {"health", "search_gpu_offers", "estimate_run_cost"})
                    self.assertTrue(all(tool.annotations.readOnlyHint for tool in tools))
                    result = await session.call_tool("health", {})
                    self.assertEqual(result.structuredContent["live_search"], BLOCKED)
                    denied = await session.call_tool("vast_rent_gpu", {"offer_id": 123})
                    self.assertTrue(denied.isError)
        anyio.run(scenario)
