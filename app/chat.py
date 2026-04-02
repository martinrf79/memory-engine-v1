from typing import Annotated, Optional
import re
import unicodedata

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from app.firestore_store import chat_events_collection
from app.llm_service import get_user_llm_settings
from app.semantic_memory import (
    extract_structured_memory,
    is_project_memory,
    is_user_memory,
    query_active_semantic_memories,
    upsert_semantic_memory,
)
from app.utils import new_memory_id, utc_now_iso

router = APIRouter()

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class ChatRequest(BaseModel):
    user_id: NonEmptyStr
    message: NonEmptyStr
    project: OptionalNonEmptyStr = None
    book_id: OptionalNonEmptyStr = None
    save_interaction: bool = True


class UsedMemory(BaseModel):
    id: str
    summary: str


class ChatResponse(BaseModel):
    mode: str
    answer: str
    used_memories: list[UsedMemory]
    options: list[str] = Field(default_factory=list)


def normalize_text(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFD", value.lower())
        if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.split())


def _contains_any(text: str, phrases: list[str]) -> bool:
    return any(phrase in text for phrase in phrases)


def _looks_like_question(text: str) -> bool:
    return "?" in text or _contains_any(
        text,
        [
            "que ",
            "cual ",
            "como ",
            "cuando ",
            "debo ",
            "hay ",
            "recuerdas ",
            "sabes ",
        ],
    )


def _asks_what_to_do(text: str) -> bool:
    return _contains_any(
        text,
        [
            "que debo hacer",
            "que hay que hacer",
            "que hacer",
            "debo hacer",
            "hay que hacer",
            "como debo actuar",
            "como tengo que actuar",
        ],
    )


def _asks_memory_summary(text: str) -> bool:
    return _contains_any(
        text,
        [
            "que recuerdas",
            "que sabes",
            "que tenes en memoria",
            "que tienes en memoria",
            "responde solo con lo que realmente tengas en memoria",
        ],
    )


def _guess_query_target(message: str) -> Optional[tuple[str, str]]:
    text = normalize_text(message)

    if ("user_id" in text and "project" in text and "prueba" in text) or _contains_any(
        text,
        [
            "configuracion de pruebas",
            "configuracion de test",
            "user_id y project de pruebas",
            "user_id y project del test",
        ],
    ):
        return ("test_config", "user_id_project")

    if _contains_any(
        text,
        [
            "deba evitar",
            "evitar al probar",
            "algo importante que deba evitar",
            "que debo evitar",
            "que hay que evitar",
        ],
    ):
        return ("test_rule", "avoidances")

    if (
        _asks_what_to_do(text)
        and _contains_any(
            text,
            [
                "falta informacion",
                "falta memoria",
                "falta dato",
                "si no tienes informacion suficiente",
                "si no tenes informacion suficiente",
                "si no hay suficiente informacion",
            ],
        )
    ):
        return ("test_rule", "ask_for_missing_data")

    if (
        _asks_what_to_do(text)
        and _contains_any(
            text,
            [
                "hay ambiguedad",
                "si hay ambiguedad",
                "consulta ambigua",
                "si la consulta es ambigua",
                "si es ambiguo",
            ],
        )
    ):
        return ("test_rule", "ask_clarification_on_ambiguity")

    if _asks_what_to_do(text) and _contains_any(
        text,
        [
            "no invent",
            "inventar",
        ],
    ):
        return ("test_rule", "do_not_invent")

    asks_project = _contains_any(
        text,
        [
            "sobre el proyecto",
            "de este proyecto",
            "sobre memoria-guia",
            "del proyecto memoria-guia",
        ],
    )
    asks_user = _contains_any(
        text,
        [
            "sobre mi",
            "de mi",
            "sobre martin",
            "del usuario martin",
        ],
    )

    if _asks_memory_summary(text) and asks_project and asks_user:
        return ("scoped", "summary")

    if _asks_memory_summary(text) and asks_project:
        return ("project", "summary")

    if _asks_memory_summary(text) and asks_user:
        return ("user", "summary")

    if "color favorito" in text:
        return ("user", "favorite_color")

    if "comida favorita" in text:
        return ("user", "favorite_food")

    return None


def retrieve_semantic_memories(payload: ChatRequest) -> list[dict]:
    return query_active_semantic_memories(payload.user_id, payload.project, payload.book_id)


def _memory_to_used(memory: dict) -> UsedMemory:
    summary = f"{memory.get('entity')}.{memory.get('attribute')}={memory.get('value_text')}"
    return UsedMemory(id=memory["id"], summary=summary)


def _dedupe_active_memories(memories: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}

    for memory in memories:
        key = memory.get("dedupe_key") or memory["id"]
        current = by_key.get(key)

        if not current:
            by_key[key] = memory
            continue

        current_version = int(current.get("version") or 1)
        new_version = int(memory.get("version") or 1)

        if new_version >= current_version:
            by_key[key] = memory

    return list(by_key.values())


