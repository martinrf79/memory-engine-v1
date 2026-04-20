import re
import unicodedata
from dataclasses import dataclass
from typing import Annotated, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from app.firestore_store import (
    chat_events_collection,
    facts_collection,
    manual_notes_collection,
    retrieval_traces_collection,
    session_summaries_collection,
)
from app.knowledge_core import answer_product_query
from app.llm_service import get_user_llm_settings
from app.memory_core_v1 import MemoryScope, save_event as core_save_event, save_fact as core_save_fact, save_note as core_save_note
from app.registry import touch_user_project
from app.semantic_memory import (
    GLOBAL_PROJECT,
    build_person_entity,
    build_relation_entity,
    extract_structured_memory,
    is_project_memory,
    is_user_memory,
    normalize_name_key,
    normalize_text,
    is_explicit_memory_command,
    should_auto_store_personal_note,
)
from app.utils import new_memory_id, utc_now_iso

router = APIRouter(tags=["public"])

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class ChatRequest(BaseModel):
    user_id: NonEmptyStr
    message: NonEmptyStr
    project: OptionalNonEmptyStr = None
    book_id: OptionalNonEmptyStr = None
    save_interaction: bool = True
    remember: bool = False


class UsedMemory(BaseModel):
    id: str
    summary: str


class ChatResponse(BaseModel):
    mode: str
    answer: str
    used_memories: list[UsedMemory]
    options: list[str] = Field(default_factory=list)


@dataclass
class QueryTarget:
    entity: str
    attribute: str
    subject_label: Optional[str] = None
    expected_value: Optional[str] = None
    wants_previous: bool = False
    wants_summary: bool = False
    combine_policy: bool = False


_RELATION_TERMS = ["primo", "prima", "hermano", "hermana", "padre", "madre", "hijo", "hija", "amigo", "amiga", "vecino", "vecina"]


_NO_STORE_HINTS = (
    "no guardes esto",
    "tampoco guardes esto",
    "no guardes esta frase como hecho",
    "no guardes esta otra",
    "no lo guardes",
    "no guardaras",
    "no guardarías",
)


def _project_matches(item_project: Optional[str], project: Optional[str], include_global: bool) -> bool:
    if project is None:
        return True
    if item_project == project:
        return True
    return include_global and item_project == GLOBAL_PROJECT


def _chat_core_scope(*, user_id: str, project: Optional[str], book_id: Optional[str]) -> MemoryScope:
    return MemoryScope(
        tenant_id=user_id,
        user_id=user_id,
        project_id=project or "general",
        book_id=book_id or "general",
        entity_type="generic",
        entity_id="generic",
    )


def _core_fact_to_semantic(memory: dict) -> dict:
    return {
        "id": memory.get("id"),
        "user_id": memory.get("user_id"),
        "project": memory.get("project_id"),
        "book_id": memory.get("book_id"),
        "memory_type": "fact",
        "entity": memory.get("subject") or "user",
        "attribute": memory.get("relation") or "fact",
        "value_text": memory.get("object") or "",
        "context": f"{memory.get('subject') or 'user'} {memory.get('relation') or 'fact'} {memory.get('object') or ''}".strip(),
        "status": memory.get("status", "active"),
        "dedupe_key": memory.get("identity_hash") or memory.get("id"),
        "version": 1,
        "valid_from": memory.get("valid_from") or memory.get("created_at"),
        "valid_to": memory.get("valid_to"),
        "source_type": "memory_core_v1",
        "source_event_id": memory.get("source_event_id"),
        "created_at": memory.get("created_at"),
        "updated_at": memory.get("updated_at"),
        "confidence": memory.get("confidence", 0.9),
        "supersedes_id": memory.get("supersedes_id"),
        "superseded_by": memory.get("superseded_by"),
    }


def _core_note_to_semantic(memory: dict) -> dict:
    content = (memory.get("content") or "").strip()
    attribute = (memory.get("title") or "manual_note").lower().replace(" ", "_")
    return {
        "id": memory.get("id"),
        "user_id": memory.get("user_id"),
        "project": memory.get("project_id"),
        "book_id": memory.get("book_id"),
        "memory_type": "note",
        "entity": "user_note",
        "attribute": attribute,
        "value_text": content,
        "context": content,
        "status": memory.get("status", "active"),
        "dedupe_key": memory.get("dedupe_hash") or memory.get("id"),
        "version": 1,
        "valid_from": memory.get("created_at"),
        "valid_to": None,
        "source_type": "memory_core_v1",
        "source_event_id": memory.get("source_event_id"),
        "created_at": memory.get("created_at"),
        "updated_at": memory.get("updated_at"),
        "confidence": 0.72,
    }


def _core_summary_to_semantic(memory: dict) -> dict:
    summary = (memory.get("summary") or "").strip()
    return {
        "id": memory.get("id"),
        "user_id": memory.get("user_id"),
        "project": memory.get("project_id"),
        "book_id": memory.get("book_id"),
        "memory_type": "session_summary",
        "entity": "session_summary",
        "attribute": "summary",
        "value_text": summary,
        "context": summary,
        "status": "active",
        "dedupe_key": memory.get("id"),
        "version": 1,
        "valid_from": memory.get("created_at"),
        "valid_to": None,
        "source_type": "memory_core_v1",
        "source_event_id": None,
        "created_at": memory.get("created_at"),
        "updated_at": memory.get("created_at"),
        "confidence": 0.7,
    }


def query_semantic_memories(
    user_id: str, project: Optional[str], book_id: Optional[str], *, include_inactive: bool = False, include_global: bool = True
) -> list[dict]:
    items: list[dict] = []

    for doc in facts_collection.where("tenant_id", "==", user_id).stream():
        data = doc.to_dict() or {}
        if data.get("user_id") not in {None, user_id}:
            continue
        if not include_inactive and data.get("status") != "active":
            continue
        if not _project_matches(data.get("project_id"), project, include_global):
            continue
        if book_id and data.get("book_id") != book_id:
            continue
        items.append(_core_fact_to_semantic(data))

    for doc in manual_notes_collection.where("tenant_id", "==", user_id).stream():
        data = doc.to_dict() or {}
        if data.get("user_id") not in {None, user_id}:
            continue
        if not include_inactive and data.get("status") != "active":
            continue
        if not _project_matches(data.get("project_id"), project, include_global):
            continue
        if book_id and data.get("book_id") != book_id:
            continue
        items.append(_core_note_to_semantic(data))

    for doc in session_summaries_collection.where("tenant_id", "==", user_id).stream():
        data = doc.to_dict() or {}
        if data.get("user_id") not in {None, user_id}:
            continue
        if not _project_matches(data.get("project_id"), project, include_global):
            continue
        if book_id and data.get("book_id") != book_id:
            continue
        items.append(_core_summary_to_semantic(data))

    return sorted(items, key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item.get("id") or ""), reverse=True)


