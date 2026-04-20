from typing import Optional

from fastapi import APIRouter, Depends

from app.config import settings
from app.core_legacy_adapter import list_scope_items
from app.dependencies import require_internal_access
from app.firestore_store import chat_events_collection
from app.firestore_utils import memory_dict_from_firestore

router = APIRouter(include_in_schema=settings.expose_internal_routes, tags=["internal"], dependencies=[Depends(require_internal_access)])


@router.get("/memories/export")
def export_memories(
    user_id: Optional[str] = None,
    project: Optional[str] = None,
    status: Optional[str] = None,
):
    if not user_id:
        return {"count": 0, "items": []}
    items = list_scope_items(user_id=user_id, project=project, include_inactive=True)
    if status:
        items = [item for item in items if item.get("status") == status]
    return {"count": len(items), "items": items}


@router.get("/chat-events/export")
def export_chat_events(
    user_id: Optional[str] = None,
    project: Optional[str] = None,
):
    docs = chat_events_collection.stream()
    items = []
    for doc in docs:
        item = memory_dict_from_firestore(doc)
        if user_id and item.get("user_id") != user_id:
            continue
        if project and item.get("project") != project:
            continue
        items.append(item)
    return {"count": len(items), "items": items}
