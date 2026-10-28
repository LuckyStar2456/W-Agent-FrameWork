"""MCP 2026 subscription validation and explicit stream lifetime."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping

from .mcp_client import MCP_PROTOCOL_VERSION, McpProtocolError, McpTransportError, _parse_rpc_response

_META_ID = "io.modelcontextprotocol/subscriptionId"
_ACK = "notifications/subscriptions/acknowledged"
_FILTERS = {
    "notifications/tools/list_changed": "toolsListChanged",
    "notifications/prompts/list_changed": "promptsListChanged",
    "notifications/resources/list_changed": "resourcesListChanged",
    "notifications/resources/updated": "resourceSubscriptions",
}


def _validate_filter(value):
    if not isinstance(value, Mapping) or set(value) - set(_FILTERS.values()):
        raise McpProtocolError("Invalid MCP subscription filter")
    for key, item in value.items():
        if key == "resourceSubscriptions":
            if not isinstance(item, list) or len(item) > 1000 or any(not isinstance(uri, str) or not uri for uri in item):
                raise McpProtocolError("Invalid MCP resource subscription filter")
        elif not isinstance(item, bool):
            raise McpProtocolError("MCP notification filters must be booleans")
    return dict(value)


async def listen(client, notifications, *, cancellation=None):
    """Yield ack then change notifications; callers close the iterator on early exit.

    No replay or reconnect is implicit. Abrupt disconnect is an error, and a
    fresh subscription requires refetching application state.
    """
    if client.protocol_version != MCP_PROTOCOL_VERSION:
        raise McpProtocolError("Subscriptions require MCP 2026-07-28")
    filters = _validate_filter(notifications)
    stream_method = getattr(client.transport, "stream", None)
    if stream_method is None:
        raise McpTransportError("This transport does not support subscription streams")
    request_id = client._next_id
    client._next_id += 1
    message = {"jsonrpc": "2.0", "id": request_id, "method": "subscriptions/listen", "params": {
        "notifications": filters,
        "_meta": {"io.modelcontextprotocol/protocolVersion": client.protocol_version,
                  "io.modelcontextprotocol/clientInfo": {"name": client.client_info.name, "version": client.client_info.version},
                  "io.modelcontextprotocol/clientCapabilities": dict(client.client_capabilities)},
    }}
    stream = stream_method(message, cancellation=cancellation)
    acknowledged = None
    try:
        while True:
            try:
                if acknowledged is None:
                    event = await asyncio.wait_for(anext(stream), getattr(client.transport, "request_timeout", 30))
                else:
                    event = await anext(stream)
            except StopAsyncIteration:
                break
            except TimeoutError as exc:
                raise McpTransportError("MCP subscription acknowledgment timed out") from exc
            if event.get("jsonrpc") != "2.0":
                raise McpProtocolError("Invalid subscription JSON-RPC envelope")
            if "id" in event and "method" not in event:
                result = _parse_rpc_response(event, request_id)
                if acknowledged is None:
                    raise McpProtocolError("Subscription closed before acknowledgment")
                metadata = result.get("_meta", {})
                if result.get("resultType") != "complete" or not isinstance(metadata, Mapping) or metadata.get(_META_ID) != request_id:
                    raise McpProtocolError("Invalid subscription completion")
                return
            params = event.get("params", {})
            if not isinstance(params, Mapping) or not isinstance(params.get("_meta"), Mapping) or params["_meta"].get(_META_ID) != request_id:
                raise McpProtocolError("Subscription notification has wrong correlation ID")
            method = event.get("method")
            if acknowledged is None:
                if method != _ACK:
                    raise McpProtocolError("Subscription notification preceded acknowledgment")
                acknowledged = _validate_filter(params.get("notifications"))
                for key, value in acknowledged.items():
                    if key == "resourceSubscriptions":
                        if not set(value).issubset(filters.get(key, [])):
                            raise McpProtocolError("Server acknowledged unrequested resources")
                    elif value and not filters.get(key):
                        raise McpProtocolError("Server acknowledged unrequested notification type")
            else:
                key = _FILTERS.get(method)
                if key is None or not acknowledged.get(key):
                    raise McpProtocolError("Server sent an unrequested subscription event")
                if key == "resourceSubscriptions" and params.get("uri") not in acknowledged[key]:
                    raise McpProtocolError("Server sent an unrequested resource update")
                await client._handle_notification(event)
            yield event
        raise McpTransportError("MCP subscription disconnected without graceful completion")
    finally:
        await stream.aclose()
