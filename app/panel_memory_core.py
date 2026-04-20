"""
Wrapper de compatibilidad que delega al memory_engine V2.

Mantiene las firmas públicas (panel_chat_fallback, store_panel_manual_memory,
is_question, build_panel_scope) para no romper imports existentes en auth.py.
"""
from __future__ import annotations

from typing import Optional

from app.memory_engine import (
    Scope,
    get_engine,
    is_question,  # re-exportado
)


def build_panel_scope(*, user_id: str, project: str, book_id: str) -> Scope:
    return Scope.from_panel(user_id=user_id, project=project, book_id=book_id)


def store_panel_manual_memory(*, user_id: str, project: str, book_id: str, content: str) -> dict:
    """
    Guarda contenido como memoria. Mantiene compat shape con la versión anterior.
    """
    scope = build_panel_scope(user_id=user_id, project=project, book_id=book_id)
    engine = get_engine()
    result = engine.remember(scope, content, source="panel_manual")

    base = {"id": result.entry_id}
    return {
        "event": base,
        "note": base if result.facts_extracted == 0 else None,
        "fact": base if result.facts_extracted > 0 else None,
        "mode": result.mode,
        "message": result.message,
        "superseded_ids": result.superseded_ids,
    }


def panel_chat_fallback(*, user_id: str, project: str, book_id: str, message: str) -> Optional[dict]:
    """
    Responde una pregunta usando solo la memoria guardada.
    Devuelve None si el mensaje no es pregunta o no hay match confiable.
    """
    scope = build_panel_scope(user_id=user_id, project=project, book_id=book_id)
    engine = get_engine()
    result = engine.recall(scope, message)

    if result.mode != "answer" or not result.answer:
        return None

    return {
        "mode": "answer",
        "answer": result.answer,
        "used_memories": [
            {"id": u["id"], "summary": u["content"]} for u in result.used_entries
        ],
        "options": [],
    }


__all__ = [
    "build_panel_scope",
    "store_panel_manual_memory",
    "panel_chat_fallback",
    "is_question",
]
