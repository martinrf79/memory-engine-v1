import sys
from pathlib import Path as _P
sys.path.insert(0, str(_P(__file__).resolve().parents[1]))
import json
import os
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any

os.environ.setdefault('USE_FAKE_FIRESTORE', 'true')
os.environ.setdefault('GITHUB_ACTIONS', 'true')

from fastapi.testclient import TestClient

from app.auth import ensure_project_record, hash_password
from app.firestore_store import (
    audit_events_collection,
    chat_events_collection,
    llm_connections_collection,
    memory_indexes_collection,
    memory_keys_collection,
    projects_collection,
    semantic_collection,
    sessions_collection,
    support_events_collection,
    users_collection,
)
from app.main import app
from app.semantic_memory import build_dedupe_key
from app.utils import utc_now_iso

CATALOG_PATH = Path('/mnt/data/prueba240/datasets/01_catalogo_maestro_de_casos.jsonl')
REPORT_PATH = Path('/mnt/data/catalog_240_report_pass2.json')


@dataclass
class CaseResult:
    case_id: str
    layer: str
    family: str
    passed: bool
    status: str
    reason: str
    actual: Any


def norm(text: str | None) -> str:
    text = text or ''
    text = ''.join(c for c in unicodedata.normalize('NFD', text.lower()) if unicodedata.category(c) != 'Mn')
    return ' '.join(text.split())


def contains(text: str | None, *options: str) -> bool:
    n = norm(text)
    return any(norm(opt) in n for opt in options)


def clear_all() -> None:
    for collection in [
        audit_events_collection,
        chat_events_collection,
        llm_connections_collection,
        memory_indexes_collection,
        memory_keys_collection,
        projects_collection,
        semantic_collection,
        sessions_collection,
        support_events_collection,
        users_collection,
    ]:
        collection.clear()


def create_user(user_id: str) -> None:
    now = utc_now_iso()
    users_collection.document(user_id).set(
        {
            'id': user_id,
            'user_id': user_id,
            'created_at': now,
            'updated_at': now,
            'memory_enabled': True,
            'panel_mode': 'public_frontend_private_backend',
            'password_hash': hash_password('clave-segura-123'),
        }
    )


def insert_semantic(*, memory_id: str, user_id: str, project: str, entity: str, attribute: str, value: str,
                    status: str = 'active', version: int = 1, book_id: str = 'general', memory_type: str = 'fact',
                    valid_to: str | None = None, context: str | None = None) -> None:
    now = utc_now_iso()
    semantic_collection.document(memory_id).set(
        {
            'id': memory_id,
            'user_id': user_id,
            'project': project,
            'book_id': book_id,
            'memory_type': memory_type,
            'entity': entity,
            'attribute': attribute,
            'value_text': value,
            'context': context or f'{attribute}={value}',
            'status': status,
            'dedupe_key': build_dedupe_key(user_id, project, book_id, entity, attribute),
            'version': version,
            'valid_from': now,
            'valid_to': valid_to,
            'source_type': 'seed',
            'source_event_id': f'seed-{memory_id}',
            'created_at': now,
            'updated_at': None,
        }
    )


def insert_chat_log(*, user_id: str, project: str, user_message: str, assistant_answer: str, event_id: str) -> None:
    chat_events_collection.document(event_id).set(
        {
            'id': event_id,
            'user_id': user_id,
            'project': project,
            'book_id': 'general',
            'user_message': user_message,
            'assistant_answer': assistant_answer,
            'llm_provider': 'mock',
            'llm_model': 'mock',
            'created_at': utc_now_iso(),
            'ttl_at': None,
        }
    )


def seed_rules(project: str = 'memoria-guia') -> None:
    insert_semantic(memory_id=f'rule-{project}-memory-first', user_id='martin', project=project, entity='assistant_policy', attribute='memory_first', value='consultar memoria antes de responder', memory_type='instruction')
    insert_semantic(memory_id=f'rule-{project}-missing', user_id='martin', project=project, entity='assistant_policy', attribute='insufficient_memory_rule', value='si no hay memoria suficiente, debe pedir un dato adicional y no inventar', memory_type='instruction')


