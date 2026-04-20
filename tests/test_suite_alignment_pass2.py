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


def _seed_default_state():
    _chat("Guardar: mi color favorito es azul")
    _chat("Corrijo: antes era azul, ahora es verde")
    _chat("El color favorito de Pedro es negro")
    _chat("El color favorito de Martina es rojo")
    _chat("Guardar: COC debe consultar memoria antes de responder")
    _chat("Guardar: si no hay memoria suficiente, debe pedir un dato adicional y no inventar")


def test_language_difficult_queries_for_current_and_previous_value():
    _clear()
    _seed_default_state()

    current_cases = [
        "Antes era azul, ahora no. ¿Cuál queda vigente?",
        "¿Y eso que te corregí ayer, al final en qué quedó?",
        "No me hace falta el detalle entero, solo qué quedó vigente.",
    ]
    for question in current_cases:
        body = _chat(question)
        assert body["mode"] == "answer"
        assert "verde" in body["answer"].lower()
        assert "azul" not in body["answer"].lower()

    previous_cases = [
        "¿Qué color tenía guardado antes del cambio?",
        "El valor anterior del color, ¿cuál era?",
    ]
    for question in previous_cases:
        body = _chat(question)
        assert body["mode"] == "answer"
        assert "azul" in body["answer"].lower()


def test_policy_questions_with_human_language():
    _clear()
    _seed_default_state()

    for question in [
        "Ya sabes, lo de no inventar, ¿sigue igual?",
        "Con todo lo anterior, ¿qué debería responderse?",
        "Se sobreentiende que hablo del proyecto actual. ¿Qué regla rige?",
    ]:
        body = _chat(question)
        text = body["answer"].lower()
        assert body["mode"] == "answer"
        assert "consult" in text or "leer memoria" in text
        assert "no invent" in text


def test_user_only_summary_and_name_isolation():
    _clear()
    _seed_default_state()

    summary = _chat("Lo de Pedro era una cosa y lo mío otra. ¿Qué recuerdas de mí?")
    text = summary["answer"].lower()
    assert summary["mode"] == "answer"
    assert "verde" in text
    assert "negro" not in text
    assert "rojo" not in text

    pair = _chat("¿Qué color quedó para mí y cuál para Pedro?")
    pair_text = pair["answer"].lower()
    assert pair["mode"] == "answer"
    assert "verde" in pair_text
    assert "negro" in pair_text


def test_provider_greeting_and_priority_more_human_queries():
    _clear()
    _chat("Crear memoria: mi proveedor preferido es taller norte")
    _chat("Guardar: la forma de saludo preferida es directa")
    _chat("Guardar nota: el proyecto prioritario actual es memoria-guia")

    provider = _chat("¿Con qué taller prefiero trabajar?")
    assert provider["mode"] == "answer"
    assert "taller norte" in provider["answer"].lower()

    provider2 = _chat("Lo del proveedor habitual, ¿cuál era?")
    assert provider2["mode"] == "answer"
    assert "taller norte" in provider2["answer"].lower()

    greeting = _chat("Mi preferencia de saludo, ¿cuál tienes anotada?")
    assert greeting["mode"] == "answer"
    assert "directa" in greeting["answer"].lower()

    priority = _chat("¿Qué prioridad tengo yo, no mi equipo?")
    assert priority["mode"] == "answer"
    assert "memoria-guia" in priority["answer"].lower()


def test_control_answers_for_do_not_store_and_identity_mix():
    _clear()
    _seed_default_state()

    ignored = _chat("Lo que te dije que no guardaras, ¿lo sigues ignorando?")
    assert ignored["mode"] == "answer"
    assert "ignor" in ignored["answer"].lower() or "no lo voy a guardar" in ignored["answer"].lower() or "no lo guard" in ignored["answer"].lower()

    isolation = _chat("No te confundas entre Martin y Martina.")
    assert isolation["mode"] == "answer"
    assert "separad" in isolation["answer"].lower() or "mezclar" in isolation["answer"].lower()
