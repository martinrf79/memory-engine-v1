from uuid import uuid4

from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, collection, memory_keys_collection
from app.main import app


def _clear_all():
    for col in (collection, chat_events_collection, memory_keys_collection):
        if hasattr(col, "clear"):
            col.clear()


def run():
    _clear_all()

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        valid_payload = {
            "id": str(uuid4()),
            "user_id": "martin",
            "project": "memoria-guia",
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
            "updated_at": None,
        }

        create_response = client.post("/memories", json=valid_payload)
        assert create_response.status_code == 200

        list_response = client.get("/memories")
        assert list_response.status_code == 200
        items = list_response.json()
        assert len(items) == 1

        search_response = client.post(
            "/memories/search",
            json={"user_id": "martin", "project": "memoria-guia", "query": "prueba automatica"},
        )
        assert search_response.status_code == 200
        assert len(search_response.json()) >= 1

        save_color = client.post(
            "/chat",
            json={
                "user_id": "martin",
                "project": "memoria-guia",
                "book_id": "general",
                "message": "Mi color favorito es azul",
            },
        )
        assert save_color.status_code == 200
        assert save_color.json()["mode"] == "answer"

        ask_color = client.post(
            "/chat",
            json={
                "user_id": "martin",
                "project": "memoria-guia",
                "book_id": "general",
                "message": "¿Cuál es mi color favorito?",
            },
        )
        assert ask_color.status_code == 200
        assert ask_color.json()["answer"] == "Tu color favorito es azul."

        seed_response = client.post(
            "/memories/seed-operational",
            params={"user_id": "martin", "project": "memoria-guia", "book_id": "general"},
        )
        assert seed_response.status_code == 200
        assert seed_response.json()["count"] == 6

        config_response = client.post(
            "/chat",
            json={
                "user_id": "martin",
                "project": "memoria-guia",
                "book_id": "general",
                "message": "¿Cuál es el user_id y project de pruebas?",
            },
        )
        assert config_response.status_code == 200
        assert config_response.json()["mode"] == "answer"

        avoid_response = client.post(
            "/chat",
            json={
                "user_id": "martin",
                "project": "memoria-guia",
                "book_id": "general",
                "message": "¿Hay algo importante que deba evitar al probar este backend?",
            },
        )
        assert avoid_response.status_code == 200
        assert "user_id=default" in avoid_response.json()["answer"]

        invalid_chat_response = client.post(
            "/chat",
            json={"user_id": "martin", "message": "   ", "save_interaction": False},
        )
        assert invalid_chat_response.status_code == 422


if __name__ == "__main__":
    run()
