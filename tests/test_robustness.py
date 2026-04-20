from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def test_paraphrase_favorite_color():
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Me gusta el color azul"},
    )

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )
    body = ask.json()
    assert body["mode"] == "answer"
    assert "azul" in body["answer"].lower()


def test_paraphrase_favorite_food():
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "Anotá que mi comida preferida es la pizza"},
    )

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Qué me gusta comer?"},
    )
    body = ask.json()
    assert body["mode"] == "answer"
    assert "pizza" in body["answer"].lower()


def test_negative_statement_is_not_stored_for_color():
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "No me gusta el color azul"},
    )

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )
    body = ask.json()
    assert body["mode"] == "insufficient_memory"


def test_negative_statement_is_not_stored_for_food():
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "No me gusta comer pizza"},
    )

    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi comida favorita?"},
    )
    body = ask.json()
    assert body["mode"] == "insufficient_memory"