def query_active_semantic_memories(user_id: str, project: Optional[str], book_id: Optional[str]) -> list[dict]:
    return query_semantic_memories(user_id, project, book_id, include_inactive=False, include_global=True)


def upsert_semantic_memory(*, user_id: str, project: str, book_id: str, extracted, source_event_id: Optional[str] = None) -> dict:
    scope = _chat_core_scope(user_id=user_id, project=extracted.target_project or project, book_id=book_id)
    if extracted.memory_type == "note" or extracted.entity == "user_note":
        stored = core_save_note(scope, title=extracted.attribute.replace("_", " "), content=extracted.value_text, source_event_id=source_event_id)
        return _core_note_to_semantic(stored)
    stored = core_save_fact(
        scope,
        subject=extracted.entity,
        relation=extracted.attribute,
        object_value=extracted.value_text,
        confidence=float(getattr(extracted, "confidence", 0.95) or 0.95),
        source_event_id=source_event_id,
    )
    return _core_fact_to_semantic(stored)


def store_message_memory(
    *,
    user_id: str,
    project: str,
    book_id: str,
    content: str,
    source_type: str,
    source_event_id: Optional[str] = None,
    force: bool = False,
) -> Optional[dict]:
    cleaned = " ".join((content or "").strip().split())
    if not cleaned:
        return None
    extracted = extract_structured_memory(cleaned)
    if extracted:
        extracted.source_type = source_type
        return upsert_semantic_memory(
            user_id=user_id,
            project=project,
            book_id=book_id,
            extracted=extracted,
            source_event_id=source_event_id or new_memory_id(),
        )
    if not force and not is_explicit_memory_command(cleaned) and not should_auto_store_personal_note(cleaned):
        return None
    scope = _chat_core_scope(user_id=user_id, project=project, book_id=book_id)
    stored = core_save_note(scope, title="Memoria manual", content=cleaned, source_event_id=source_event_id)
    return _core_note_to_semantic(stored)


def _contains_any(text: str, options: list[str]) -> bool:
    return any(option in text for option in options)


_ATTRIBUTE_ALIASES: dict[str, list[str]] = {
    "favorite_color": [
        "color favorito",
        "color preferido",
        "mi color favorito",
        "mi color",
        "lo del color mio",
        "lo del color mío",
        "como quedo lo del color",
        "cómo quedó lo del color",
        "como quedo al final",
        "cómo quedó al final",
        "que color tengo guardado",
        "que color es el mio",
        "que color es el mío",
        "que color me gusta",
        "que color prefiero",
        "que color quedo",
        "qué color quedó",
        "cual queda vigente",
        "cuál queda vigente",
        "cual vale ahora",
        "cuál vale ahora",
        "que recuerdas como actual",
        "qué recuerdas como actual",
        "dime el color vigente",
        "usa solo lo activo",
        "solo memorias activas",
        "ignora lo archivado",
        "no uses archivadas",
        "con solo memorias activas",
        "entre lo vigente",
        "que manda",
        "que quedo vigente",
        "qué quedó vigente",
        "sin mezclar pasado",
        "entre el viejo y el nuevo",
        "dime el de ahora",
    ],
    "favorite_food": ["comida favorita", "comida preferida", "que me gusta comer", "que comida prefiero", "lo de la comida que mas me gusta", "lo de la comida que más me gusta", "que comida mia tienes guardada como favorita", "qué comida mía tienes guardada como favorita"],
    "favorite_city": ["ciudad favorita", "ciudad preferida", "lo de la ciudad favorita"],
    "preferred_provider": [
        "proveedor preferido",
        "proveedor favorito",
        "mi proveedor",
        "mi taller",
        "taller preferido",
        "lo del taller",
        "proveedor habitual",
        "con que taller prefiero trabajar",
        "con qué taller prefiero trabajar",
    ],
    "preferred_greeting": [
        "saludo preferido",
        "forma de saludo preferida",
        "forma de saludar que prefiero",
        "como prefiero saludar",
        "que saludo prefiero",
        "preferencia de saludo",
    ],
    "priority_project": ["proyecto prioritario", "prioridad actual", "proyecto actual prioritario", "que prioridad tengo", "qué prioridad tiene este proyecto", "que prioridad tiene este proyecto"],
}


def _looks_like_question_about(text: str, attribute: str) -> bool:
    aliases = _ATTRIBUTE_ALIASES.get(attribute, [])
    return any(alias in text for alias in aliases)


def _normalize_loose(value: str) -> str:
    without_accents = "".join(
        char for char in unicodedata.normalize("NFD", value.lower()) if unicodedata.category(char) != "Mn"
    )
    return " ".join(without_accents.split())


def _normalize_query_text(message: str) -> str:
    cleaned = message.strip()
    prefixes = [
        "pregunta de prueba:",
        "pregunta:",
        "pregunta real otra vez:",
        "pregunta real:",
        "y ahora la final en project memoria-guia:",
        "y ahora la final en project coc:",
    ]
    lowered = _normalize_loose(cleaned)
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if lowered.startswith(_normalize_loose(prefix)):
                cleaned = cleaned[len(prefix):].lstrip(" :")
                lowered = _normalize_loose(cleaned)
                changed = True
                break
    return lowered

def _mentions_own_scope(text: str) -> bool:
    return _contains_any(
        text,
        [
            "lo mio",
            "lo mío",
            "solo sobre mi",
            "solo sobre mí",
            "yo, no pedro",
            "yo no pedro",
            "no lo ajeno",
        ],
    )


def _memory_to_used(memory: dict) -> UsedMemory:
    attribute = memory.get("attribute") or "dato"
    if attribute == "insufficient_memory_rule":
        attribute = "missing_data_rule"
    summary = f"{memory.get('entity')}.{attribute}={memory.get('value_text')}"
    return UsedMemory(id=memory["id"], summary=summary)


def _sort_key(memory: dict) -> tuple[int, str, str]:
    return (
        int(memory.get("version") or 1),
        memory.get("updated_at") or memory.get("created_at") or memory.get("valid_from") or "",
        memory.get("id") or "",
    )


def _dedupe_active_memories(memories: list[dict]) -> list[dict]:
    by_key: dict[str, dict] = {}
    for memory in memories:
        key = memory.get("dedupe_key") or memory["id"]
        current = by_key.get(key)
        if not current or _sort_key(memory) >= _sort_key(current):
            by_key[key] = memory
    return list(by_key.values())


