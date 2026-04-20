from __future__ import annotations

from typing import Optional

from fastapi import HTTPException

from app.firestore_store import (
    facts_collection,
    manual_notes_collection,
    session_summaries_collection,
)
from app.memory_core_v1 import MemoryScope, save_event, save_fact, save_note, save_session_summary, search_memory
from app.utils import utc_now_iso


def legacy_scope(*, user_id: str, project: str, book_id: str) -> MemoryScope:
    return MemoryScope(
        tenant_id=user_id,
        user_id=user_id,
        project_id=project or "general",
        book_id=book_id or "general",
        entity_type="generic",
        entity_id="generic",
    )


_COLLECTIONS = [facts_collection, manual_notes_collection, session_summaries_collection]


def get_doc(memory_id: str):
    for collection in _COLLECTIONS:
        data = collection.document(memory_id).get().to_dict()
        if data:
            return collection, data
    return None, None



def _enum_value(value) -> str:
    return getattr(value, "value", value) if value is not None else ""


def _legacy_memory_type(data: dict) -> str:
    original = str(_enum_value(data.get("original_type")) or "").strip()
    if original:
        return original
    doc_id = str(data.get("id") or "")
    if doc_id.startswith("fact:"):
        return "fact"
    if doc_id.startswith("summary:"):
        return "session_summary"
    return "note"



def to_legacy_item(data: dict) -> dict:
    doc_id = str(data.get("id") or "")
    memory_type = _legacy_memory_type(data)
    if doc_id.startswith("fact:"):
        content = f"{data.get('subject') or ''} {data.get('relation') or ''} {data.get('object') or ''}".strip()
        summary = content
        trigger = data.get("relation") or "fact"
    elif doc_id.startswith("summary:"):
        content = data.get("summary") or ""
        summary = content
        trigger = "session_summary"
    else:
        content = data.get("content") or data.get("title") or ""
        summary = data.get("content") or data.get("title") or ""
        trigger = data.get("title") or "note"
    return {
        "id": doc_id,
        "user_id": data.get("user_id") or data.get("tenant_id"),
        "project": data.get("project_id") or data.get("project") or "general",
        "book_id": data.get("book_id") or "general",
        "memory_type": memory_type,
        "status": data.get("status", "active"),
        "content": content,
        "summary": summary,
        "user_message": data.get("user_message") or "",
        "assistant_answer": data.get("assistant_answer") or "",
        "trigger_query": trigger,
        "importance": data.get("importance"),
        "keywords_json": data.get("keywords_json"),
        "embedding_json": data.get("embedding_json"),
        "source": data.get("source_type") or data.get("source") or "memory_core_v1",
        "created_at": data.get("created_at") or utc_now_iso(),
        "updated_at": data.get("updated_at"),
        "entity": data.get("subject") or data.get("entity") or "generic",
        "attribute": data.get("relation") or data.get("title") or data.get("attribute") or "memory",
        "value_text": data.get("object") or data.get("content") or data.get("summary") or "",
        "context": data.get("content") or data.get("summary") or "",
    }



def list_scope_items(*, user_id: str, project: Optional[str] = None, book_id: Optional[str] = None, include_inactive: bool = True) -> list[dict]:
    items: list[dict] = []
    for collection in _COLLECTIONS:
        for doc in collection.where("tenant_id", "==", user_id).stream():
            data = doc.to_dict() or {}
            if data.get("user_id") not in {None, user_id}:
                continue
            if project and (data.get("project_id") or data.get("project")) != project:
                continue
            if book_id and data.get("book_id") != book_id:
                continue
            if not include_inactive and data.get("status") != "active":
                continue
            items.append(to_legacy_item(data))
    items.sort(key=lambda item: (item.get("updated_at") or item.get("created_at") or "", item.get("id") or ""), reverse=True)
    return items



def create_from_legacy_payload(payload) -> dict:
    data = payload.model_dump()
    scope = legacy_scope(user_id=data["user_id"], project=data["project"], book_id=data["book_id"])
    event = save_event(scope, role="user", content=data.get("user_message") or data.get("content") or data.get("summary") or "", source=data.get("source") or "legacy_api")
    memory_type = str(_enum_value(data.get("memory_type")) or "note")
    if memory_type == "fact":
        stored = save_fact(
            scope,
            subject=data.get("entity") or "user",
            relation=data.get("trigger_query") or data.get("attribute") or "fact",
            object_value=data.get("content") or data.get("summary") or "",
            source_event_id=event["id"],
        )
    elif memory_type == "session_summary":
        stored = save_session_summary(scope, summary=data.get("summary") or data.get("content") or "")
    else:
        stored = save_note(scope, title=data.get("trigger_query") or data.get("summary") or "Memoria", content=data.get("content") or data.get("summary") or "", source_event_id=event["id"])
        if memory_type not in {"note", "conversation"}:
            manual_notes_collection.document(stored["id"]).update({"original_type": memory_type, "updated_at": utc_now_iso()})
            stored = manual_notes_collection.document(stored["id"]).get().to_dict() or stored
    return to_legacy_item(stored)



def update_legacy_memory(memory_id: str, updates: dict) -> dict:
    collection, existing = get_doc(memory_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")
    mapped: dict = {"updated_at": updates.get("updated_at") or utc_now_iso()}
    if "status" in updates and updates["status"] is not None:
        mapped["status"] = getattr(updates["status"], "value", updates["status"])
    if collection is facts_collection:
        if updates.get("project"):
            mapped["project_id"] = updates["project"]
        if updates.get("book_id"):
            mapped["book_id"] = updates["book_id"]
        if updates.get("content"):
            mapped["object"] = updates["content"]
        if updates.get("trigger_query"):
            mapped["relation"] = updates["trigger_query"]
    elif collection is manual_notes_collection:
        if updates.get("project"):
            mapped["project_id"] = updates["project"]
        if updates.get("book_id"):
            mapped["book_id"] = updates["book_id"]
        if updates.get("content"):
            mapped["content"] = updates["content"]
        if updates.get("summary"):
            mapped["title"] = updates["summary"]
        if updates.get("memory_type"):
            mapped["original_type"] = _enum_value(updates["memory_type"])
    else:
        if updates.get("project"):
            mapped["project_id"] = updates["project"]
        if updates.get("book_id"):
            mapped["book_id"] = updates["book_id"]
        if updates.get("summary") or updates.get("content"):
            mapped["summary"] = updates.get("summary") or updates.get("content")
    collection.document(memory_id).update(mapped)
    refreshed = collection.document(memory_id).get().to_dict() or existing
    return to_legacy_item(refreshed)



def archive_legacy_memory(memory_id: str) -> dict:
    return update_legacy_memory(memory_id, {"status": "archived"})



def delete_legacy_memory(memory_id: str) -> dict:
    collection, existing = get_doc(memory_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Memory not found")
    collection.document(memory_id).delete()
    return {"status": "deleted", "id": memory_id}



def search_legacy_memories(*, user_id: str, project: str, book_id: str, query: Optional[str], top_k: int = 20) -> list[dict]:
    if not query:
        return list_scope_items(user_id=user_id, project=project, book_id=book_id, include_inactive=True)[:top_k]
    scope = legacy_scope(user_id=user_id, project=project, book_id=book_id)
    result = search_memory(scope, query, top_k=top_k, include_history=True)
    output: list[dict] = []
    for item in result.get("items") or []:
        payload = item.get("payload") or {}
        output.append(to_legacy_item(payload))
    return output
