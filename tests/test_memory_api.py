import uuid
import requests

BASE_URL = "https://memory-engine-v1-1000939441597.southamerica-east1.run.app"


def unique_id(prefix="test"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_health():
    r = requests.get(f"{BASE_URL}/health", timeout=20)
    assert r.status_code == 200


def test_memory_crud_flow():
    memory_id = unique_id("mem")

    payload = {
        "id": memory_id,
        "user_id": "martin",
        "project": "test",
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "Prueba automatica de memoria.",
        "summary": "Memoria automatica.",
        "user_message": "Guardar prueba automatica",
        "assistant_answer": "Prueba automatica guardada",
        "trigger_query": "prueba automatica",
        "importance": 1,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    r = requests.post(f"{BASE_URL}/memories", json=payload, timeout=20)
    assert r.status_code in (200, 201)

    r2 = requests.post(f"{BASE_URL}/memories", json=payload, timeout=20)
    assert r2.status_code == 400
    assert "already exists" in r2.text.lower()

    r3 = requests.get(f"{BASE_URL}/memories", timeout=20)
    assert r3.status_code == 200
    items = r3.json()
    assert any(x["id"] == memory_id for x in items)

    search_payload = {
        "user_id": "martin",
        "project": "test",
        "query": "prueba automatica"
    }
    r4 = requests.post(f"{BASE_URL}/memories/search", json=search_payload, timeout=20)
    assert r4.status_code == 200
    results = r4.json()
    assert any(x["id"] == memory_id for x in results)

    patch_payload = {
        "summary": "Resumen automatizado actualizado."
    }
    r5 = requests.patch(f"{BASE_URL}/memories/{memory_id}", json=patch_payload, timeout=20)
    assert r5.status_code == 200
    assert r5.json()["summary"] == "Resumen automatizado actualizado."

    r6 = requests.post(f"{BASE_URL}/memories/{memory_id}/archive", timeout=20)
    assert r6.status_code == 200
    assert r6.json()["status"] == "archived"

    r7 = requests.delete(f"{BASE_URL}/memories/{memory_id}", timeout=20)
    assert r7.status_code == 200
    assert r7.json()["status"] == "deleted"

    r8 = requests.get(f"{BASE_URL}/memories/export", timeout=20)
    assert r8.status_code == 200
    export_data = r8.json()
    assert "count" in export_data
    assert "items" in export_data