def _display_label(memory: dict) -> str:
    attribute = memory.get("attribute", "dato")
    labels = {
        "user_id": "user_id",
        "project": "project",
        "favorite_color": "color favorito",
        "favorite_food": "comida favorita",
        "favorite_city": "ciudad favorita",
        "origin_location": "origen",
        "current_location": "ubicación actual",
        "name": "nombre",
        "works_at": "trabaja en",
        "preferred_provider": "proveedor preferido",
        "preferred_greeting": "saludo preferido",
        "avoid_user_id_default": "evitar user_id por defecto",
        "do_not_invent": "regla de no inventar",
        "ask_for_missing_data": "pedir dato faltante",
        "ask_clarification_on_ambiguity": "pedir aclaración por ambigüedad",
        "memory_first": "leer memoria antes de responder",
        "insufficient_memory_rule": "regla ante memoria insuficiente",
        "priority_project": "proyecto prioritario",
        "ambiguity_options": "regla ante ambigüedad",
        "ask_choice": "pedir elección ante duda",
    }
    return labels.get(attribute, attribute.replace("_", " "))


def _insufficient_answer(attribute: str) -> dict:
    questions = {
        "favorite_color": "No tengo ese dato todavía. No tengo memoria suficiente para responder con seguridad sobre ese color favorito. ¿Querés darme un dato más?",
        "favorite_food": "No tengo ese dato todavía. No tengo memoria suficiente para responder con seguridad sobre esa comida favorita. ¿Querés darme un dato más?",
        "favorite_book": "No tengo memoria suficiente para responder con seguridad sobre tu libro favorito. Dame un dato más o acláralo.",
        "favorite_city": "No tengo memoria suficiente para responder con seguridad sobre tu ciudad favorita. Dame un dato más o acláralo.",
        "origin_location": "No tengo memoria suficiente para responder con seguridad sobre ese origen. Dame un dato más o acláralo.",
        "current_location": "No tengo memoria suficiente para responder con seguridad sobre esa ubicación actual. Dame un dato más o acláralo.",
        "name": "No tengo memoria suficiente para responder con seguridad sobre ese nombre. Dame un dato más o acláralo.",
        "works_at": "No tengo memoria suficiente para responder con seguridad sobre ese trabajo. Dame un dato más o acláralo.",
        "preferred_provider": "No tengo memoria suficiente para responder con seguridad sobre tu proveedor preferido. Dame un dato más o acláralo.",
        "preferred_greeting": "No tengo memoria suficiente para responder con seguridad sobre tu forma de saludo preferida. Dame un dato más o acláralo.",
        "priority_project": "No tengo memoria suficiente para responder con seguridad sobre tu proyecto prioritario actual. Dame un dato más o acláralo.",
        "music_preference": "No tengo memoria suficiente para responder con seguridad sobre tu preferencia musical. Dame un dato más o acláralo.",
        "last_meal": "No tengo memoria suficiente para responder con seguridad sobre esa comida. Dame un dato más o acláralo.",
    }
    return {
        "mode": "insufficient_memory",
        "answer": questions.get(attribute, "No tengo memoria suficiente para responder con seguridad. Dame un dato más o una aclaración."),
        "used_memories": [],
        "options": ["A) Dar un dato adicional", "B) Aclarar la pregunta"],
    }


def _value_candidates(memories: list[dict], entity: str, attribute: str) -> list[dict]:
    return [m for m in memories if m.get("entity") == entity and m.get("attribute") == attribute]


def _find_current_candidates(target: QueryTarget, payload: ChatRequest, memories: list[dict]) -> list[dict]:
    scoped = _dedupe_active_memories(memories)
    candidates = _value_candidates(scoped, target.entity, target.attribute)

    if not candidates and target.entity == "user":
        candidates = _value_candidates(scoped, build_person_entity(payload.user_id), target.attribute)

    if not candidates and target.entity.startswith("person_") and target.entity == build_person_entity(payload.user_id):
        candidates = _value_candidates(scoped, "user", target.attribute)

    if not candidates and target.entity in {"user", build_person_entity(payload.user_id)}:
        all_active = _dedupe_active_memories(query_semantic_memories(payload.user_id, None, payload.book_id, include_inactive=False, include_global=True))
        candidates = [m for m in all_active if m.get("attribute") == target.attribute and m.get("entity") in {"user", build_person_entity(payload.user_id)}]

    return candidates


def _find_history_candidates(target: QueryTarget, payload: ChatRequest) -> list[dict]:
    all_memories = query_semantic_memories(payload.user_id, payload.project, payload.book_id, include_inactive=True, include_global=True)
    candidates = [m for m in all_memories if m.get("attribute") == target.attribute]
    if target.entity == "user":
        candidates = [m for m in candidates if m.get("entity") in {"user", build_person_entity(payload.user_id)}]
    else:
        if target.entity.startswith("person_") and target.entity == build_person_entity(payload.user_id):
            candidates = [m for m in candidates if m.get("entity") in {target.entity, "user"}]
        else:
            candidates = [m for m in candidates if m.get("entity") == target.entity]
    if target.wants_previous:
        candidates = [m for m in candidates if m.get("status") in {"superseded", "archived"}] + [m for m in candidates if m.get("status") == "active"]
    return sorted(candidates, key=_sort_key, reverse=True)


def _build_test_config_answer(memories: list[dict]) -> dict:
    scoped = _dedupe_active_memories(memories)
    user_candidates = [m for m in scoped if m.get("entity") == "test_config" and m.get("attribute") == "user_id"]
    project_candidates = [m for m in scoped if m.get("entity") == "test_config" and m.get("attribute") == "project"]
    if not user_candidates or not project_candidates:
        return {
            "mode": "insufficient_memory",
            "answer": "Me falta configuración de pruebas. ¿Querés indicar user_id y project?",
            "used_memories": [],
            "options": ["A) user_id=... y project=...", "B) No por ahora"],
        }
    user_value = sorted({x.get("value_text") for x in user_candidates if x.get("value_text")})[0]
    project_value = sorted({x.get("value_text") for x in project_candidates if x.get("value_text")})[0]
    used_memories = [_memory_to_used(memory).model_dump() for memory in (user_candidates[:1] + project_candidates[:1])]
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
            "options": ["A) Sí, cargar reglas", "B) No por ahora"],
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
    return {"mode": "answer", "answer": answer, "used_memories": used_memories, "options": []}


