from fastapi import APIRouter, HTTPException

from app.firestore_store import semantic_collection
from app.firestore_utils import memory_dict_from_firestore, memory_dict_from_payload
from app.schemas import MemoryCreate
from app.semantic_memory import build_dedupe_key
from app.utils import utc_now_iso

router = APIRouter()


@router.post("/memories")
def create_memory(payload: MemoryCreate):
    doc_ref = semantic_collection.document(payload.id)
    existing = doc_ref.get()

    if existing.exists:
        raise HTTPException(status_code=400, detail="Memory with this id already exists")

    data = payload.model_dump()

    if not data.get("created_at"):
        data["created_at"] = utc_now_iso()

    memory_data = memory_dict_from_payload(data)
    memory_data = {
        "id": memory_data["id"],
        "user_id": memory_data["user_id"],
        "project": memory_data["project"],
        "book_id": memory_data["book_id"],
        "memory_type": memory_data["memory_type"],
        "entity": "legacy",
        "attribute": memory_data.get("trigger_query") or "fact",
        "value_text": memory_data.get("content"),
        "context": memory_data.get("summary"),
        "status": memory_data["status"],
        "dedupe_key": build_dedupe_key(
            memory_data["user_id"],
            memory_data["project"],
            memory_data["book_id"],
            "legacy",
            memory_data.get("trigger_query") or "fact",
        ),
        "version": 1,
        "valid_from": memory_data["created_at"],
        "valid_to": None,
        "source_type": memory_data.get("source") or "legacy_api",
        "source_event_id": memory_data["id"],
        "created_at": memory_data["created_at"],
        "updated_at": memory_data.get("updated_at"),
    }
    doc_ref.set(memory_data)

    created = doc_ref.get()
    return memory_dict_from_firestore(created)


@router.get("/memories")
def list_memories():
    docs = semantic_collection.stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]
    return items
