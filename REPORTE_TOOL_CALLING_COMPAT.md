# REPORTE TOOL CALLING COMPAT

Base usada: `backend-mcp-first-v1.zip`

## Objetivo
Agregar compatibilidad nativa de **tool calling / function calling** sin romper la capa MCP existente.

## Cambios aplicados
- Nuevo router `app/tool_calling.py`
- Nuevas rutas:
  - `GET /tool-calling/manifest`
  - `GET /tool-calling/providers`
  - `GET /tool-calling/{provider}/manifest`
  - `POST /tool-calling/{provider}/call`
- `app/provider_adapters.py` ahora genera:
  - `generic_tools`
  - `openai_tools`
  - `gemini_function_declarations`
- `app/bridges.py` y `provider_manifest()` exponen también:
  - `tool_call_manifest_endpoint`
  - `tool_call_endpoint`
- `app/main.py` incluye el nuevo router de tool calling
- Nueva prueba `tests/test_tool_calling_api.py`

## Resultado
- La base sigue siendo MCP-first
- Se agrega una segunda vía compatible con Gemini / DeepSeek / otros modelos con tool calling
- No se reemplaza el bridge anterior; se complementa

## Validación local
- `pytest -q` -> `105 passed, 7 deselected`
- `pytest -q tests/test_bridge_api.py tests/test_tool_calling_api.py tests/test_auth_panel_security.py` -> `8 passed`
