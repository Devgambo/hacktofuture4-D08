"""
MCP client setup for GitHub tools and custom tool wrappers.
Supports per-user OAuth tokens for GitHub MCP server.
"""

import logging
from langchain_mcp_adapters.client import MultiServerMCPClient
from config import get_settings

logger = logging.getLogger("devops_agent.tools")

# Per-token MCP client cache — maps github_token → client
_mcp_clients: dict[str, MultiServerMCPClient] = {}


async def get_mcp_client(github_token: str | None = None) -> MultiServerMCPClient:
    """
    Return a cached MCP client for the given GitHub token.
    Falls back to settings.github_token if no token is provided.
    """
    settings = get_settings()
    token = github_token or settings.github_token

    if not token:
        raise RuntimeError("No GitHub token available — user must log in via OAuth")

    if token not in _mcp_clients:
        _mcp_clients[token] = MultiServerMCPClient(
            {
                "github": {
                    "command": "npx",
                    "args": ["-y", "@modelcontextprotocol/server-github"],
                    "env": {"GITHUB_PERSONAL_ACCESS_TOKEN": token},
                    "transport": "stdio",
                }
            }
        )

    return _mcp_clients[token]


async def get_github_tools(github_token: str | None = None):
    """Fetch LangChain-compatible tools from the GitHub MCP server."""
    client = await get_mcp_client(github_token)
    tools = await client.get_tools()
    logger.info("Loaded %d GitHub MCP tools", len(tools))
    return tools


def invalidate_mcp_client(token: str) -> None:
    """R1: Remove a cached MCP client (e.g. when a 401 indicates the token is stale).
    The next call to get_mcp_client will create a fresh client."""
    if token in _mcp_clients:
        logger.info("Invalidating stale MCP client for token ending ...%s", token[-6:])
        # We don't await aclose here because we may be called from sync context;
        # the old client's subprocess will be cleaned up at shutdown.
        del _mcp_clients[token]


async def shutdown_mcp():
    """Cleanly close all MCP clients (call on app shutdown).
    B12: actually close each client before clearing the cache so the
    npx subprocesses are terminated properly.
    """
    global _mcp_clients
    for token, client in list(_mcp_clients.items()):
        try:
            # MultiServerMCPClient implements async context manager;
            # call __aexit__ to tear down the subprocess connections.
            if hasattr(client, "aclose"):
                await client.aclose()
            elif hasattr(client, "__aexit__"):
                await client.__aexit__(None, None, None)
        except Exception as exc:
            logger.warning("Error closing MCP client: %s", exc)
    _mcp_clients = {}
