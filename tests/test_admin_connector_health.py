import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.config import settings
from app.firestore_store import (
    facts_collection,
    llm_connections_collection,
    manual_notes_collection,
    projects_collection,
    session_summaries_collection,
    users_collection,
)
from app.main import app
from app.utils import utc_now_iso

client = TestClient(app)


def _clear():
    for collection in [
        facts_collection,
        llm_connections_collection,
        manual_notes_collection,
        projects_collection,
        session_summaries_collection,
        users_collection,
    ]:
        collection.clear()


def test_admin_connector_self_check_and_maintenance_report():
    _clear()
    settings.enable_admin_panel = True
    settings.admin_token = "super-admin"
    now = utc_now_iso()
    users_collection.document("martin").set({"id": "martin", "user_id": "martin", "created_at": now, "updated_at": now})
    projects_collection.document("martin:memoria-guia").set({"id": "martin:memoria-guia", "user_id": "martin", "project": "memoria-guia", "status": "active"})
    llm_connections_collection.document("martin:chatgpt").set(
        {
            "id": "martin:chatgpt",
            "user_id": "martin",
            "provider": "chatgpt",
            "model_name": "chatgpt-main",
            "bridge_mode": "mcp",
            "status": "connected",
            "bridge_token": "chat-token",
            "created_at": now,
            "updated_at": now,
        }
    )
    llm_connections_collection.document("ghost:weird").set(
        {
            "id": "ghost:weird",
            "user_id": "ghost",
            "provider": "weird",
            "model_name": "unknown",
            "bridge_mode": "custom",
            "status": "connected",
            "created_at": now,
            "updated_at": now,
        }
    )
    manual_notes_collection.document("note:broken").set(
        {
            "id": "note:broken",
            "tenant_id": "martin",
            "project_id": "memoria-guia",
            "book_id": "general",
            "user_id": "martin",
            "title": "Nota",
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
    )

    r = client.get("/admin/connectors/self-check?user_id=martin", headers={"x-admin-token": "super-admin"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    providers = {item["provider"]: item for item in body["checks"]}
    assert providers["chatgpt"]["active_connection"] is True
    assert providers["chatgpt"]["urls"]["mcp_http"].endswith("token=chat-token&provider=chatgpt")
    assert providers["gemini"]["supports_function_calling"] is True
    assert providers["generic"]["active_connection"] is False

    r = client.get("/admin/maintenance/verify", headers={"x-admin-token": "super-admin"})
    assert r.status_code == 200
    report = r.json()
    assert report["status"] == "warning"
    issue_kinds = {item["kind"] for item in report["issues"]}
    assert "unsupported_provider" in issue_kinds
    assert "orphan_connection" in issue_kinds
    assert "missing_required_fields" in issue_kinds
    assert "rotate_missing_bridge_tokens" in report["safe_actions"]

    settings.enable_admin_panel = False
    settings.admin_token = None
