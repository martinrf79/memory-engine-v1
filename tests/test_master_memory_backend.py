from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def _memory_payload(
    *,
    id: str,
    user_id: str,
    project: str,
    book_id: str,
    memory_type: str,
    content: str,
    created_at: str,
    status: str = "active",
    trigger_query: str = "fact",
):
    return {
        "id": id,
        "user_id": user_id,
        "project": project,
        "book_id": book_id,
        "memory_type": memory_type,
        "status": status,
        "content": content,
        "summary": content,
        "user_message": f"Guardar: {content}",
        "assistant_answer": "Guardado",
        "trigger_query": trigger_query,
        "importance": 1,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": created_at,
        "updated_at": None,
    }


def _seed_master_case():
    _clear_collections()
    base = {"user_id": "martin", "project": "memoria-guia", "book_id": "general"}

    valid_payloads = [
        _memory_payload(id="m1", **base, memory_type="fact", content="El color favorito de Martín es azul.", created_at="2026-01-01T00:00:00Z"),
        _memory_payload(id="m2", **base, memory_type="fact", content="Martín cambió su color favorito de azul a verde.", created_at="2026-02-01T00:00:00Z"),
        _memory_payload(id="m3", **base, memory_type="fact", content="COC debe leer memoria antes de responder.", created_at="2026-02-02T00:00:00Z"),
        _memory_payload(id="m4", **base, memory_type="fact", content="Si no hay memoria suficiente, debe pedir un dato adicional y no inventar.", created_at="2026-02-03T00:00:00Z"),
        _memory_payload(id="m5", **base, memory_type="fact", content="El proyecto prioritario actual es memoria-guia.", created_at="2026-02-04T00:00:00Z"),
        _memory_payload(id="m6", **base, memory_type="fact", content="El color favorito de Martín es rojo.", created_at="2025-12-01T00:00:00Z", status="archived"),
        _memory_payload(
            id="m7",
            **base,
            memory_type="conversation",
            content='Usuario: "¿Cuál es mi color favorito?" / Asistente: "No tengo memoria suficiente para responder con seguridad."',
            created_at="2026-02-05T00:00:00Z",
            trigger_query="conversation-log",
        ),
        _memory_payload(
            id="m8",
            user_id="pedro",
            project="memoria-guia",
            book_id="general",
            memory_type="fact",
            content="El color favorito de Pedro es negro.",
            created_at="2026-02-05T00:00:00Z",
        ),
    ]

    for payload in valid_payloads:
        response = client.post("/memories", json=payload)
        assert response.status_code == 200, response.text


def test_master_memory_backend_end_to_end():
    _seed_master_case()

    invalid_payload = _memory_payload(
        id="bad-1",
        user_id="martin",
        project="memoria-guia",
        book_id="general",
        memory_type="fact",
        content="Dato inválido",
        created_at="fecha-mala",
    )
    invalid_response = client.post("/memories", json=invalid_payload)
    assert invalid_response.status_code == 422

    duplicate_payload = _memory_payload(
        id="m1",
        user_id="martin",
        project="memoria-guia",
        book_id="general",
        memory_type="fact",
        content="Duplicado",
        created_at="2026-03-01T00:00:00Z",
    )
    duplicate_response = client.post("/memories", json=duplicate_payload)
    assert duplicate_response.status_code == 400
    assert "already exists" in duplicate_response.json()["detail"]

    active_items = client.post(
        "/memories/search",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "status": "active"},
    )
    assert active_items.status_code == 200
    active_data = active_items.json()
    active_ids = {item["id"] for item in active_data}
    assert "m6" not in active_ids
    assert "m8" not in active_ids
    assert "m7" not in active_ids
    assert {"m1", "m2", "m3", "m4", "m5"}.issubset(active_ids)

    color_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Cuál es el color favorito de Martín?"},
    )
    assert color_response.status_code == 200
    color_body = color_response.json()
    assert color_body["mode"] == "answer"
    assert "verde" in color_body["answer"].lower()
    assert "azul" not in color_body["answer"].lower()
    assert "rojo" not in color_body["answer"].lower()
    assert "negro" not in color_body["answer"].lower()
    assert "no tengo memoria suficiente" not in color_body["answer"].lower()

    coc_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Cómo debe responder COC?"},
    )
    coc_body = coc_response.json()
    assert coc_body["mode"] == "answer"
    coc_text = coc_body["answer"].lower()
    assert "consultar memoria" in coc_text or "leer memoria" in coc_text
    assert "pedir un dato adicional" in coc_text
    assert "no inventar" in coc_text

    food_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Cuál es mi comida favorita?"},
    )
    food_body = food_response.json()
    assert food_body["mode"] == "insufficient_memory"
    assert "no tengo memoria suficiente" in food_body["answer"].lower()
    assert food_body["options"]

    isolation_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Cuál es el color favorito de Pedro?"},
    )
    isolation_body = isolation_response.json()
    assert isolation_body["mode"] == "insufficient_memory"
    assert "negro" not in isolation_body["answer"].lower()

    sem_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Qué sabes de mi color favorito?"},
    )
    sem_body = sem_response.json()
    assert sem_body["mode"] == "answer"
    assert "verde" in sem_body["answer"].lower()
    joined_used = " ".join(memory["summary"].lower() for memory in sem_body["used_memories"])
    assert "conversation" not in joined_used
    assert "insufficient_memory" not in joined_used

    archive_response = client.post("/memories/m2/archive")
    assert archive_response.status_code == 200
    recolor_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Cuál es el color favorito de Martín?"},
    )
    recolor_body = recolor_response.json()
    assert recolor_body["mode"] == "answer"
    assert "azul" in recolor_body["answer"].lower()
    assert "rojo" not in recolor_body["answer"].lower()

    delete_response = client.delete("/memories/m1")
    assert delete_response.status_code == 200
    final_response = client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "¿Cuál es el color favorito de Martín?"},
    )
    final_body = final_response.json()
    assert final_body["mode"] == "insufficient_memory"
    assert "no tengo memoria suficiente" in final_body["answer"].lower()
    assert final_body["options"]
