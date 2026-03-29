import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app
from app.semantic_memory import build_dedupe_key, dedupe_key_hash


client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def test_chat_event_is_always_saved():
    _clear_collections()

    response = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "hola", "save_interaction": False},
    )
    assert response.status_code == 200

    events = [doc.to_dict() for doc in chat_events_collection.stream()]
    assert len(events) == 1
    assert events[0]["user_message"] == "hola"
    assert events[0]["assistant_answer"]


def test_extracts_structured_preference_and_answers_directly():
    _clear_collections()

    client.post(
        "/chat",
        json={
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "message": "Mi color favorito es azul",
        },
    )

    ask = client.post(
        "/chat",
        json={
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "message": "¿Cuál es mi color favorito?",
        },
    )
    assert ask.status_code == 200
    body = ask.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Tu color favorito es azul."


def test_does_not_contaminate_with_assistant_answer_text():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "hola"},
    )

    memories = [doc.to_dict() for doc in semantic_collection.stream()]
    assert memories == []


def test_update_without_duplicate_blue_to_red():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es azul"},
    )
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es rojo"},
    )

    memories = [doc.to_dict() for doc in semantic_collection.stream()]
    actives = [m for m in memories if m["status"] == "active"]
    superseded = [m for m in memories if m["status"] == "superseded"]

    assert len(actives) == 1
    assert actives[0]["value_text"] == "rojo"
    assert len(superseded) == 1
    assert superseded[0]["value_text"] == "azul"


def test_prevents_two_active_same_dedupe_key():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es azul"},
    )
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es azul"},
    )

    dedupe = build_dedupe_key("u1", "p1", "b1", "user", "favorite_color")
    key_doc = memory_keys_collection.document(dedupe_key_hash(dedupe)).get().to_dict()
    memories = [doc.to_dict() for doc in semantic_collection.stream()]
    actives = [m for m in memories if m["dedupe_key"] == dedupe and m["status"] == "active"]

    assert key_doc["active_memory_id"] == actives[0]["id"]
    assert len(actives) == 1


def test_retrieval_uses_only_semantic_memories():
    _clear_collections()

    chat_events_collection.document("e1").set(
        {
            "id": "e1",
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "user_message": "Mi color favorito es violeta",
            "assistant_answer": "Tu color favorito es violeta.",
            "llm_provider": "mock",
            "llm_model": "mock-model",
            "created_at": "2026-01-01T00:00:00Z",
            "ttl_at": None,
        }
    )

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )
    body = ask.json()
    assert body["mode"] == "insufficient_memory"


def test_multi_project_ambiguity_without_project_filter():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "work", "book_id": "b1", "message": "Mi color favorito es azul"},
    )
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "home", "book_id": "b1", "message": "Mi color favorito es rojo"},
    )

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )
    body = ask.json()

    assert body["mode"] == "clarification_required"
    assert body["options"]


def test_missing_data_prompts_without_technical_error():
    _clear_collections()

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )
    body = ask.json()

    assert body["mode"] == "insufficient_memory"
    assert "insufficient_memory:" not in body["answer"]


def test_export_memories_does_not_mix_chat_logs():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es azul"},
    )
    export_memories = client.get("/memories/export", params={"user_id": "u1"}).json()
    export_events = client.get("/chat-events/export", params={"user_id": "u1"}).json()

    assert export_memories["count"] == 1
    assert export_events["count"] >= 1
    assert all("value_text" in item for item in export_memories["items"])
    assert all("user_message" in item for item in export_events["items"])


def test_audit_detects_duplicate_active_keys():
    _clear_collections()

    dedupe = build_dedupe_key("u1", "p1", "b1", "user", "favorite_color")
    semantic_collection.document("m1").set(
        {
            "id": "m1",
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "memory_type": "preference",
            "entity": "user",
            "attribute": "favorite_color",
            "value_text": "azul",
            "context": "Mi color favorito es azul",
            "status": "active",
            "dedupe_key": dedupe,
            "version": 1,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "source_type": "chat_user_message",
            "source_event_id": "e1",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": None,
        }
    )
    semantic_collection.document("m2").set(
        {
            "id": "m2",
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "memory_type": "preference",
            "entity": "user",
            "attribute": "favorite_color",
            "value_text": "rojo",
            "context": "Mi color favorito es rojo",
            "status": "active",
            "dedupe_key": dedupe,
            "version": 2,
            "valid_from": "2026-01-02T00:00:00Z",
            "valid_to": None,
            "source_type": "chat_user_message",
            "source_event_id": "e2",
            "created_at": "2026-01-02T00:00:00Z",
            "updated_at": None,
        }
    )

    audit = client.post("/memories/audit", params={"dry_run": "true"})
    assert audit.status_code == 200
    body = audit.json()
    assert body["findings"]["duplicate_active_keys"]
