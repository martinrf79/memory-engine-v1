import os

os.environ['GITHUB_ACTIONS'] = 'true'

from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection, projects_collection, sessions_collection, users_collection
from app.main import app

client = TestClient(app)


def _clear_all():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()
    projects_collection.clear()
    sessions_collection.clear()
    users_collection.clear()


def test_relation_origin_is_stored_and_recalled():
    _clear_all()

    save = client.post(
        '/chat',
        json={
            'user_id': 'u11',
            'project': 'familia',
            'book_id': 'general',
            'message': 'Mi primo es de Río Tercero',
        },
    )
    assert save.status_code == 200
    assert 'guardé' in save.json()['answer']

    ask = client.post(
        '/chat',
        json={
            'user_id': 'u11',
            'project': 'familia',
            'book_id': 'general',
            'message': '¿De dónde es mi primo?',
        },
    )
    body = ask.json()
    assert body['mode'] == 'answer'
    assert body['answer'] == 'Tu primo es de Río Tercero.'
    assert any('origin_location' in m['summary'] for m in body['used_memories'])


def test_user_profile_location_is_stored_and_recalled():
    _clear_all()

    client.post('/chat', json={'user_id': 'u11', 'project': 'perfil', 'book_id': 'general', 'message': 'Soy de Córdoba'})
    client.post('/chat', json={'user_id': 'u11', 'project': 'perfil', 'book_id': 'general', 'message': 'Vivo en San Agustín'})

    ask_origin = client.post('/chat', json={'user_id': 'u11', 'project': 'perfil', 'book_id': 'general', 'message': '¿De dónde soy?'})
    ask_current = client.post('/chat', json={'user_id': 'u11', 'project': 'perfil', 'book_id': 'general', 'message': '¿Dónde vivo?'})

    assert ask_origin.json()['answer'] == 'Sos de Córdoba.'
    assert ask_current.json()['answer'] == 'Vivís en San Agustín.'


def test_relation_summary_is_visible_in_safe_summary():
    _clear_all()

    client.post('/chat', json={'user_id': 'u11', 'project': 'familia', 'book_id': 'general', 'message': 'Mi hermana vive en Rosario'})

    ask = client.post(
        '/chat',
        json={'user_id': 'u11', 'project': 'familia', 'book_id': 'general', 'message': '¿Qué recuerdas de mí?'},
    )
    body = ask.json()
    assert body['mode'] == 'answer'
    assert 'Rosario' in body['answer']


def test_manual_panel_memory_uses_structured_extraction_when_possible():
    _clear_all()

    reg = client.post('/auth/register', json={'user_id': 'u11', 'password': 'supersecreto', 'project': 'familia'})
    assert reg.status_code == 200

    save = client.post(
        '/panel/memories/manual',
        json={'project': 'familia', 'book_id': 'general', 'content': 'Mi primo se llama Juan'},
    )
    assert save.status_code == 200

    ask = client.post(
        '/panel/chat',
        json={'project': 'familia', 'book_id': 'general', 'message': '¿Cómo se llama mi primo?'},
    )
    body = ask.json()
    assert body['mode'] == 'answer'
    assert body['answer'] == 'Tu primo se llama Juan.'
