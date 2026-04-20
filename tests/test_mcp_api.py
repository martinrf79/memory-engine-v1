import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.main import app
from app.firestore_store import (
    facts_collection,
    llm_connections_collection,
    manual_notes_collection,
    retrieval_traces_collection,
    session_summaries_collection,
    sessions_collection,
    users_collection,
    projects_collection,
    event_log_collection,
)
from app.utils import utc_now_iso

client = TestClient(app)


def _clear():
    for collection in [
        facts_collection,
        llm_connections_collection,
        manual_notes_collection,
        retrieval_traces_collection,
        session_summaries_collection,
        sessions_collection,
        users_collection,
        projects_collection,
        event_log_collection,
    ]:
        collection.clear()



def test_mcp_manifest_and_tool_call_via_bridge_token():
    _clear()
    now = utc_now_iso()
    llm_connections_collection.document("martin:chatgpt").set(
        {
            "id": "martin:chatgpt",
            "user_id": "martin",
            "provider": "chatgpt",
            "model_name": "chatgpt-main",
            "bridge_mode": "mcp",
            "status": "connected",
            "bridge_token": "mcp-secret",
            "created_at": now,
            "updated_at": now,
        }
    )

    manifest = client.get("/mcp/manifest")
    assert manifest.status_code == 200
    body = manifest.json()
    assert body["server_name"] == "memory-core"
    assert any(tool["name"] == "save_fact" for tool in body["tools"])

    save_fact = client.post(
        "/mcp/call",
        headers={"x-mcp-token": "mcp-secret", "x-mcp-user": "martin"},
        json={
            "tool_name": "save_fact",
            "arguments": {
                "tenant_id": "martin",
                "project_id": "memoria-guia",
                "book_id": "producer",
                "entity_type": "producer",
                "entity_id": "producer-martin",
                "subject": "producer-martin",
                "relation": "country",
                "object": "Argentina",
            },
        },
    )
    assert save_fact.status_code == 200
    fact_body = save_fact.json()
    assert fact_body["ok"] is True
    assert fact_body["result"]["status"] == "active"

    search = client.post(
        "/mcp/call",
        headers={"x-mcp-token": "mcp-secret", "x-mcp-user": "martin"},
        json={
            "tool_name": "search_memory",
            "arguments": {
                "tenant_id": "martin",
                "project_id": "memoria-guia",
                "book_id": "producer",
                "entity_type": "producer",
                "entity_id": "producer-martin",
                "query": "Argentina",
            },
        },
    )
    assert search.status_code == 200
    search_body = search.json()
    assert search_body["ok"] is True
    assert search_body["result"]["items"]
    assert any("argentina" in item["preview"].lower() for item in search_body["result"]["items"])



def test_bridge_new_tools_work_without_breaking_existing_bridge_surface():
    _clear()
    now = utc_now_iso()
    llm_connections_collection.document("martin:chatgpt").set(
        {
            "id": "martin:chatgpt",
            "user_id": "martin",
            "provider": "chatgpt",
            "model_name": "chatgpt-main",
            "bridge_mode": "mcp",
            "status": "connected",
            "bridge_token": "secret-bridge-token",
            "created_at": now,
            "updated_at": now,
        }
    )

    note = client.post(
        "/bridge/chatgpt/tool-call",
        headers={"x-bridge-token": "secret-bridge-token"},
        json={
            "user_id": "martin",
            "tool_name": "save_note",
            "arguments": {
                "tenant_id": "martin",
                "project_id": "memoria-guia",
                "book_id": "passport",
                "content": "El productor apunta a premium export.",
                "title": "Posicionamiento",
            },
        },
    )
    assert note.status_code == 200
    note_body = note.json()
    assert note_body["ok"] is True
    assert note_body["result"]["title"] == "Posicionamiento"

    books = client.post(
        "/bridge/chatgpt/tool-call",
        headers={"x-bridge-token": "secret-bridge-token"},
        json={
            "user_id": "martin",
            "tool_name": "list_books",
            "arguments": {
                "tenant_id": "martin",
                "project_id": "memoria-guia",
            },
        },
    )
    assert books.status_code == 200
    books_body = books.json()
    assert books_body["ok"] is True
    assert "passport" in books_body["result"]["books"]
