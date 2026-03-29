from fastapi.testclient import TestClient

from app.firestore_store import FakeCollection
from app.main import app


def _memory_payload(memory_id: str, content: str, summary: str, memory_type: str = "fact") -> dict:
    return {
        "id": memory_id,
        "user_id": "martin",
        "project": "test",
        "book_id": "general",
        "memory_type": memory_type,
        "status": "active",
        "content": content,
        "summary": summary,
        "user_message": "seed",
        "assistant_answer": "seed",
        "trigger_query": "seed",
        "importance": 1,
        "keywords_json": None,
        "embedding_json": None,
        "source": "test",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None,
    }


def test_chat_uses_semantic_memory_and_answers_entity_value(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr("app.chat.collection", fake)
    monkeypatch.setattr("app.memories.collection", fake)

    client = TestClient(app)

    r0 = client.post(
        "/memories",
        json=_memory_payload(
            "fav-color-1",
            content="Mi color favorito es azul.",
            summary="Preferencia de color: azul.",
        ),
    )
    assert r0.status_code == 200

    r1 = client.post(
        "/chat",
        json={
            "user_id": "martin",
            "project": "test",
            "book_id": "general",
            "message": "¿Cuál es mi color favorito?",
            "save_interaction": True,
        },
    )

    assert r1.status_code == 200
    body = r1.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Tu color favorito es azul."
    assert "insufficient_memory" not in body["answer"]
    assert "Según la memoria encontrada" not in body["answer"]
    assert any(m["id"] == "fav-color-1" for m in body["used_memories"])

    stored_items = [doc.to_dict() for doc in fake.stream()]
    conv = next(item for item in stored_items if item["memory_type"] == "conversation")
    assert conv["status"] == "archived"


def test_chat_without_memory_returns_options(monkeypatch):
    fake = FakeCollection()
    monkeypatch.setattr("app.chat.collection", fake)
    monkeypatch.setattr("app.memories.collection", fake)

    client = TestClient(app)
    response = client.post(
        "/chat",
        json={
            "user_id": "martin",
            "project": "test",
            "book_id": "general",
            "message": "¿Cuál es mi color favorito?",
            "save_interaction": False,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "insufficient_memory"
    assert body["options"]
    assert "insufficient_memory:" not in body["answer"]
