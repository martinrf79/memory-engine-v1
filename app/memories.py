from fastapi import APIRouter, HTTPException

from app.firestore_store import collection
from app.firestore_utils import memory_dict_from_firestore, memory_dict_from_payload
from app.schemas import MemoryCreate, MemoryResponse
from app.utils import utc_now_iso

router = APIRouter()


@router.post("/memories", response_model=MemoryResponse)
def create_memory(payload: MemoryCreate):
    doc_ref = collection.document(payload.id)
    existing = doc_ref.get()

    if existing.exists:
        raise HTTPException(status_code=400, detail="Memory with this id already exists")

    data = payload.model_dump()

    if not data.get("created_at"):
        data["created_at"] = utc_now_iso()

    memory_data = memory_dict_from_payload(data)
    doc_ref.set(memory_data)

    created = doc_ref.get()
    return memory_dict_from_firestore(created)


@router.get("/memories", response_model=list[MemoryResponse])
def list_memories():
    docs = collection.stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]
    return items
