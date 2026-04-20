import os

os.environ['GITHUB_ACTIONS'] = 'true'

from fastapi.testclient import TestClient

from app.firestore_store import (
    event_log_collection,
    facts_collection,
    llm_connections_collection,
    manual_notes_collection,
    memory_keys_collection,
    projects_collection,
    retrieval_traces_collection,
    semantic_collection,
    session_summaries_collection,
    sessions_collection,
    users_collection,
)
from app.main import app

client = TestClient(app)


def _clear_all():
    for collection in [
        semantic_collection,
        memory_keys_collection,
        users_collection,
        projects_collection,
        sessions_collection,
        manual_notes_collection,
        facts_collection,
        event_log_collection,
        session_summaries_collection,
        retrieval_traces_collection,
        llm_connections_collection,
    ]:
        collection.clear()



def _register(user_id: str, project: str):
    response = client.post('/auth/register', json={'user_id': user_id, 'password': 'supersecreto', 'project': project})
    assert response.status_code == 200



def test_panel_manual_memory_survives_logout_login_and_is_recalled():
    _clear_all()
    _register('u_persist', 'premium')

    save = client.post('/panel/memories/manual', json={'project': 'premium', 'book_id': 'general', 'content': 'Mi productor favorito es Alfa'})
    assert save.status_code == 200
    assert save.json()['status'] == 'stored'

    logout = client.post('/auth/logout')
    assert logout.status_code == 200

    login = client.post('/auth/login', json={'user_id': 'u_persist', 'password': 'supersecreto'})
    assert login.status_code == 200

    ask = client.post('/panel/chat', json={'project': 'premium', 'book_id': 'general', 'message': '¿Cuál es mi productor favorito?'})
    assert ask.status_code == 200
    body = ask.json()
    assert body['mode'] == 'answer'
    assert 'Alfa' in body['answer']



def test_panel_saved_memory_is_searchable_from_tool_calling_adapter():
    _clear_all()
    _register('u_tool', 'premium')

    save = client.post('/panel/memories/manual', json={'project': 'premium', 'book_id': 'general', 'content': 'Mi productor favorito es Alfa'})
    assert save.status_code == 200

    from app.utils import utc_now_iso

    llm_connections_collection.document('u_tool:gemini').set({
        'id': 'u_tool:gemini',
        'user_id': 'u_tool',
        'provider': 'gemini',
        'model_name': 'gemini-main',
        'bridge_mode': 'function_calling',
        'status': 'connected',
        'bridge_token': 'gemini-tool-token',
        'created_at': utc_now_iso(),
        'updated_at': utc_now_iso(),
    })

    search = client.post(
        '/tool-calling/gemini/call',
        headers={'x-bridge-token': 'gemini-tool-token'},
        json={
            'user_id': 'u_tool',
            'tool_name': 'search_memory',
            'arguments': {
                'tenant_id': 'u_tool',
                'project_id': 'premium',
                'book_id': 'general',
                'query': 'productor favorito',
            },
        },
    )
    assert search.status_code == 200
    body = search.json()
    assert body['ok'] is True
    assert any('Alfa' in item['preview'] for item in body['result']['items'])



def test_frontend_chat_request_wires_remember_toggle_to_backend_payload():
    js = client.get('/ui/app.js')
    assert js.status_code == 200
    body = js.text
    assert 'rememberToggle' in body
    assert 'JSON.stringify({ project, book_id: "general", message, remember })' in body


def test_panel_chat_remember_is_retrievable_with_human_answer():
    _clear_all()
    _register('u_remember', 'premium')

    save = client.post('/panel/chat', json={'project': 'premium', 'book_id': 'general', 'message': 'Mi canal semiautomático preferido es WhatsApp', 'remember': True})
    assert save.status_code == 200

    ask = client.post('/panel/chat', json={'project': 'premium', 'book_id': 'general', 'message': '¿Cuál es mi canal semiautomático preferido?'})
    assert ask.status_code == 200
    body = ask.json()
    assert body['mode'] == 'answer'
    assert 'WhatsApp' in body['answer']
    assert 'user_note' not in body['answer']


def test_panel_chat_does_not_answer_with_unrelated_memory_from_same_user_other_project():
    _clear_all()
    _register('u_isolation', 'premium')
    create_project = client.post('/panel/projects', json={'project': 'sensores'})
    assert create_project.status_code == 200

    save = client.post('/panel/memories/manual', json={'project': 'sensores', 'book_id': 'general', 'content': 'Mi sensor crítico es el del eje 2'})
    assert save.status_code == 200

    ask = client.post('/panel/chat', json={'project': 'premium', 'book_id': 'general', 'message': '¿Cuál es mi sensor crítico?'})
    assert ask.status_code == 200
    body = ask.json()
    assert body['mode'] in {'clarification_required', 'insufficient_memory'}
    assert 'eje 2' not in str(body)
