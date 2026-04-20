from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def _chat(message: str, *, project: str = "memoria-guia") -> dict:
    response = client.post(
        "/chat",
        json={"user_id": "martin", "project": project, "book_id": "general", "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_color_fuzzy_queries_and_history():
    _clear()
    _chat("Guardar: mi color favorito es azul")
    _chat("Corrijo: antes era azul, ahora es verde")

    body = _chat("Lo del color mío, ¿cómo quedó?")
    assert body["mode"] == "answer"
    assert "verde" in body["answer"].lower()

    previous = _chat("¿Y cuál era antes?")
    assert previous["mode"] == "answer"
    assert "azul" in previous["answer"].lower()


def test_provider_and_greeting_are_stored_and_retrieved():
    _clear()
    _chat("Crear memoria: mi proveedor preferido es taller norte")
    _chat("Guardar: la forma de saludo preferida es directa")

    provider = _chat("Mi proveedor, no el de Martina.")
    assert provider["mode"] == "answer"
    assert "taller norte" in provider["answer"].lower()

    greeting = _chat("¿Qué saludo prefiero yo?")
    assert greeting["mode"] == "answer"
    assert "directa" in greeting["answer"].lower()


def test_provider_correction_replaces_current_value():
    _clear()
    _chat("Crear memoria: mi proveedor preferido es taller norte")
    _chat("Me expresé mal recién; no era taller norte sino taller sur")

    provider = _chat("¿Cuál es mi proveedor preferido actual?")
    assert provider["mode"] == "answer"
    text = provider["answer"].lower()
    assert "taller sur" in text
    assert "taller norte" not in text


def test_priority_project_can_be_saved_and_answered():
    _clear()
    _chat("Guardar nota: el proyecto prioritario actual es memoria-guia")

    response = _chat("¿Qué proyecto prioritario tengo yo?")
    assert response["mode"] == "answer"
    assert "memoria-guia" in response["answer"].lower()


def test_noise_marked_as_do_not_store_does_not_create_false_food_memory():
    _clear()
    _chat("No guardes esto: hoy almorcé milanesas")
    response = _chat("¿Cuál es mi comida favorita?")
    assert response["mode"] == "insufficient_memory"
    assert "milanesas" not in response["answer"].lower()
