from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def test_project_summary_is_natural_and_without_pipes():
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
            "message": "¿Qué recuerdas de este proyecto?",
        },
    )
    body = response.json()
    assert body["mode"] == "answer"
    assert "|" not in body["answer"]
    assert "Recuerdo esto de este proyecto:" in body["answer"]
    assert "- user_id: martin." in body["answer"]
    assert "- project: memoria-guia." in body["answer"]
