from app.llm_settings import UserLLMSettings


def get_user_llm_settings(user_id: str) -> UserLLMSettings:
    return UserLLMSettings(user_id=user_id)


def generate_answer_from_memories(
    settings: UserLLMSettings,
    user_message: str,
    memories: list[dict],
) -> str:
    summaries = [memory.get("summary") for memory in memories if memory.get("summary")]

    if not summaries:
        return "No tengo ese dato todavía."

    if settings.provider == "mock":
        return summaries[0]

    return "Proveedor LLM no soportado todavía."
