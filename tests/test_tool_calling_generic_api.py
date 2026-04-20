import os
os.environ['GITHUB_ACTIONS']='true'

from fastapi.testclient import TestClient
from app.main import app
from app.firestore_store import llm_connections_collection, facts_collection, manual_notes_collection, retrieval_traces_collection, session_summaries_collection, event_log_collection

client=TestClient(app)

def _clear():
    for c in [llm_connections_collection, facts_collection, manual_notes_collection, retrieval_traces_collection, session_summaries_collection, event_log_collection]:
        c.clear()


def test_generic_tool_calling_works_without_provider_token():
    _clear()
    save = client.post('/tool-calling/generic/call', json={
        'user_id':'test-user',
        'tool_name':'save_note',
        'arguments':{
            'tenant_id':'test',
            'project_id':'memoria-guia',
            'book_id':'general',
            'content':'Mi productor favorito es Alfa',
            'title':'Pref'
        }
    })
    assert save.status_code == 200, save.text
    search = client.post('/tool-calling/generic/call', json={
        'user_id':'test-user',
        'tool_name':'search_memory',
        'arguments':{
            'tenant_id':'test',
            'project_id':'memoria-guia',
            'book_id':'general',
            'query':'productor favorito'
        }
    })
    assert search.status_code == 200, search.text
    body = search.json()
    assert body['ok'] is True
    assert any('alfa' in item['preview'].lower() for item in body['result']['items'])
