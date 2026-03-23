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
        return "No tengo memoria suficiente para responder con seguridad."

    if settings.provider == "mock":
        if len(summaries) == 1:
            return f"Según la memoria encontrada: {summaries[0]}"
        return "Según las memorias encontradas: " + " | ".join(summaries)

    return "Proveedor LLM no soportado todavía."
