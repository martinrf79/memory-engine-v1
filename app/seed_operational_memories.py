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
        ExtractedMemory(
            memory_type="constraint",
            entity="test_rule",
            attribute="avoid_user_id_default",
            value_text="No usar user_id=default",
            context="No usar user_id default",
            source_type="seed",
        ),
        ExtractedMemory(
            memory_type="instruction",
            entity="test_rule",
            attribute="ask_for_missing_data",
            value_text="Si falta información, pedirla",
            context="Si falta dato, pedirlo",
            source_type="seed",
        ),
        ExtractedMemory(
            memory_type="constraint",
            entity="test_rule",
            attribute="do_not_invent",
            value_text="No inventar",
            context="No inventar",
            source_type="seed",
        ),
        ExtractedMemory(
            memory_type="instruction",
            entity="test_rule",
            attribute="ask_clarification_on_ambiguity",
            value_text="Si hay ambigüedad, pedir aclaración",
            context="Si hay ambigüedad, pedir aclaración",
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
