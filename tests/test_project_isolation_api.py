import pytest

pytestmark = pytest.mark.external_api
import uuid
import requests

BASE_URL = "https://memory-engine-v1-1000939441597.southamerica-east1.run.app"


def unique_id(prefix="iso"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_project_isolation_flow():
    project_a = f"iso-a-{uuid.uuid4().hex[:6]}"
    project_b = f"iso-b-{uuid.uuid4().hex[:6]}"

    mem_a = unique_id("projA")
    mem_b = unique_id("projB")

    payload_a = {
        "id": mem_a,
        "user_id": "martin",
        "project": project_a,
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "En el proyecto A, la prioridad es consultar memoria técnica antes de responder.",
        "summary": "Proyecto A consulta memoria técnica primero.",
        "user_message": "¿Cuál es la prioridad?",
        "assistant_answer": "Consultar memoria técnica primero.",
        "trigger_query": "prioridad proyecto",
        "importance": 3,
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
        "content": "En el proyecto B, la prioridad es pedir confirmación comercial antes de responder.",
        "summary": "Proyecto B pide confirmación comercial primero.",
        "user_message": "¿Cuál es la prioridad?",
        "assistant_answer": "Pedir confirmación comercial primero.",
        "trigger_query": "prioridad proyecto",
        "importance": 3,
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

    # Buscar en proyecto A
    search_a = {
        "user_id": "martin",
        "project": project_a,
        "query": "prioridad proyecto"
    }
    r2 = requests.post(f"{BASE_URL}/memories/search", json=search_a, timeout=20)
    assert r2.status_code == 200
    results_a = r2.json()
    assert any(x["id"] == mem_a for x in results_a)
    assert not any(x["id"] == mem_b for x in results_a)

    # Buscar en proyecto B
    search_b = {
        "user_id": "martin",
        "project": project_b,
        "query": "prioridad proyecto"
    }
    r3 = requests.post(f"{BASE_URL}/memories/search", json=search_b, timeout=20)
    assert r3.status_code == 200
    results_b = r3.json()
    assert any(x["id"] == mem_b for x in results_b)
    assert not any(x["id"] == mem_a for x in results_b)

    # Chat en proyecto A
    chat_a = {
        "user_id": "martin",
        "project": project_a,
        "message": "¿Cuál es la prioridad?",
        "save_interaction": False
    }
    r4 = requests.post(f"{BASE_URL}/chat", json=chat_a, timeout=30)
    assert r4.status_code == 200
    body_a = r4.json()
    assert body_a["mode"] == "answer"
    assert any(m["id"] == mem_a for m in body_a["used_memories"])
    assert not any(m["id"] == mem_b for m in body_a["used_memories"])

    # Chat en proyecto B
    chat_b = {
        "user_id": "martin",
        "project": project_b,
        "message": "¿Cuál es la prioridad?",
        "save_interaction": False
    }
    r5 = requests.post(f"{BASE_URL}/chat", json=chat_b, timeout=30)
    assert r5.status_code == 200
    body_b = r5.json()
    assert body_b["mode"] == "answer"
    assert any(m["id"] == mem_b for m in body_b["used_memories"])
    assert not any(m["id"] == mem_a for m in body_b["used_memories"])

    requests.delete(f"{BASE_URL}/memories/{mem_a}", timeout=20)
    requests.delete(f"{BASE_URL}/memories/{mem_b}", timeout=20)
