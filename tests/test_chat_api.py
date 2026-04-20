import pytest

pytestmark = pytest.mark.external_api
import uuid
import requests

BASE_URL = "https://memory-engine-v1-1000939441597.southamerica-east1.run.app"


def unique_id(prefix="chat"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_chat_modes():
    memory_id = unique_id("chatmem")

    payload = {
        "id": memory_id,
        "user_id": "martin",
        "project": "test",
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "Prueba simple de memoria.",
        "summary": "Memoria de prueba simple.",
        "user_message": "Guardar prueba",
        "assistant_answer": "Prueba guardada",
        "trigger_query": "prueba simple",
        "importance": 1,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    r0 = requests.post(f"{BASE_URL}/memories", json=payload, timeout=20)
    assert r0.status_code in (200, 201)

    chat_ok = {
        "user_id": "martin",
        "project": "test",
        "message": "prueba simple",
        "save_interaction": False
    }
    r1 = requests.post(f"{BASE_URL}/chat", json=chat_ok, timeout=30)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["mode"] == "answer"
    assert any(m["id"] == memory_id for m in body1["used_memories"])

    chat_fail = {
        "user_id": "martin",
        "project": "test",
        "message": "tema inexistente total",
        "save_interaction": False
    }
    r2 = requests.post(f"{BASE_URL}/chat", json=chat_fail, timeout=30)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["mode"] == "insufficient_memory"

    r3 = requests.delete(f"{BASE_URL}/memories/{memory_id}", timeout=20)
    assert r3.status_code == 200
