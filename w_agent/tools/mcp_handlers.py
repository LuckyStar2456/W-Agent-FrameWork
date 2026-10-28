"""Explicit application-owned callbacks for MCP client-side requests."""

from __future__ import annotations

import copy
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

McpRequestHandler = Callable[[Mapping[str, Any]], Awaitable[Mapping[str, Any]]]
McpNotificationHandler = Callable[[Mapping[str, Any]], Awaitable[None]]

_CAPABILITIES = {
    "sampling/createMessage": "sampling",
    "elicitation/create": "elicitation",
    "roots/list": "roots",
}


class McpClientHandlers:
    """Callbacks are authority; server metadata or configuration cannot install them.

    Handlers must obtain any application approval before sampling, eliciting, or
    disclosing roots. No model, UI, filesystem, or tool is invoked by this class.
    """

    def __init__(
        self,
        *,
        sampling: McpRequestHandler | None = None,
        elicitation: McpRequestHandler | None = None,
        roots: McpRequestHandler | None = None,
    ) -> None:
        self._handlers = {
            method: handler
            for method, handler in zip(_CAPABILITIES, (sampling, elicitation, roots))
            if handler is not None
        }
        if any(not callable(handler) for handler in self._handlers.values()):
            raise TypeError("MCP handlers must be callable")

    def capabilities(self, declared: Mapping[str, Any] | None = None) -> dict[str, Any]:
        result = copy.deepcopy(dict(declared or {}))
        for method, capability in _CAPABILITIES.items():
            if capability in result and method not in self._handlers:
                raise ValueError(f"MCP cannot advertise {capability} without an explicit handler")
            if method in self._handlers:
                result.setdefault(capability, {"form": {}} if capability == "elicitation" else {})
            if capability in result and not isinstance(result[capability], Mapping):
                raise ValueError(f"MCP {capability} capability must be an object")
        return result

    def supports(self, method: str) -> bool:
        return method in self._handlers

    async def invoke(
        self, method: str, params: Mapping[str, Any], *,
        capabilities: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        from .mcp_client import McpProtocolError

        handler = self._handlers.get(method)
        if handler is None:
            raise McpProtocolError(f"No application handler registered for {method}")
        declared = self.capabilities() if capabilities is None else capabilities
        if method == "elicitation/create":
            mode = params.get("mode", "form")
            capability = declared.get("elicitation", {})
            if mode not in ("form", "url") or (mode not in capability and not (mode == "form" and not capability)):
                raise McpProtocolError("Server requested an undeclared elicitation mode")
        if method == "sampling/createMessage" and ("tools" in params or "toolChoice" in params):
            if "tools" not in declared.get("sampling", {}):
                raise McpProtocolError("Server requested undeclared sampling tools")
        result = await handler(copy.deepcopy(dict(params)))
        if not isinstance(result, Mapping):
            raise McpProtocolError("MCP client handler must return an object")
        return copy.deepcopy(dict(result))

    async def respond(
        self, message: Mapping[str, Any], *, capabilities: Mapping[str, Any] | None = None,
    ) -> Mapping[str, Any]:
        """Produce a legacy JSON-RPC reply without leaking callback exceptions."""
        method = message.get("method")
        params = message.get("params", {})
        response: dict[str, Any] = {"jsonrpc": "2.0", "id": message.get("id")}
        if method == "ping":
            response["result"] = {}
        elif not isinstance(method, str) or not self.supports(method):
            response["error"] = {"code": -32601, "message": "Client method not supported"}
        elif not isinstance(params, Mapping):
            response["error"] = {"code": -32602, "message": "Request params must be an object"}
        else:
            try:
                response["result"] = dict(await self.invoke(method, params, capabilities=capabilities))
            except Exception:
                response["error"] = {"code": -32603, "message": "Client handler failed"}
        return response