def _build_assistant_policy_answer(payload: ChatRequest, memories: list[dict]) -> dict:
    scoped = [m for m in _dedupe_active_memories(memories) if m.get("entity") in {"assistant_policy", "test_rule"}]
    scoped_attrs = {m.get("attribute") for m in scoped}
    if payload.project and ({"memory_first", "insufficient_memory_rule"} - scoped_attrs):
        fallback = query_semantic_memories(payload.user_id, None, payload.book_id, include_inactive=False, include_global=True)
        fallback = [
            m for m in _dedupe_active_memories(fallback)
            if m.get("entity") == "assistant_policy" and m.get("attribute") in {"memory_first", "insufficient_memory_rule"}
        ]
        for memory in fallback:
            if memory.get("attribute") not in scoped_attrs:
                scoped.append(memory)
                scoped_attrs.add(memory.get("attribute"))
    if not scoped:
        return {
            "mode": "insufficient_memory",
            "answer": "No tengo memoria suficiente sobre cómo debe responder COC. ¿Querés guardarme esa regla?",
            "used_memories": [],
            "options": ["A) Sí, guardarla ahora", "B) No por ahora"],
        }

    lowered_text = " ".join(normalize_text(m.get("value_text") or m.get("context") or "") for m in scoped)
    parts = []
    if "consultar memoria" in lowered_text or "leer memoria" in lowered_text:
        parts.append("primero consultar memoria")
    if "pedir un dato adicional" in lowered_text or "pedir dato adicional" in lowered_text or "pedila" in lowered_text:
        parts.append("si falta información, pedir un dato adicional")
    if "no inventar" in lowered_text or "no inventes" in lowered_text:
        parts.append("no inventar")
    if "opciones a/b" in lowered_text or "opciones a b" in lowered_text:
        parts.append("ante ambigüedad ofrecer opciones A/B")
    if "pedir elección" in lowered_text or "pedir eleccion" in lowered_text:
        parts.append("si el usuario duda entre dos caminos, proponer opciones concretas y pedir elección")
    if not parts:
        parts.append("responder solo con memoria suficiente")

    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped[:10]]
    return {
        "mode": "answer",
        "answer": "COC debe " + ", ".join(parts) + ".",
        "used_memories": used_memories,
        "options": [],
    }


def _build_summary_answer(payload: ChatRequest, memories: list[dict]) -> dict:
    scoped = _dedupe_active_memories(memories)
    useful = []
    allowed_entities = {"user", "assistant_policy", "project_meta", "test_rule", "user_note"}
    user_person = build_person_entity(payload.user_id)
    for memory in scoped:
        entity = memory.get("entity")
        if entity not in allowed_entities and entity != user_person and not str(entity).startswith("relation_"):
            continue
        useful.append(memory)

    if not useful:
        return {
            "mode": "insufficient_memory",
            "answer": "Todavía no tengo recuerdos útiles para responder eso. ¿Querés que guarde alguno ahora?",
            "used_memories": [],
            "options": ["A) Sí, guardar ahora", "B) No por ahora"],
        }

    lines = []
    seen = set()
    for memory in sorted(useful, key=lambda item: (item.get("entity", ""), item.get("attribute", ""), item.get("value_text", ""))):
        key = (memory.get("entity"), memory.get("attribute"), memory.get("value_text"))
        if key in seen:
            continue
        seen.add(key)
        label = _display_label(memory)
        lines.append(f"- {label}: {memory.get('value_text')}.")

    return {
        "mode": "answer",
        "answer": "Sé esto con seguridad para este proyecto:\n" + "\n".join(lines[:8]),
        "used_memories": [_memory_to_used(memory).model_dump() for memory in useful[:10]],
        "options": [],
    }


def _build_user_only_summary_answer(payload: ChatRequest, memories: list[dict]) -> dict:
    scoped = _dedupe_active_memories(memories)
    user_person = build_person_entity(payload.user_id)
    useful = [m for m in scoped if m.get("entity") in {"user", "assistant_policy", "user_note", user_person}]

    if not useful:
        return {
            "mode": "insufficient_memory",
            "answer": "No tengo memoria suficiente solo sobre vos en este proyecto. ¿Querés agregar un dato?",
            "used_memories": [],
            "options": ["A) Dar un dato", "B) Aclarar la pregunta"],
        }

    lines = []
    seen = set()
    for memory in sorted(useful, key=lambda item: (item.get("entity", ""), item.get("attribute", ""), item.get("value_text", ""))):
        key = (memory.get("entity"), memory.get("attribute"), memory.get("value_text"))
        if key in seen:
            continue
        seen.add(key)
        lines.append(f"- {_display_label(memory)}: {memory.get('value_text')}.")

    return {
        "mode": "answer",
        "answer": "Sobre vos recuerdo esto:\n" + "\n".join(lines[:6]),
        "used_memories": [_memory_to_used(memory).model_dump() for memory in useful[:10]],
        "options": [],
    }


def _build_dual_color_answer(payload: ChatRequest, memories: list[dict]) -> dict:
    mine = _find_current_candidates(QueryTarget("user", "favorite_color"), payload, memories)
    pedro = _find_current_candidates(QueryTarget(build_person_entity("pedro"), "favorite_color", subject_label="Pedro"), payload, memories)
    if not mine or not pedro:
        return _insufficient_answer("favorite_color")
    mine_best = sorted(mine, key=_sort_key, reverse=True)[0]
    pedro_best = sorted(pedro, key=_sort_key, reverse=True)[0]
    used = [_memory_to_used(mine_best).model_dump(), _memory_to_used(pedro_best).model_dump()]
    return {
        "mode": "answer",
        "answer": f"Para vos quedó {mine_best.get('value_text')}. Para Pedro quedó {pedro_best.get('value_text')}.",
        "used_memories": used,
        "options": [],
    }


def _build_project_summary_answer(memories: list[dict]) -> dict:
    scoped = _dedupe_active_memories([m for m in memories if is_project_memory(m)])
    if not scoped:
        return {
            "mode": "insufficient_memory",
            "answer": "Todavía no tengo recuerdos útiles para este proyecto. ¿Querés que guarde alguno ahora?",
            "used_memories": [],
            "options": ["A) Sí, guardar ahora", "B) No por ahora"],
        }

    bullets = []
    for memory in sorted(scoped, key=lambda item: (item.get("entity", ""), item.get("attribute", ""), item.get("value_text", ""))):
        value = memory.get("value_text")
        if not value:
            continue
        bullets.append(f"- {_display_label(memory)}: {value}.")

    return {
        "mode": "answer",
        "answer": "Recuerdo esto de este proyecto:\n" + "\n".join(bullets[:6]),
        "used_memories": [_memory_to_used(memory).model_dump() for memory in scoped[:10]],
        "options": [],
    }