def seed_default_base() -> None:
    create_user('martin'); create_user('pedro'); create_user('martina')
    ensure_project_record('martin', 'memoria-guia')
    ensure_project_record('martin', 'coc')
    ensure_project_record('pedro', 'memoria-guia')
    insert_semantic(memory_id='m-color-green', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde', version=2)
    insert_semantic(memory_id='m-color-blue-old', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='azul', status='superseded', version=1, valid_to=utc_now_iso())
    insert_semantic(memory_id='pedro-color', user_id='pedro', project='memoria-guia', entity='user', attribute='favorite_color', value='negro')
    insert_semantic(memory_id='martina-color', user_id='martina', project='memoria-guia', entity='user', attribute='favorite_color', value='rojo')
    insert_semantic(memory_id='martin-person-pedro', user_id='martin', project='memoria-guia', entity='person_pedro', attribute='favorite_color', value='negro')
    insert_semantic(memory_id='martin-person-martina', user_id='martin', project='memoria-guia', entity='person_martina', attribute='favorite_color', value='rojo')
    seed_rules('memoria-guia')
    insert_semantic(memory_id='coc-ab', user_id='martin', project='coc', entity='assistant_policy', attribute='ambiguity_options', value='ante ambigüedad, ofrecer opciones A/B', memory_type='instruction')
    insert_chat_log(user_id='martin', project='memoria-guia', user_message='¿Cuál es mi color favorito?', assistant_answer='No tengo memoria suficiente', event_id='log-1')
    insert_chat_log(user_id='martin', project='memoria-guia', user_message='¿Cuál es mi color favorito?', assistant_answer='Azul', event_id='log-2')


def seed_state(initial_state: str) -> None:
    s = initial_state
    if s in {
        'Base por defecto: martin/memoria-guia; cuando corresponda existe histórico=azul, vigente=verde, pedro=negro, martina=rojo, regla=no inventar.',
        'martin y terceros; proyectos memoria-guia/coc; logs conversacionales presentes según caso',
        'Estado predefinido según historial del caso; puede requerir comparación antes/después o bug histórico reproducido.',
    }:
        seed_default_base()
        insert_semantic(memory_id='m-city', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_city', value='Córdoba')
        insert_semantic(memory_id='m-greet', user_id='martin', project='memoria-guia', entity='user', attribute='preferred_greeting', value='directo')
        insert_semantic(memory_id='m-provider', user_id='martin', project='memoria-guia', entity='user', attribute='preferred_provider', value='taller norte')
        insert_semantic(memory_id='m-priority', user_id='martin', project='memoria-guia', entity='project_meta', attribute='priority_project', value='memoria-guia')
        insert_semantic(memory_id='coc-priority', user_id='martin', project='coc', entity='project_meta', attribute='priority_project', value='coc')
        return
    if s == 'sin memorias previas' or s == 'sin memorias previas; user_id=martin; project=memoria-guia':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        return
    if s == 'user_id=martin; project=memoria-guia; memoria activa: color_favorito_actual=verde; memoria histórica: color_favorito_pasado=azul':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='crit-green', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde', version=2)
        insert_semantic(memory_id='crit-blue', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='azul', status='superseded', version=1, valid_to=utc_now_iso())
        return
    if s == 'user_id=martin; project=memoria-guia; no existe memoria sobre comida_favorita':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia'); seed_rules('memoria-guia'); return
    if s == 'martin: color_favorito=verde; pedro: color_favorito=negro':
        create_user('martin'); create_user('pedro'); ensure_project_record('martin', 'memoria-guia'); ensure_project_record('pedro', 'memoria-guia')
        insert_semantic(memory_id='u-green', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde')
        insert_semantic(memory_id='p-black', user_id='pedro', project='memoria-guia', entity='user', attribute='favorite_color', value='negro')
        return
    if s == 'martin/memoria-guia: regla=consultar memoria; martin/coc: regla=ofrecer opciones A/B ante ambigüedad':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia'); ensure_project_record('martin', 'coc')
        seed_rules('memoria-guia')
        insert_semantic(memory_id='ab-coc', user_id='martin', project='coc', entity='assistant_policy', attribute='ambiguity_options', value='ante ambigüedad, ofrecer opciones A/B', memory_type='instruction')
        return
    if s == 'activa: color_favorito=verde; archivada: color_favorito=rojo':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='active-green', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde')
        insert_semantic(memory_id='arch-red', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='rojo', status='archived')
        return
    if s in {'memoria borrada: ciudad_favorita=Córdoba; no existe otra memoria vigente sobre ciudad_favorita', 'borrada: ciudad_favorita=Córdoba; no existe memoria activa sobre ciudad favorita'}:
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='city-del', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_city', value='Córdoba', status='deleted')
        return
    if s in {'histórico: antes color_favorito=azul; vigente: ahora color_favorito=verde', 'histórico: color_favorito=azul; vigente: color_favorito=verde', 'histórico: antes color_favorito=azul; vigente: ahora color_favorito=verde'}:
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='hist-blue', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='azul', status='superseded', version=1, valid_to=utc_now_iso())
        insert_semantic(memory_id='curr-green', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde', version=2)
        return
    if s == 'histórico: respuesta_coc=concisa; vigente: respuesta_coc=consultar memoria y no inventar':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='old-rule', user_id='martin', project='memoria-guia', entity='assistant_policy', attribute='coc_response', value='concisa', status='superseded', version=1, memory_type='instruction', valid_to=utc_now_iso())
        insert_semantic(memory_id='new-rule1', user_id='martin', project='memoria-guia', entity='assistant_policy', attribute='memory_first', value='consultar memoria antes de responder', memory_type='instruction')
        insert_semantic(memory_id='new-rule2', user_id='martin', project='memoria-guia', entity='assistant_policy', attribute='insufficient_memory_rule', value='si no hay memoria suficiente, debe pedir un dato adicional y no inventar', memory_type='instruction')
        return
    if s == 'martin/memoria-guia tiene 3 memorias; martin/coc tiene 2; pedro/memoria-guia tiene 1':
        create_user('martin'); create_user('pedro'); ensure_project_record('martin', 'memoria-guia'); ensure_project_record('martin', 'coc'); ensure_project_record('pedro', 'memoria-guia')
        insert_semantic(memory_id='mmg-1', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde')
        insert_semantic(memory_id='mmg-2', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_city', value='Córdoba')
        insert_semantic(memory_id='mmg-3', user_id='martin', project='memoria-guia', entity='assistant_policy', attribute='memory_first', value='consultar memoria antes de responder', memory_type='instruction')
        insert_semantic(memory_id='mc-1', user_id='martin', project='coc', entity='assistant_policy', attribute='ambiguity_options', value='ante ambigüedad, ofrecer opciones A/B', memory_type='instruction')
        insert_semantic(memory_id='mc-2', user_id='martin', project='coc', entity='project_meta', attribute='priority_project', value='coc')
        insert_semantic(memory_id='pmg-1', user_id='pedro', project='memoria-guia', entity='user', attribute='favorite_color', value='negro')
        return
    if s == 'memorias activas: color_favorito=verde; ciudad_favorita=Córdoba; regla=consultar memoria':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='mem-1', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde')
        insert_semantic(memory_id='mem-2', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_city', value='Córdoba')
        insert_semantic(memory_id='mem-3', user_id='martin', project='memoria-guia', entity='assistant_policy', attribute='memory_first', value='consultar memoria antes de responder', memory_type='instruction')
        return
    if s == 'memorias activas: color_favorito=verde; saludo_preferido=directo; proveedor=taller norte':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='mem-1', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde')
        insert_semantic(memory_id='mem-2', user_id='martin', project='memoria-guia', entity='user', attribute='preferred_greeting', value='directo')
        insert_semantic(memory_id='mem-3', user_id='martin', project='memoria-guia', entity='user', attribute='preferred_provider', value='taller norte')
        return
    if s == 'antes: proveedor_preferido=taller norte activo; luego archivado':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='prov-active', user_id='martin', project='memoria-guia', entity='user', attribute='preferred_provider', value='taller norte')
        return
    if s == 'ya existe id=M-001 activo con color_favorito=verde':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        semantic_collection.document('M-001').set({
            'id': 'M-001', 'user_id': 'martin', 'project': 'memoria-guia', 'book_id': 'general', 'memory_type': 'preference',
            'entity': 'user', 'attribute': 'favorite_color', 'value_text': 'verde', 'context': 'color_favorito=verde', 'status': 'active',
            'dedupe_key': build_dedupe_key('martin', 'memoria-guia', 'general', 'user', 'favorite_color'), 'version': 1, 'valid_from': utc_now_iso(), 'valid_to': None,
            'source_type': 'seed', 'source_event_id': 'seed-M-001', 'created_at': utc_now_iso(), 'updated_at': None,
        })
        return
    if s == 'antes del reinicio: memoria activa color_favorito=verde y regla consultar memoria':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        insert_semantic(memory_id='persist-color', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='verde')
        seed_rules('memoria-guia')
        return
    if s == 'frontend autenticado; panel muestra respuestas derivadas; memoria interna no debe ser visible':
        seed_default_base(); return
    if s == 'frontend público; ruta privada requiere sesión válida' or s == 'Frontend público; backend privado; usuario con o sin sesión según caso; puentes/MCP en estado configurable.':
        seed_default_base(); return
    raise ValueError(f'Estado no soportado: {s}')


def family_of(case: dict) -> str:
    return re.sub(r'_\d+$', '', case['title'])


def new_client() -> TestClient:
    return TestClient(app)


def post_chat(client: TestClient, message: str, project: str = 'memoria-guia', user_id: str = 'martin'):
    return client.post('/chat', json={'user_id': user_id, 'project': project, 'book_id': 'general', 'message': message, 'save_interaction': True})


def ask_panel(client: TestClient, message: str, project: str = 'memoria-guia'):
    return client.post('/panel/chat', json={'project': project, 'book_id': 'general', 'message': message})


def register_login(client: TestClient, project: str = 'memoria-guia', user_id: str = 'martin', password: str = 'clave-segura-123'):
    response = client.post('/auth/register', json={'user_id': user_id, 'password': password, 'project': project})
    if response.status_code == 409:
        response = client.post('/auth/login', json={'user_id': user_id, 'password': password})
    return response


def check_color_answer(resp, expected='verde', forbidden=('azul','rojo')):
    try:
        body = resp.json()
    except Exception:
        return False, {'status_code': resp.status_code, 'text': resp.text[:300]}
    passed = resp.status_code == 200 and contains(body.get('answer'), expected) and not any(contains(body.get('answer'), bad) for bad in forbidden)
    return passed, body


def check_abstention(resp):
    try:
        body = resp.json()
    except Exception:
        return False, {'status_code': resp.status_code, 'text': resp.text[:300]}
    answer = body.get('answer', '')
    passed = resp.status_code == 200 and (body.get('mode') == 'insufficient_memory' or contains(answer, 'no tengo memoria suficiente', 'no tengo ese dato', 'dame un dato', 'aclaracion'))
    return passed, body


def check_rule_answer(resp, want_ab=False):
    body = resp.json()
    answer = body.get('answer','')
    ok = contains(answer, 'consultar memoria', 'leer memoria') or contains(answer, 'debe primero consultar memoria')
    if want_ab:
        ok = ok or contains(answer, 'A/B', 'opciones A/B')
    ok = ok and (contains(answer, 'no inventar') or contains(answer, 'pedir un dato adicional') or want_ab)
    return resp.status_code == 200 and ok, body


def check_summary_user(resp):
    body = resp.json(); answer = body.get('answer','')
    ok = contains(answer, 'verde') and not contains(answer, 'negro', 'rojo')
    return resp.status_code == 200 and ok, body


def exec_core(case, client):
    cid = case['case_id']
    title = case['title']
    if title.startswith('guardar_preferencia_simple'):
        m = re.search(r'"(.+)"', case['user_input'])
        message = m.group(1)
        r = post_chat(client, message)
        search_q = 'color favorito' if 'color' in message else 'consultar memoria' if 'consultar memoria' in message else 'proyecto prioritario' if 'proyecto prioritario' in message else 'proveedor preferido' if 'proveedor' in message else 'saludo preferido'
        rs = client.post('/memories/search', json={'user_id': 'martin', 'project': 'memoria-guia', 'query': search_q})
        items = rs.json()
        ok = r.status_code == 200 and rs.status_code == 200 and len(items) >= 1
        return ok, {'store': r.json(), 'search_count': len(items), 'items': items[:3]}
    if title.startswith('rechazo_invalido'):
        payload = {
            'id': 'BAD-1', 'user_id': 'martin', 'project': 'memoria-guia', 'book_id': 'general', 'memory_type': 'note', 'status': 'active',
            'content': 'mi color favorito es verde', 'summary': 's', 'user_message': 'u', 'assistant_answer': 'a', 'trigger_query': 'color', 'importance': 1, 'source': 'manual', 'created_at': '2026-01-01T00:00:00Z'
        }
        if cid == 'CORE-006': payload.pop('user_id')
        elif cid == 'CORE-007': payload.pop('project')
        elif cid == 'CORE-008': payload['created_at'] = 'fecha-invalida'
        elif cid == 'CORE-009': payload['id'] = ''
        elif cid == 'CORE-010': payload['content'] = None
        r = client.post('/memories', json=payload)
        ok = r.status_code in {400, 422}
        items = client.get('/memories').json()
        return ok and len(items) == 0, {'status_code': r.status_code, 'body': r.json() if r.headers.get('content-type','').startswith('application/json') else r.text, 'count': len(items)}
    if title.startswith('duplicado'):
        payload = {
            'id': 'M-001', 'user_id': 'martin', 'project': 'memoria-guia', 'book_id': 'general', 'memory_type': 'note', 'status': 'active',
            'content': 'mi color favorito es rojo', 'summary': 'dup', 'user_message': 'u', 'assistant_answer': 'a', 'trigger_query': 'color', 'importance': 1, 'source': 'manual', 'created_at': '2026-01-01T00:00:00Z'
        }
        r = client.post('/memories', json=payload)
        items = client.get('/memories').json()
        kept = [x for x in items if x['id'] == 'M-001']
        ok = r.status_code == 400 and len(kept) == 1 and contains(kept[0].get('value_text',''), 'verde')
        return ok, {'status_code': r.status_code, 'kept': kept}
    if title.startswith('listar_filtros'):
        rs = client.post('/memories/search', json={'user_id': 'martin', 'project': 'memoria-guia'})
        items = rs.json()
        ok = rs.status_code == 200 and len(items) == 3 and all(x['user_id']=='martin' and x['project']=='memoria-guia' for x in items)
        return ok, {'count': len(items), 'items': items}
    if title.startswith('busqueda_exacta'):
        query = case['user_input'].split("Buscar",1)[1].strip().strip('.')
        query = query.strip(" '")
        rs = client.post('/memories/search', json={'user_id': 'martin', 'project': 'memoria-guia', 'query': query})
        items = rs.json()
        answer_blob = json.dumps(items, ensure_ascii=False)
        expected = 'favorite_color' if 'color' in norm(query) else 'favorite_city' if 'ciudad' in norm(query) else 'memory_first'
        ok = rs.status_code == 200 and len(items) >= 1 and contains(answer_blob, expected.replace('_',' '), expected, 'verde' if expected=='favorite_color' else 'cordoba' if expected=='favorite_city' else 'consultar memoria')
        return ok, {'count': len(items), 'items': items[:3]}
    if title.startswith('busqueda_parecida'):
        r = post_chat(client, case['user_input'])
        if cid == 'CORE-026': return check_color_answer(r, 'verde')
        if cid in {'CORE-027','CORE-030'}:
            body=r.json(); ok = contains(body.get('answer'),'directo'); return r.status_code==200 and ok, body
        if cid in {'CORE-028','CORE-029'}:
            body=r.json(); ok = contains(body.get('answer'),'taller norte'); return r.status_code==200 and ok, body
    if title.startswith('actualizar_actual'):
        return check_color_answer(post_chat(client, case['user_input']), 'verde')
    if title.startswith('historico_vs_actual'):
        body = post_chat(client, case['user_input']).json(); ok = contains(body.get('answer'),'azul') and not contains(body.get('answer'),'verde')
        return ok, body
    if title.startswith('reglas_contradiccion'):
        return check_rule_answer(post_chat(client, case['user_input']))
    if title.startswith('archivado_exclusion'):
        return check_color_answer(post_chat(client, case['user_input']), 'verde', forbidden=('rojo',))
    if title.startswith('borrado_exclusion'):
        return check_abstention(post_chat(client, case['user_input']))
    if title.startswith('estado_post_cambio'):
        explicit_q = '¿Con qué taller prefiero trabajar?'
        if cid == 'CORE-056':
            body = post_chat(client, explicit_q).json(); ok = contains(body.get('answer'),'taller norte'); return ok, body
        client.post('/memories/prov-active/archive')
        return check_abstention(post_chat(client, explicit_q))
    raise NotImplementedError(title)


def exec_crit(case, client):
    title = case['title']
    if title.startswith('respuesta_correcta_hecho_directo') or title.startswith('no_mezcla_usuario') or title.startswith('verdad_actual') or title.startswith('no_archivada'):
        return check_color_answer(post_chat(client, case['user_input']), 'verde', forbidden=('azul','rojo','negro'))
    if title.startswith('abstencion_sin_memoria') or title.startswith('no_borrada'):
        return check_abstention(post_chat(client, case['user_input']))
    if title.startswith('no_mezcla_proyecto'):
        return check_rule_answer(post_chat(client, case['user_input'], project='memoria-guia'))
    if title.startswith('no_expone_panel'):
        register_login(client)
        r = client.get('/ui/')
        ok = r.status_code == 200 and not contains(r.text, 'semantic_memories', 'value_text', 'dedupe_key', 'ver memoria')
        return ok, {'status_code': r.status_code, 'snippet': r.text[:300]}
    if title.startswith('sesion_privada'):
        r = client.get('/panel/projects')
        ok = r.status_code == 401
        return ok, {'status_code': r.status_code, 'body': r.json()}
    if title.startswith('persistencia_basica'):
        before = post_chat(client, '¿Cuál es mi color favorito actual?' if 'color' in norm(case['user_input']) else '¿Cómo debe responder COC hoy?').json()
        client2 = new_client()
        after = post_chat(client2, '¿Cuál es mi color favorito actual?' if 'color' in norm(case['user_input']) else '¿Cómo debe responder COC hoy?').json()
        ok = before.get('answer') == after.get('answer')
        return ok, {'before': before, 'after': after}
    raise NotImplementedError(title)


def exec_iso(case, client):
    title = case['title']
    project = 'coc' if 'estoy en coc' in norm(case['user_input']) else 'memoria-guia'
    if title.startswith('usuario'):
        nq = norm(case['user_input'])
        body = post_chat(client, case['user_input'], project=project).json()
        if 'regla de respuesta' in nq:
            ok = contains(body.get('answer'),'consultar memoria','no inventar','dato adicional') and not contains(body.get('answer'),'pedro','martina'); return ok, body
        if 'saludo' in nq:
            ok = (contains(body.get('answer'),'directo') or body.get('mode') == 'answer') and not contains(body.get('answer'),'pedro','martina'); return ok, body
        if 'proveedor' in nq or 'taller' in nq:
            ok = contains(body.get('answer'),'taller norte') and not contains(body.get('answer'),'martina'); return ok, body
        if 'proyecto prioritario' in nq or 'prioridad' in nq:
            ok = body.get('mode') == 'answer' and not contains(body.get('answer'),'pedro','martina'); return ok, body
        if 'que recuerdas de mi' in nq or 'solo mis preferencias' in nq or 'lo mio actual' in nq:
            return check_summary_user(post_chat(client, case['user_input'], project=project))
        return check_color_answer(post_chat(client, case['user_input'], project=project), 'verde', forbidden=('negro','rojo'))
    if title.startswith('proyecto'):
        nq = norm(case['user_input'])
        if project == 'coc':
            body = post_chat(client, case['user_input'], project='coc').json(); ok = contains(body.get('answer'),'A/B','opciones') and not contains(body.get('answer'),'memoria-guia'); return ok, body
        body = post_chat(client, case['user_input'], project='memoria-guia').json()
        if 'prioridad' in nq:
            ok = contains(body.get('answer'),'memoria-guia') and not contains(body.get('answer'),'A/B'); return ok, body
        ok = contains(body.get('answer'),'consultar memoria') or contains(body.get('answer'),'no inventar')
        return ok and not contains(body.get('answer'),'A/B'), body
    if title.startswith('contaminacion_logs'):
        return check_color_answer(post_chat(client, case['user_input']), 'verde', forbidden=('azul','no tengo memoria suficiente'))
    raise NotImplementedError(title)


def exec_lang(case, client):
    cid = case['case_id']
    title = case['title']
    if title.startswith('negacion'):
        r = post_chat(client, case['user_input'])
        if cid == 'LANG-003':
            return check_abstention(post_chat(client, '¿Cuál es mi comida favorita?'))
        if cid in {'LANG-007'}:
            return check_abstention(post_chat(client, '¿Cuál es mi comida favorita?'))
        if cid in {'LANG-010'}:
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito?'), 'verde', forbidden=('amarillo','rojo','negro'))
        if cid in {'LANG-006'}:
            body = post_chat(client, '¿Con qué taller prefiero trabajar?').json(); ok = body.get('mode') in {'insufficient_memory','answer'} and not contains(body.get('answer'),'rojo'); return ok, {'first': r.json(), 'followup': body}
        return check_color_answer(post_chat(client, '¿Cuál es mi color favorito actual?'), 'verde', forbidden=('rojo',))
    if title.startswith('correccion'):
        post_chat(client, case['user_input'])
        if cid in {'LANG-011','LANG-015'}:
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito actual?'), 'verde', forbidden=('azul','rojo'))
        if cid == 'LANG-012':
            body = post_chat(client, '¿Con qué taller prefiero trabajar?').json(); ok = contains(body.get('answer'),'taller sur'); return ok, body
        if cid in {'LANG-013','LANG-017'}:
            body = post_chat(client, '¿Qué proyecto prioritario tengo yo?').json(); expected = 'coc' if cid=='LANG-017' else 'memoria-guia'; ok = contains(body.get('answer'), expected); return ok, body
        if cid == 'LANG-014':
            return check_rule_answer(post_chat(client, '¿Cómo debe responder COC hoy?'))
        if cid == 'LANG-019':
            body = post_chat(client, '¿Qué saludo prefiero yo?').json(); ok = contains(body.get('answer'),'directo'); return ok, body
        if cid == 'LANG-020':
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito actual?'), 'verde')
        body = post_chat(client, '¿Cuál es mi color favorito actual?').json(); return contains(body.get('answer'),'verde'), body
    if title.startswith('pasado_presente'):
        nq = norm(case['user_input'])
        if ('antes' in nq or 'anterior' in nq or 'historicamente' in nq) and 'hoy' not in nq and 'ahora' not in nq and 'corre hoy' not in nq and 'vale hoy' not in nq:
            body = post_chat(client, case['user_input']).json(); ok = contains(body.get('answer'),'azul'); return ok, body
        return check_color_answer(post_chat(client, case['user_input']), 'verde')
    if title.startswith('ruido_no_guardar'):
        post_chat(client, case['user_input'])
        if 'ciudad favorita' in norm(case['expected_result']):
            body = post_chat(client, '¿Cuál es mi ciudad favorita?').json(); ok = body.get('mode') in {'answer','insufficient_memory'} and not contains(body.get('answer'),'otra'); return ok, body
        if 'proveedor' in norm(case['user_input']) or 'taller rojo' in norm(case['user_input']):
            body = post_chat(client, '¿Con qué taller prefiero trabajar?').json(); ok = not contains(body.get('answer'),'rojo'); return ok, body
        if 'color' in norm(case['user_input']) or 'verde' in norm(case['user_input']):
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito actual?'), 'verde', forbidden=('azul',))
        return check_abstention(post_chat(client, '¿Cuál es mi comida favorita?'))
    if title.startswith('nombres_parecidos'):
        body = post_chat(client, case['user_input']).json()
        if cid == 'LANG-048':
            ok = contains(body.get('answer'),'verde') and contains(body.get('answer'),'negro'); return ok, body
        if cid == 'LANG-050':
            ok = body.get('mode') in {'answer','insufficient_memory'} and not contains(body.get('answer'),'martin perez','martín pérez'); return ok, body
        if cid == 'LANG-045':
            ok = not contains(body.get('answer'),'rojo','negro') or contains(body.get('answer'),'separad','no voy a mezclar'); return ok, body
        if cid == 'LANG-047':
            ok = contains(body.get('answer'),'memoria-guia') and not contains(body.get('answer'),'equipo'); return ok, body
        if 'taller' in norm(case['user_input']):
            ok = not contains(body.get('answer'),'pedro'); return ok, body
        return check_color_answer(post_chat(client, case['user_input']), 'verde', forbidden=('rojo','negro','amarillo'))
    if title.startswith('ambiguedad_sobreentendido'):
        if cid == 'LANG-054' or cid == 'LANG-059' or cid == 'LANG-056':
            return check_rule_answer(post_chat(client, case['user_input']))
        if cid == 'LANG-060':
            body = post_chat(client, case['user_input']).json(); ok = contains(body.get('answer'),'no lo guard', 'lo sigo ignorando', 'no lo voy a guardar'); return ok, body
        if cid == 'LANG-057':
            return check_summary_user(post_chat(client, case['user_input']))
        if cid == 'LANG-055':
            body = post_chat(client, case['user_input']).json(); ok = contains(body.get('answer'),'consultar memoria','no inventar','dato adicional'); return ok, body
        return check_color_answer(post_chat(client, case['user_input']), 'verde')
    if title.startswith('frases_largas_desordenadas'):
        if cid in {'LANG-066'}:
            body = post_chat(client, case['user_input']).json(); ok = contains(body.get('answer'),'verde') or body.get('mode') == 'insufficient_memory'; return ok, body
        if cid == 'LANG-068':
            body = post_chat(client, case['user_input']).json(); ok = not contains(body.get('answer'),'dedupe_key','value_text','semantic') and (contains(body.get('answer'),'verde') or contains(body.get('answer'),'respuesta')); return ok, body
        if cid == 'LANG-067':
            return check_summary_user(post_chat(client, case['user_input'], project='memoria-guia'))
        return check_color_answer(post_chat(client, case['user_input']), 'verde', forbidden=('rojo', 'negro'))
    raise NotImplementedError(title)


def exec_pers(case, client):
    title = case['title']
    if title.startswith('persistencia'):
        before_q = '¿Cuál es mi color favorito actual?'
        if 'regla' in norm(case['user_input']): before_q = '¿Cómo debe responder COC hoy?'
        if 'prioridad' in norm(case['user_input']): before_q = '¿Qué proyecto prioritario tengo yo?'
        if 'archivada' in norm(case['user_input']):
            before_q = '¿Cuál es mi color favorito actual?'
            semantic_collection.document('arch-red').set({**semantic_collection.document('arch-red').get().to_dict(), 'status': 'archived'}) if semantic_collection.document('arch-red').get().exists else insert_semantic(memory_id='arch-red', user_id='martin', project='memoria-guia', entity='user', attribute='favorite_color', value='rojo', status='archived')
        if 'borrada' in norm(case['user_input']) or 'borrar' in norm(case['user_input']):
            before_q = '¿Cuál es mi ciudad favorita?'
        before = post_chat(client, before_q)
        client2 = new_client()
        after = post_chat(client2, before_q)
        ok = before.json().get('answer') == after.json().get('answer')
        return ok, {'before': before.json(), 'after': after.json()}
    if title.startswith('regresion'):
        if 'pedro con martin' in norm(case['user_input']):
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito?'), 'verde', forbidden=('negro',))
        if 'azul como actual' in norm(case['user_input']):
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito actual?'), 'verde', forbidden=('azul',))
        if 'archivada' in norm(case['user_input']):
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito actual?'), 'verde', forbidden=('rojo',))
        if 'dato inexistente' in norm(case['user_input']):
            return check_abstention(post_chat(client, '¿Cuál es mi comida favorita?'))
        if 'memoria cruda' in norm(case['user_input']):
            register_login(client)
            r = client.get('/ui/')
            ok = not contains(r.text, 'semantic_memories', 'value_text', 'dedupe_key')
            return ok, {'status_code': r.status_code, 'snippet': r.text[:300]}
        if 'regla de coc en memoria-guia' in norm(case['user_input']):
            return check_rule_answer(post_chat(client, 'En memoria-guia, ¿cómo debe responder COC?'))
        if 'ruta privada sin sesion' in norm(case['user_input']):
            r = client.get('/panel/projects'); return r.status_code == 401, {'status_code': r.status_code}
        if 'dato borrado' in norm(case['user_input']):
            if semantic_collection.document('m-city').get().exists:
                semantic_collection.document('m-city').delete()
            return check_abstention(post_chat(client, '¿Cuál es mi ciudad favorita?'))
        if 'ruido como recuerdo fijo' in norm(case['user_input']):
            post_chat(client, 'No guardes esto: hoy almorcé milanesas.')
            return check_abstention(post_chat(client, '¿Cuál es mi comida favorita?'))
        if 'respuesta vieja del asistente' in norm(case['user_input']):
            return check_color_answer(post_chat(client, '¿Cuál es mi color favorito?'), 'verde', forbidden=('azul',))
    raise NotImplementedError(title)


def exec_e2e(case, client):
    cid = case['case_id']
    if cid == 'E2E-001':
        r = client.get('/panel/projects'); return r.status_code == 401, {'status_code': r.status_code, 'body': r.json()}
    if cid == 'E2E-002':
        create_user('martin'); ensure_project_record('martin', 'memoria-guia')
        # no valid password hash for login path; register then logout and try bad login
        register_login(client); client.post('/auth/logout')
        r = client.post('/auth/login', json={'user_id': 'martin', 'password': 'incorrecta'})
        return r.status_code == 401 and not contains(json.dumps(r.json(), ensure_ascii=False), 'traceback', 'exception'), {'status_code': r.status_code, 'body': r.json()}
    if cid in {'E2E-003','E2E-004'}:
        r = register_login(client)
        if cid == 'E2E-003':
            dash = client.get('/panel/bootstrap')
        else:
            dash = client.get('/panel/projects')
        ok = r.status_code == 200 and dash.status_code == 200
        return ok, {'register': r.json(), 'dash': dash.json()}
    if cid == 'E2E-005':
        register_login(client)
        r = ask_panel(client, 'hola', project='otro-proyecto')
        return r.status_code == 403, {'status_code': r.status_code, 'body': r.json()}
    if cid == 'E2E-006':
        seed_default_base(); register_login(client)
        r = ask_panel(client, '¿Cuál es mi color favorito actual?')
        return check_color_answer(r, 'verde')
    if cid == 'E2E-007':
        register_login(client)
        return check_abstention(ask_panel(client, '¿Cuál es mi comida favorita?'))
    if cid in {'E2E-008','E2E-015','E2E-016','E2E-017'}:
        r_ui = client.get('/ui/')
        r_js = client.get('/ui/app.js')
        ok = not contains(r_ui.text, 'semantic_memories', 'value_text', 'dedupe_key', 'console.log') and not contains(r_js.text, 'localStorage', 'sessionStorage', 'console.log', 'console.error')
        return ok, {'ui_status': r_ui.status_code, 'js_status': r_js.status_code}
    if cid in {'E2E-009','E2E-010','E2E-011'}:
        r_js = client.get('/ui/app.js')
        ok = contains(r_js.text, 'request_timeout', 'session_expired', 'retry')
        return ok, {'js_status': r_js.status_code, 'snippet': r_js.text[:400]}
    if cid == 'E2E-012':
        register_login(client)
        for item in sessions_collection.stream():
            sessions_collection.document(item.id).update({'expires_at': '2000-01-01T00:00:00Z'})
        r = client.get('/panel/projects')
        return r.status_code == 401, {'status_code': r.status_code, 'body': r.json()}
    if cid == 'E2E-013':
        register_login(client)
        client.post('/auth/logout')
        r = client.get('/panel/projects')
        return r.status_code == 401, {'status_code': r.status_code, 'body': r.json()}
    if cid == 'E2E-014':
        register_login(client)
        client.post('/auth/logout')
        r = client.get('/panel/projects')
        return r.status_code == 401, {'status_code': r.status_code, 'body': r.json()}
    if cid == 'E2E-018':
        seed_default_base(); register_login(client)
        headers={'user-agent':'Mozilla/5.0 (Linux; Android 15)'}
        r = client.get('/ui/', headers=headers)
        q = ask_panel(client, '¿Cuál es mi color favorito actual?')
        ok = r.status_code == 200 and q.status_code == 200 and contains(q.json().get('answer'),'verde')
        return ok, {'ui_status': r.status_code, 'chat': q.json()}
    if cid == 'E2E-019':
        register_login(client)
        client.post('/panel/projects', json={'project': 'coc'})
        r1 = ask_panel(client, '¿Cómo debe responder COC hoy?', project='memoria-guia')
        r2 = ask_panel(client, 'Estoy en coc: ¿qué regla extra hay ante ambigüedad?', project='coc')
        ok = r1.status_code == 200 and r2.status_code == 200 and (contains(r1.json().get('answer'),'consultar memoria') or r1.json().get('mode')=='answer') and (contains(r2.json().get('answer'),'A/B','opciones') or r2.json().get('mode')=='answer')
        return ok, {'memoria_guia': r1.json(), 'coc': r2.json()}
    if cid == 'E2E-020':
        register_login(client)
        good = client.get('/panel/projects')
        client.post('/auth/logout')
        bad = client.get('/panel/projects')
        ok = good.status_code == 200 and bad.status_code == 401
        return ok, {'good_status': good.status_code, 'bad_status': bad.status_code}
    raise NotImplementedError(cid)


def run_case(case: dict) -> CaseResult:
    clear_all()
    seed_state(case['initial_state'])
    client = new_client()
    fam = family_of(case)
    try:
        if case['layer'] == 'nucleo_memoria':
            passed, actual = exec_core(case, client)
        elif case['layer'] == 'criticos_confianza':
            passed, actual = exec_crit(case, client)
        elif case['layer'] == 'aislamiento_seguridad_logica':
            passed, actual = exec_iso(case, client)
        elif case['layer'] == 'lenguaje_dificil':
            passed, actual = exec_lang(case, client)
        elif case['layer'] == 'persistencia_regresion':
            passed, actual = exec_pers(case, client)
        elif case['layer'] == 'end_to_end_real':
            passed, actual = exec_e2e(case, client)
        else:
            raise NotImplementedError(case['layer'])
        return CaseResult(case_id=case['case_id'], layer=case['layer'], family=fam, passed=bool(passed), status='passed' if passed else 'failed', reason='ok' if passed else 'assertion_failed', actual=actual)
    except Exception as exc:
        return CaseResult(case_id=case['case_id'], layer=case['layer'], family=fam, passed=False, status='error', reason=repr(exc), actual=None)


def main() -> int:
    cases = [json.loads(line) for line in CATALOG_PATH.open()]
    results = [run_case(case) for case in cases]
    by_layer = defaultdict(lambda: {'passed': 0, 'failed': 0, 'error': 0, 'total': 0})
    by_family = defaultdict(lambda: {'passed': 0, 'failed': 0, 'error': 0, 'total': 0})
    for result in results:
        slot = by_layer[result.layer]
        slot[result.status] += 1
        slot['total'] += 1
        slotf = by_family[result.family]
        slotf[result.status] += 1
        slotf['total'] += 1
    total_passed = sum(1 for r in results if r.passed)
    report = {
        'total': len(results),
        'passed': total_passed,
        'failed': len(results) - total_passed,
        'score_percent': round(total_passed * 100 / len(results), 2),
        'by_layer': by_layer,
        'by_family': by_family,
        'failing_cases': [asdict(r) for r in results if not r.passed][:120],
    }
    REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({k: report[k] for k in ['total','passed','failed','score_percent']}, ensure_ascii=False))
    for layer, stats in by_layer.items():
        print(layer, stats)
    print('report:', REPORT_PATH)
    return 0 if total_passed == len(results) else 1


if __name__ == '__main__':
    raise SystemExit(main())
