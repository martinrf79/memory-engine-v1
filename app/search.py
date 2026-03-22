from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.enums import MemoryStatus, MemoryType
from app.models import Memory
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
def search_memories(payload: MemorySearchRequest, db: Session = Depends(get_db)):
    db_query = db.query(Memory)

    if payload.user_id:
        db_query = db_query.filter(Memory.user_id == payload.user_id)
    if payload.project:
        db_query = db_query.filter(Memory.project == payload.project)
    if payload.book_id:
        db_query = db_query.filter(Memory.book_id == payload.book_id)
    if payload.memory_type:
        db_query = db_query.filter(Memory.memory_type == payload.memory_type)
    if payload.status:
        db_query = db_query.filter(Memory.status == payload.status)

    if payload.query:
        q = payload.query.lower()
        db_query = db_query.filter(
            or_(
                func.lower(Memory.content).contains(q),
                func.lower(Memory.summary).contains(q),
                func.lower(Memory.trigger_query).contains(q),
                func.lower(Memory.user_message).contains(q),
                func.lower(Memory.assistant_answer).contains(q),
            )
        )

    return db_query.all()
