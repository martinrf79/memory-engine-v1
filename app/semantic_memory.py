from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Iterable, Optional

from app.firestore_store import db, memory_keys_collection, semantic_collection
from app.firestore_utils import memory_dict_from_firestore
from app.utils import new_memory_id, utc_now_iso

VALID_MEMORY_STATUS = {"active", "superseded", "archived"}
BLOCKED_TEXT_MARKERS = (
    "insufficient_memory",
    "answer:",
    "según las memorias encontradas",
    "segun las memorias encontradas",
    "traceback",
    "error:",
)


@dataclass
class ExtractedMemory:
    memory_type: str
    entity: str
    attribute: str
    value_text: str
    context: Optional[str] = None
    source_type: str = "chat_user_message"


def _normalize_value(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().strip("."))


def normalize_text(value: Optional[str]) -> str:
    return _normalize_value(value or "").lower()


def is_recordable_user_message(message: str) -> bool:
    lowered = normalize_text(message)
    return lowered != "" and not any(marker in lowered for marker in BLOCKED_TEXT_MARKERS)


def text_contains_blocked_markers(*parts: Optional[str]) -> bool:
    lowered = " ".join(normalize_text(part) for part in parts)
    return any(marker in lowered for marker in BLOCKED_TEXT_MARKERS)


def is_semantic_memory_record(memory: dict) -> bool:
    if not memory:
        return False
    if memory.get("status") not in VALID_MEMORY_STATUS:
        return False
    if memory.get("memory_type") == "conversation":
        return False
    required_fields = ("user_id", "project", "book_id", "entity", "attribute", "value_text", "dedupe_key")
    if any(not memory.get(field) for field in required_fields):
        return False
    if text_contains_blocked_markers(memory.get("value_text"), memory.get("context"), memory.get("attribute")):
        return False
    return True


def is_project_memory(memory: dict) -> bool:
    if not is_semantic_memory_record(memory):
        return False
    return memory.get("entity") in {"test_config", "test_rule", "backend"}


def is_user_memory(memory: dict) -> bool:
    return is_semantic_memory_record(memory) and memory.get("entity") == "user"


def tokenize_search_query(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_\-áéíóúñ]+", normalize_text(query)) if len(token) >= 2]


def extract_structured_memory(message: str) -> Optional[ExtractedMemory]:
    if not is_recordable_user_message(message):
        return None

    normalized = normalize_text(message)
    rules = [
        (r"mi color favorito es ([a-záéíóúñ ]+)", "preference", "user", "favorite_color"),
        (r"mi comida favorita es ([a-záéíóúñ ]+)", "preference", "user", "favorite_food"),
        (r"prefiero ([a-záéíóúñ ]+)", "preference", "user", "preference"),
        (r"el user_id de pruebas es ([a-z0-9_-]+)", "instruction", "test_config", "user_id"),
        (r"el project de pruebas es ([a-z0-9_-]+)", "instruction", "test_config", "project"),
        (r"no usar user_id default", "constraint", "test_rule", "avoid_user_id_default"),
        (r"si falta (?:dato|memoria|informacion|información), pedir(?:lo| un dato)?", "instruction", "test_rule", "ask_for_missing_data"),
        (r"no inventar", "constraint", "test_rule", "do_not_invent"),
        (r"si hay ambiguedad, pedir aclaracion", "instruction", "test_rule", "ask_clarification_on_ambiguity"),
        (r"si hay ambigüedad, pedir aclaración", "instruction", "test_rule", "ask_clarification_on_ambiguity"),
    ]

    for pattern, memory_type, entity, attribute in rules:
        match = re.search(pattern, normalized)
        if not match:
            continue
        value_text = match.group(1) if match.groups() else message.strip()
        return ExtractedMemory(
            memory_type=memory_type,
            entity=entity,
            attribute=attribute,
            value_text=_normalize_value(value_text),
            context=message.strip(),
        )

    return None


def build_dedupe_key(user_id: str, project: str, book_id: str, entity: str, attribute: str) -> str:
    return f"{user_id}|{project}|{book_id}|{entity}|{attribute}"


