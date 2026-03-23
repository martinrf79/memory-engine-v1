from typing import Optional

from fastapi import APIRouter

from app.firestore_store import collection
from app.firestore_utils import memory_dict_from_firestore

router = APIRouter()


@router.get("/memories/export")
def export_memories(
    user_id: Optional[str] = None,
    project: Optional[str] = None,
    status: Optional[str] = None,
):
    docs = collection.stream()
    items = []

    for doc in docs:
        item = memory_dict_from_firestore(doc)

        if user_id and item.get("user_id") != user_id:
            continue
        if project and item.get("project") != project:
            continue
        if status and item.get("status") != status:
            continue

        items.append(item)

    return {"count": len(items), "items": items}
