from __future__ import annotations

from typing import Any

from mcp.server.fastmcp import FastMCP

from runtime import claude_mcp_server, server_v2, vps_ops_server


mcp = FastMCP(
    "EIROS Claude Operator",
    instructions=(
        "Full operator connector for Rico's EIROS/EBRIDGE environment. "
        "This connector combines the Claude dialogue bridge, the complete EIROS control-plane toolset, "
        "and VPS Ops including root/git/systemd capabilities. Inspect before mutating, use tests before "
        "restarts, never expose secrets, and never force-push unless Rico explicitly requests it."
    ),
    stateless_http=True,
    json_response=True,
    host="127.0.0.1",
    port=8794,
    warn_on_duplicate_tools=False,
)


def _mirror_tools(source: FastMCP[Any]) -> None:
    for tool in source._tool_manager.list_tools():
        mcp.add_tool(
            tool.fn,
            name=tool.name,
            title=tool.title,
            description=tool.description,
            annotations=tool.annotations,
            icons=tool.icons,
            # Do not inherit ChatGPT App-only visibility metadata. The operator
            # connector is a model-facing MCP surface, not an MCP App iframe.
            meta=None,
        )


# Order matters for duplicate names: Claude-specific dialogue defaults win,
# then EIROS core, then VPS Ops contributes its unique privileged tools.
for source_mcp in (claude_mcp_server.mcp, server_v2.mcp, vps_ops_server.mcp):
    _mirror_tools(source_mcp)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
