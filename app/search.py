from fastapi import APIRouter
from pydantic import BaseModel, StringConstraints
from typing import Annotated, Optional

from app.enums import MemoryStatus, MemoryType
from app.firestore_store import collection
from app.firestore_utils import memory_dict_from_firestore
from app.schemas import MemoryResponse

router = APIRouter()

FilterStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class MemorySearchRequest(BaseModel):
    user_id: FilterStr = None
    project: FilterStr = None
    book_id: FilterStr = None
    memory_type: Optional[MemoryType] = None
    status: Optional[MemoryStatus] = None
    query: FilterStr = None


@router.post("/memories/search", response_model=list[MemoryResponse])
def search_memories(payload: MemorySearchRequest):
    docs = collection.stream()
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
                    item.get("content") or "",
                    item.get("summary") or "",
                    item.get("trigger_query") or "",
                    item.get("user_message") or "",
                    item.get("assistant_answer") or "",
                ]
            ).lower()

            if text_query not in haystack:
                continue

        results.append(item)

    return results
