from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm_settings import UserLLMSettings
from app.schemas import BridgeBootstrapResponse, BridgeInstruction, BridgeProviderInfo, BridgeToolCallRequest, BridgeToolCallResponse, BridgeToolDefinition, BridgeToolParameter


@dataclass(frozen=True)
class ProviderAdapter:
    provider: str
    display_name: str
    bridge_mode: str
    supports_remote_chat: bool
    supports_mcp: bool
    supports_function_calling: bool
    requires_user_api_key: bool
    default_model: str
    connection_summary: str

    def instructions(self) -> list[BridgeInstruction]:
        raise NotImplementedError

    def tools(self) -> list[BridgeToolDefinition]:
        return [
            BridgeToolDefinition(
                name="memory_chat",
                description="Usa la memoria del usuario para responder sin inventar cuando falte información.",
                parameters=[
                    BridgeToolParameter(name="user_id", type="string", required=True, description="Identificador del usuario"),
                    BridgeToolParameter(name="project", type="string", required=False, description="Proyecto activo del usuario"),
                    BridgeToolParameter(name="book_id", type="string", required=False, description="Espacio o libro de memoria"),
                    BridgeToolParameter(name="message", type="string", required=True, description="Mensaje actual del usuario"),
                ],
            ),
            BridgeToolDefinition(
                name="memory_connection_status",
                description="Devuelve el estado actual de conexión de memoria del usuario.",
                parameters=[
                    BridgeToolParameter(name="user_id", type="string", required=True, description="Identificador del usuario"),
                ],
            ),
            BridgeToolDefinition(
                name="search_memory",
                description="Busca memoria en el núcleo MCP-first por tenant/proyecto/libro.",
                parameters=[
                    BridgeToolParameter(name="tenant_id", type="string", required=True, description="Tenant o espacio dueño de la memoria"),
                    BridgeToolParameter(name="project_id", type="string", required=True, description="Proyecto activo"),
                    BridgeToolParameter(name="book_id", type="string", required=True, description="Libro de memoria"),
                    BridgeToolParameter(name="query", type="string", required=True, description="Consulta a buscar"),
                    BridgeToolParameter(name="entity_type", type="string", required=False, description="Tipo de entidad"),
                    BridgeToolParameter(name="entity_id", type="string", required=False, description="Entidad concreta"),
                ],
            ),
            BridgeToolDefinition(
                name="fetch_memory",
                description="Recupera recuerdos exactos por id.",
                parameters=[
                    BridgeToolParameter(name="tenant_id", type="string", required=True, description="Tenant o espacio dueño de la memoria"),
                    BridgeToolParameter(name="project_id", type="string", required=True, description="Proyecto activo"),
                    BridgeToolParameter(name="book_id", type="string", required=True, description="Libro de memoria"),
                    BridgeToolParameter(name="memory_ids", type="array", required=True, description="Ids a recuperar"),
                ],
            ),
            BridgeToolDefinition(
                name="save_note",
                description="Guarda una nota explícita en la memoria central.",
                parameters=[
                    BridgeToolParameter(name="tenant_id", type="string", required=True, description="Tenant o espacio dueño de la memoria"),
                    BridgeToolParameter(name="project_id", type="string", required=True, description="Proyecto activo"),
                    BridgeToolParameter(name="book_id", type="string", required=True, description="Libro de memoria"),
                    BridgeToolParameter(name="content", type="string", required=True, description="Contenido de la nota"),
                    BridgeToolParameter(name="title", type="string", required=False, description="Título de la nota"),
                ],
            ),
            BridgeToolDefinition(
                name="save_fact",
                description="Guarda un hecho estructurado y vigente.",
                parameters=[
                    BridgeToolParameter(name="tenant_id", type="string", required=True, description="Tenant o espacio dueño de la memoria"),
                    BridgeToolParameter(name="project_id", type="string", required=True, description="Proyecto activo"),
                    BridgeToolParameter(name="book_id", type="string", required=True, description="Libro de memoria"),
                    BridgeToolParameter(name="subject", type="string", required=True, description="Sujeto"),
                    BridgeToolParameter(name="relation", type="string", required=True, description="Relación"),
                    BridgeToolParameter(name="object", type="string", required=True, description="Objeto o valor"),
                ],
            ),
            BridgeToolDefinition(
                name="list_books",
                description="Lista los libros activos del proyecto.",
                parameters=[
                    BridgeToolParameter(name="tenant_id", type="string", required=True, description="Tenant o espacio dueño de la memoria"),
                    BridgeToolParameter(name="project_id", type="string", required=True, description="Proyecto activo"),
                ],
            ),
            BridgeToolDefinition(
                name="save_session_summary",
                description="Guarda un resumen por sesión en la memoria central.",
                parameters=[
                    BridgeToolParameter(name="tenant_id", type="string", required=True, description="Tenant o espacio dueño de la memoria"),
                    BridgeToolParameter(name="project_id", type="string", required=True, description="Proyecto activo"),
                    BridgeToolParameter(name="book_id", type="string", required=True, description="Libro de memoria"),
                    BridgeToolParameter(name="summary", type="string", required=True, description="Resumen"),
                    BridgeToolParameter(name="session_id", type="string", required=False, description="Sesión"),
                ],
            ),
        ]

    def bootstrap(self, base_url: str) -> BridgeBootstrapResponse:
        return BridgeBootstrapResponse(
            provider=self.provider,
            display_name=self.display_name,
            bridge_mode=self.bridge_mode,
            supports_remote_chat=self.supports_remote_chat,
            supports_mcp=self.supports_mcp,
            supports_function_calling=self.supports_function_calling,
            requires_user_api_key=self.requires_user_api_key,
            default_model=self.default_model,
            connection_summary=self.connection_summary,
            instructions=self.instructions(),
            tools=self.tools(),
            bridge_endpoint=f"{base_url.rstrip('/')}/bridge/{self.provider}/tool-call",
            manifest_endpoint=f"{base_url.rstrip('/')}/bridge/{self.provider}/manifest",
        )

    def handle_tool_call(self, request: BridgeToolCallRequest, settings: UserLLMSettings) -> BridgeToolCallResponse:
        from app.tool_registry import ToolExecutionError, execute_tool

        if request.tool_name == "memory_connection_status":
            return BridgeToolCallResponse(
                provider=self.provider,
                tool_name=request.tool_name,
                ok=True,
                result={
                    "user_id": settings.user_id,
                    "provider": settings.provider,
                    "model_name": settings.model_name,
                    "bridge_mode": settings.bridge_mode,
                    "status": settings.connection_status,
                },
            )
        try:
            result = execute_tool(request.tool_name, request.arguments, principal_user_id=settings.user_id, source="bridge")
            return BridgeToolCallResponse(provider=self.provider, tool_name=request.tool_name, ok=True, result=result)
        except ToolExecutionError as exc:
            return BridgeToolCallResponse(provider=self.provider, tool_name=request.tool_name, ok=False, error=exc.code)


