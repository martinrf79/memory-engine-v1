import uuid
import requests

BASE_URL = "https://memory-engine-v1-1000939441597.southamerica-east1.run.app"


def unique_id(prefix="coc"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_coc_chat_flow():
    project_name = f"coc-test-{uuid.uuid4().hex[:6]}"

    mem_1 = unique_id("cocrule")
    mem_2 = unique_id("cocsafe")

    payload_1 = {
        "id": mem_1,
        "user_id": "martin",
        "project": project_name,
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "La guía COC debe consultar memoria antes de responder.",
        "summary": "COC consulta memoria primero.",
        "user_message": "¿Cómo debe responder COC?",
        "assistant_answer": "Primero revisa memoria y luego responde.",
        "trigger_query": "coc memoria primero",
        "importance": 3,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    payload_2 = {
        "id": mem_2,
        "user_id": "martin",
        "project": project_name,
        "book_id": "general",
        "memory_type": "rule",
        "status": "active",
        "content": "Si no hay memoria suficiente, el sistema no debe inventar.",
        "summary": "No inventar cuando falte memoria.",
        "user_message": "¿Qué pasa si falta memoria?",
        "assistant_answer": "Debe indicar que no tiene memoria suficiente.",
        "trigger_query": "falta memoria no inventar",
        "importance": 5,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    # Crear memorias base
    r0 = requests.post(f"{BASE_URL}/memories", json=payload_1, timeout=20)
    assert r0.status_code in (200, 201)

    r1 = requests.post(f"{BASE_URL}/memories", json=payload_2, timeout=20)
    assert r1.status_code in (200, 201)

    # Chat con memoria clara
    chat_ok = {
        "user_id": "martin",
        "project": project_name,
        "message": "¿Cómo debe responder COC?",
        "save_interaction": False
    }
    r2 = requests.post(f"{BASE_URL}/chat", json=chat_ok, timeout=30)
    assert r2.status_code == 200
    body_ok = r2.json()
    assert body_ok["mode"] == "answer"
    assert any(m["id"] == mem_1 for m in body_ok["used_memories"])

    # Chat sin memoria suficiente
    chat_fail = {
        "user_id": "martin",
        "project": project_name,
        "message": "tema inexistente total de coc",
        "save_interaction": False
    }
    r3 = requests.post(f"{BASE_URL}/chat", json=chat_fail, timeout=30)
    assert r3.status_code == 200
    body_fail = r3.json()
    assert body_fail["mode"] == "insufficient_memory"

    # Guardar interacción
    chat_save = {
        "user_id": "martin",
        "project": project_name,
        "message": "¿Cómo debe responder COC?",
        "save_interaction": True
    }
    r4 = requests.post(f"{BASE_URL}/chat", json=chat_save, timeout=30)
    assert r4.status_code == 200
    body_save = r4.json()
    assert body_save["mode"] == "answer"

    # Verificar que se guardó una conversación
    r5 = requests.get(f"{BASE_URL}/memories", timeout=20)
    assert r5.status_code == 200
    items = r5.json()
    assert any(
        x["project"] == project_name
        and x["memory_type"] == "conversation"
        and x["source"] == "chat"
        for x in items
    )

    # Limpieza básica
    requests.delete(f"{BASE_URL}/memories/{mem_1}", timeout=20)
    requests.delete(f"{BASE_URL}/memories/{mem_2}", timeout=20)
