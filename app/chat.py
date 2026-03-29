from typing import Annotated, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from app.firestore_store import chat_events_collection
from app.llm_service import get_user_llm_settings
from app.semantic_memory import (
    extract_structured_memory,
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


def _guess_query_target(message: str) -> Optional[tuple[str, str]]:
    text = message.lower()
    if "que recuerdas de este proyecto" in text or "qué recuerdas de este proyecto" in text:
        return ("project", "summary")
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


def _build_project_context_answer(memories: list[dict]) -> dict:
    scoped = _dedupe_active_memories(memories)
    if not scoped:
        return {
            "mode": "insufficient_memory",
            "answer": "Todavía no tengo recuerdos útiles de este proyecto. ¿Querés que guarde alguno ahora?",
            "used_memories": [],
            "options": ["Sí, guardar ahora", "No por ahora"],
        }

    grouped = {}
    for memory in scoped:
        grouped.setdefault(memory.get("attribute"), set()).add(memory.get("value_text"))

    lines = []
    for attribute, values in sorted(grouped.items()):
        clean_values = ", ".join(sorted(v for v in values if v))
        if clean_values:
            lines.append(f"{attribute}: {clean_values}")

    answer = "Recuerdo esto de este proyecto: " + " | ".join(lines[:5])
    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped[:10]]
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
            "options": ["Color favorito", "Comida favorita"],
        }

    entity, attribute = target
    if entity == "project" and attribute == "summary":
        return _build_project_context_answer(scoped_memories)

    candidates = [m for m in scoped_memories if m.get("entity") == entity and m.get("attribute") == attribute]
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

    unique_values = sorted({(m.get("value_text") or "").strip() for m in candidates if m.get("value_text")})
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


def maybe_store_semantic_memory(payload: ChatRequest, source_event_id: str) -> None:
    extracted = extract_structured_memory(payload.message)
    if not extracted:
        return

    upsert_semantic_memory(
        user_id=payload.user_id,
        project=payload.project or "general",
        book_id=payload.book_id or "general",
        extracted=extracted,
        source_event_id=source_event_id,
    )


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    memories = retrieve_semantic_memories(payload)
    result = build_chat_result(payload, memories)
    event_id = save_chat_event(payload, result["answer"])
    maybe_store_semantic_memory(payload, source_event_id=event_id)
    return result
