from __future__ import annotations

import re
from typing import Optional

from app.memory_core_v1 import (
    MemoryScope,
    save_event,
    save_fact,
    save_note,
    search_memory,
)


def build_panel_scope(*, user_id: str, project: str, book_id: str) -> MemoryScope:
    return MemoryScope(
        tenant_id=user_id,
        user_id=user_id,
        project_id=project or "general",
        book_id=book_id or "general",
        entity_type="generic",
        entity_id="generic",
    )


def _clean(value: str) -> str:
    return " ".join((value or "").strip().split())


def _extract_fact(content: str) -> Optional[tuple[str, str, str]]:
    text = _clean(content).strip(" .!?")

    patterns: list[tuple[str, callable]] = [
        (r"^mi\s+(.+?)\s+se\s+llama\s+(.+)$", lambda m: (_clean(m.group(1)), "se llama", _clean(m.group(2)))),
        (r"^mi\s+(.+?)\s+vive\s+en\s+(.+)$", lambda m: (_clean(m.group(1)), "vive en", _clean(m.group(2)))),
        (r"^mi\s+(.+?)\s+es\s+de\s+(.+)$", lambda m: (_clean(m.group(1)), "es de", _clean(m.group(2)))),
        (r"^mi\s+(.+?)\s+favorit[oa]\s+es\s+(.+)$", lambda m: ("user", f"{_clean(m.group(1))} favorito", _clean(m.group(2)))),
        (r"^mi\s+(.+?)\s+preferid[oa]\s+es\s+(.+)$", lambda m: ("user", f"{_clean(m.group(1))} preferido", _clean(m.group(2)))),
        (r"^soy\s+de\s+(.+)$", lambda m: ("user", "es de", _clean(m.group(1)))),
        (r"^vivo\s+en\s+(.+)$", lambda m: ("user", "vive en", _clean(m.group(1)))),
        (r"^me\s+llamo\s+(.+)$", lambda m: ("user", "se llama", _clean(m.group(1)))),
        (r"^mi\s+nombre\s+es\s+(.+)$", lambda m: ("user", "se llama", _clean(m.group(1)))),
        (r"^mi\s+(.+?)\s+es\s+(.+)$", lambda m: ("user", _clean(m.group(1)), _clean(m.group(2)))),
    ]

    for pattern, builder in patterns:
        match = re.match(pattern, text, flags=re.IGNORECASE)
        if match:
            subject, relation, obj = builder(match)
            return _clean(subject), _clean(relation), obj
    return None


def store_panel_manual_memory(*, user_id: str, project: str, book_id: str, content: str) -> dict:
    scope = build_panel_scope(user_id=user_id, project=project, book_id=book_id)
    event = save_event(scope, role="user", content=content, source="panel_manual")
    note = save_note(scope, title="Memoria manual", content=content, source_event_id=event["id"])
    extracted = _extract_fact(content)
    fact = None
    if extracted:
        subject, relation, obj = extracted
        fact = save_fact(scope, subject, relation, obj, source_event_id=event["id"])
    return {"event": event, "note": note, "fact": fact}


QUESTION_PREFIX_RE = re.compile(r"^(¿|\?)?(cual|cu[aá]l|que|qu[eé]|como|c[oó]mo|de d[oó]nde|d[oó]nde|donde|cuanto|cu[aá]nto|quien|qui[eé]n|trabaja|vive|llama|es|tiene)\b", re.IGNORECASE)
FALLBACK_STOPWORDS = {
    "cual", "cuál", "que", "qué", "como", "cómo", "donde", "dónde", "de", "del", "la", "las", "el", "los",
    "un", "una", "unos", "unas", "mi", "mis", "tu", "tus", "su", "sus", "es", "son", "era", "eran", "fue",
    "por", "para", "en", "al", "a", "y", "o", "se", "llama", "vive", "favorito", "favorita", "preferido", "preferida"
}


def _meaningful_tokens(value: str) -> set[str]:
    return {token for token in re.findall(r"[a-z0-9_áéíóúñ-]{2,}", _clean(value).lower()) if token not in FALLBACK_STOPWORDS}


def _answer_from_fact(subject: str, relation: str, obj: str) -> str:
    subject_clean = _clean(subject)
    relation_clean = _clean(relation)
    obj_clean = _clean(obj)
    relation_low = relation_clean.lower()
    subject_low = subject_clean.lower()

    if subject_low == "user":
        if relation_low == "es de":
            return f"Sos de {obj_clean}."
        if relation_low == "vive en":
            return f"Vivís en {obj_clean}."
        if relation_low == "se llama":
            return f"Te llamás {obj_clean}."
        return f"Tu {relation_clean} es {obj_clean}."

    if relation_low == "se llama":
        return f"Tu {subject_clean} se llama {obj_clean}."
    if relation_low == "vive en":
        return f"Tu {subject_clean} vive en {obj_clean}."
    if relation_low == "es de":
        return f"Tu {subject_clean} es de {obj_clean}."
    if relation_low in {"es", "son"}:
        return f"Tu {subject_clean} es {obj_clean}."
    if relation_low.startswith("tiene"):
        return f"Tu {subject_clean} {relation_clean} {obj_clean}."
    return f"Tu {subject_clean} {relation_clean} es {obj_clean}."


FACT_PREVIEW_RE = re.compile(r"^(.*?)\s+(se llama|vive en|es de|.+?)\s+(.+)$", re.IGNORECASE)


def _build_answer_from_item(item: dict) -> Optional[str]:
    kind = item.get("kind")
    payload = item.get("payload") or {}
    if kind in {"fact", "legacy_fact"}:
        subject = payload.get("subject") or payload.get("entity") or "user"
        relation = payload.get("relation") or payload.get("attribute") or "dato"
        obj = payload.get("object") or payload.get("value_text") or ""
        if obj:
            if kind == "legacy_fact" and (str(subject).startswith("user_note") or str(relation).startswith("manual_note_")):
                return f"Según tu memoria: {_clean(obj)}."
            return _answer_from_fact(subject, relation, obj)
    if kind == "note":
        extracted = _extract_fact(payload.get("content") or item.get("preview") or "")
        if extracted:
            return _answer_from_fact(*extracted)
        content = _clean(payload.get("content") or item.get("preview") or "")
        if content:
            return f"Según tu memoria: {content}."
    if kind == "summary":
        summary = _clean(payload.get("summary") or item.get("preview") or "")
        if summary:
            return f"Según el resumen guardado: {summary}."
    return None


def panel_chat_fallback(*, user_id: str, project: str, book_id: str, message: str) -> Optional[dict]:
    cleaned = _clean(message).lower()
    if not QUESTION_PREFIX_RE.search(cleaned):
        return None
    scope = build_panel_scope(user_id=user_id, project=project, book_id=book_id)
    result = search_memory(scope, message, top_k=5)
    items = result.get("items") or []
    if not items:
        return None

    query_tokens = _meaningful_tokens(message)
    best = items[0]
    best_tokens = _meaningful_tokens(best.get("preview") or "")
    if query_tokens and not (query_tokens & best_tokens):
        return None

    answer = _build_answer_from_item(best)
    if not answer:
        return None
    used_memories = []
    for item in items[:3]:
        used_memories.append({"id": item.get("id"), "summary": item.get("preview") or ""})
    return {
        "mode": "answer",
        "answer": answer,
        "used_memories": used_memories,
        "options": [],
    }
