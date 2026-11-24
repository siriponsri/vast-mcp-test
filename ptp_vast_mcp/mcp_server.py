"""The PTP local stdio server, with synthetic offers while live scope is blocked."""
import logging
import os

from vast_mcp import BLOCKED, CONSOLE, VERSION
from vast_mcp.profile import TOOL_NAMES


def main() -> None:
    # The open project can supply a .env or telemetry settings. Ignore both.
    for name in list(os.environ):
        if name.upper().startswith(("FASTMCP_", "OTEL_", "VAST_")):
            del os.environ[name]
    os.environ["FASTMCP_ENV_FILE"] = os.devnull
    os.environ["FASTMCP_CHECK_FOR_UPDATES"] = "off"
    logging.disable(logging.CRITICAL)

    from fastmcp import FastMCP
    from fastmcp.exceptions import ToolError, ValidationError
    from fastmcp.server.middleware import Middleware
    from mcp.types import ToolAnnotations

    from vast_mcp.offers import estimate_run_cost, search_gpu_offers

    class RedactToolInput(Middleware):
        async def on_call_tool(self, context, call_next):
            if context.message.name not in TOOL_NAMES:
                raise ToolError("Unknown Vast MCP tool.")
            try:
                return await call_next(context)
            except ValidationError:
                raise ToolError("Invalid arguments. Check the published tool schema.") from None

    server = FastMCP("Vast GPU Offers", version=VERSION, mask_error_details=True)
    server.add_middleware(RedactToolInput())
    annotations = ToolAnnotations(readOnlyHint=True, openWorldHint=False,
                                  destructiveHint=False, idempotentHint=True)

    @server.tool(annotations=annotations)
    def health() -> dict:
        """Report mock readiness and the provider grant gate."""
        return {
            "version": VERSION,
            "transport": "stdio",
            "mode": "mock",
            "search_readiness": "LOCAL_MOCK",
            "live_search": BLOCKED,
            "console": CONSOLE,
        }

    server.tool(search_gpu_offers, annotations=annotations)
    server.tool(estimate_run_cost, annotations=annotations)
    server.run(transport="stdio", show_banner=False)


if __name__ == "__main__":
    main()
