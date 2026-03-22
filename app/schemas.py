from typing import Optional

from pydantic import BaseModel, ConfigDict


class MemoryBase(BaseModel):
    user_id: str
    project: str
    book_id: str
    memory_type: str
    status: str = "active"
    content: str
    summary: str
    user_message: str
    assistant_answer: str
    trigger_query: str
    importance: Optional[int] = None
    keywords_json: Optional[str] = None
    embedding_json: Optional[str] = None
    source: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None


class MemoryCreate(MemoryBase):
    id: str


class MemoryUpdate(BaseModel):
    project: Optional[str] = None
    book_id: Optional[str] = None
    memory_type: Optional[str] = None
    status: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    user_message: Optional[str] = None
    assistant_answer: Optional[str] = None
    trigger_query: Optional[str] = None
    importance: Optional[int] = None
    keywords_json: Optional[str] = None
    embedding_json: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[str] = None


class MemoryResponse(MemoryBase):
    id: str

    model_config = ConfigDict(from_attributes=True)
