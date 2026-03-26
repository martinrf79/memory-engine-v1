import uuid
import requests

BASE_URL = "https://memory-engine-v1-1000939441597.southamerica-east1.run.app"


def unique_id(prefix="amb"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_chat_ambiguity_flow():
    project_a = f"amb-a-{uuid.uuid4().hex[:6]}"
    project_b = f"amb-b-{uuid.uuid4().hex[:6]}"

    mem_a = unique_id("projectA")
    mem_b = unique_id("projectB")

    payload_a = {
        "id": mem_a,
        "user_id": "martin",
        "project": project_a,
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "En este proyecto la regla es revisar memoria documental antes de responder.",
        "summary": "Revisar memoria documental primero.",
        "user_message": "¿Cuál es la regla principal?",
        "assistant_answer": "Revisar memoria documental primero.",
        "trigger_query": "regla principal",
        "importance": 4,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    payload_b = {
        "id": mem_b,
        "user_id": "martin",
        "project": project_b,
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "En este proyecto la regla es pedir contexto comercial antes de responder.",
        "summary": "Pedir contexto comercial primero.",
        "user_message": "¿Cuál es la regla principal?",
        "assistant_answer": "Pedir contexto comercial primero.",
        "trigger_query": "regla principal",
        "importance": 4,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    r0 = requests.post(f"{BASE_URL}/memories", json=payload_a, timeout=20)
    assert r0.status_code in (200, 201)

    r1 = requests.post(f"{BASE_URL}/memories", json=payload_b, timeout=20)
    assert r1.status_code in (200, 201)

    chat_payload = {
        "user_id": "martin",
        "message": "¿Cuál es la regla principal?",
        "save_interaction": False
    }

    r2 = requests.post(f"{BASE_URL}/chat", json=chat_payload, timeout=30)
    assert r2.status_code == 200
    body = r2.json()

    assert body["mode"] in ["clarification_required", "answer"]

    if body["mode"] == "clarification_required":
        assert "options" in body
        assert len(body["options"]) > 0
    else:
        assert "used_memories" in body
        assert len(body["used_memories"]) > 0

    requests.delete(f"{BASE_URL}/memories/{mem_a}", timeout=20)
    requests.delete(f"{BASE_URL}/memories/{mem_b}", timeout=20)
