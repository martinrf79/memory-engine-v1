from uuid import uuid4

from fastapi.testclient import TestClient

from app.db import Base, engine
from app.main import app


def run():
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as client:
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}

        valid_payload = {
            "id": str(uuid4()),
            "user_id": "user-1",
            "project": "project-a",
            "book_id": "general",
            "memory_type": "note",
            "status": "active",
            "content": "Memoria de prueba sobre cosecha",
            "summary": "Resumen de prueba sobre cosecha",
            "user_message": "Guardar prueba",
            "assistant_answer": "Prueba guardada",
            "trigger_query": "cosecha",
            "importance": 1,
            "keywords_json": None,
            "embedding_json": None,
            "source": "test",
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
            json={"user_id": "user-1", "query": "cosecha"},
        )
        assert search_response.status_code == 200
        assert len(search_response.json()) >= 1

        chat_response = client.post(
            "/chat",
            json={"user_id": "user-1", "message": "cosecha", "save_interaction": False},
        )
        assert chat_response.status_code == 200
        assert chat_response.json()["mode"] == "answer"

        second_payload = dict(valid_payload)
        second_payload["id"] = str(uuid4())
        second_payload["project"] = "project-b"
        second_payload["summary"] = "Resumen alternativo sobre cosecha"
        second_payload["content"] = "Otra memoria de prueba sobre cosecha"
        second_payload["assistant_answer"] = "Prueba guardada en otro proyecto"

        second_create_response = client.post("/memories", json=second_payload)
        assert second_create_response.status_code == 200

        ambiguous_chat_response = client.post(
            "/chat",
            json={"user_id": "user-1", "message": "cosecha", "save_interaction": False},
        )
        assert ambiguous_chat_response.status_code == 200
        ambiguous_data = ambiguous_chat_response.json()
        assert ambiguous_data["mode"] == "clarification_required"
        assert "project-a" in ambiguous_data["options"]
        assert "project-b" in ambiguous_data["options"]

        explicit_project_chat_response = client.post(
            "/chat",
            json={
                "user_id": "user-1",
                "project": "project-a",
                "message": "cosecha",
                "save_interaction": False,
            },
        )
        assert explicit_project_chat_response.status_code == 200
        assert explicit_project_chat_response.json()["mode"] == "answer"

        invalid_type_payload = dict(valid_payload)
        invalid_type_payload["id"] = str(uuid4())
        invalid_type_payload["memory_type"] = "invalid_type"
        invalid_type_response = client.post("/memories", json=invalid_type_payload)
        assert invalid_type_response.status_code == 422

        invalid_status_payload = dict(valid_payload)
        invalid_status_payload["id"] = str(uuid4())
        invalid_status_payload["status"] = "invalid_status"
        invalid_status_response = client.post("/memories", json=invalid_status_payload)
        assert invalid_status_response.status_code == 422

        blank_project_payload = dict(valid_payload)
        blank_project_payload["id"] = str(uuid4())
        blank_project_payload["project"] = "   "
        blank_project_response = client.post("/memories", json=blank_project_payload)
        assert blank_project_response.status_code == 422

        invalid_date_payload = dict(valid_payload)
        invalid_date_payload["id"] = str(uuid4())
        invalid_date_payload["created_at"] = "fecha-mala"
        invalid_date_response = client.post("/memories", json=invalid_date_payload)
        assert invalid_date_response.status_code == 422

        invalid_chat_response = client.post(
            "/chat",
            json={"user_id": "user-1", "message": "   ", "save_interaction": False},
        )
        assert invalid_chat_response.status_code == 422


if __name__ == "__main__":
    run()
