from enum import Enum


def enum_to_value(value):
    if isinstance(value, Enum):
        return value.value
    return value


def memory_dict_from_payload(data: dict) -> dict:
    return {
        "id": data["id"],
        "user_id": data["user_id"],
        "project": data["project"],
        "book_id": data["book_id"],
        "memory_type": enum_to_value(data["memory_type"]),
        "status": enum_to_value(data["status"]),
        "content": data["content"],
        "summary": data["summary"],
        "user_message": data["user_message"],
        "assistant_answer": data["assistant_answer"],
        "trigger_query": data["trigger_query"],
        "importance": data.get("importance"),
        "keywords_json": data.get("keywords_json"),
        "embedding_json": data.get("embedding_json"),
        "source": data.get("source"),
        "created_at": data["created_at"],
        "updated_at": data.get("updated_at"),
    }


def memory_dict_from_firestore(doc) -> dict:
    data = doc.to_dict() or {}
    data["id"] = doc.id
    return data


def semantic_memory_dict_from_payload(data: dict) -> dict:
    return {
        "id": data["id"],
        "user_id": data["user_id"],
        "project": data["project"],
        "book_id": data["book_id"],
        "memory_type": data["memory_type"],
        "entity": data["entity"],
        "attribute": data["attribute"],
        "value_text": data["value_text"],
        "context": data.get("context"),
        "status": enum_to_value(data["status"]),
        "dedupe_key": data["dedupe_key"],
        "version": data["version"],
        "valid_from": data["valid_from"],
        "valid_to": data.get("valid_to"),
        "source_type": data["source_type"],
        "source_event_id": data["source_event_id"],
        "created_at": data["created_at"],
        "updated_at": data.get("updated_at"),
    }


def chat_event_dict_from_payload(data: dict) -> dict:
    return {
        "id": data["id"],
        "user_id": data["user_id"],
        "project": data["project"],
        "book_id": data["book_id"],
        "user_message": data["user_message"],
        "assistant_answer": data["assistant_answer"],
        "llm_provider": data["llm_provider"],
        "llm_model": data["llm_model"],
        "created_at": data["created_at"],
        "ttl_at": data.get("ttl_at"),
    }
