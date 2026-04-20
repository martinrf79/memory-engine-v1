import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.firestore_store import llm_connections_collection, semantic_collection
from app.main import app
from app.utils import utc_now_iso

client = TestClient(app)


def _clear():
    llm_connections_collection.clear()
    semantic_collection.clear()


def test_bridge_bootstrap_and_manifest_expose_tools():
    _clear()
    response = client.get("/bridge/chatgpt/bootstrap")
    assert response.status_code == 200
    body = response.json()
    assert body["provider"] == "chatgpt"
    assert body["supports_mcp"] is True
    assert any(tool["name"] == "memory_chat" for tool in body["tools"])

    manifest = client.get("/bridge/chatgpt/manifest")
    assert manifest.status_code == 200
    manifest_body = manifest.json()
    assert manifest_body["mcp_ready"] is True
    assert any(tool["name"] == "memory_connection_status" for tool in manifest_body["tools"])



def test_bridge_tool_call_requires_bridge_token_and_respects_pause():
    _clear()
    now = utc_now_iso()
    llm_connections_collection.document("martin:chatgpt").set({
        "id": "martin:chatgpt",
        "user_id": "martin",
        "provider": "chatgpt",
        "model_name": "chatgpt-main",
        "bridge_mode": "mcp",
        "status": "connected",
        "bridge_token": "secret-bridge-token",
        "created_at": now,
        "updated_at": now,
    })

    store = client.post(
        "/chat",
        json={
            "user_id": "martin",
            "project": "memoria-guia",
            "book_id": "general",
            "message": "Quiero que recuerdes esto: mi color favorito es azul.",
        },
    )
    assert store.status_code == 200

    denied = client.post(
        "/bridge/chatgpt/tool-call",
        json={
            "user_id": "martin",
            "tool_name": "memory_chat",
            "arguments": {
                "user_id": "martin",
                "project": "memoria-guia",
                "book_id": "general",
                "message": "¿Cuál es mi color favorito?",
            },
        },
    )
    assert denied.status_code == 401

    call = client.post(
        "/bridge/chatgpt/tool-call",
        headers={"x-bridge-token": "secret-bridge-token"},
        json={
            "user_id": "martin",
            "tool_name": "memory_chat",
            "arguments": {
                "user_id": "martin",
                "project": "memoria-guia",
                "book_id": "general",
                "message": "¿Cuál es mi color favorito?",
            },
        },
    )
    assert call.status_code == 200
    body = call.json()
    assert body["ok"] is True
    assert body["result"]["mode"] == "answer"
    assert "azul" in body["result"]["answer"].lower()

    llm_connections_collection.document("martin:chatgpt").update({"status": "paused", "updated_at": utc_now_iso()})
    paused = client.post(
        "/bridge/chatgpt/tool-call",
        headers={"x-bridge-token": "secret-bridge-token"},
        json={
            "user_id": "martin",
            "tool_name": "memory_chat",
            "arguments": {"user_id": "martin", "project": "memoria-guia", "message": "¿Cuál es mi color favorito?"},
        },
    )
    assert paused.status_code == 200
    paused_body = paused.json()
    assert paused_body["ok"] is False
    assert "pausada" in paused_body["error"].lower()


def test_bridge_tool_call_accepts_query_token():
    _clear()
    now = utc_now_iso()
    llm_connections_collection.document("martin:chatgpt").set({
        "id": "martin:chatgpt",
        "user_id": "martin",
        "provider": "chatgpt",
        "model_name": "chatgpt-main",
        "bridge_mode": "mcp",
        "status": "connected",
        "bridge_token": "query-bridge-token",
        "created_at": now,
        "updated_at": now,
    })

    call = client.post(
        "/bridge/chatgpt/tool-call?token=query-bridge-token",
        json={
            "user_id": "martin",
            "tool_name": "save_note",
            "arguments": {
                "tenant_id": "martin",
                "project_id": "memoria-guia",
                "book_id": "general",
                "content": "Consulta desde bridge con token en query",
            },
        },
    )
    assert call.status_code == 200
    assert call.json()["ok"] is True
