from typing import Annotated, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, StringConstraints
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
    options: list[str] = Field(default_factory=list)


def retrieve_memories(payload: ChatRequest, db: Session) -> list[Memory]:
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

    return db_query.limit(10).all()


def build_chat_result(payload: ChatRequest, memories: list[Memory]) -> dict:
    if not memories:
        return {
            "mode": "insufficient_memory",
            "answer": "No tengo memoria suficiente para responder con seguridad. Dame un dato más o indica proyecto y categoría.",
            "used_memories": [],
            "options": [],
        }

    used = [{"id": memory.id, "summary": memory.summary} for memory in memories]

    if not payload.project:
        projects = sorted({memory.project for memory in memories if memory.project})
        if len(projects) > 1:
            return {
                "mode": "clarification_required",
                "answer": "Encontré recuerdos en más de un proyecto. Indícame cuál quieres usar.",
                "used_memories": used,
                "options": projects,
            }

    if not payload.book_id:
        book_ids = sorted({memory.book_id for memory in memories if memory.book_id})
        if len(book_ids) > 1:
            return {
                "mode": "clarification_required",
                "answer": "Encontré recuerdos en más de una categoría. Indícame cuál quieres usar.",
                "used_memories": used,
                "options": book_ids,
            }

    context_parts = [memory.summary for memory in memories if memory.summary]

    if len(context_parts) == 1:
        answer_text = f"Según la memoria encontrada: {context_parts[0]}"
    else:
        answer_text = "Según las memorias encontradas: " + " | ".join(context_parts)

    return {
        "mode": "answer",
        "answer": answer_text,
        "used_memories": used,
        "options": [],
    }


def save_chat_interaction(payload: ChatRequest, result: dict, db: Session) -> None:
    if not payload.save_interaction:
        return

    now = utc_now_iso()
    options_text = ", ".join(result["options"]) if result["options"] else ""

    conversation_memory = Memory(
        id=new_memory_id(),
        user_id=payload.user_id,
        project=payload.project or "general",
        book_id=payload.book_id or "general",
        memory_type="conversation",
        status="active",
        content=f"Usuario: {payload.message}\nAsistente: {result['answer']}\nOpciones: {options_text}",
        summary=f"{result['mode']}: {payload.message[:80]}",
        user_message=payload.message,
        assistant_answer=result["answer"],
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


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    memories = retrieve_memories(payload, db)
    result = build_chat_result(payload, memories)
    save_chat_interaction(payload, result, db)
    return result
