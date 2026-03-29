from app.semantic_memory import ExtractedMemory, upsert_semantic_memory
from app.utils import new_memory_id


def seed_operational_memories(user_id: str, project: str, book_id: str = "general") -> list[dict]:
    source_event_id = f"seed-{new_memory_id()}"
    records = [
        ExtractedMemory(
            memory_type="instruction",
            entity="test_config",
            attribute="user_id",
            value_text=user_id,
            context=f"El user_id de pruebas es {user_id}",
            source_type="seed",
        ),
        ExtractedMemory(
            memory_type="instruction",
            entity="test_config",
            attribute="project",
            value_text=project,
            context=f"El project de pruebas es {project}",
            source_type="seed",
        ),
    ]

    results = []
    for record in records:
        results.append(
            upsert_semantic_memory(
                user_id=user_id,
                project=project,
                book_id=book_id,
                extracted=record,
                source_event_id=source_event_id,
            )
        )
    return results
