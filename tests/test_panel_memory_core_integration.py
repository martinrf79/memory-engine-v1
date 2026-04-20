import os

os.environ['GITHUB_ACTIONS'] = 'true'

from fastapi.testclient import TestClient

from app.firestore_store import (
    event_log_collection,
    facts_collection,
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
    ]:
        collection.clear()



def _register(user_id: str, project: str):
    response = client.post('/auth/register', json={'user_id': user_id, 'password': 'supersecreto', 'project': project})
    assert response.status_code == 200



def test_panel_manual_memory_generic_fact_is_recalled_from_chat():
    _clear_all()
    _register('u_panel', 'premium')

    save = client.post(
        '/panel/memories/manual',
        json={'project': 'premium', 'book_id': 'general', 'content': 'Mi productor favorito es Alfa'},
    )
    assert save.status_code == 200
    body = save.json()
    assert body['status'] == 'stored'

    ask = client.post(
        '/panel/chat',
        json={'project': 'premium', 'book_id': 'general', 'message': '¿Cuál es mi productor favorito?'},
    )
    data = ask.json()
    assert data['mode'] == 'answer'
    assert 'Alfa' in data['answer']
    assert any('Alfa' in memory['summary'] for memory in data['used_memories'])



def test_panel_manual_memory_does_not_leak_between_projects():
    _clear_all()
    _register('u_panel2', 'premium')
    client.post('/panel/projects', json={'project': 'otro'})

    save = client.post(
        '/panel/memories/manual',
        json={'project': 'premium', 'book_id': 'general', 'content': 'Mi productor favorito es Alfa'},
    )
    assert save.status_code == 200

    ask = client.post(
        '/panel/chat',
        json={'project': 'otro', 'book_id': 'general', 'message': '¿Cuál es mi productor favorito?'},
    )
    data = ask.json()
    assert data['mode'] in {'clarification_required', 'insufficient_memory'}
    assert 'Alfa' not in data['answer']



def test_panel_manual_memory_writes_core_note_and_fact_when_possible():
    _clear_all()
    _register('u_panel3', 'premium')

    save = client.post(
        '/panel/memories/manual',
        json={'project': 'premium', 'book_id': 'general', 'content': 'Mi productor favorito es Alfa'},
    )
    assert save.status_code == 200

    notes = [doc.to_dict() or {} for doc in manual_notes_collection.stream()]
    facts = [doc.to_dict() or {} for doc in facts_collection.stream()]
    assert any('productor favorito' in (item.get('content') or '').lower() for item in notes)
    assert any((item.get('relation') or '').lower() == 'productor favorito' and (item.get('object') or '') == 'Alfa' for item in facts)