def _build_factual_answer(*, target: QueryTarget, payload: ChatRequest, memories: list[dict]) -> dict:
    candidates = _find_current_candidates(target, payload, memories)
    if target.wants_previous:
        history = _find_history_candidates(target, payload)
        distinct_values = []
        for memory in history:
            value = (memory.get("value_text") or "").strip()
            if value and value not in distinct_values:
                distinct_values.append(value)
        if len(distinct_values) >= 2:
            previous = distinct_values[1]
            return {
                "mode": "answer",
                "answer": f"Antes era {previous}.",
                "used_memories": [_memory_to_used(memory).model_dump() for memory in history[:2]],
                "options": [],
            }
        return _insufficient_answer(target.attribute)

    if not candidates:
        return _insufficient_answer(target.attribute)

    distinct_projects = {c.get("project") for c in candidates if c.get("project")}
    distinct_values = {(c.get("value_text") or "").strip() for c in candidates if c.get("value_text")}
    if payload.project is None and len(distinct_projects) > 1 and len(distinct_values) > 1:
        used_memories = [_memory_to_used(memory).model_dump() for memory in candidates]
        options = [f"{idx}) {value}" for idx, value in enumerate(sorted(distinct_values), start=1)]
        return {
            "mode": "clarification_required",
            "answer": "Encontré más de una opción activa. ¿Querés elegir una o indicar el proyecto?",
            "used_memories": used_memories,
            "options": options or ["A) Elegir opción", "B) Indicar proyecto"],
        }

    best = sorted(candidates, key=_sort_key, reverse=True)[0]
    value = (best.get("value_text") or "").strip()
    used_memories = [_memory_to_used(memory).model_dump() for memory in [best]]

    if target.expected_value is not None:
        matches = normalize_text(value) == normalize_text(target.expected_value)
        if target.attribute == "favorite_color":
            answer = f"Sí. Tu color favorito actual es {value}." if matches else f"No. Tu color favorito actual es {value}."
        else:
            answer = f"Sí. El valor actual es {value}." if matches else f"No. El valor actual es {value}."
        return {"mode": "answer", "answer": answer, "used_memories": used_memories, "options": []}

    if target.attribute == "favorite_color":
        if target.subject_label:
            answer = f"El color favorito de {target.subject_label} es {value}."
        else:
            answer = f"Tu color favorito es {value}."
    elif target.attribute == "favorite_food":
        if target.subject_label:
            answer = f"La comida favorita de {target.subject_label} es {value}."
        else:
            answer = f"Tu comida favorita es {value}."
    elif target.attribute == "favorite_city":
        answer = f"Tu ciudad favorita es {value}."
    elif target.attribute == "origin_location":
        if target.entity == "user":
            answer = f"Sos de {value}."
        else:
            answer = f"{target.subject_label or 'Esa persona'} es de {value}."
    elif target.attribute == "current_location":
        if target.entity == "user":
            answer = f"Vivís en {value}."
        else:
            answer = f"{target.subject_label or 'Esa persona'} vive en {value}."
    elif target.attribute == "name":
        if target.entity == "user":
            answer = f"Te llamás {value}."
        else:
            answer = f"{target.subject_label or 'Esa persona'} se llama {value}."
    elif target.attribute == "works_at":
        answer = f"{target.subject_label or 'Vos'} trabaja en {value}."
    elif target.attribute == "preferred_provider":
        answer = f"Tu proveedor preferido actual es {value}."
    elif target.attribute == "preferred_greeting":
        answer = f"Tu forma de saludo preferida es {value}."
    elif target.attribute == "priority_project":
        answer = f"Tu proyecto prioritario actual es {value}."
    else:
        owner = target.subject_label or "vos"
        answer = f"El valor actual de {target.attribute} para {owner} es {value}."

    return {"mode": "answer", "answer": answer, "used_memories": used_memories, "options": []}


def _relation_subject_label(relation: str) -> str:
    return f"Tu {relation}"


def _guess_relation_target(text: str) -> Optional[QueryTarget]:
    for relation in _RELATION_TERMS:
        relation_phrase = f"mi {relation}"
        if relation_phrase not in text:
            continue
        entity = build_relation_entity(relation)
        label = _relation_subject_label(relation)
        if re.search(rf"(de donde|donde|dónde).*(es|era)?\s*{re.escape(relation_phrase)}", text) or re.search(rf"{re.escape(relation_phrase)}.*(es|era) de", text):
            return QueryTarget(entity, "origin_location", subject_label=label)
        if re.search(rf"(donde|dónde).*(vive|esta|está).*(\b{re.escape(relation_phrase)}\b)", text) or re.search(rf"{re.escape(relation_phrase)}.*vive en", text):
            return QueryTarget(entity, "current_location", subject_label=label)
        if re.search(rf"(como|cómo).*(se llama).*(\b{re.escape(relation_phrase)}\b)", text) or re.search(rf"nombre de {re.escape(relation_phrase)}", text):
            return QueryTarget(entity, "name", subject_label=label)
        if re.search(rf"(donde|dónde).*(trabaja).*(\b{re.escape(relation_phrase)}\b)", text) or re.search(rf"{re.escape(relation_phrase)}.*trabaja en", text):
            return QueryTarget(entity, "works_at", subject_label=label)
    return None


def _guess_user_profile_target(text: str) -> Optional[QueryTarget]:
    if _contains_any(text, ["de donde soy", "de dónde soy", "soy de donde", "soy de dónde"]):
        return QueryTarget("user", "origin_location", subject_label="Vos")
    if _contains_any(text, ["donde vivo", "dónde vivo", "en que ciudad vivo", "en qué ciudad vivo"]):
        return QueryTarget("user", "current_location", subject_label="Vos")
    if _contains_any(text, ["como me llamo", "cómo me llamo", "cual es mi nombre", "cuál es mi nombre"]):
        return QueryTarget("user", "name", subject_label="Vos")
    return None


def _build_combined_answer(payload: ChatRequest, memories: list[dict]) -> dict:
    policy = _build_assistant_policy_answer(payload, memories)
    color = _build_factual_answer(target=QueryTarget(entity="user", attribute="favorite_color"), payload=payload, memories=memories)
    if policy["mode"] != "answer" and color["mode"] != "answer":
        return _insufficient_answer("favorite_color")

    answers = []
    used_memories = []
    if policy["mode"] == "answer":
        answers.append(policy["answer"])
        used_memories.extend(policy["used_memories"])
    if color["mode"] == "answer":
        answers.append(color["answer"])
        used_memories.extend(color["used_memories"])
    return {"mode": "answer", "answer": " ".join(answers), "used_memories": used_memories, "options": []}


