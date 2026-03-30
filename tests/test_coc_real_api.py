import uuid
import requests

BASE_URL = "https://memory-engine-v1-1000939441597.southamerica-east1.run.app"


def unique_id(prefix="cocreal"):
    return f"{prefix}-{uuid.uuid4().hex[:8]}"


def test_coc_real_rules_flow():
    project_name = f"coc-real-{uuid.uuid4().hex[:6]}"

    mem_1 = unique_id("respond")
    mem_2 = unique_id("nomake")
    mem_3 = unique_id("clarify")
    mem_4 = unique_id("savechat")

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
        "importance": 5,
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
        "memory_type": "note",
        "status": "active",
        "content": "Si no hay memoria suficiente, COC no debe inventar y debe pedir un dato más.",
        "summary": "No inventar y pedir un dato más.",
        "user_message": "¿Qué hacer si falta memoria?",
        "assistant_answer": "Debe pedir un dato más y no inventar.",
        "trigger_query": "falta memoria no inventar pedir dato",
        "importance": 5,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    payload_3 = {
        "id": mem_3,
        "user_id": "martin",
        "project": project_name,
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "Si la consulta es ambigua entre proyecto o categoría, COC debe pedir aclaración.",
        "summary": "Pedir aclaración si hay ambigüedad.",
        "user_message": "¿Qué hacer si la consulta es ambigua?",
        "assistant_answer": "Debe pedir aclaración.",
        "trigger_query": "ambiguedad pedir aclaracion",
        "importance": 4,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    payload_4 = {
        "id": mem_4,
        "user_id": "martin",
        "project": project_name,
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "content": "COC debe guardar interacción solo cuando save_interaction sea true.",
        "summary": "Guardar solo con save_interaction true.",
        "user_message": "¿Cuándo guardar interacción?",
        "assistant_answer": "Solo cuando save_interaction sea true.",
        "trigger_query": "guardar interaccion save_interaction true",
        "importance": 4,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None
    }

    for payload in [payload_1, payload_2, payload_3, payload_4]:
        r = requests.post(f"{BASE_URL}/memories", json=payload, timeout=20)
        assert r.status_code in (200, 201)

    chat_1 = {
        "user_id": "martin",
        "project": project_name,
        "message": "¿Cómo debe responder COC?",
        "save_interaction": False
    }
    r1 = requests.post(f"{BASE_URL}/chat", json=chat_1, timeout=30)
    assert r1.status_code == 200
    body1 = r1.json()
    assert body1["mode"] == "answer"
    assert any(m["id"] == mem_1 for m in body1["used_memories"])

    chat_2 = {
        "user_id": "martin",
        "project": project_name,
        "message": "¿Qué hacer si falta memoria?",
        "save_interaction": False
    }
    r2 = requests.post(f"{BASE_URL}/chat", json=chat_2, timeout=30)
    assert r2.status_code == 200
    body2 = r2.json()
    assert body2["mode"] == "answer"
    assert any(m["id"] == mem_2 for m in body2["used_memories"])

    chat_3 = {
        "user_id": "martin",
        "project": project_name,
        "message": "¿Qué hacer si la consulta es ambigua?",
        "save_interaction": False
    }
    r3 = requests.post(f"{BASE_URL}/chat", json=chat_3, timeout=30)
    assert r3.status_code == 200
    body3 = r3.json()
    assert body3["mode"] == "answer"
    assert any(m["id"] == mem_3 for m in body3["used_memories"])

    chat_4 = {
        "user_id": "martin",
        "project": project_name,
        "message": "¿Cuándo guardar interacción?",
        "save_interaction": True
    }
    r4 = requests.post(f"{BASE_URL}/chat", json=chat_4, timeout=30)
    assert r4.status_code == 200
    body4 = r4.json()
    assert body4["mode"] == "answer"
    assert any(m["id"] == mem_4 for m in body4["used_memories"])

    r5 = requests.get(f"{BASE_URL}/memories", timeout=20)
    assert r5.status_code == 200
    items = r5.json()
    assert any(
        x["project"] == project_name
        and x["memory_type"] == "conversation"
        and x["source"] == "chat"
        for x in items
    )

    for memory_id in [mem_1, mem_2, mem_3, mem_4]:
        requests.delete(f"{BASE_URL}/memories/{memory_id}", timeout=20)