def _render_summary_answer(memories: list[dict], intro: str) -> dict:
    scoped = _dedupe_active_memories(memories)

    if not scoped:
        return {
            "mode": "insufficient_memory",
            "answer": "Todavía no tengo recuerdos útiles para responder eso. ¿Querés que guarde alguno ahora?",
            "used_memories": [],
            "options": ["Sí, guardar ahora", "No por ahora"],
        }

    lines = []
    for memory in sorted(
        scoped,
        key=lambda item: (
            item.get("entity", ""),
            item.get("attribute", ""),
            item.get("value_text", ""),
        ),
    ):
        value = (memory.get("value_text") or "").strip()
        if not value:
            continue
        lines.append(f"{memory.get('attribute')}: {value}")

    answer = intro
    if lines:
        answer += " " + " | ".join(lines[:5])

    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped[:10]]
    return {
        "mode": "answer",
        "answer": answer,
        "used_memories": used_memories,
        "options": [],
    }


def _build_test_config_answer(memories: list[dict]) -> dict:
    user_candidates = [m for m in memories if m.get("entity") == "test_config" and m.get("attribute") == "user_id"]
    project_candidates = [m for m in memories if m.get("entity") == "test_config" and m.get("attribute") == "project"]

    if not user_candidates or not project_candidates:
        return {
            "mode": "insufficient_memory",
            "answer": "Me falta configuración de pruebas. ¿Querés indicar user_id y project?",
            "used_memories": [],
            "options": ["user_id=... y project=...", "No por ahora"],
        }

    user_value = sorted({x.get("value_text") for x in user_candidates if x.get("value_text")})[0]
    project_value = sorted({x.get("value_text") for x in project_candidates if x.get("value_text")})[0]

    used_memories = [
        _memory_to_used(memory).model_dump()
        for memory in (user_candidates[:1] + project_candidates[:1])
    ]

    return {
        "mode": "answer",
        "answer": f"La configuración de pruebas es user_id={user_value} y project={project_value}.",
        "used_memories": used_memories,
        "options": [],
    }


def _build_avoidances_answer(memories: list[dict]) -> dict:
    scoped = [m for m in _dedupe_active_memories(memories) if m.get("entity") == "test_rule"]

    if not scoped:
        return {
            "mode": "insufficient_memory",
            "answer": "No tengo reglas de prueba guardadas todavía. ¿Querés que las cargue ahora?",
            "used_memories": [],
            "options": ["Sí, cargar reglas", "No por ahora"],
        }

    facts = {memory.get("attribute"): memory.get("value_text") for memory in scoped}
    parts = []

    if "avoid_user_id_default" in facts:
        parts.append("evitá usar user_id=default")
    if "do_not_invent" in facts:
        parts.append("no inventes datos")
    if "ask_for_missing_data" in facts:
        parts.append("si falta información, pedila")
    if "ask_clarification_on_ambiguity" in facts:
        parts.append("si hay ambigüedad, pedí aclaración")

    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped[:10]]
    answer = "Sí. " + ", ".join(parts) + "."

    return {
        "mode": "answer",
        "answer": answer,
        "used_memories": used_memories,
        "options": [],
    }


def _build_specific_test_rule_answer(memories: list[dict], attribute: str) -> dict:
    scoped = [
        m
        for m in _dedupe_active_memories(memories)
        if m.get("entity") == "test_rule" and m.get("attribute") == attribute
    ]

    if not scoped:
        return {
            "mode": "insufficient_memory",
            "answer": "No tengo esa regla guardada todavía.",
            "used_memories": [],
            "options": [],
        }

    templates = {
        "ask_for_missing_data": "Si falta información, pedila.",
        "ask_clarification_on_ambiguity": "Si hay ambigüedad, pedí aclaración.",
        "do_not_invent": "No inventes datos.",
        "avoid_user_id_default": "Evitá usar user_id=default.",
    }

    answer = templates.get(attribute) or (scoped[0].get("value_text") or "Sí.")
    if answer[-1] not in ".!?":
        answer += "."

    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped[:10]]

    return {
        "mode": "answer",
        "answer": answer,
        "used_memories": used_memories,
        "options": [],
    }