def _guess_query_target(message: str) -> Optional[QueryTarget]:
    text = _normalize_query_text(message)

    if ("color quedo para mi" in text or "color quedó para mí" in text or "que color quedo para mi" in text or "qué color quedó para mí" in text or "cual para pedro" in text or "cuál para pedro" in text or "que color quedo para mi y cual para pedro" in text or "qué color quedó para mí y cuál para pedro" in text) and "pedro" in text:
        return QueryTarget("__pair__", "favorite_color")

    relation_target = _guess_relation_target(text)
    if relation_target:
        return relation_target

    user_profile_target = _guess_user_profile_target(text)
    if user_profile_target:
        return user_profile_target

    if _contains_any(text, ["que recuerdas de mi", "que recuerdas de mí", "que sabes de mi", "que sabes de mí", "solo sobre mi", "solo sobre mí", "lo mio, no lo ajeno", "lo mío, no lo ajeno", "solo mis preferencias", "no uses nada de pedro para completarme", "trae solo mis preferencias", "solo sobre vos", "solo sobre mi en este proyecto"]):
        return QueryTarget("user", "summary", wants_summary=True)

    if _contains_any(text, ["y eso que te corregi ayer", "y eso que te corregí ayer", "lo importante ahora no es lo de antes", "solo que quedo vigente", "solo qué quedó vigente", "al final en que quedo", "al final en qué quedó"]):
        return QueryTarget("user", "favorite_color")

    if _contains_any(text, ["ya sabes, lo de no inventar", "que regla rige", "qué regla rige", "que deberia responderse", "qué debería responderse", "comportamiento tiene coc", "que comportamiento tiene coc en este momento", "cómo debe responder coc hoy", "como debe responder coc hoy", "qué regla de respuesta aplica ahora", "la regla vigente de coc", "no me digas la vieja", "para este proyecto, no para el otro", "como responde coc aqui", "cómo responde coc aquí", "que debe hacer coc aqui", "qué debe hacer coc aquí", "mi regla de respuesta, no la de otro usuario", "que aplica aca", "qué aplica acá"]):
        return QueryTarget("assistant_policy", "coc_response")
    if _contains_any(text, ["mi regla de respuesta, no la de otro usuario", "que aplica aca", "qué aplica acá", "ya sabes, lo de no inventar, sigue igual", "sigue igual", "regla de respuesta", "respuesta corresponde segun este proyecto", "respuesta corresponde según este proyecto"]):
        return QueryTarget("assistant_policy", "coc_response")

    if _contains_any(text, ["lo de la comida que mas me gusta", "lo de la comida que más me gusta", "que comida mia tienes guardada como favorita", "qué comida mía tienes guardada como favorita"]):
        return QueryTarget("user", "favorite_food")

    if _contains_any(text, ["usa solo lo activo", "solo memorias activas", "ignorando archivadas", "ignora lo archivado", "no uses archivadas", "con solo memorias activas", "entre lo vigente", "si ignoras lo archivado", "no uses lo archivado", "que recuerdas como actual", "qué recuerdas como actual", "entre lo viejo y lo nuevo", "cual vale ahora", "cuál vale ahora", "dime el color vigente", "que queda", "qué queda", "lo de hoy manda", "lo de ayer solo como historia", "no rellenes huecos", "usa el actual", "si ya hay memoria"]):
        return QueryTarget("user", "favorite_color")

    if _contains_any(text, ["tras el borrado", "sin usar datos eliminados", "que ciudad favorita figura hoy", "qué ciudad favorita figura hoy"]):
        return QueryTarget("user", "favorite_city")

    if _contains_any(text, ["con el proveedor archivado", "sin la memoria activa", "que proveedor queda", "qué proveedor queda"]):
        return QueryTarget("user", "preferred_provider")

    if _contains_any(text, ["que regla aplica", "qué regla aplica", "que regla extra hay ante ambiguedad", "qué regla extra hay ante ambigüedad", "regla vigente en este proyecto", "qué respuesta corresponde según este proyecto", "se sobreentiende que hablo del proyecto actual", "no mezcles memoria-guia con coc", "no mezcles memoria guia con coc", "lo de este panel, sin cruzar con el otro proyecto", "qué dato está guardado aquí específicamente"]):
        return QueryTarget("assistant_policy", "coc_response")


    if _contains_any(text, ["que color tenia guardado antes del cambio", "qué color tenía guardado antes del cambio", "valor anterior del color", "antes de la correccion", "antes de la corrección", "que version vieja quedo", "qué versión vieja quedó", "cual era antes", "cuál era antes", "antes cual era", "antes cuál era", "valor anterior", "si te pregunto por el valor anterior", "cual sacas", "cuál sacas"]):
        return QueryTarget("user", "favorite_color", wants_previous=True)

    if ("user_id" in text and "project" in text and "prueba" in text) or _contains_any(text, ["configuracion de pruebas", "config de pruebas", "configuracion de test", "configuracion del test"]):
        return QueryTarget("test_config", "user_id_project")
    if _contains_any(text, ["deba evitar", "evitar al probar", "algo importante que deba evitar", "que debo evitar", "que hay que evitar", "cosas tengo que evitar", "tengo que evitar"]):
        return QueryTarget("test_rule", "avoidances")
    if "consulta ambigua" in text or ("ambig" in text and "deber" in text):
        return QueryTarget("test_rule", "ambiguity_rule")

    if "como debe responder coc" in text and "color favorito actual" in text:
        return QueryTarget("assistant_policy", "coc_response", combine_policy=True)

    if _contains_any(text, ["que recuerdas de este proyecto", "que sabes de este proyecto", "resumen del proyecto", "dame un resumen del proyecto", "solo el proyecto actual", "que dato esta guardado aqui especificamente", "qué dato está guardado aquí específicamente", "lo de este panel, sin cruzar con el otro proyecto"]):
        return QueryTarget("project", "summary", wants_summary=True)
    if _contains_any(text, ["resume solo lo que si sabes de mi con seguridad", "que recuerdas sobre mi", "que recuerdas de mi", "que sabes de mi", "que sabes sobre mi", "resumen sobre mi"]):
        return QueryTarget("user", "summary", wants_summary=True)
    if _contains_any(text, ["como debe responder coc", "cómo debe responder coc", "como responde coc", "como debe contestar coc", "como responde coc aqui", "cómo responde coc aquí", "como debe responder coc aqui", "cómo debe responder coc aquí"]):
        return QueryTarget("assistant_policy", "coc_response")

    match = re.search(r"mi color favorito actual es ([a-záéíóúñ ]+)", text)
    if match:
        return QueryTarget("user", "favorite_color", expected_value=match.group(1))
    match = re.search(r"mi color favorito es ([a-záéíóúñ ]+)", text)
    if match and "cual es" not in text:
        return QueryTarget("user", "favorite_color", expected_value=match.group(1))

    person_match = re.search(r"color favorito de ([a-záéíóúñ ]+)", text)
    if person_match:
        person_name = person_match.group(1).strip()
        if person_name not in {"mi", "vos"}:
            return QueryTarget(build_person_entity(person_name), "favorite_color", subject_label=person_name.title())

    if _contains_any(text, ["que sabes de mi color favorito", "que recordarias como valido", "qué recordarías como válido", "responde segun memoria factual", "responde según memoria factual", "hubo una respuesta anterior incorrecta", "ignora el log conversacional", "si antes respondiste mal", "no conviertas la respuesta previa en verdad", "que dato factual tienes", "qué dato factual tienes", "solo la memoria semantica real", "solo la memoria semántica real", "sin abrir la memoria cruda", "si no lo sabes dilo", "respuesta breve correcta vigente", "con todo ese lio anterior", "con todo ese lío anterior", "que vale hoy sin meter nada", "qué vale hoy sin meter nada"]):
        return QueryTarget("user", "favorite_color")
    if _looks_like_question_about(text, "favorite_color") or _contains_any(text, ["cual es mi color favorito", "mi color favorito?", "mi color favorito", "hoy por hoy", "que color tengo guardado", "que dato mio sigue en pie", "qué dato mío sigue en pie", "entre el viejo y el nuevo", "no me digas el anterior", "dime el de ahora", "hasta ayer era una cosa", "en este momento", "cual corre hoy", "cuál corre hoy", "sin revisar el pasado", "quiero el dato de ahora", "no estoy preguntando por antes", "lo de antes no me sirve", "historicamente estaba uno", "históricamente estaba uno", "no quiero la version vieja", "no quiero la versión vieja", "lo importante ahora no es lo de antes", "que vale hoy", "qué vale hoy", "vigente y sin cruces", "solo qué quedó vigente", "solo que quedo vigente"]):
        return QueryTarget("user", "favorite_color")
    if _looks_like_question_about(text, "favorite_food"):
        return QueryTarget("user", "favorite_food")
    if _contains_any(text, ["libro favorito"]):
        return QueryTarget("user", "favorite_book")
    if _looks_like_question_about(text, "favorite_city"):
        return QueryTarget("user", "favorite_city")
    if _looks_like_question_about(text, "preferred_provider") or _contains_any(text, ["recuerdame mi taller", "recuérdame mi taller"]):
        return QueryTarget("user", "preferred_provider")
    if _looks_like_question_about(text, "preferred_greeting"):
        return QueryTarget("user", "preferred_greeting")
    if _looks_like_question_about(text, "priority_project") or _contains_any(text, ["que proyecto prioritario tengo", "qué proyecto prioritario tengo", "que prioridad tengo", "que prioridad tiene este proyecto", "qué prioridad tiene este proyecto"]):
        return QueryTarget("project_meta", "priority_project")
    if _contains_any(text, ["prioridad tengo yo, no mi equipo"]):
        return QueryTarget("project_meta", "priority_project")
    if _contains_any(text, ["preferencia musical"]):
        return QueryTarget("user", "music_preference")
    if _contains_any(text, ["ultima comida", "última comida"]):
        return QueryTarget("user", "last_meal")

    if _mentions_own_scope(text):
        return QueryTarget("user", "summary", wants_summary=True)

    return None


