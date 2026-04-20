from app.memory_core_v1 import MemoryScope, save_fact


def seed_operational_memories(user_id: str, project: str, book_id: str = "general") -> list[dict]:
    scope = MemoryScope(tenant_id=user_id, user_id=user_id, project_id=project, book_id=book_id, entity_type="generic", entity_id="generic")
    records = [
        ("test_config", "user_id", user_id),
        ("test_config", "project", project),
        ("test_rule", "avoid_user_id_default", "No usar user_id=default"),
        ("test_rule", "ask_for_missing_data", "Si falta información, pedirla"),
        ("test_rule", "do_not_invent", "No inventar"),
        ("test_rule", "ask_clarification_on_ambiguity", "Si hay ambigüedad, pedir aclaración"),
    ]

    results = []
    for subject, relation, obj in records:
        results.append(save_fact(scope, subject=subject, relation=relation, object_value=obj, source_event_id=f"seed:{subject}:{relation}"))
    return results
