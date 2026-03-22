from typing import Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Memory

router = APIRouter()


@router.get("/memories/export")
def export_memories(
    user_id: Optional[str] = None,
    project: Optional[str] = None,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
):
    db_query = db.query(Memory)

    if user_id:
        db_query = db_query.filter(Memory.user_id == user_id)
    if project:
        db_query = db_query.filter(Memory.project == project)
    if status:
        db_query = db_query.filter(Memory.status == status)

    memories = db_query.all()

    items = []
    for memory in memories:
        items.append(
            {
                "id": memory.id,
                "user_id": memory.user_id,
                "project": memory.project,
                "book_id": memory.book_id,
                "memory_type": memory.memory_type,
                "status": memory.status,
                "content": memory.content,
                "summary": memory.summary,
                "user_message": memory.user_message,
                "assistant_answer": memory.assistant_answer,
                "trigger_query": memory.trigger_query,
                "importance": memory.importance,
                "keywords_json": memory.keywords_json,
                "embedding_json": memory.embedding_json,
                "source": memory.source,
                "created_at": memory.created_at,
                "updated_at": memory.updated_at,
            }
        )

    return {"count": len(items), "items": items}
