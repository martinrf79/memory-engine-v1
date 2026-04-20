from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse

from app.auth import get_optional_session
from app.firestore_store import llm_connections_collection
from app.memory_core_v1 import resolve_mcp_auth
from app.schemas import MCPManifestResponse, MCPToolArgumentSchema, MCPToolCallRequest, MCPToolCallResponse, MCPToolSchema
from app.tool_registry import MEMORY_TOOL_NAMES, ToolExecutionError, execute_tool, list_tool_definitions

router = APIRouter(tags=["public"])

MCP_PROTOCOL_VERSION = "2025-03-26"


def _tool_specs() -> list[MCPToolSchema]:
    specs: list[MCPToolSchema] = []
    for item in list_tool_definitions(MEMORY_TOOL_NAMES):
        properties = item.input_schema.get("properties", {})
        required = set(item.input_schema.get("required", []))
        args = []
        for name, schema in properties.items():
            args.append(
                MCPToolArgumentSchema(
                    name=name,
                    type=str(schema.get("type") or "string"),
                    required=name in required,
                    description=str(schema.get("description") or name),
                )
            )
        specs.append(MCPToolSchema(name=item.name, description=item.description, arguments=args))
    return specs


def _find_connection_by_token(token: str | None, *, provider: str | None = None) -> dict[str, Any] | None:
    if not token:
        return None
    for doc in llm_connections_collection.stream():
        data = doc.to_dict() or {}
        if data.get("bridge_token") != token:
            continue
        if data.get("status") not in {"connected", "paused"}:
            continue
        if provider and (data.get("provider") or "").lower() != provider.lower():
            continue
        return data
    return None


def _resolve_user(request: Request, x_mcp_token: str | None, x_mcp_user: str | None, token: str | None = None, provider: str | None = None) -> str:
    principal = get_optional_session(request)
    if principal:
        return principal.user_id
    if resolve_mcp_auth(x_mcp_user, x_mcp_token):
        return str(x_mcp_user)
    matched = _find_connection_by_token(token or x_mcp_token, provider=provider)
    if matched:
        return str(matched.get("user_id"))
    raise HTTPException(status_code=401, detail="mcp_auth_required")


def _json_rpc_response(message_id: Any, *, result: Any | None = None, error: dict[str, Any] | None = None, status_code: int = 200) -> JSONResponse:
    payload: dict[str, Any] = {"jsonrpc": "2.0", "id": message_id}
    if error is not None:
        payload["error"] = error
    else:
        payload["result"] = result if result is not None else {}
    return JSONResponse(payload, status_code=status_code)


def _mcp_tool_list() -> list[dict[str, Any]]:
    tools = []
    for item in list_tool_definitions(MEMORY_TOOL_NAMES):
        payload = {
            "name": item.name,
            "title": item.title,
            "description": item.description,
            "inputSchema": item.input_schema,
        }
        if item.annotations:
            payload["annotations"] = item.annotations
        tools.append(payload)
    return tools


def _endpoint_query(token: str | None, provider: str | None) -> str:
    query: dict[str, str] = {}
    if token:
        query["token"] = token
    if provider:
        query["provider"] = provider
    return urlencode(query)


def _rpc_endpoint_url(request: Request, token: str | None, provider: str | None) -> str:
    base = str(request.base_url).rstrip("/")
    query = _endpoint_query(token, provider)
    suffix = f"?{query}" if query else ""
    return f"{base}/mcp/rpc{suffix}"


def _sse_messages_url(request: Request, token: str | None, provider: str | None) -> str:
    base = str(request.base_url).rstrip("/")
    query = _endpoint_query(token, provider)
    suffix = f"?{query}" if query else ""
    return f"{base}/sse/messages{suffix}"


def _event_stream_response(endpoint_url: str) -> StreamingResponse:
    async def event_stream():
        yield f"event: endpoint\ndata: {endpoint_url}\n\n"
        yield ": keepalive\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})


def _execute_rpc(method: str, params: dict[str, Any] | None, *, user_id: str | None, source: str) -> dict[str, Any]:
    params = params or {}
    if method == "initialize":
        return {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "memory-core", "version": "1.3.0"},
            "instructions": "Use tools to search and persist project memory without mixing projects.",
        }
    if method == "ping":
        return {}
    if method == "tools/list":
        return {"tools": _mcp_tool_list()}
    if method == "tools/call":
        if not user_id:
            raise ToolExecutionError("mcp_auth_required", status_code=401)
        tool_name = str(params.get("name") or "").strip()
        arguments = params.get("arguments") or {}
        result = execute_tool(tool_name, arguments, principal_user_id=user_id, source=source)
        content = [
            {
                "type": "text",
                "text": json.dumps(result, ensure_ascii=False),
            }
        ]
        return {"content": content, "structuredContent": result, "isError": False}
    if method == "notifications/initialized":
        return {}
    raise ToolExecutionError("method_not_found", status_code=404)


