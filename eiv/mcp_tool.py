"""
EIV — MCP tool wrapper (optional)

Wraps validate_execution(intent, tx_ref) as an MCP tool.

mcp is an optional dependency:
  - validate_execution() can be imported and used directly whether or not mcp is
    installed (it is a plain function).
  - The MCP server tool is registered only when mcp is installed
    (python -m eiv.mcp_tool starts the server).

Run: python -m eiv.mcp_tool (requires mcp to be installed)
"""

from __future__ import annotations

import os
import sys

_PARENT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PARENT not in sys.path:
    sys.path.insert(0, _PARENT)

# Windows consoles may default to a non-UTF-8 codepage; force UTF-8 output.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    except Exception:
        pass

from eiv.api import service_from_env

_RUNS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runs")
# Same environment-driven composition as the HTTP service (RPC_URL,
# EIV_VALIDATION_REGISTRY_ADDRESS, ...): unset variables fall back to the
# reference implementations.
_service = service_from_env(_RUNS)


def validate_execution(intent: dict | str, tx_ref: str) -> dict:
    """Validate, after the fact, whether an agent's on-chain execution complies with
    its signature-authorized intent (IntentSpec).

    Args:
        intent: the signature-authorized intent (IntentSpec JSON; enveloped or flat).
        tx_ref: reference to the execution (currently a fixture name, e.g. "tx_clean").

    Returns:
        The full validation record, containing the result schema
        ({"verdict": "PASS"|"FAIL", "violations": [...]}) and attestation info.
    """
    return _service.run(intent, tx_ref)


# Optional MCP server registration
try:
    from mcp.server.fastmcp import FastMCP

    _HAS_MCP = True
except ImportError:  # mcp not installed; the plain function still works
    _HAS_MCP = False


if _HAS_MCP:
    mcp = FastMCP("eiv")

    @mcp.tool()
    def validate_execution_tool(intent: dict, tx_ref: str) -> dict:
        """Validate an AI agent's on-chain execution against its signed intent (EIV, L2 compliance)."""
        return validate_execution(intent, tx_ref)

    def main() -> None:
        mcp.run()

else:

    def main() -> None:
        print(
            "mcp is not installed; validate_execution() can still be imported and used directly.\n"
            "To start the MCP server: install mcp, then run python -m eiv.mcp_tool"
        )


if __name__ == "__main__":
    main()
