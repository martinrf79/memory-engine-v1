from __future__ import annotations

from app.firestore_store import llm_connections_collection
from app.llm_settings import UserLLMSettings
from app.provider_adapters import ADAPTERS, get_adapter


PROVIDER_CATALOG: dict[str, dict] = {
    name: {
        "default_model": adapter.default_model,
        "bridge_mode": adapter.bridge_mode,
        "supports_remote_chat": adapter.supports_remote_chat,
        "supports_mcp": adapter.supports_mcp,
        "supports_function_calling": adapter.supports_function_calling,
        "requires_user_api_key": adapter.requires_user_api_key,
        "display_name": adapter.display_name,
        "connection_summary": adapter.connection_summary,
    }
    for name, adapter in ADAPTERS.items()
}


def get_provider_catalog() -> dict[str, dict]:
    return PROVIDER_CATALOG


def _base_settings(user_id: str, provider: str = "mock") -> UserLLMSettings:
    adapter = get_adapter(provider)
    return UserLLMSettings(
        user_id=user_id,
        provider=adapter.provider,
        model_name=adapter.default_model,
        bridge_mode=adapter.bridge_mode,
        connection_status="not_connected" if provider != "mock" else "ready",
        is_enabled=True,
        requires_user_api_key=adapter.requires_user_api_key,
        supports_remote_chat=adapter.supports_remote_chat,
        supports_mcp=adapter.supports_mcp,
        supports_function_calling=adapter.supports_function_calling,
    )


def get_user_llm_settings(user_id: str) -> UserLLMSettings:
    docs = llm_connections_collection.where("user_id", "==", user_id).stream()
    items = [doc.to_dict() or {} for doc in docs]
    active = [item for item in items if item.get("status") in {"connected", "paused"}]
    if not active:
        return _base_settings(user_id=user_id, provider="mock")

    latest = sorted(
        active,
        key=lambda item: (
            item.get("updated_at") or item.get("created_at") or "",
            item.get("id") or "",
        ),
        reverse=True,
    )[0]
    adapter = get_adapter(latest.get("provider") or "mock")
    return UserLLMSettings(
        user_id=user_id,
        provider=adapter.provider,
        model_name=latest.get("model_name") or adapter.default_model,
        bridge_mode=latest.get("bridge_mode") or adapter.bridge_mode,
        connection_status=latest.get("status") or "connected",
        is_enabled=latest.get("status") != "paused",
        requires_user_api_key=adapter.requires_user_api_key,
        supports_remote_chat=adapter.supports_remote_chat,
        supports_mcp=adapter.supports_mcp,
        supports_function_calling=adapter.supports_function_calling,
        system_prompt=latest.get("system_prompt"),
    )


def generate_answer_from_memories(
    settings: UserLLMSettings,
    user_message: str,
    memories: list[dict],
) -> str:
    summaries = [memory.get("summary") for memory in memories if memory.get("summary")]
    if not summaries:
        return "No tengo ese dato todavía."
    return summaries[0]
