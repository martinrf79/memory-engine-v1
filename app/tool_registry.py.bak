from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.chat import ChatRequest, chat
from app.memory_core_v1 import (
    build_scope,
    fetch_memory,
    list_books,
    save_event,
    save_fact,
    save_note,
    save_session_summary,
    search_memory,
)


class ToolExecutionError(Exception):
    def __init__(self, code: str, message: str | None = None, status_code: int = 400):
        super().__init__(message or code)
        self.code = code
        self.message = message or code
        self.status_code = status_code


@dataclass(frozen=True)
class ToolDefinition:
    name: str
    title: str
    description: str
    input_schema: dict[str, Any]
    annotations: dict[str, Any] | None = None


def _json_schema(properties: dict[str, dict[str, Any]], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


TOOL_DEFINITIONS: dict[str, ToolDefinition] = {
    "search_memory": ToolDefinition(
        name="search_memory",
        title="Buscar memoria",
        description="Busca recuerdos por tenant, proyecto, libro y entidad.",
        input_schema=_json_schema(
            {
                "tenant_id": {"type": "string", "description": "Tenant o espacio dueño de la memoria"},
                "project_id": {"type": "string", "description": "Proyecto activo"},
                "book_id": {"type": "string", "description": "Libro de memoria"},
                "entity_type": {"type": "string", "description": "Tipo de entidad"},
                "entity_id": {"type": "string", "description": "Entidad concreta"},
                "query": {"type": "string", "description": "Consulta de búsqueda"},
                "top_k": {"type": "integer", "description": "Máximo de resultados"},
            },
            ["tenant_id", "project_id", "book_id", "query"],
        ),
        annotations={"readOnlyHint": True},
    ),
    "fetch_memory": ToolDefinition(
        name="fetch_memory",
        title="Traer memoria",
        description="Trae recuerdos exactos por id.",
        input_schema=_json_schema(
            {
                "tenant_id": {"type": "string", "description": "Tenant o espacio dueño de la memoria"},
                "project_id": {"type": "string", "description": "Proyecto activo"},
                "book_id": {"type": "string", "description": "Libro de memoria"},
                "memory_ids": {"type": "array", "description": "Ids a recuperar", "items": {"type": "string"}},
            },
            ["tenant_id", "project_id", "book_id", "memory_ids"],
        ),
        annotations={"readOnlyHint": True},
    ),
    "save_note": ToolDefinition(
        name="save_note",
        title="Guardar nota",
        description="Guarda una nota explícita y persistente.",
        input_schema=_json_schema(
            {
                "tenant_id": {"type": "string", "description": "Tenant o espacio dueño de la memoria"},
                "project_id": {"type": "string", "description": "Proyecto activo"},
                "book_id": {"type": "string", "description": "Libro de memoria"},
                "entity_type": {"type": "string", "description": "Tipo de entidad"},
                "entity_id": {"type": "string", "description": "Entidad concreta"},
                "title": {"type": "string", "description": "Título de la nota"},
                "content": {"type": "string", "description": "Contenido de la nota"},
            },
            ["tenant_id", "project_id", "book_id", "content"],
        ),
    ),
    "save_fact": ToolDefinition(
        name="save_fact",
        title="Guardar hecho",
        description="Guarda un hecho estructurado y supersede el anterior si cambia.",
        input_schema=_json_schema(
            {
                "tenant_id": {"type": "string", "description": "Tenant o espacio dueño de la memoria"},
                "project_id": {"type": "string", "description": "Proyecto activo"},
                "book_id": {"type": "string", "description": "Libro de memoria"},
                "entity_type": {"type": "string", "description": "Tipo de entidad"},
                "entity_id": {"type": "string", "description": "Entidad concreta"},
                "subject": {"type": "string", "description": "Sujeto del hecho"},
                "relation": {"type": "string", "description": "Relación del hecho"},
                "object": {"type": "string", "description": "Valor u objeto del hecho"},
                "confidence": {"type": "number", "description": "Confianza del hecho"},
                "evidence_doc_ids": {"type": "array", "description": "Ids de evidencia", "items": {"type": "string"}},
            },
            ["tenant_id", "project_id", "book_id", "subject", "relation", "object"],
        ),
    ),
    "list_books": ToolDefinition(
        name="list_books",
        title="Listar libros",
        description="Lista los libros detectados para un proyecto.",
        input_schema=_json_schema(
            {
                "tenant_id": {"type": "string", "description": "Tenant o espacio dueño de la memoria"},
                "project_id": {"type": "string", "description": "Proyecto activo"},
            },
            ["tenant_id", "project_id"],
        ),
        annotations={"readOnlyHint": True},
    ),
    "save_session_summary": ToolDefinition(
        name="save_session_summary",
        title="Guardar resumen",
        description="Guarda un resumen por sesión.",
        input_schema=_json_schema(
            {
                "tenant_id": {"type": "string", "description": "Tenant o espacio dueño de la memoria"},
                "project_id": {"type": "string", "description": "Proyecto activo"},
                "book_id": {"type": "string", "description": "Libro de memoria"},
                "entity_type": {"type": "string", "description": "Tipo de entidad"},
                "entity_id": {"type": "string", "description": "Entidad concreta"},
                "session_id": {"type": "string", "description": "Sesión a resumir"},
                "summary": {"type": "string", "description": "Resumen de la sesión"},
                "new_facts": {"type": "array", "description": "Nuevos hechos", "items": {"type": "object"}},
                "updated_facts": {"type": "array", "description": "Hechos actualizados", "items": {"type": "object"}},
                "open_questions": {"type": "array", "description": "Preguntas abiertas", "items": {"type": "string"}},
                "decisions": {"type": "array", "description": "Decisiones", "items": {"type": "string"}},
            },
            ["tenant_id", "project_id", "book_id", "summary"],
        ),
    ),
    "memory_chat": ToolDefinition(
        name="memory_chat",
        title="Chat con memoria",
        description="Consulta el chat del backend con memoria del usuario.",
        input_schema=_json_schema(
            {
                "user_id": {"type": "string", "description": "Identificador del usuario"},
                "project": {"type": "string", "description": "Proyecto activo"},
                "book_id": {"type": "string", "description": "Libro de memoria"},
                "message": {"type": "string", "description": "Mensaje actual del usuario"},
            },
            ["message"],
        ),
    ),
}


def list_tool_definitions(names: list[str] | None = None) -> list[ToolDefinition]:
    items = TOOL_DEFINITIONS
    if names is None:
        return list(items.values())
    return [items[name] for name in names if name in items]


MEMORY_TOOL_NAMES = [
    "search_memory",
    "fetch_memory",
    "save_note",
    "save_fact",
    "list_books",
    "save_session_summary",
]


def execute_tool(tool_name: str, arguments: dict[str, Any] | None, *, principal_user_id: str, source: str = "bridge") -> dict[str, Any]:
    args = arguments or {}
    if tool_name == "memory_chat":
        payload = ChatRequest(
            user_id=str(args.get("user_id") or principal_user_id),
            project=args.get("project"),
            book_id=args.get("book_id"),
            message=str(args.get("message") or "").strip(),
        )
        if not payload.message:
            raise ToolExecutionError("message_required")
        response = chat(payload)
        return response if isinstance(response, dict) else response.model_dump()

    scope = build_scope(args, principal_user_id=principal_user_id)

    if tool_name == "search_memory":
        query = str(args.get("query") or "").strip()
        if not query:
            raise ToolExecutionError("query_required")
        result = search_memory(scope, query, top_k=int(args.get("top_k") or 8))
        save_event(scope, "tool", f"search_memory: {query}", source=source)
        return result

    if tool_name == "fetch_memory":
        ids = args.get("memory_ids") or []
        if not ids:
            raise ToolExecutionError("memory_ids_required")
        return {"items": fetch_memory(scope, ids)}

    if tool_name == "save_note":
        content = str(args.get("content") or "").strip()
        if not content:
            raise ToolExecutionError("content_required")
        source_event = save_event(scope, "user", content, source=source)
        return save_note(scope, title=str(args.get("title") or "Nota"), content=content, source_event_id=source_event["id"])

    if tool_name == "save_fact":
        subject = str(args.get("subject") or "").strip()
        relation = str(args.get("relation") or "").strip()
        object_value = str(args.get("object") or "").strip()
        if not subject or not relation or not object_value:
            raise ToolExecutionError("subject_relation_object_required")
        source_event = save_event(scope, "user", f"{subject} {relation} {object_value}", source=source)
        return save_fact(
            scope,
            subject=subject,
            relation=relation,
            object_value=object_value,
            confidence=float(args.get("confidence") or 0.9),
            source_event_id=source_event["id"],
            evidence_doc_ids=list(args.get("evidence_doc_ids") or []),
        )

    if tool_name == "list_books":
        return {"books": list_books(scope.tenant_id, scope.project_id, user_id=scope.user_id)}

    if tool_name == "save_session_summary":
        summary = str(args.get("summary") or "").strip()
        if not summary:
            raise ToolExecutionError("summary_required")
        return save_session_summary(
            scope,
            summary,
            new_facts=list(args.get("new_facts") or []),
            updated_facts=list(args.get("updated_facts") or []),
            open_questions=list(args.get("open_questions") or []),
            decisions=list(args.get("decisions") or []),
        )

    raise ToolExecutionError("tool_not_supported", status_code=404)
