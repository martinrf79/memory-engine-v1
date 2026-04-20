from fastapi import APIRouter, Depends

from app.config import settings
from app.core_legacy_adapter import create_from_legacy_payload, list_scope_items
from app.dependencies import require_internal_access
from app.schemas import MemoryCreate

router = APIRouter(include_in_schema=settings.expose_internal_routes, tags=["internal"], dependencies=[Depends(require_internal_access)])


@router.post("/memories")
def create_memory(payload: MemoryCreate):
    return create_from_legacy_payload(payload)


@router.get("/memories")
def list_memories(user_id: str | None = None, project: str | None = None, book_id: str | None = None, include_inactive: bool = True):
    if not user_id:
        return []
    return list_scope_items(user_id=user_id, project=project, book_id=book_id, include_inactive=include_inactive)
