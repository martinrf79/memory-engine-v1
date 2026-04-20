from uuid import uuid4

from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def test_preference_value_is_normalized_without_trailing_punctuation():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es azul!"},
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )

    body = ask.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Tu color favorito es azul."



def test_negation_inside_longer_sentence_is_not_stored():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Hoy no me gusta el color azul"},
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )

    assert ask.json()["mode"] == "insufficient_memory"



def test_negation_with_prefix_is_not_stored_for_food():
    _clear_collections()

    client.post(
        "/chat",
        json={
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "message": "Anotá que no me gusta comer pizza",
        },
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi comida favorita?"},
    )

    assert ask.json()["mode"] == "insufficient_memory"



def test_rules_starting_with_no_can_be_saved_from_chat():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "martin", "project": "memoria-guia", "book_id": "general", "message": "No inventar"},
    )
    response = client.post(
        "/chat",
        json={
            "user_id": "martin",
            "project": "memoria-guia",
            "book_id": "general",
            "message": "¿Hay algo importante que deba evitar al probar este backend?",
        },
    )

    body = response.json()
    assert body["mode"] == "answer"
    assert "no inventes datos" in body["answer"].lower()



def test_user_summary_paraphrase_returns_saved_preferences():
    _clear_collections()

    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi color favorito es azul"},
    )
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Mi comida favorita es pizza"},
    )

    response = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Qué sabes de mí?"},
    )
    body = response.json()

    assert body["mode"] == "answer"
    assert "color favorito: azul." in body["answer"].lower()
    assert "comida favorita: pizza." in body["answer"].lower()



def test_project_summary_paraphrase_returns_seeded_project_memories():
    _clear_collections()

    client.post(
        "/memories/seed-operational",
        params={"user_id": "martin", "project": "memoria-guia", "book_id": "general"},
    )

    response = client.post(
        "/chat",
        json={
            "user_id": "martin",
            "project": "memoria-guia",
            "book_id": "general",
            "message": "Dame un resumen del proyecto",
        },
    )
    body = response.json()

    assert body["mode"] == "answer"
    assert "recuerdo esto de este proyecto" in body["answer"].lower()
    assert "user_id: martin." in body["answer"].lower()



def test_search_is_accent_insensitive_and_project_isolated():
    _clear_collections()
    memory_id_1 = f"mem-{uuid4().hex[:8]}"
    memory_id_2 = f"mem-{uuid4().hex[:8]}"

    payload_common = {
        "user_id": "martin",
        "book_id": "general",
        "memory_type": "note",
        "status": "active",
        "user_message": "Guardar prueba",
        "assistant_answer": "Prueba guardada",
        "importance": 1,
        "keywords_json": None,
        "embedding_json": None,
        "source": "manual",
        "created_at": "2026-01-01T00:00:00Z",
        "updated_at": None,
    }

    client.post(
        "/memories",
        json={
            **payload_common,
            "id": memory_id_1,
            "project": "alpha",
            "content": "La regla principal es pedir aclaración si hay ambigüedad.",
            "summary": "Pedir aclaración por ambigüedad.",
            "trigger_query": "ambigüedad",
        },
    )
    client.post(
        "/memories",
        json={
            **payload_common,
            "id": memory_id_2,
            "project": "beta",
            "content": "La regla principal es pedir contexto comercial.",
            "summary": "Pedir contexto comercial.",
            "trigger_query": "contexto comercial",
        },
    )

    search = client.post(
        "/memories/search",
        json={"user_id": "martin", "project": "alpha", "query": "ambiguedad"},
    )
    body = search.json()

    assert search.status_code == 200
    assert [item["id"] for item in body] == [memory_id_1]



def test_memory_crud_flow_is_locally_stable():
    _clear_collections()
    memory_id = f"mem-{uuid4().hex[:8]}"

    create = client.post(
        "/memories",
        json={
            "id": memory_id,
            "user_id": "martin",
            "project": "memoria-guia",
            "book_id": "general",
            "memory_type": "note",
            "status": "active",
            "content": "Prueba de CRUD local.",
            "summary": "CRUD local.",
            "user_message": "Guardar CRUD",
            "assistant_answer": "CRUD guardado",
            "trigger_query": "crud local",
            "importance": 1,
            "keywords_json": None,
            "embedding_json": None,
            "source": "manual",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": None,
        },
    )
    assert create.status_code == 200

    update = client.patch(f"/memories/{memory_id}", json={"summary": "CRUD local actualizado"})
    assert update.status_code == 200
    assert update.json()["summary"] == "CRUD local actualizado"

    archive = client.post(f"/memories/{memory_id}/archive")
    assert archive.status_code == 200
    assert archive.json()["status"] == "archived"

    delete = client.delete(f"/memories/{memory_id}")
    assert delete.status_code == 200
    assert delete.json()["status"] == "deleted"



def test_seed_operational_is_idempotent_for_active_memories():
    _clear_collections()

    first = client.post(
        "/memories/seed-operational",
        params={"user_id": "martin", "project": "memoria-guia", "book_id": "general"},
    )
    second = client.post(
        "/memories/seed-operational",
        params={"user_id": "martin", "project": "memoria-guia", "book_id": "general"},
    )

    assert first.status_code == 200
    assert second.status_code == 200

    active = [doc.to_dict() for doc in semantic_collection.stream() if doc.to_dict().get("status") == "active"]
    keys = {(item["entity"], item["attribute"]) for item in active}
    assert len(active) == 6
    assert len(keys) == 6



def test_audit_reports_and_archives_contaminated_memories():
    _clear_collections()
    contaminated_id = f"mem-{uuid4().hex[:8]}"
    semantic_collection.document(contaminated_id).set(
        {
            "id": contaminated_id,
            "user_id": "u1",
            "project": "p1",
            "book_id": "b1",
            "memory_type": "preference",
            "entity": "user",
            "attribute": "favorite_color",
            "value_text": "answer: azul",
            "context": "según las memorias encontradas",
            "status": "active",
            "dedupe_key": "u1|p1|b1|user|favorite_color",
            "version": 1,
            "valid_from": "2026-01-01T00:00:00Z",
            "valid_to": None,
            "source_type": "manual",
            "source_event_id": "seed-1",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": None,
        }
    )

    dry_run = client.post("/memories/audit", params={"dry_run": True})
    assert contaminated_id in dry_run.json()["findings"]["contaminated"]

    apply_run = client.post("/memories/audit", params={"dry_run": False})
    assert contaminated_id in apply_run.json()["findings"]["contaminated"]
    archived = semantic_collection.document(contaminated_id).get().to_dict()
    assert archived["status"] == "archived"