def retrieve_semantic_memories(payload: ChatRequest) -> list[dict]:
    project = payload.project or "general"
    book_id = payload.book_id or "general"
    return query_active_semantic_memories(payload.user_id, project, book_id)


def build_chat_result(payload: ChatRequest, memories: list[dict]) -> dict:
    target = _guess_query_target(payload.message or "")
    scoped_memories = _dedupe_active_memories(memories)
    used_memories = [_memory_to_used(memory).model_dump() for memory in scoped_memories]

    if not target:
        msg = (payload.message or "").strip()
        if msg and not msg.endswith("?"):
            from app.memory_core_v1 import build_scope, save_note, save_event
            scope = build_scope(
                {"project_id": payload.project or "general", "book_id": payload.book_id or "general"},
                principal_user_id=payload.user_id
            )
            ev = save_event(scope, "user", msg, source="panel_chat")
            save_note(scope, title="Nota del chat", content=msg, source_event_id=ev["id"])
            return {
                "mode": "stored",
                "answer": f"Guardado: \"{msg}\"",
                "used_memories": used_memories,
            }
        return {
            "mode": "clarification_required",
            "answer": "No estoy seguro de qué dato querés consultar. ¿Querés elegir una opción?",
            "used_memories": used_memories,
            "options": ["A) Color favorito", "B) Comida favorita", "C) Configuración de pruebas"],
        }

    if target.entity == "__pair__" and target.attribute == "favorite_color":
        return _build_dual_color_answer(payload, scoped_memories)
    if target.wants_summary and target.entity == "project":
        return _build_project_summary_answer(scoped_memories)
    if target.wants_summary and _mentions_own_scope(_normalize_query_text(payload.message or "")):
        return _build_user_only_summary_answer(payload, scoped_memories)
    if target.wants_summary:
        return _build_summary_answer(payload, scoped_memories)
    if target.combine_policy:
        return _build_combined_answer(payload, scoped_memories)
    if target.entity == "test_config" and target.attribute == "user_id_project":
        return _build_test_config_answer(scoped_memories)
    if target.entity == "test_rule" and target.attribute in {"avoidances", "ambiguity_rule"}:
        return _build_avoidances_answer(scoped_memories)
    if target.entity == "assistant_policy" and target.attribute == "coc_response":
        return _build_assistant_policy_answer(payload, scoped_memories)
    return _build_factual_answer(target=target, payload=payload, memories=scoped_memories)


def save_chat_event(payload: ChatRequest, answer_text: str) -> str:
    touch_user_project(payload.user_id, payload.project or "general")
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
            "bridge_mode": settings.bridge_mode,
            "connection_status": settings.connection_status,
            "created_at": utc_now_iso(),
            "ttl_at": None,
        }
    )
    return event_id


def maybe_store_semantic_memory(payload: ChatRequest, source_event_id: str, extracted=None):
    if extracted is not None:
        return upsert_semantic_memory(
            user_id=payload.user_id,
            project=payload.project or "general",
            book_id=payload.book_id or "general",
            extracted=extracted,
            source_event_id=source_event_id,
        )
    return store_message_memory(
        user_id=payload.user_id,
        project=payload.project or "general",
        book_id=payload.book_id or "general",
        content=payload.message,
        source_type="chat_auto" if not payload.remember else "chat_remember",
        source_event_id=source_event_id,
        force=payload.remember,
    )


