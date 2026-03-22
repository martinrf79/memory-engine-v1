from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, StringConstraints
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Memory
from app.utils import new_memory_id, utc_now_iso

router = APIRouter()

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class ChatRequest(BaseModel):
    user_id: NonEmptyStr
    message: NonEmptyStr
    project: OptionalNonEmptyStr = None
    book_id: OptionalNonEmptyStr = None
    save_interaction: bool = False


class UsedMemory(BaseModel):
    id: str
    summary: str


class ChatResponse(BaseModel):
    mode: str
    answer: str
    used_memories: list[UsedMemory]


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    db_query = db.query(Memory).filter(
        Memory.user_id == payload.user_id,
        Memory.status == "active",
    )

    if payload.project:
        db_query = db_query.filter(Memory.project == payload.project)

    if payload.book_id:
        db_query = db_query.filter(Memory.book_id == payload.book_id)

    q = payload.message.lower()
    db_query = db_query.filter(
        or_(
            func.lower(Memory.content).contains(q),
            func.lower(Memory.summary).contains(q),
            func.lower(Memory.trigger_query).contains(q),
            func.lower(Memory.user_message).contains(q),
            func.lower(Memory.assistant_answer).contains(q),
        )
    )

    memories = db_query.limit(5).all()

    if not memories:
        answer_text = "No tengo memoria suficiente para responder con seguridad."
        mode = "insufficient_memory"
        used = []
    else:
        used = [{"id": memory.id, "summary": memory.summary} for memory in memories]
        context_parts = [memory.summary for memory in memories if memory.summary]

        if len(context_parts) == 1:
            mode = "answer"
            answer_text = f"Según la memoria encontrada: {context_parts[0]}"
        else:
            mode = "answer"
            answer_text = "Según las memorias encontradas: " + " | ".join(context_parts)

    if payload.save_interaction:
        now = utc_now_iso()
        conversation_memory = Memory(
            id=new_memory_id(),
            user_id=payload.user_id,
            project=payload.project or "general",
            book_id=payload.book_id or "general",
            memory_type="conversation",
            status="active",
            content=f"Usuario: {payload.message}\nAsistente: {answer_text}",
            summary=f"Interacción sobre: {payload.message[:80]}",
            user_message=payload.message,
            assistant_answer=answer_text,
            trigger_query=payload.message,
            importance=None,
            keywords_json=None,
            embedding_json=None,
            source="chat",
            created_at=now,
            updated_at=None,
        )
        db.add(conversation_memory)
        db.commit()

    return {
        "mode": mode,
        "answer": answer_text,
        "used_memories": used,
    }
