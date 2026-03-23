from fastapi import APIRouter, HTTPException

from app.firestore_store import collection
from app.firestore_utils import enum_to_value, memory_dict_from_firestore
from app.schemas import MemoryResponse, MemoryUpdate
from app.utils import utc_now_iso

router = APIRouter()


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
def update_memory(memory_id: str, payload: MemoryUpdate):
    doc_ref = collection.document(memory_id)
    existing = doc_ref.get()

    if not existing.exists:
        raise HTTPException(status_code=404, detail="Memory not found")

    updates = payload.model_dump(exclude_unset=True)

    if "updated_at" not in updates:
        updates["updated_at"] = utc_now_iso()

    updates = {field: enum_to_value(value) for field, value in updates.items()}

    doc_ref.update(updates)
    updated = doc_ref.get()
    return memory_dict_from_firestore(updated)


@router.post("/memories/{memory_id}/archive", response_model=MemoryResponse)
def archive_memory(memory_id: str):
    doc_ref = collection.document(memory_id)
    existing = doc_ref.get()

    if not existing.exists:
        raise HTTPException(status_code=404, detail="Memory not found")

    doc_ref.update(
        {
            "status": "archived",
            "updated_at": utc_now_iso(),
        }
    )

    updated = doc_ref.get()
    return memory_dict_from_firestore(updated)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str):
    doc_ref = collection.document(memory_id)
    existing = doc_ref.get()

    if not existing.exists:
        raise HTTPException(status_code=404, detail="Memory not found")

    doc_ref.delete()
    return {"status": "deleted", "id": memory_id}