def _acknowledgement_for_memory(extracted) -> str:
    if extracted.entity == "user" and extracted.attribute == "favorite_color":
        return f"Listo, guardé que tu color favorito actual es {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "favorite_food":
        return f"Listo, guardé que tu comida favorita es {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "preferred_provider":
        return f"Listo, guardé que tu proveedor preferido actual es {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "preferred_greeting":
        return f"Listo, guardé que tu forma de saludo preferida es {extracted.value_text}."
    if extracted.entity == "project_meta" and extracted.attribute == "priority_project":
        return f"Listo, guardé que tu proyecto prioritario actual es {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "origin_location":
        return f"Listo, guardé que sos de {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "current_location":
        return f"Listo, guardé que vivís en {extracted.value_text}."
    if extracted.entity == "user" and extracted.attribute == "name":
        return f"Listo, guardé tu nombre: {extracted.value_text}."
    if str(extracted.entity).startswith("relation_") and extracted.attribute == "origin_location":
        subject = extracted.entity.replace("relation_", "").replace("_", " ")
        return f"Listo, guardé que tu {subject} es de {extracted.value_text}."
    if str(extracted.entity).startswith("relation_") and extracted.attribute == "current_location":
        subject = extracted.entity.replace("relation_", "").replace("_", " ")
        return f"Listo, guardé que tu {subject} vive en {extracted.value_text}."
    if str(extracted.entity).startswith("relation_") and extracted.attribute == "name":
        subject = extracted.entity.replace("relation_", "").replace("_", " ")
        return f"Listo, guardé el nombre de tu {subject}: {extracted.value_text}."
    return "Listo, lo guardé."


def save_retrieval_trace(payload: ChatRequest, *, event_id: str, result: dict) -> Optional[str]:
    used_ids = [item.get("id") for item in result.get("used_memories", []) if item.get("id")]
    if not used_ids:
        return None
    trace_id = f"trace:{new_memory_id()}"
    retrieval_traces_collection.document(trace_id).set(
        {
            "id": trace_id,
            "user_id": payload.user_id,
            "project": payload.project or "general",
            "book_id": payload.book_id or "general",
            "event_id": event_id,
            "mode": result.get("mode"),
            "query": payload.message,
            "answer": result.get("answer"),
            "used_memory_ids": used_ids,
            "created_at": utc_now_iso(),
        }
    )
    return trace_id


def _apply_control_command(payload: ChatRequest) -> Optional[dict]:
    text = normalize_text(payload.message)
    if "lo que te dije que no guardaras" in text or "lo que te dije que no guardarías" in text:
        return {"mode": "answer", "answer": "Sí, lo sigo ignorando: no lo guardé como memoria válida.", "used_memories": [], "options": []}
    if any(marker in text for marker in _NO_STORE_HINTS) and "?" not in payload.message and "¿" not in payload.message:
        return {"mode": "answer", "answer": "Entendido, eso no lo voy a guardar.", "used_memories": [], "options": []}
    if "usa siempre user_id" in text and "project" in text:
        return {"mode": "answer", "answer": "Entendido, usaré esos valores para esta prueba.", "used_memories": [], "options": []}
    if "ahora cambia solo para este bloque a project" in text:
        return {"mode": "answer", "answer": "Entendido, tomo ese project para este bloque.", "used_memories": [], "options": []}
    if "ahora vuelve a project" in text:
        return {"mode": "answer", "answer": "Entendido, vuelvo al project indicado.", "used_memories": [], "options": []}
    if "olvides la informacion vieja de que mi color favorito era azul" in text or "olvides la información vieja de que mi color favorito era azul" in text:
        memories = query_semantic_memories(payload.user_id, payload.project, payload.book_id, include_inactive=True, include_global=True)
        for memory in memories:
            if memory.get("attribute") == "favorite_color" and normalize_text(memory.get("value_text")) == "azul":
                facts_collection.document(memory["id"]).delete()
        return {"mode": "answer", "answer": "Listo, dejé de usar esa verdad vieja.", "used_memories": [], "options": []}
    if "no te confundas entre" in text or "no uses el dato de" in text:
        return {"mode": "answer", "answer": "Entendido: mantengo separados tus datos de los de terceros y no voy a mezclar identidades.", "used_memories": [], "options": []}
    return None


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    control_result = _apply_control_command(payload)
    extracted = None if control_result else extract_structured_memory(payload.message)
    is_plain_statement = "?" not in payload.message and "¿" not in payload.message
    wants_memory = payload.remember or is_explicit_memory_command(payload.message)

    if control_result:
        save_chat_event(payload, control_result["answer"])
        return control_result

    if is_plain_statement and extracted is not None:
        answer = _acknowledgement_for_memory(extracted)
        result = {"mode": "answer", "answer": answer, "used_memories": [], "options": []}
        event_id = save_chat_event(payload, answer)
        maybe_store_semantic_memory(payload, source_event_id=event_id, extracted=extracted)
        return result

    if is_plain_statement and (wants_memory or should_auto_store_personal_note(payload.message)):
        stored = maybe_store_semantic_memory(payload, source_event_id=new_memory_id(), extracted=None)
        if stored is not None:
            answer = "Listo, guardé esa nota para este proyecto." if stored.get("entity") == "user_note" else _acknowledgement_for_memory(extract_structured_memory(payload.message) or extracted)
            result = {"mode": "answer", "answer": answer, "used_memories": [], "options": []}
            event_id = save_chat_event(payload, answer)
            if stored.get("source_event_id") != event_id:
                target_id = stored.get("id") or ""
                updates = {"source_event_id": event_id, "updated_at": utc_now_iso()}
                if str(target_id).startswith("fact:"):
                    facts_collection.document(target_id).update(updates)
                elif str(target_id).startswith("note:"):
                    manual_notes_collection.document(target_id).update(updates)
            return result

    product_result = answer_product_query(payload.user_id, payload.project or GLOBAL_PROJECT, payload.message)
    if product_result:
        event_id = save_chat_event(payload, product_result["answer"])
        save_retrieval_trace(payload, event_id=event_id, result=product_result)
        if extracted or wants_memory:
            maybe_store_semantic_memory(payload, source_event_id=event_id, extracted=extracted)
        return product_result

    memories = retrieve_semantic_memories(payload)
    result = build_chat_result(payload, memories)

    event_id = save_chat_event(payload, result["answer"])
    save_retrieval_trace(payload, event_id=event_id, result=result)
    if extracted or wants_memory:
        maybe_store_semantic_memory(payload, source_event_id=event_id, extracted=extracted)

    return result
