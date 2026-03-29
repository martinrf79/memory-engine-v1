from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints
from typing import Annotated, Optional

from app.enums import MemoryStatus, MemoryType
from app.firestore_store import semantic_collection
from app.firestore_utils import memory_dict_from_firestore

router = APIRouter()

FilterStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class MemorySearchRequest(BaseModel):
    user_id: FilterStr = None
    project: FilterStr = None
    book_id: FilterStr = None
    memory_type: Optional[MemoryType] = None
    status: Optional[MemoryStatus] = None
    query: FilterStr = None


@router.post("/memories/search")
def search_memories(payload: MemorySearchRequest):
    docs = semantic_collection.stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]

    results = []
    text_query = payload.query.lower() if payload.query else None

    for item in items:
        if payload.user_id and item.get("user_id") != payload.user_id:
            continue
        if payload.project and item.get("project") != payload.project:
            continue
        if payload.book_id and item.get("book_id") != payload.book_id:
            continue
        if payload.memory_type and item.get("memory_type") != payload.memory_type.value:
            continue
        if payload.status and item.get("status") != payload.status.value:
            continue

        if text_query:
            haystack = " ".join(
                [
                    item.get("entity") or "",
                    item.get("attribute") or "",
                    item.get("value_text") or "",
                    item.get("context") or "",
                ]
            ).lower()

            if text_query not in haystack:
                continue

        results.append(item)

    return results
