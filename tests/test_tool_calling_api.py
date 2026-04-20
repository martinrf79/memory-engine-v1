import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.firestore_store import llm_connections_collection, semantic_collection
from app.main import app
from app.utils import utc_now_iso

client = TestClient(app)


def _clear():
    llm_connections_collection.clear()
    semantic_collection.clear()


def test_tool_calling_manifest_exposes_provider_specific_payloads():
    _clear()
    manifest = client.get('/tool-calling/gemini/manifest')
    assert manifest.status_code == 200
    body = manifest.json()
    assert body['provider'] == 'gemini'
    assert body['function_calling_ready'] is True
    assert any(tool['function']['name'] == 'search_memory' for tool in body['openai_tools'])
    assert any(tool['name'] == 'save_fact' for tool in body['gemini_function_declarations'])


def test_tool_calling_can_use_same_bridge_token_and_search_memory():
    _clear()
    now = utc_now_iso()
    llm_connections_collection.document('martin:gemini').set({
        'id': 'martin:gemini',
        'user_id': 'martin',
        'provider': 'gemini',
        'model_name': 'gemini-main',
        'bridge_mode': 'function_calling',
        'status': 'connected',
        'bridge_token': 'gemini-secret-token',
        'created_at': now,
        'updated_at': now,
    })

    store = client.post(
        '/tool-calling/gemini/call',
        headers={'x-bridge-token': 'gemini-secret-token'},
        json={
            'user_id': 'martin',
            'tool_name': 'save_fact',
            'arguments': {
                'tenant_id': 'martin',
                'project_id': 'memoria-guia',
                'book_id': 'general',
                'subject': 'color favorito',
                'relation': 'es',
                'object': 'azul',
            },
        },
    )
    assert store.status_code == 200
    assert store.json()['ok'] is True

    search = client.post(
        '/tool-calling/gemini/call',
        headers={'x-bridge-token': 'gemini-secret-token'},
        json={
            'user_id': 'martin',
            'tool_name': 'search_memory',
            'arguments': {
                'tenant_id': 'martin',
                'project_id': 'memoria-guia',
                'book_id': 'general',
                'query': 'color favorito',
            },
        },
    )
    assert search.status_code == 200
    body = search.json()
    assert body['ok'] is True
    items = body['result']['items']
    assert items
    assert any('azul' in item['preview'].lower() for item in items)