@router.get("/mcp/manifest", response_model=MCPManifestResponse)
def mcp_manifest():
    return MCPManifestResponse(
        server_name="memory-core",
        server_version="1.3.0",
        protocol="mcp-bridge",
        auth="session_or_bridge_token",
        tools=_tool_specs(),
    )


@router.get("/mcp/tools", response_model=list[MCPToolSchema])
def mcp_tools():
    return _tool_specs()


@router.post("/mcp/call", response_model=MCPToolCallResponse)
def mcp_call(
    payload: MCPToolCallRequest,
    request: Request,
    x_mcp_token: str | None = Header(default=None),
    x_mcp_user: str | None = Header(default=None),
    token: str | None = Query(default=None),
):
    user_id = _resolve_user(request, x_mcp_token, x_mcp_user, token=token)
    try:
        result = execute_tool(payload.tool_name, payload.arguments, principal_user_id=user_id, source="mcp")
    except ToolExecutionError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return MCPToolCallResponse(ok=True, tool_name=payload.tool_name, result=result)


@router.get("/mcp/rpc")
def mcp_rpc_get(
    request: Request,
    token: str | None = Query(default=None),
    provider: str | None = Query(default=None),
):
    accept = (request.headers.get("accept") or "").lower()
    if "text/event-stream" in accept:
        return _event_stream_response(_rpc_endpoint_url(request, token, provider))
    user_id = None
    try:
        user_id = _resolve_user(request, None, None, token=token, provider=provider)
    except HTTPException:
        pass
    return {
        "name": "memory-core",
        "transport": "streamable-http",
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "authenticated_user": user_id,
        "tools": _mcp_tool_list(),
    }


@router.post("/mcp/rpc")
def mcp_rpc_post(
    request: Request,
    body: dict[str, Any],
    x_mcp_token: str | None = Header(default=None),
    x_mcp_user: str | None = Header(default=None),
    token: str | None = Query(default=None),
    provider: str | None = Query(default=None),
):
    message_id = body.get("id")
    method = str(body.get("method") or "").strip()
    params = body.get("params") or {}
    try:
        auth_optional_methods = {"initialize", "ping", "tools/list", "notifications/initialized"}
        user_id = _resolve_user(request, x_mcp_token, x_mcp_user, token=token, provider=provider) if method not in auth_optional_methods else None
        result = _execute_rpc(method, params, user_id=user_id, source="mcp_rpc")
        return _json_rpc_response(message_id, result=result)
    except ToolExecutionError as exc:
        code = -32601 if exc.code == "method_not_found" else -32000
        return _json_rpc_response(message_id, error={"code": code, "message": exc.code}, status_code=exc.status_code)
    except HTTPException as exc:
        return _json_rpc_response(message_id, error={"code": -32001, "message": str(exc.detail)}, status_code=exc.status_code)


@router.get("/sse/")
def mcp_sse_endpoint(request: Request, token: str, provider: str | None = Query(default=None)):
    connection = _find_connection_by_token(token, provider=provider)
    if not connection:
        raise HTTPException(status_code=401, detail="mcp_auth_required")
    return _event_stream_response(_sse_messages_url(request, token, provider))


@router.get("/mcp/sse")
def mcp_sse_endpoint_alias(request: Request, token: str, provider: str | None = Query(default=None)):
    return mcp_sse_endpoint(request, token, provider)


@router.post("/sse/messages")
def mcp_sse_messages(
    request: Request,
    body: dict[str, Any],
    token: str = Query(...),
    provider: str | None = Query(default=None),
):
    message_id = body.get("id")
    method = str(body.get("method") or "").strip()
    params = body.get("params") or {}
    try:
        auth_optional_methods = {"initialize", "ping", "tools/list", "notifications/initialized"}
        user_id = _resolve_user(request, None, None, token=token, provider=provider) if method not in auth_optional_methods else None
        result = _execute_rpc(method, params, user_id=user_id, source="mcp_sse")
        return _json_rpc_response(message_id, result=result)
    except ToolExecutionError as exc:
        code = -32601 if exc.code == "method_not_found" else -32000
        return _json_rpc_response(message_id, error={"code": code, "message": exc.code}, status_code=exc.status_code)


@router.post("/mcp/messages")
def mcp_messages_alias(
    request: Request,
    body: dict[str, Any],
    token: str = Query(...),
    provider: str | None = Query(default=None),
):
    return mcp_sse_messages(request, body, token=token, provider=provider)
