import os
from concurrent.futures import ThreadPoolExecutor

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.chat import ChatRequest, chat
from app.firestore_store import (
    chat_events_collection,
    memory_keys_collection,
    projects_collection,
    retrieval_traces_collection,
    semantic_collection,
    sessions_collection,
    users_collection,
)
from app.main import app
from app.semantic_memory import ExtractedMemory, query_semantic_memories, upsert_semantic_memory
from app.utils import new_memory_id

client = TestClient(app)


def _clear_all():
    for collection in [
        semantic_collection,
        chat_events_collection,
        memory_keys_collection,
        projects_collection,
        retrieval_traces_collection,
        sessions_collection,
        users_collection,
    ]:
        collection.clear()


def test_panel_chat_remember_stores_non_structured_note_and_dedupes():
    _clear_all()
    reg = client.post('/auth/register', json={'user_id': 'u20', 'password': 'supersecreto', 'project': 'taller'})
    assert reg.status_code == 200

    body = {'project': 'taller', 'book_id': 'general', 'message': 'Mi contacto técnico preferido revisa los martes por la tarde.', 'remember': True}
    first = client.post('/panel/chat', json=body)
    second = client.post('/panel/chat', json=body)

    assert first.status_code == 200
    assert second.status_code == 200
    memories = query_semantic_memories('u20', 'taller', 'general', include_inactive=True, include_global=True)
    notes = [m for m in memories if m.get('entity') == 'user_note']
    assert len(notes) == 1
    assert notes[0]['source_type'] in {'chat_remember', 'chat_auto'}


def test_temporal_supersession_keeps_history_links():
    _clear_all()
    first = upsert_semantic_memory(
        user_id='u21',
        project='perfil',
        book_id='general',
        extracted=ExtractedMemory(memory_type='preference', entity='user', attribute='favorite_color', value_text='azul', context='Mi color favorito es azul'),
        source_event_id=new_memory_id(),
    )
    second = upsert_semantic_memory(
        user_id='u21',
        project='perfil',
        book_id='general',
        extracted=ExtractedMemory(memory_type='preference', entity='user', attribute='favorite_color', value_text='verde', context='Ahora es verde'),
        source_event_id=new_memory_id(),
    )

    all_memories = {m['id']: m for m in query_semantic_memories('u21', 'perfil', 'general', include_inactive=True, include_global=True)}
    assert all_memories[first['id']]['status'] == 'superseded'
    assert all_memories[first['id']]['superseded_by'] == second['id']
    assert all_memories[second['id']]['supersedes_id'] == first['id']


def test_chat_answers_create_internal_retrieval_trace():
    _clear_all()
    client.post('/chat', json={'user_id': 'u22', 'project': 'perfil', 'book_id': 'general', 'message': 'Mi color favorito es verde'})
    ask = client.post('/chat', json={'user_id': 'u22', 'project': 'perfil', 'book_id': 'general', 'message': '¿Cuál es mi color favorito?'})
    assert ask.status_code == 200
    traces = [doc.to_dict() or {} for doc in retrieval_traces_collection.stream()]
    assert traces
    assert traces[-1]['used_memory_ids']
    assert traces[-1]['query'] == '¿Cuál es mi color favorito?'


def test_concurrent_upserts_leave_single_active_memory():
    _clear_all()

    values = ['azul', 'verde', 'rojo', 'amarillo']

    def _write(value):
        return upsert_semantic_memory(
            user_id='u23',
            project='perfil',
            book_id='general',
            extracted=ExtractedMemory(memory_type='preference', entity='user', attribute='favorite_color', value_text=value, context=f'Mi color favorito es {value}'),
            source_event_id=new_memory_id(),
        )

    with ThreadPoolExecutor(max_workers=4) as executor:
        list(executor.map(_write, values))

    all_memories = query_semantic_memories('u23', 'perfil', 'general', include_inactive=True, include_global=True)
    active = [m for m in all_memories if m.get('status') == 'active' and m.get('attribute') == 'favorite_color']
    assert len(active) == 1
    assert len([m for m in all_memories if m.get('attribute') == 'favorite_color']) == len(values)
