import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.main import app
from app.firestore_store import (
    event_log_collection,
    facts_collection,
    llm_connections_collection,
    manual_notes_collection,
    projects_collection,
    retrieval_traces_collection,
    session_summaries_collection,
    sessions_collection,
    users_collection,
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


def _connect(user_id="martin", provider="chatgpt", token="mcp-remote-token"):
    now = utc_now_iso()
    llm_connections_collection.document(f"{user_id}:{provider}").set(
        {
            "id": f"{user_id}:{provider}",
            "user_id": user_id,
            "provider": provider,
            "model_name": f"{provider}-main",
            "bridge_mode": "mcp" if provider in {"chatgpt", "claude"} else "function_calling",
            "status": "connected",
            "bridge_token": token,
            "created_at": now,
            "updated_at": now,
        }
    )
    return token


def test_remote_mcp_sse_and_rpc_flow():
    _clear()
    token = _connect()

    sse = client.get(f"/sse/?token={token}")
    assert sse.status_code == 200
    assert sse.headers["content-type"].startswith("text/event-stream")
    assert "event: endpoint" in sse.text
    assert f"/sse/messages?token={token}" in sse.text

    init = client.post(
        f"/mcp/rpc?token={token}",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"clientInfo": {"name": "tester"}}},
    )
    assert init.status_code == 200
    init_body = init.json()
    assert init_body["result"]["protocolVersion"]
    assert init_body["result"]["capabilities"]["tools"] == {"listChanged": False}

    tools = client.post(f"/mcp/rpc?token={token}", json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert tools.status_code == 200
    tool_names = {item["name"] for item in tools.json()["result"]["tools"]}
    assert {"search_memory", "save_note", "save_fact"}.issubset(tool_names)

    save = client.post(
        f"/mcp/rpc?token={token}",
        json={
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "save_note",
                "arguments": {
                    "tenant_id": "martin",
                    "project_id": "memoria-guia",
                    "book_id": "general",
                    "content": "Mi productor favorito es Alfa",
                    "title": "Preferencia",
                },
            },
        },
    )
    assert save.status_code == 200
    save_body = save.json()["result"]
    assert save_body["structuredContent"]["title"] == "Preferencia"

    search = client.post(
        f"/mcp/rpc?token={token}",
        json={
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "search_memory",
                "arguments": {
                    "tenant_id": "martin",
                    "project_id": "memoria-guia",
                    "book_id": "general",
                    "query": "productor favorito",
                },
            },
        },
    )
    assert search.status_code == 200
    items = search.json()["result"]["structuredContent"]["items"]
    assert items
    assert any("alfa" in item["preview"].lower() for item in items)


def test_sse_messages_endpoint_is_compatible_with_same_token():
    _clear()
    token = _connect(provider="claude", token="claude-secret")
    init = client.post(
        f"/sse/messages?token={token}&provider=claude",
        json={"jsonrpc": "2.0", "id": 10, "method": "initialize", "params": {}},
    )
    assert init.status_code == 200
    call = client.post(
        f"/sse/messages?token={token}&provider=claude",
        json={
            "jsonrpc": "2.0",
            "id": 11,
            "method": "tools/call",
            "params": {
                "name": "save_fact",
                "arguments": {
                    "tenant_id": "martin",
                    "project_id": "passport",
                    "book_id": "producer",
                    "entity_type": "producer",
                    "entity_id": "alpha",
                    "subject": "alpha",
                    "relation": "country",
                    "object": "Argentina",
                },
            },
        },
    )
    assert call.status_code == 200
    structured = call.json()["result"]["structuredContent"]
    assert structured["status"] == "active"


def test_remote_mcp_rpc_allows_initialize_and_tools_list_without_auth():
    _clear()
    init = client.post(
        "/mcp/rpc",
        json={"jsonrpc": "2.0", "id": 20, "method": "initialize", "params": {}},
    )
    assert init.status_code == 200
    tools = client.post(
        "/mcp/rpc",
        json={"jsonrpc": "2.0", "id": 21, "method": "tools/list", "params": {}},
    )
    assert tools.status_code == 200
    names = {item["name"] for item in tools.json()["result"]["tools"]}
    assert "search_memory" in names

    denied = client.post(
        "/mcp/rpc",
        json={"jsonrpc": "2.0", "id": 22, "method": "tools/call", "params": {"name": "list_books", "arguments": {"tenant_id": "x", "project_id": "y"}}},
    )
    assert denied.status_code == 401


def test_mcp_rpc_get_can_negotiate_event_stream():
    _clear()
    token = _connect(token="stream-token")
    stream = client.get(f"/mcp/rpc?token={token}", headers={"accept": "text/event-stream"})
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert f"/mcp/rpc?token={token}" in stream.text


def test_mcp_sse_alias_is_available():
    _clear()
    token = _connect(token="alias-token")
    stream = client.get(f"/mcp/sse?token={token}")
    assert stream.status_code == 200
    assert stream.headers["content-type"].startswith("text/event-stream")
    assert f"/sse/messages?token={token}" in stream.text