def _build_value_answer(scoped_memories: list[dict], entity: str, attribute: str) -> dict:
    candidates = [
        m
        for m in scoped_memories
        if m.get("entity") == entity and m.get("attribute") == attribute
    ]

    used_memories = [_memory_to_used(memory).model_dump() for memory in candidates]

    if not candidates:
        question = "No tengo ese dato todavía. ¿Querés decirme tu color favorito?"
        if attribute == "favorite_food":
            question = "No tengo ese dato todavía. ¿Querés decirme tu comida favorita?"
        return {
            "mode": "insufficient_memory",
            "answer": question,
            "used_memories": [],
            "options": ["Sí, te lo digo ahora", "No por ahora"],
        }

    unique_values = sorted(
        {(m.get("value_text") or "").strip() for m in candidates if m.get("value_text")}
    )

    if len(unique_values) > 1:
        options = [f"{idx}) {value}" for idx, value in enumerate(unique_values, start=1)]
        return {
            "mode": "clarification_required",
            "answer": "Encontré más de una opción. ¿Querés elegir una?",
            "used_memories": used_memories,
            "options": options,
        }

    value = unique_values[0]
    if attribute == "favorite_color":
        answer = f"Tu color favorito es {value}."
    elif attribute == "favorite_food":
        answer = f"Tu comida favorita es {value}."
    else:
        answer = f"Tu {attribute} es {value}."

    return {
        "mode": "answer",
        "answer": answer,
        "used_memories": used_memories,
        "options": [],
    }


def build_chat_result(payload: ChatRequest, memories: list[dict]) -> dict:
    target = _guess_query_target(payload.message or "")
    scoped_memories = _dedupe_active_memories(memories)
    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped_memories]

    if not target:
        return {
            "mode": "clarification_required",
            "answer": "¿Qué dato querés que recuerde o consulte?",
            "used_memories": used_memories,
            "options": ["Color favorito", "Comida favorita", "Configuración de pruebas"],
        }

    entity, attribute = target

    if entity == "scoped" and attribute == "summary":
        return _render_summary_answer(scoped_memories, "Recuerdo esto en este contexto:")

    if entity == "project" and attribute == "summary":
        project_memories = [m for m in scoped_memories if is_project_memory(m)]
        return _render_summary_answer(project_memories, "Recuerdo esto de este proyecto:")

    if entity == "user" and attribute == "summary":
        user_memories = [m for m in scoped_memories if is_user_memory(m)]
        return _render_summary_answer(user_memories, "Recuerdo esto sobre vos en este proyecto:")

    if entity == "test_config" and attribute == "user_id_project":
        return _build_test_config_answer(scoped_memories)

    if entity == "test_rule" and attribute == "avoidances":
        return _build_avoidances_answer(scoped_memories)

    if entity == "test_rule" and attribute in {
        "ask_for_missing_data",
        "ask_clarification_on_ambiguity",
        "do_not_invent",
        "avoid_user_id_default",
    }:
        return _build_specific_test_rule_answer(scoped_memories, attribute)

    return _build_value_answer(scoped_memories, entity, attribute)


def save_chat_event(payload: ChatRequest, answer_text: str) -> str:
    settings = get_user_llm_settings(payload.user_id)
    event_id = new_memory_id()

    chat_events_collection.document(event_id).set(
        {
            "id": event_id,
            "user_id": payload.user_id,
            "project": payload.project or "general",
            "book_id": payload.book_id or "general",
            "user_message": payload.message,
            "assistant_answer": answer_text,
            "llm_provider": settings.provider,
            "llm_model": settings.model_name,
            "created_at": utc_now_iso(),
            "ttl_at": None,
        }
    )

    return event_id


def maybe_store_semantic_memory(
    payload: ChatRequest,
    source_event_id: Optional[str],
    extracted=None,
) -> None:
    extracted = extracted or extract_structured_memory(payload.message)
    if not extracted:
        return

    source_id = source_event_id or f"nosave-{new_memory_id()}"

    upsert_semantic_memory(
        user_id=payload.user_id,
        project=payload.project or "general",
        book_id=payload.book_id or "general",
        extracted=extracted,
        source_event_id=source_id,
    )


def _acknowledgement_for_memory(extracted) -> str:
    if extracted.entity == "user" and extracted.attribute == "favorite_color":
        return f"Listo, guardé que tu color favorito es {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "favorite_food":
        return f"Listo, guardé que tu comida favorita es {extracted.value_text}."
    return "Listo, lo guardé."


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    extracted = extract_structured_memory(payload.message)
    normalized_message = normalize_text(payload.message)
    is_statement = (
        extracted is not None
        and not _looks_like_question(normalized_message)
    )

    if is_statement:
        answer = _acknowledgement_for_memory(extracted)
        result = {"mode": "answer", "answer": answer, "used_memories": [], "options": []}
        event_id = save_chat_event(payload, answer)
        maybe_store_semantic_memory(payload, source_event_id=event_id, extracted=extracted)
        return result

    memories = retrieve_semantic_memories(payload)
    result = build_chat_result(payload, memories)
    event_id = save_chat_event(payload, result["answer"])
    maybe_store_semantic_memory(payload, source_event_id=event_id, extracted=extracted)
    return result