def dedupe_key_hash(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()


def _get_snapshot(doc_ref, transaction):
    if transaction is None:
        return doc_ref.get()
    return doc_ref.get(transaction=transaction)


def upsert_semantic_memory(
    *,
    user_id: str,
    project: str,
    book_id: str,
    extracted: ExtractedMemory,
    source_event_id: str,
) -> dict:
    dedupe_key = build_dedupe_key(user_id, project, book_id, extracted.entity, extracted.attribute)
    key_hash = dedupe_key_hash(dedupe_key)
    now = utc_now_iso()

    def _tx(transaction, *, key_hash: str, dedupe_key: str):
        key_ref = memory_keys_collection.document(key_hash)
        key_snapshot = _get_snapshot(key_ref, transaction)
        key_data = key_snapshot.to_dict() or {}
        active_memory_id = key_data.get("active_memory_id")
        new_version = 1

        if active_memory_id:
            active_ref = semantic_collection.document(active_memory_id)
            active_snapshot = _get_snapshot(active_ref, transaction)
            active_data = active_snapshot.to_dict() or {}

            if active_data and active_data.get("status") == "active":
                existing_value = normalize_text(active_data.get("value_text"))
                new_value = normalize_text(extracted.value_text)
                if existing_value == new_value:
                    return memory_dict_from_firestore(active_snapshot)

                updates = {
                    "status": "superseded",
                    "valid_to": now,
                    "updated_at": now,
                }
                if transaction is None:
                    active_ref.update(updates)
                else:
                    transaction.update(active_ref, updates)
                new_version = int(active_data.get("version") or 1) + 1

        memory_id = new_memory_id()
        new_data = {
            "id": memory_id,
            "user_id": user_id,
            "project": project,
            "book_id": book_id,
            "memory_type": extracted.memory_type,
            "entity": extracted.entity,
            "attribute": extracted.attribute,
            "value_text": _normalize_value(extracted.value_text),
            "context": extracted.context,
            "status": "active",
            "dedupe_key": dedupe_key,
            "version": new_version,
            "valid_from": now,
            "valid_to": None,
            "source_type": extracted.source_type,
            "source_event_id": source_event_id,
            "created_at": now,
            "updated_at": None,
        }
        new_ref = semantic_collection.document(memory_id)

        key_data = {
            "dedupe_key_hash": key_hash,
            "dedupe_key": dedupe_key,
            "active_memory_id": memory_id,
            "updated_at": now,
        }
        if transaction is None:
            new_ref.set(new_data)
            key_ref.set(key_data)
        else:
            transaction.set(new_ref, new_data)
            transaction.set(key_ref, key_data)
        return new_data

    return db.run_transaction(_tx, key_hash=key_hash, dedupe_key=dedupe_key)


def _filter_memories(items: Iterable[dict], *, user_id: str, project: Optional[str], book_id: Optional[str]) -> list[dict]:
    results = []
    for item in items:
        if item.get("user_id") != user_id:
            continue
        if item.get("status") != "active":
            continue
        if project and item.get("project") != project:
            continue
        if book_id and item.get("book_id") != book_id:
            continue
        if not is_semantic_memory_record(item):
            continue
        results.append(item)
    return results


def query_active_semantic_memories(user_id: str, project: Optional[str], book_id: Optional[str]) -> list[dict]:
    docs = semantic_collection.stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]
    return _filter_memories(items, user_id=user_id, project=project, book_id=book_id)


def audit_semantic_memories(*, dry_run: bool = True) -> dict:
    docs = semantic_collection.stream()
    memories = [memory_dict_from_firestore(doc) for doc in docs]
    findings = {
        "contaminated": [],
        "duplicate_active_keys": [],
        "invalid_status": [],
        "invalid_shape": [],
    }
    by_key: dict[str, list[dict]] = {}
    now = utc_now_iso()

    for memory in memories:
        status = memory.get("status")
        if status not in VALID_MEMORY_STATUS:
            findings["invalid_status"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": now})
            continue

        if not is_semantic_memory_record(memory):
            findings["invalid_shape"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": now})
            continue

        if text_contains_blocked_markers(memory.get("value_text"), memory.get("context")):
            findings["contaminated"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": now})
            continue

        key = memory.get("dedupe_key")
        if key and memory.get("status") == "active":
            by_key.setdefault(key, []).append(memory)

    for key, items in by_key.items():
        if len(items) <= 1:
            continue
        items_sorted = sorted(items, key=lambda x: int(x.get("version") or 1), reverse=True)
        keep = items_sorted[0]["id"]
        findings["duplicate_active_keys"].append({"dedupe_key": key, "active_ids": [x["id"] for x in items_sorted]})
        if not dry_run:
            for memory in items_sorted[1:]:
                semantic_collection.document(memory["id"]).update({"status": "superseded", "valid_to": now, "updated_at": now})
            memory_keys_collection.document(dedupe_key_hash(key)).set(
                {
                    "dedupe_key_hash": dedupe_key_hash(key),
                    "dedupe_key": key,
                    "active_memory_id": keep,
                    "updated_at": now,
                }
            )

    return findings
