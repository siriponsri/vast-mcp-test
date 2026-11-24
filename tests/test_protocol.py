import asyncio
import os
import sys
from datetime import datetime
from uuid import uuid4

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from vast_mcp import BLOCKED
from vast_mcp.profile import TOOL_NAMES


def test_real_stdio_mock_and_redaction(tmp_path):
    canary = f"FAKE_VAST_SECRET_{uuid4().hex}"
    dot_env = tmp_path / ".env"
    dot_env.write_text(f"FASTMCP_LOG_LEVEL={canary}", encoding="utf-8")
    params = StdioServerParameters(
        command=sys.executable, args=["-I", "-m", "vast_mcp", "serve", "--profile", "mock"],
        cwd=str(tmp_path),
        env={**os.environ, "VAST_API_KEY": canary, "FASTMCP_LOG_LEVEL": "DEBUG"},
    )

    async def verify(errlog):
        async with asyncio.timeout(45), stdio_client(params, errlog=errlog) as (rx, tx):
            async with ClientSession(rx, tx) as session:
                initialized = await session.initialize()
                assert initialized.serverInfo.name == "Vast GPU Offers"
                tools = (await session.list_tools()).tools
                assert {tool.name for tool in tools} == TOOL_NAMES
                assert all(tool.annotations.readOnlyHint for tool in tools)

                health = await session.call_tool("health")
                assert health.structuredContent["live_search"] == BLOCKED
                result = await session.call_tool("search_gpu_offers", {"disk_gb": 100})
                data = result.structuredContent
                assert data["source"] == "synthetic"
                assert datetime.fromisoformat(data["snapshot_utc"]).utcoffset().total_seconds() == 0
                assert [offer["offer_id"] for offer in data["offers"]] == [
                    "mock-101", "mock-102", "mock-103"
                ]
                row = data["offers"][0]
                estimate = await session.call_tool("estimate_run_cost", {
                    "offer_id": row["offer_id"], "disk_gb": row["disk_gb"], "hours": "2.5",
                    "upload_to_host_gb": "1.5", "download_from_host_gb": "2",
                })
                assert estimate.structuredContent["estimated_total_usd"] == "0.735000"
                assert estimate.structuredContent["hourly_including_disk_usd"] == row[
                    "hourly_including_disk_usd"
                ]
                for name, args in (
                    ("search_gpu_offers", {"disk_gb": canary}),
                    ("search_gpu_offers", {"disk_gb": -1}),
                    ("search_gpu_offers", {"min_reliability": "NaN"}),
                    ("estimate_run_cost", {"offer_id": canary, "disk_gb": 40,
                                           "hours": 1, "upload_to_host_gb": 0,
                                           "download_from_host_gb": 0}),
                    (canary, {}),
                ):
                    error = await session.call_tool(name, args)
                    assert error.isError
                    assert canary not in error.model_dump_json()

    log = tmp_path / "stderr"
    with log.open("w", encoding="utf-8") as stream:
        asyncio.run(verify(stream))
    assert canary not in log.read_text(encoding="utf-8")
