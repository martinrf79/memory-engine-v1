from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints

from app.config import settings
from app.core_legacy_adapter import list_scope_items, search_legacy_memories
from app.dependencies import require_internal_access
from app.enums import MemoryStatus, MemoryType

router = APIRouter(include_in_schema=settings.expose_internal_routes, tags=["internal"], dependencies=[Depends(require_internal_access)])

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
    if not payload.user_id:
        return []
    project = payload.project or "general"
    book_id = payload.book_id or "general"
    if payload.query:
        items = search_legacy_memories(user_id=payload.user_id, project=project, book_id=book_id, query=payload.query, top_k=20)
    else:
        items = list_scope_items(user_id=payload.user_id, project=payload.project, book_id=payload.book_id, include_inactive=True)
    if payload.memory_type:
        items = [item for item in items if item.get("memory_type") == payload.memory_type.value]
    if payload.status:
        items = [item for item in items if item.get("status") == payload.status.value]
    if payload.project:
        items = [item for item in items if item.get("project") == payload.project]
    if payload.book_id:
        items = [item for item in items if item.get("book_id") == payload.book_id]
    return items
