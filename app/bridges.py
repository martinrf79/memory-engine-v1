from __future__ import annotations

from fastapi import APIRouter, Header, HTTPException, Query, Request

from app.firestore_store import llm_connections_collection
from app.llm_service import get_user_llm_settings
from app.provider_adapters import get_adapter, provider_manifest
from app.schemas import BridgeBootstrapResponse, BridgeProviderInfo, BridgeToolCallRequest, BridgeToolCallResponse

router = APIRouter(tags=["public"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _require_bridge_token(provider: str, user_id: str, token: str | None) -> None:
    doc_id = f"{user_id}:{provider.lower()}"
    snapshot = llm_connections_collection.document(doc_id).get().to_dict() or {}
    expected = snapshot.get("bridge_token")
    if not expected or token != expected:
        raise HTTPException(status_code=401, detail="bridge_auth_required")


@router.get("/bridge/providers", response_model=list[BridgeProviderInfo])
def list_bridge_providers():
    providers = []
    for name in ["chatgpt", "claude", "gemini", "deepseek", "mock"]:
        adapter = get_adapter(name)
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


@router.get("/bridge/{provider}/bootstrap", response_model=BridgeBootstrapResponse)
def bridge_bootstrap(provider: str, request: Request, token: str | None = Query(default=None)):
    adapter = get_adapter(provider)
    if adapter.provider == "mock" and provider.lower() != "mock":
        raise HTTPException(status_code=404, detail="Proveedor no soportado")
    payload = adapter.bootstrap(_base_url(request)).model_dump()
    if token:
        payload["bridge_endpoint"] = f"{_base_url(request)}/bridge/{provider}/tool-call?token={token}"
        payload["manifest_endpoint"] = f"{_base_url(request)}/bridge/{provider}/manifest?token={token}"
    return BridgeBootstrapResponse(**payload)


@router.get("/bridge/{provider}/manifest")
def bridge_manifest(provider: str, request: Request, token: str | None = Query(default=None)):
    adapter = get_adapter(provider)
    if adapter.provider == "mock" and provider.lower() != "mock":
        raise HTTPException(status_code=404, detail="Proveedor no soportado")
    payload = provider_manifest(provider, _base_url(request))
    if token and isinstance(payload, dict):
        payload["call_endpoint"] = f"{_base_url(request)}/bridge/{provider}/tool-call?token={token}"
        payload["manifest_endpoint"] = f"{_base_url(request)}/bridge/{provider}/manifest?token={token}"
    return payload


@router.post("/bridge/{provider}/tool-call", response_model=BridgeToolCallResponse)
def bridge_tool_call(provider: str, payload: BridgeToolCallRequest, x_bridge_token: str | None = Header(default=None), token: str | None = Query(default=None)):
    adapter = get_adapter(provider)
    if adapter.provider == "mock" and provider.lower() != "mock":
        raise HTTPException(status_code=404, detail="Proveedor no soportado")
    _require_bridge_token(provider, payload.user_id, x_bridge_token or token)
    settings = get_user_llm_settings(payload.user_id)
    if settings.connection_status == "paused" and payload.tool_name == "memory_chat":
        return BridgeToolCallResponse(provider=adapter.provider, tool_name=payload.tool_name, ok=False, error="La memoria está pausada")
    return adapter.handle_tool_call(payload, settings)
