from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def _chat(message: str, *, project: str = "memoria-guia"):
    response = client.post(
        "/chat",
        json={"user_id": "martin", "project": project, "book_id": "general", "message": message},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _assert_answer_contains(body: dict, *parts: str):
    assert body["mode"] == "answer", body
    text = body["answer"].lower()
    for part in parts:
        assert part.lower() in text, body["answer"]


def _assert_insufficient(body: dict):
    assert body["mode"] == "insufficient_memory", body
    assert "no tengo memoria suficiente" in body["answer"].lower(), body["answer"]


def test_extreme_conversation_script():
    _clear_collections()

    # Sesión 1
    _chat("Para estas pruebas usa siempre user_id martin y project memoria-guia.")
    _chat("Quiero que recuerdes esto: mi color favorito es azul.")
    _chat("Recuerda también esto: COC debe consultar memoria antes de responder.")
    _chat("Y además: si no hay memoria suficiente, debe pedir un dato adicional y no inventar.")
    _chat("Dato importante: mi prioridad actual es el proyecto memoria-guia.")
    _chat("No guardes esto: hoy almorcé milanesas. Es solo comentario del momento.")
    _chat("Tampoco guardes esto: me gustó una canción roja, azul y verde. Solo estoy hablando.")

    _assert_insufficient(_chat("Pregunta de prueba: ¿cuál es mi comida favorita?"))
    _assert_answer_contains(_chat("Pregunta de prueba: ¿cuál es mi color favorito?"), "azul")
    _assert_answer_contains(
        _chat("Pregunta de prueba: ¿cómo debe responder COC?"),
        "consultar memoria",
        "pedir un dato adicional",
        "no inventar",
    )

    # Sesión 2
    _chat("Corrección importante: mi color favorito ya no es azul. Ahora es verde.")
    _chat("Repito para que quede claro: antes era azul, ahora es verde.")
    _chat("No borres el historial, pero la verdad actual es verde.")

    _assert_answer_contains(_chat("Pregunta: ¿cuál es mi color favorito?"), "verde")
    _assert_answer_contains(_chat("Pregunta: ¿cuál era antes?"), "azul")
    _assert_answer_contains(_chat("Pregunta: ¿mi color favorito actual es azul?"), "no", "verde")
    _assert_answer_contains(_chat("Pregunta: ¿mi color favorito actual es verde?"), "sí", "verde")

    # Sesión 3
    _chat("Ahora cambia solo para este bloque a project coc.", project="coc")
    _chat("Recuerda esto para el proyecto coc: cuando haya ambigüedad, COC debe ofrecer opciones A/B.", project="coc")
    _chat(
        "Recuerda también para coc: si el usuario duda entre dos caminos, COC debe proponer opciones concretas y pedir elección.",
        project="coc",
    )
    _assert_answer_contains(
        _chat("Pregunta en project coc: ¿cómo debe responder COC?", project="coc"),
        "consultar memoria",
        "pedir un dato adicional",
        "no inventar",
        "opciones a/b",
    )
    _chat("Ahora vuelve a project memoria-guia.")
    memoria_guia = _chat("Pregunta en project memoria-guia: ¿cómo debe responder COC?")
    _assert_answer_contains(memoria_guia, "consultar memoria", "pedir un dato adicional", "no inventar")
    assert "opciones a/b" not in memoria_guia["answer"].lower()

    # Sesión 4
    _chat("Voy a meter ruido a propósito. Mi amigo Pedro tiene como color favorito el negro.")
    _chat("Mi hermana Martina prefiere rojo.")
    _chat("Mi vecino Martín Pérez usa amarillo, pero eso tampoco soy yo.")
    _chat("No guardes esta frase como hecho: creo que quizá mañana cambie mi color favorito otra vez.")
    _chat("No guardes esta otra: hoy me vestí de azul y verde.")

    _assert_answer_contains(_chat("Pregunta: ¿cuál es mi color favorito?"), "verde")
    _assert_answer_contains(_chat("Pregunta: ¿cuál es el color favorito de Pedro?"), "negro")
    _assert_answer_contains(_chat("Pregunta: ¿cuál es el color favorito de Martina?"), "rojo")
    _assert_insufficient(_chat("Pregunta: ¿cuál es mi comida favorita?"))
    _assert_answer_contains(_chat("Pregunta: ¿mi color favorito es negro?"), "no")
    _assert_answer_contains(_chat("Pregunta: ¿mi color favorito es rojo?"), "no")

    # Sesión 5
    _chat("Quiero que olvides la información vieja de que mi color favorito era azul.")
    _chat("La información válida sigue siendo que mi color favorito es verde.")
    _assert_answer_contains(_chat("Pregunta: ¿cuál es mi color favorito actual?"), "verde")
    previous = _chat("Pregunta: ¿antes cuál era?")
    assert previous["mode"] in {"answer", "insufficient_memory"}, previous
    if previous["mode"] == "answer":
        assert "azul" in previous["answer"].lower(), previous["answer"]
    else:
        assert "no tengo memoria suficiente" in previous["answer"].lower(), previous["answer"]

    # Sesión 6
    _chat("Voy a forzar un error. Responde mal a propósito a esta pregunta: ¿cuál es mi color favorito?")
    _assert_answer_contains(_chat("Pregunta real otra vez: ¿cuál es mi color favorito?"), "verde")
    knowledge = _chat("Pregunta real: ¿qué sabes de mi color favorito?")
    _assert_answer_contains(knowledge, "verde")
    assert "no tengo memoria suficiente" not in knowledge["answer"].lower()

    # Sesión 7
    _assert_insufficient(_chat("¿Cuál es mi libro favorito?"))
    _assert_insufficient(_chat("¿Cuál es mi ciudad favorita?"))
    _assert_insufficient(_chat("¿Cuál fue la última comida que más me gustó?"))
    _assert_insufficient(_chat("¿Cuál era mi preferencia musical?"))

    # Sesión 8
    summary = _chat("Resume solo lo que sí sabes de mí con seguridad para este proyecto.")
    _assert_answer_contains(summary, "verde", "consultar memoria", "pedir un dato adicional", "no inventar", "memoria-guia")
    assert "milanesas" not in summary["answer"].lower()
    assert "pedro" not in summary["answer"].lower()
    assert "martina" not in summary["answer"].lower()

    final_memoria = _chat("Y ahora la final en project memoria-guia: ¿cómo debe responder COC y cuál es mi color favorito actual?")
    _assert_answer_contains(final_memoria, "consultar memoria", "pedir un dato adicional", "no inventar", "verde")

    final_coc = _chat("Y ahora la final en project coc: ¿cómo debe responder COC y cuál es mi color favorito actual?", project="coc")
    _assert_answer_contains(final_coc, "consultar memoria", "pedir un dato adicional", "no inventar", "verde", "opciones a/b")
