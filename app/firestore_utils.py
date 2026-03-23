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
