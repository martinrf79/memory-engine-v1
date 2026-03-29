from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Optional

from app.firestore_store import db, memory_keys_collection, semantic_collection
from app.firestore_utils import memory_dict_from_firestore
from app.utils import new_memory_id, utc_now_iso


VALID_MEMORY_STATUS = {"active", "superseded", "archived"}


@dataclass
class ExtractedMemory:
    memory_type: str
    entity: str
    attribute: str
    value_text: str
    context: Optional[str] = None
    source_type: str = "chat_user_message"


def _normalize_value(value: str) -> str:
    return value.strip().strip(".").strip()


def is_recordable_user_message(message: str) -> bool:
    lowered = message.lower()
    blocked_markers = [
        "insufficient_memory",
        "error:",
        "traceback",
        "según la memoria",
        "answer:",
    ]
    return not any(marker in lowered for marker in blocked_markers)


def extract_structured_memory(message: str) -> Optional[ExtractedMemory]:
    if not is_recordable_user_message(message):
        return None

    rules = [
        (r"mi color favorito es ([a-záéíóúñ]+)", "preference", "user", "favorite_color"),
        (r"prefiero ([a-záéíóúñ]+)", "preference", "user", "preference"),
        (r"mi comida favorita es ([a-záéíóúñ ]+)", "preference", "user", "favorite_food"),
    ]

    normalized = message.strip().lower()
    for pattern, memory_type, entity, attribute in rules:
        match = re.search(pattern, normalized)
        if not match:
            continue
        return ExtractedMemory(
            memory_type=memory_type,
            entity=entity,
            attribute=attribute,
            value_text=_normalize_value(match.group(1)),
            context=message.strip(),
        )

    return None


def build_dedupe_key(user_id: str, project: str, book_id: str, entity: str, attribute: str) -> str:
    return f"{user_id}|{project}|{book_id}|{entity}|{attribute}"


def dedupe_key_hash(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()


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
        key_snapshot = key_ref.get() if transaction is None else key_ref.get(transaction=transaction)
        key_data = key_snapshot.to_dict() or {}
        active_memory_id = key_data.get("active_memory_id")

        if active_memory_id:
            active_ref = semantic_collection.document(active_memory_id)
            active_snapshot = active_ref.get() if transaction is None else active_ref.get(transaction=transaction)
            active_data = active_snapshot.to_dict() or {}

            if active_data and active_data.get("status") == "active":
                if (active_data.get("value_text") or "").strip().lower() == extracted.value_text.lower():
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
            else:
                new_version = 1
        else:
            new_version = 1

        memory_id = new_memory_id()
        new_data = {
            "id": memory_id,
            "user_id": user_id,
            "project": project,
            "book_id": book_id,
            "memory_type": extracted.memory_type,
            "entity": extracted.entity,
            "attribute": extracted.attribute,
            "value_text": extracted.value_text,
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


def query_active_semantic_memories(user_id: str, project: Optional[str], book_id: Optional[str]) -> list[dict]:
    docs = semantic_collection.stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]
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
        results.append(item)
    return results


def audit_semantic_memories(*, dry_run: bool = True) -> dict:
    docs = semantic_collection.stream()
    memories = [memory_dict_from_firestore(doc) for doc in docs]
    findings = {"contaminated": [], "duplicate_active_keys": [], "invalid_status": []}
    by_key: dict[str, list[dict]] = {}

    for memory in memories:
        status = memory.get("status")
        if status not in VALID_MEMORY_STATUS:
            findings["invalid_status"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": utc_now_iso()})
            continue

        text = " ".join(
            [
                memory.get("value_text") or "",
                memory.get("context") or "",
            ]
        ).lower()
        if any(marker in text for marker in ("insufficient_memory", "answer:", "traceback", "error:")):
            findings["contaminated"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": utc_now_iso()})

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
                semantic_collection.document(memory["id"]).update(
                    {"status": "superseded", "valid_to": utc_now_iso(), "updated_at": utc_now_iso()}
                )
            memory_keys_collection.document(dedupe_key_hash(key)).set(
                {
                    "dedupe_key_hash": dedupe_key_hash(key),
                    "dedupe_key": key,
                    "active_memory_id": keep,
                    "updated_at": utc_now_iso(),
                }
            )

    return findings
