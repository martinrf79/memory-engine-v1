from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Request

from app.bridges import _require_bridge_token
from app.llm_service import get_user_llm_settings
from app.provider_adapters import function_tool_manifest, get_adapter
from app.schemas import BridgeProviderInfo, BridgeToolCallRequest, BridgeToolCallResponse

router = APIRouter(tags=["public"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


@router.get("/tool-calling/providers", response_model=list[BridgeProviderInfo])
def list_tool_calling_providers():
    providers = []
    for name in ["generic", "chatgpt", "claude", "gemini", "deepseek", "mock"]:
        adapter = get_adapter(name)
        if not adapter.supports_function_calling:
            continue
        providers.append(
            BridgeProviderInfo(
                provider=adapter.provider,
                display_name=adapter.display_name,
                bridge_mode=adapter.bridge_mode,
                supports_remote_chat=adapter.supports_remote_chat,
                supports_mcp=adapter.supports_mcp,
                supports_function_calling=adapter.supports_function_calling,
                requires_user_api_key=adapter.requires_user_api_key,
                default_model=adapter.default_model,
                connection_summary=adapter.connection_summary,
            )
        )
    return providers


@router.get("/tool-calling/manifest")
def generic_tool_calling_manifest(request: Request):
    return {
        "server_name": "memory-core",
        "server_version": "1.1.0",
        "mode": "tool-calling",
        "providers": ["generic", "chatgpt", "claude", "gemini", "deepseek"],
        "provider_endpoints": {
            name: f"{_base_url(request)}/tool-calling/{name}/manifest" for name in ["generic", "chatgpt", "claude", "gemini", "deepseek"]
        },
    }


def _resolve_tool_provider(provider: str) -> str:
    value = (provider or "").strip().lower()
    if value in {"", "generic", "default", "universal", "openai"}:
        return "gemini"
    return value


@router.get("/tool-calling/{provider}/manifest")
def provider_tool_calling_manifest(provider: str, request: Request):
    resolved = _resolve_tool_provider(provider)
    adapter = get_adapter(resolved)
    if adapter.provider == "mock" and resolved != "mock":
        raise HTTPException(status_code=404, detail="Proveedor no soportado")
    payload = function_tool_manifest(resolved, _base_url(request))
    payload["requested_provider"] = provider
    payload["provider"] = provider if provider.lower() == "generic" else payload["provider"]
    payload["call_endpoint"] = f"{_base_url(request)}/tool-calling/{provider}/call"
    payload["tool_call_manifest_endpoint"] = f"{_base_url(request)}/tool-calling/{provider}/manifest"
    payload["tool_call_endpoint"] = f"{_base_url(request)}/tool-calling/{provider}/call"
    return payload


@router.post("/tool-calling/{provider}/call", response_model=BridgeToolCallResponse)
def provider_tool_calling_call(provider: str, payload: BridgeToolCallRequest, x_bridge_token: str | None = Header(default=None), token: str | None = None):
    resolved = _resolve_tool_provider(provider)
    adapter = get_adapter(resolved)
    if adapter.provider == "mock" and resolved != "mock":
        raise HTTPException(status_code=404, detail="Proveedor no soportado")
    if provider.lower() != "generic":
        _require_bridge_token(resolved, payload.user_id, x_bridge_token or token)
        settings = get_user_llm_settings(payload.user_id)
    else:
        settings = get_user_llm_settings(payload.user_id)
    if not adapter.supports_function_calling:
        raise HTTPException(status_code=400, detail="provider_not_function_calling_ready")
    response = adapter.handle_tool_call(payload, settings)
    if provider.lower() == "generic":
        response.provider = "generic"
    return response
