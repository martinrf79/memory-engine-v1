from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


def run():
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        payload = {
            "id": "mem-1",
            "user_id": "user-1",
            "project": "test-project",
            "book_id": "general",
            "memory_type": "note",
            "status": "active",
            "content": "Memoria de prueba",
            "summary": "Resumen de prueba",
            "user_message": "Guardar prueba",
            "assistant_answer": "Prueba guardada",
            "trigger_query": "prueba",
            "importance": 1,
            "keywords_json": None,
            "embedding_json": None,
            "source": "test",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": None,
        }

        create_response = client.post("/memories", json=payload)
        assert create_response.status_code == 200

        list_response = client.get("/memories")
        assert list_response.status_code == 200
        items = list_response.json()
        assert len(items) >= 1

        search_response = client.post(
            "/memories/search",
            json={"user_id": "user-1", "query": "prueba"},
        )
        assert search_response.status_code == 200

        chat_response = client.post(
            "/chat",
            json={"user_id": "user-1", "message": "prueba", "save_interaction": False},
        )
        assert chat_response.status_code == 200


if __name__ == "__main__":
    run()
