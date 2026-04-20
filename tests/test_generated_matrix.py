import pytest
from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


COLOR_STATEMENTS = [
    "Mi color favorito es azul",
    "Mi color favorito es azul.",
    "Mi color favorito es azul!",
    "Me gusta el color azul",
    "Anotá que mi color favorito es azul",
]
COLOR_QUESTIONS = [
    "¿Cuál es mi color favorito?",
    "¿Qué color me gusta?",
    "¿Qué color prefiero?",
]
FOOD_STATEMENTS = [
    "Mi comida favorita es pizza",
    "Mi comida favorita es pizza.",
    "Mi comida favorita es pizza!",
    "Me gusta comer pizza",
    "Anotá que mi comida preferida es pizza",
]
FOOD_QUESTIONS = [
    "¿Cuál es mi comida favorita?",
    "¿Qué me gusta comer?",
    "¿Qué comida prefiero?",
]
NEGATIVE_COLOR_STATEMENTS = [
    "No me gusta el color azul",
    "Hoy no me gusta el color azul",
    "Anotá que no me gusta el color azul",
]
NEGATIVE_FOOD_STATEMENTS = [
    "No me gusta comer pizza",
    "Hoy no me gusta comer pizza",
    "Anotá que no me gusta comer pizza",
]


@pytest.mark.parametrize("statement", COLOR_STATEMENTS)
@pytest.mark.parametrize("question", COLOR_QUESTIONS)
def test_generated_color_matrix(statement: str, question: str):
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": statement},
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": question},
    )
    body = ask.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Tu color favorito es azul."


@pytest.mark.parametrize("statement", FOOD_STATEMENTS)
@pytest.mark.parametrize("question", FOOD_QUESTIONS)
def test_generated_food_matrix(statement: str, question: str):
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": statement},
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": question},
    )
    body = ask.json()
    assert body["mode"] == "answer"
    assert body["answer"] == "Tu comida favorita es pizza."


@pytest.mark.parametrize("statement", NEGATIVE_COLOR_STATEMENTS)
def test_generated_negative_color_matrix(statement: str):
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": statement},
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi color favorito?"},
    )
    body = ask.json()
    assert body["mode"] == "insufficient_memory"


@pytest.mark.parametrize("statement", NEGATIVE_FOOD_STATEMENTS)
def test_generated_negative_food_matrix(statement: str):
    _clear_collections()
    client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": statement},
    )
    ask = client.post(
        "/chat",
        json={"user_id": "u1", "project": "p1", "book_id": "b1", "message": "¿Cuál es mi comida favorita?"},
    )
    body = ask.json()
    assert body["mode"] == "insufficient_memory"
