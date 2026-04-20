import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.main import app
from app.firestore_store import llm_connections_collection, projects_collection, sessions_collection, users_collection
from app.utils import utc_now_iso

client = TestClient(app)


def _clear():
    for collection in [llm_connections_collection, projects_collection, sessions_collection, users_collection]:
        collection.clear()


def _register_login(user_id="martin"):
    resp = client.post("/auth/register", json={"user_id": user_id, "password": "secret123", "project": "memoria-guia"})
    assert resp.status_code == 200


def test_connection_status_exposes_connector_urls():
    _clear()
    _register_login()
    create = client.post("/panel/projects", json={"project": "memoria-guia"})
    assert create.status_code == 200
    connect = client.post("/connection/connect", json={"user_id": "martin", "provider": "chatgpt", "project": "memoria-guia"})
    assert connect.status_code == 200
    body = connect.json()
    assert body["bridge_token"]
    assert "/mcp/sse?token=" in body["mcp_connector_url"]
    assert "/sse/?token=" in body["mcp_sse_url"]
    assert "/mcp/rpc?token=" in body["mcp_http_url"]
    assert "/sse/messages?token=" in body["mcp_messages_url"]
    assert body["bridge_tool_call_url"].endswith(f"token={body['bridge_token']}")
    assert body["bridge_manifest_url"].endswith(f"token={body['bridge_token']}")
    assert body["tool_calling_call_url"].endswith(f"token={body['bridge_token']}")
    assert body["tool_calling_manifest_url"].endswith(f"token={body['bridge_token']}")


def test_tool_calling_accepts_query_token_for_provider_call():
    _clear()
    now = utc_now_iso()
    llm_connections_collection.document("martin:gemini").set(
        {
            "id": "martin:gemini",
            "user_id": "martin",
            "provider": "gemini",
            "model_name": "gemini-main",
            "bridge_mode": "function_calling",
            "status": "connected",
            "bridge_token": "query-token",
            "created_at": now,
            "updated_at": now,
        }
    )
    save = client.post(
        "/tool-calling/gemini/call?token=query-token",
        json={
            "user_id": "martin",
            "tool_name": "save_note",
            "arguments": {
                "tenant_id": "martin",
                "project_id": "memoria-guia",
                "book_id": "general",
                "content": "El productor premium favorito es Alfa",
            },
        },
    )
    assert save.status_code == 200
    assert save.json()["ok"] is True