class ChatGPTAdapter(ProviderAdapter):
    def instructions(self) -> list[BridgeInstruction]:
        return [
            BridgeInstruction(step=1, title="Registrar conexión", detail="Conectá la memoria desde el panel y dejá el proveedor en estado connected."),
            BridgeInstruction(step=2, title="Usar servidor MCP remoto", detail="Este proveedor está pensado para exponer herramientas vía MCP Apps o un bridge HTTP equivalente."),
            BridgeInstruction(step=3, title="Usar memory_chat", detail="Cuando el modelo necesite memoria, llamá a la herramienta memory_chat con user_id, project y message."),
        ]


class ClaudeAdapter(ProviderAdapter):
    def instructions(self) -> list[BridgeInstruction]:
        return [
            BridgeInstruction(step=1, title="Registrar conexión", detail="Conectá la memoria desde el panel y mantené el proveedor conectado o pausado."),
            BridgeInstruction(step=2, title="Configurar MCP", detail="Claude puede consumir este backend por un bridge MCP o un wrapper HTTP del mismo conjunto de herramientas."),
            BridgeInstruction(step=3, title="Llamar memory_chat", detail="El flujo principal usa memory_chat para recuperar contexto sin inventar datos."),
        ]


class GeminiAdapter(ProviderAdapter):
    def instructions(self) -> list[BridgeInstruction]:
        return [
            BridgeInstruction(step=1, title="Registrar conexión", detail="Conectá la memoria desde el panel con el proveedor Gemini."),
            BridgeInstruction(step=2, title="Configurar tool calling", detail="Gemini usa function calling; definí las herramientas expuestas por el endpoint de manifest."),
            BridgeInstruction(step=3, title="Llamar memory_chat", detail="Ejecutá la llamada de herramienta desde tu orquestador y devolvé el resultado al modelo."),
        ]


class DeepSeekAdapter(ProviderAdapter):
    def instructions(self) -> list[BridgeInstruction]:
        return [
            BridgeInstruction(step=1, title="Registrar conexión", detail="Conectá la memoria desde el panel con el proveedor DeepSeek."),
            BridgeInstruction(step=2, title="Usar bridge HTTP", detail="Este proveedor queda previsto para integración por HTTP bridge o capa intermedia propia."),
            BridgeInstruction(step=3, title="Llamar memory_chat", detail="El bridge debe invocar memory_chat cuando falte contexto en la conversación."),
        ]


