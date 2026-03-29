from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, StringConstraints, field_validator

from app.enums import MemoryStatus, MemoryType

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class MemoryBase(BaseModel):
    user_id: NonEmptyStr
    project: NonEmptyStr
    book_id: NonEmptyStr
    memory_type: MemoryType
    status: MemoryStatus = MemoryStatus.active
    content: NonEmptyStr
    summary: NonEmptyStr
    user_message: NonEmptyStr
    assistant_answer: NonEmptyStr
    trigger_query: NonEmptyStr
    importance: Optional[int] = None
    keywords_json: Optional[str] = None
    embedding_json: Optional[str] = None
    source: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_datetime_string(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be a valid ISO 8601 datetime") from exc

        return parsed.isoformat().replace("+00:00", "Z")


class MemoryCreate(MemoryBase):
    id: NonEmptyStr


class MemoryUpdate(BaseModel):
    project: OptionalNonEmptyStr = None
    book_id: OptionalNonEmptyStr = None
    memory_type: Optional[MemoryType] = None
    status: Optional[MemoryStatus] = None
    content: OptionalNonEmptyStr = None
    summary: OptionalNonEmptyStr = None
    user_message: OptionalNonEmptyStr = None
    assistant_answer: OptionalNonEmptyStr = None
    trigger_query: OptionalNonEmptyStr = None
    importance: Optional[int] = None
    keywords_json: Optional[str] = None
    embedding_json: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be a valid ISO 8601 datetime") from exc

        return parsed.isoformat().replace("+00:00", "Z")


class MemoryResponse(MemoryBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


class SemanticMemoryBase(BaseModel):
    user_id: NonEmptyStr
    project: NonEmptyStr
    book_id: NonEmptyStr
    memory_type: NonEmptyStr
    entity: NonEmptyStr
    attribute: NonEmptyStr
    value_text: NonEmptyStr
    context: Optional[str] = None
    status: MemoryStatus = MemoryStatus.active
    dedupe_key: NonEmptyStr
    version: int = 1
    valid_from: NonEmptyStr
    valid_to: Optional[str] = None
    source_type: NonEmptyStr
    source_event_id: NonEmptyStr
    created_at: NonEmptyStr
    updated_at: Optional[str] = None


class SemanticMemoryResponse(SemanticMemoryBase):
    id: str


class ChatEventBase(BaseModel):
    user_id: NonEmptyStr
    project: NonEmptyStr
    book_id: NonEmptyStr
    user_message: NonEmptyStr
    assistant_answer: NonEmptyStr
    llm_provider: NonEmptyStr
    llm_model: NonEmptyStr
    created_at: NonEmptyStr
    ttl_at: Optional[str] = None


class ChatEventResponse(ChatEventBase):
    id: str
