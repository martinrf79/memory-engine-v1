from __future__ import annotations

from typing import Any

from app.firestore_store import (
    documents_collection,
    event_log_collection,
    facts_collection,
    llm_connections_collection,
    manual_notes_collection,
    projects_collection,
    retrieval_traces_collection,
    session_summaries_collection,
    users_collection,
)
from app.provider_adapters import get_adapter

SUPPORTED_PROVIDER_NAMES = ["chatgpt", "claude", "gemini", "deepseek", "generic"]


def _base_url(base_url: str) -> str:
    return str(base_url).rstrip("/")


def build_connector_self_check(base_url: str, *, user_id: str | None = None) -> dict[str, Any]:
    base = _base_url(base_url)
    connections = [doc.to_dict() or {} for doc in llm_connections_collection.stream()]
    active = [item for item in connections if item.get("status") in {"connected", "paused"}]
    checks: list[dict[str, Any]] = []
    for provider in SUPPORTED_PROVIDER_NAMES:
        if provider == "generic":
            checks.append(
                {
                    "provider": provider,
                    "supports_mcp": False,
                    "supports_function_calling": True,
                    "bridge_mode": "function_calling",
                    "active_connection": False,
                    "status": "ok",
                    "issues": [],
                    "urls": {
                        "manifest": f"{base}/tool-calling/generic/manifest",
                        "call": f"{base}/tool-calling/generic/call",
                    },
                }
            )
            continue

        adapter = get_adapter(provider)
        candidates = [item for item in active if (item.get("provider") or "").lower() == provider and (not user_id or item.get("user_id") == user_id)]
        selected = sorted(candidates, key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item.get("id") or ""), reverse=True)[0] if candidates else None
        token = selected.get("bridge_token") if selected else None
        issues: list[str] = []
        if selected and not token:
            issues.append("missing_bridge_token")
        if selected and (selected.get("status") not in {"connected", "paused"}):
            issues.append("inactive_connection")
        urls: dict[str, str] = {
            "bridge_manifest": f"{base}/bridge/{provider}/manifest",
            "bridge_call": f"{base}/bridge/{provider}/tool-call",
            "tool_manifest": f"{base}/tool-calling/{provider}/manifest",
            "tool_call": f"{base}/tool-calling/{provider}/call",
        }
        if adapter.supports_mcp:
            urls["mcp_sse"] = f"{base}/sse/"
            urls["mcp_http"] = f"{base}/mcp/rpc"
        if token:
            urls["bridge_manifest"] = f"{urls['bridge_manifest']}?token={token}"
            urls["bridge_call"] = f"{urls['bridge_call']}?token={token}"
            urls["tool_manifest"] = f"{urls['tool_manifest']}?token={token}"
            urls["tool_call"] = f"{urls['tool_call']}?token={token}"
            if adapter.supports_mcp:
                urls["mcp_sse"] = f"{base}/sse/?token={token}&provider={provider}"
                urls["mcp_http"] = f"{base}/mcp/rpc?token={token}&provider={provider}"
        checks.append(
            {
                "provider": provider,
                "supports_mcp": adapter.supports_mcp,
                "supports_function_calling": adapter.supports_function_calling,
                "bridge_mode": adapter.bridge_mode,
                "active_connection": bool(selected),
                "connection_status": selected.get("status") if selected else "not_connected",
                "status": "ok" if not issues else "warning",
                "issues": issues,
                "urls": urls,
            }
        )
    return {"status": "ok", "user_id": user_id, "checks": checks}


REQUIRED_SCOPE_FIELDS = {
    "facts": ["tenant_id", "project_id", "book_id", "user_id", "subject", "relation", "object"],
    "manual_notes": ["tenant_id", "project_id", "book_id", "user_id", "content"],
    "session_summaries": ["tenant_id", "project_id", "book_id", "user_id", "summary"],
}


def _scan_required_fields(collection_name: str, collection) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    required = REQUIRED_SCOPE_FIELDS.get(collection_name, [])
    for doc in collection.stream():
        data = doc.to_dict() or {}
        missing = [field for field in required if not data.get(field)]
        if missing:
            issues.append({
                "kind": "missing_required_fields",
                "collection": collection_name,
                "doc_id": doc.id,
                "missing": missing,
                "severity": "warning",
            })
    return issues


def build_maintenance_report() -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    users = {doc.id for doc in users_collection.stream()}
    projects = {doc.id: (doc.to_dict() or {}) for doc in projects_collection.stream()}
    for doc in llm_connections_collection.stream():
        data = doc.to_dict() or {}
        provider = (data.get("provider") or "").lower()
        if provider not in {"chatgpt", "claude", "gemini", "deepseek", "mock"}:
            issues.append({"kind": "unsupported_provider", "collection": "llm_connections", "doc_id": doc.id, "provider": provider, "severity": "warning"})
        if data.get("status") in {"connected", "paused"} and not data.get("bridge_token"):
            issues.append({"kind": "missing_bridge_token", "collection": "llm_connections", "doc_id": doc.id, "severity": "warning"})
        if data.get("user_id") not in users:
            issues.append({"kind": "orphan_connection", "collection": "llm_connections", "doc_id": doc.id, "severity": "warning"})
    for project_id, data in projects.items():
        if data.get("user_id") not in users:
            issues.append({"kind": "orphan_project", "collection": "projects", "doc_id": project_id, "severity": "warning"})
    for collection_name, collection in [
        ("facts", facts_collection),
        ("manual_notes", manual_notes_collection),
        ("session_summaries", session_summaries_collection),
    ]:
        issues.extend(_scan_required_fields(collection_name, collection))
    counts = {
        "users": len(list(users_collection.stream())),
        "projects": len(list(projects_collection.stream())),
        "connections": len(list(llm_connections_collection.stream())),
        "facts": len(list(facts_collection.stream())),
        "manual_notes": len(list(manual_notes_collection.stream())),
        "session_summaries": len(list(session_summaries_collection.stream())),
        "event_log": len(list(event_log_collection.stream())),
        "retrieval_traces": len(list(retrieval_traces_collection.stream())),
        "documents": len(list(documents_collection.stream())),
    }
    return {
        "status": "ok" if not issues else "warning",
        "counts": counts,
        "issues": issues,
        "safe_actions": [
            "rotate_missing_bridge_tokens",
            "archive_orphan_connections",
            "purge_old_retrieval_traces",
        ],
    }
