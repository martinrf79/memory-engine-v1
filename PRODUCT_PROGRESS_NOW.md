# Product progress applied now

## What was finished
- `memory_core_v1` left as the effective retrieval core.
- `chat.py` uses the core-compatible retrieval/write path.
- Legacy internal memory routes now operate on the core data model instead of `semantic_collection`:
  - `POST /memories`
  - `GET /memories`
  - `POST /memories/search`
  - `PATCH /memories/{id}`
  - `POST /memories/{id}/archive`
  - `DELETE /memories/{id}`
  - `GET /memories/export`
- Added `app/core_legacy_adapter.py` to keep compatibility for product/internal routes while moving to one core.

## Why this is product progress
This reduces the gap between the current UI/API surface and the new core. The panel/internal APIs can keep working without depending on the old semantic store as the main source of truth.

## Validation run
Executed with `USE_FAKE_FIRESTORE=true`:

```bash
pytest -q tests/test_memory_api.py tests/test_chat_api.py tests/test_connection_api.py tests/test_bridge_api.py tests/test_tool_calling_api.py tests/test_mcp_api.py
```

Result:
- `10 passed`

## Main files changed
- `app/memory_core_v1.py`
- `app/chat.py`
- `app/auth.py`
- `app/seed_operational_memories.py`
- `app/core_legacy_adapter.py`
- `app/memories.py`
- `app/search.py`
- `app/manage_memories.py`
- `app/export_memories.py`

## Still pending
- remove or migrate remaining legacy assumptions around `semantic_collection`
- validate connectors end-to-end against real provider/auth conditions
- package a deployable branch/image with these exact changes