class MockAdapter(ProviderAdapter):
    def instructions(self) -> list[BridgeInstruction]:
        return [BridgeInstruction(step=1, title="Modo de prueba", detail="Usá este adaptador para pruebas locales del backend sin depender de un proveedor externo.")]


ADAPTERS: dict[str, ProviderAdapter] = {
    "mock": MockAdapter("mock", "Modo de prueba", "internal", False, False, False, False, "mock-model", "Adaptador interno para pruebas locales y smoke tests."),
    "chatgpt": ChatGPTAdapter("chatgpt", "ChatGPT", "mcp", True, True, True, False, "chatgpt-main", "Conexión orientada a MCP Apps o bridge equivalente para ChatGPT."),
    "claude": ClaudeAdapter("claude", "Claude", "mcp", False, True, True, False, "claude-main", "Conexión orientada a MCP o wrapper HTTP compatible para Claude."),
    "gemini": GeminiAdapter("gemini", "Gemini", "function_calling", False, False, True, False, "gemini-main", "Conexión orientada a function calling / tool calling para Gemini."),
    "deepseek": DeepSeekAdapter("deepseek", "DeepSeek", "http_bridge", False, False, True, False, "deepseek-chat", "Conexión orientada a bridge HTTP para DeepSeek."),
}




def _parameter_json_schema(parameters: list[BridgeToolParameter]) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    required: list[str] = []
    type_map = {
        "string": "string",
        "number": "number",
        "integer": "integer",
        "array": "array",
        "boolean": "boolean",
        "object": "object",
    }
    for parameter in parameters:
        json_type = type_map.get(parameter.type, "string")
        schema: dict[str, Any] = {"type": json_type, "description": parameter.description}
        if json_type == "array":
            schema["items"] = {"type": "string"}
        properties[parameter.name] = schema
        if parameter.required:
            required.append(parameter.name)
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def function_tool_manifest(provider: str, base_url: str) -> dict[str, Any]:
    adapter = get_adapter(provider)
    bootstrap = adapter.bootstrap(base_url)
    tools = [item.model_dump() for item in bootstrap.tools]
    generic_tools = [
        {
            "name": item["name"],
            "description": item["description"],
            "input_schema": _parameter_json_schema(adapter.tools()[idx].parameters),
        }
        for idx, item in enumerate(tools)
    ]
    openai_tools = [
        {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": _parameter_json_schema(tool.parameters),
            },
        }
        for tool in adapter.tools()
    ]
    gemini_function_declarations = [
        {
            "name": tool.name,
            "description": tool.description,
            "parameters": _parameter_json_schema(tool.parameters),
        }
        for tool in adapter.tools()
    ]
    return {
        "provider": bootstrap.provider,
        "display_name": bootstrap.display_name,
        "bridge_mode": bootstrap.bridge_mode,
        "call_endpoint": f"{base_url.rstrip('/')}/tool-calling/{bootstrap.provider}/call",
        "tools": tools,
        "generic_tools": generic_tools,
        "openai_tools": openai_tools,
        "gemini_function_declarations": gemini_function_declarations,
        "function_calling_ready": bootstrap.supports_function_calling,
        "mcp_ready": bootstrap.supports_mcp,
        "requires_user_api_key": bootstrap.requires_user_api_key,
        "tool_call_manifest_endpoint": f"{base_url.rstrip('/')}/tool-calling/{bootstrap.provider}/manifest",
        "tool_call_endpoint": f"{base_url.rstrip('/')}/tool-calling/{bootstrap.provider}/call",
    }

def get_adapter(provider: str) -> ProviderAdapter:
    return ADAPTERS.get(provider.lower(), ADAPTERS["mock"])


def provider_manifest(provider: str, base_url: str) -> dict[str, Any]:
    adapter = get_adapter(provider)
    bootstrap = adapter.bootstrap(base_url)
    return {
        "provider": bootstrap.provider,
        "display_name": bootstrap.display_name,
        "bridge_mode": bootstrap.bridge_mode,
        "bridge_endpoint": bootstrap.bridge_endpoint,
        "instructions": [item.model_dump() for item in bootstrap.instructions],
        "tools": [item.model_dump() for item in bootstrap.tools],
        "mcp_ready": bootstrap.supports_mcp,
        "function_calling_ready": bootstrap.supports_function_calling,
        "requires_user_api_key": bootstrap.requires_user_api_key,
        "tool_call_manifest_endpoint": f"{base_url.rstrip('/')}/tool-calling/{bootstrap.provider}/manifest",
        "tool_call_endpoint": f"{base_url.rstrip('/')}/tool-calling/{bootstrap.provider}/call",
    }
