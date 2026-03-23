import re
import unicodedata
from typing import Annotated, Optional

from fastapi import APIRouter
from pydantic import BaseModel, Field, StringConstraints

from app.firestore_store import collection
from app.firestore_utils import memory_dict_from_firestore
from app.llm_service import generate_answer_from_memories, get_user_llm_settings
from app.utils import new_memory_id, utc_now_iso

router = APIRouter()

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]

STOPWORDS = {
    "que", "qué", "como", "cómo", "para", "por", "con", "sin", "una", "uno", "unos",
    "unas", "sobre", "desde", "hasta", "donde", "dónde", "cuando", "cuándo", "cual",
    "cuál", "cuales", "cuáles", "del", "las", "los", "hay", "fue", "son",
    "esta", "este", "estos", "estas", "de", "la", "el", "y", "o", "a", "en"
}


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


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text)
    text = "".join(char for char in text if not unicodedata.combining(char))
    return text.lower()


def extract_keywords(message: str) -> list[str]:
    normalized = normalize_text(message)
    words = re.findall(r"\b\w+\b", normalized)
    keywords = []

    for word in words:
        if len(word) < 3:
            continue
        if word in STOPWORDS:
            continue
        if word not in keywords:
            keywords.append(word)

    return keywords


def retrieve_memories(payload: ChatRequest) -> list[dict]:
    docs = collection.stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]

    keywords = extract_keywords(payload.message)
    if not keywords:
        keywords = [normalize_text(payload.message)]

    results = []

    for item in items:
        if item.get("user_id") != payload.user_id:
            continue
        if item.get("status") != "active":
            continue
        if payload.project and item.get("project") != payload.project:
            continue
        if payload.book_id and item.get("book_id") != payload.book_id:
            continue

        haystack = normalize_text(
            " ".join(
                [
                    item.get("content") or "",
                    item.get("summary") or "",
                    item.get("trigger_query") or "",
                    item.get("user_message") or "",
                    item.get("assistant_answer") or "",
                    item.get("project") or "",
                    item.get("book_id") or "",
                ]
            )
        )

        if any(keyword in haystack for keyword in keywords):
            results.append(item)

    return results[:10]


def build_chat_result(payload: ChatRequest, memories: list[dict]) -> dict:
    if not memories:
        return {
            "mode": "insufficient_memory",
            "answer": "No tengo memoria suficiente para responder con seguridad. Dame un dato más o indica proyecto y categoría.",
            "used_memories": [],
            "options": [],
        }

    used = [{"id": memory["id"], "summary": memory.get("summary", "")} for memory in memories]

    if not payload.project:
        projects = sorted({memory.get("project") for memory in memories if memory.get("project")})
        if len(projects) > 1:
            return {
                "mode": "clarification_required",
                "answer": "Encontré recuerdos en más de un proyecto. Indícame cuál quieres usar.",
                "used_memories": used,
                "options": projects,
            }

    if not payload.book_id:
        book_ids = sorted({memory.get("book_id") for memory in memories if memory.get("book_id")})
        if len(book_ids) > 1:
            return {
                "mode": "clarification_required",
                "answer": "Encontré recuerdos en más de una categoría. Indícame cuál quieres usar.",
                "used_memories": used,
                "options": book_ids,
            }

    settings = get_user_llm_settings(payload.user_id)
    answer_text = generate_answer_from_memories(settings, payload.message, memories)

    return {
        "mode": "answer",
        "answer": answer_text,
        "used_memories": used,
        "options": [],
    }


def save_chat_interaction(payload: ChatRequest, result: dict) -> None:
    if not payload.save_interaction:
        return

    now = utc_now_iso()
    options_text = ", ".join(result["options"]) if result["options"] else ""

    doc_ref = collection.document(new_memory_id())
    doc_ref.set(
        {
            "id": doc_ref.id,
            "user_id": payload.user_id,
            "project": payload.project or "general",
            "book_id": payload.book_id or "general",
            "memory_type": "conversation",
            "status": "active",
            "content": f"Usuario: {payload.message}\nAsistente: {result['answer']}\nOpciones: {options_text}",
            "summary": f"{result['mode']}: {payload.message[:80]}",
            "user_message": payload.message,
            "assistant_answer": result["answer"],
            "trigger_query": payload.message,
            "importance": None,
            "keywords_json": None,
            "embedding_json": None,
            "source": "chat",
            "created_at": now,
            "updated_at": None,
        }
    )


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest):
    memories = retrieve_memories(payload)
    result = build_chat_result(payload, memories)
    save_chat_interaction(payload, result)
    return result
