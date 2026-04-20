import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

os.environ.setdefault('USE_FAKE_FIRESTORE', 'true')
os.environ.setdefault('GITHUB_ACTIONS', 'true')

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.firestore_store import (
    documents_collection,
    event_log_collection,
    facts_collection,
    manual_notes_collection,
    retrieval_traces_collection,
    semantic_collection,
    session_summaries_collection,
)
from app.memory_core_v1 import MemoryScope, save_fact, save_note, search_memory


@dataclass
class CaseResult:
    category: str
    query: str
    expected_key: Optional[str]
    passed: bool
    hit_top1: bool
    hit_top3: bool
    expected_id: Optional[str]
    returned_ids: list[str]
    returned_previews: list[str]


BASE_DATA = {
    'notes': [
        ('n_beta', 'Roadmap beta', 'El lanzamiento beta de Atlas será el 15 de mayo de 2026.'),
        ('n_erp', 'ERP', 'El proveedor preferido para facturación es Nexo Azul.'),
        ('n_repo', 'Repositorio', 'El repositorio canónico del proyecto es GitHub en la organización memoria-ia.'),
        ('n_metrics', 'Métricas', 'El dashboard principal de métricas está en Grafana.'),
        ('n_legal', 'Legal', 'La reunión con abogados está prevista para el 12 de junio de 2026.'),
        ('n_decision_cloud', 'Infraestructura', 'Decisión tomada: usar Cloud Run como backend principal.'),
        ('n_rollback', 'Operaciones', 'Pendiente: ordenar Cloud Run y conservar una revisión de rollback.'),
        ('n_budget', 'Presupuesto', 'El presupuesto mensual de infraestructura es 90 USD.'),
        ('n_q2', 'Objetivo Q2', 'El objetivo del trimestre es validar memoria con usuarios reales.'),
        ('n_mobile', 'Hoja de ruta', 'La versión móvil queda postergada hasta cerrar la web.'),
    ],
    'facts': [
        ('f_drink', 'usuario', 'bebida favorita', 'café'),
        ('f_city', 'usuario', 'ciudad base', 'Córdoba'),
        ('f_priority1', 'proyecto', 'prioridad actual', 'cerrar conectores'),
        ('f_priority2', 'proyecto', 'prioridad actual', 'validar memoria'),
        ('f_provider', 'usuario', 'proveedor preferido', 'Nexo Azul'),
        ('f_greeting', 'usuario', 'saludo preferido', 'directo'),
        ('f_sot', 'proyecto', 'fuente de verdad', 'GitHub'),
        ('f_animal', 'usuario', 'animal favorito', 'gato'),
        ('f_stack', 'proyecto', 'stack principal', 'Cloud Run'),
    ],
    'tests': [
        ('exact','lanzamiento beta Atlas','n_beta'),
        ('exact','15 mayo 2026 Atlas','n_beta'),
        ('exact','facturación Nexo Azul','n_erp'),
        ('exact','repositorio canónico memoria-ia','n_repo'),
        ('exact','dashboard métricas Grafana','n_metrics'),
        ('exact','reunión abogados 12 junio 2026','n_legal'),
        ('exact','usar Cloud Run backend principal','n_decision_cloud'),
        ('exact','rollback Cloud Run','n_rollback'),
        ('exact','presupuesto mensual infraestructura','n_budget'),
        ('exact','objetivo trimestre usuarios reales','n_q2'),
        ('exact','versión móvil cerrar web','n_mobile'),
        ('exact','bebida favorita café','f_drink'),
        ('exact','ciudad base Córdoba','f_city'),
        ('exact','prioridad actual validar memoria','f_priority2'),
        ('exact','proveedor preferido Nexo Azul','f_provider'),
        ('exact','saludo preferido directo','f_greeting'),
        ('exact','fuente de verdad GitHub','f_sot'),
        ('exact','animal favorito gato','f_animal'),
        ('light','cuándo sale Atlas beta','n_beta'),
        ('light','qué proveedor usamos para facturación','n_erp'),
        ('light','dónde está el dashboard de métricas','n_metrics'),
        ('light','cuándo vemos a los abogados','n_legal'),
        ('light','qué decidimos para el backend principal','n_decision_cloud'),
        ('light','cómo dejamos el rollback','n_rollback'),
        ('light','cuánta plata va a infraestructura al mes','n_budget'),
        ('light','cuál es la meta del trimestre','n_q2'),
        ('light','qué dejamos para después de cerrar web','n_mobile'),
        ('light','qué proveedor preferimos','f_provider'),
        ('light','cuál es nuestra fuente de verdad','f_sot'),
        ('light','qué animal me gusta más','f_animal'),
        ('light','cuál es mi bebida favorita','f_drink'),
        ('light','cuál es la prioridad del proyecto','f_priority2'),
        ('light','de dónde soy','f_city'),
        ('light','cómo prefiero saludar','f_greeting'),
        ('hard','qué tomo siempre','f_drink'),
        ('hard','dónde vivo','f_city'),
        ('hard','qué sigue ahora','f_priority2'),
        ('hard','dónde vemos los números del sistema','n_metrics'),
        ('hard','qué quedó para más adelante','n_mobile'),
        ('hard','cómo quedó resuelto el hosting','n_decision_cloud'),
        ('hard','cuál es el plan para no perder rollback','n_rollback'),
        ('hard','dónde está el código fuente oficial','n_repo'),
        ('hard','con qué taller trabajamos normalmente','n_erp'),
        ('hard','qué hito manda este trimestre','n_q2'),
        ('isolation','beta Boreal', None),
        ('isolation','bebida favorita té', None),
        ('update','prioridad actual cerrar conectores','f_priority2'),
        ('update','bebida favorita café','f_drink'),
        ('negative','contrato de oficina Lisboa', None),
        ('negative','número de soporte urgente', None),
    ],
}


def clear_all() -> None:
    for collection in [
        manual_notes_collection,
        facts_collection,
        session_summaries_collection,
        retrieval_traces_collection,
        semantic_collection,
        event_log_collection,
        documents_collection,
    ]:
        collection.clear()


def seed_data() -> dict[str, str]:
    clear_all()
    scope = MemoryScope(tenant_id='martin', project_id='general', book_id='general', user_id='martin')
    other_project = MemoryScope(tenant_id='martin', project_id='work', book_id='general', user_id='martin')
    other_user = MemoryScope(tenant_id='pedro', project_id='general', book_id='general', user_id='pedro')
    ids: dict[str, str] = {}

    for key, title, content in BASE_DATA['notes']:
        ids[key] = save_note(scope, title, content)['id']
    for key, subject, relation, object_value in BASE_DATA['facts']:
        ids[key] = save_fact(scope, subject, relation, object_value)['id']

    ids['w_beta'] = save_note(other_project, 'Roadmap beta', 'El lanzamiento beta de Boreal será el 30 de junio de 2026.')['id']
    ids['u_drink'] = save_fact(other_user, 'usuario', 'bebida favorita', 'té')['id']
    return ids


def run_benchmark() -> dict:
    ids = seed_data()
    scope = MemoryScope(tenant_id='martin', project_id='general', book_id='general', user_id='martin')
    results: list[CaseResult] = []
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: {'total': 0, 'pass': 0, 'top1': 0, 'top3': 0})

    for category, query, expected_key in BASE_DATA['tests']:
        response = search_memory(scope, query, top_k=5)
        returned_ids = [item['id'] for item in response['items']]
        returned_previews = [item['preview'] for item in response['items']]
        expected_id = ids.get(expected_key) if expected_key else None
        hit_top1 = expected_id is not None and returned_ids[:1] == [expected_id]
        hit_top3 = expected_id is not None and expected_id in returned_ids[:3]
        passed = (len(returned_ids) == 0) if expected_id is None else hit_top3
        results.append(CaseResult(
            category=category,
            query=query,
            expected_key=expected_key,
            passed=passed,
            hit_top1=hit_top1,
            hit_top3=hit_top3,
            expected_id=expected_id,
            returned_ids=returned_ids,
            returned_previews=returned_previews,
        ))
        by_category[category]['total'] += 1
        by_category[category]['pass'] += int(passed)
        by_category[category]['top1'] += int(hit_top1)
        by_category[category]['top3'] += int(hit_top3)

    total = len(results)
    passed = sum(1 for item in results if item.passed)
    top1 = sum(1 for item in results if item.hit_top1)
    top3 = sum(1 for item in results if item.hit_top3)
    failures = [asdict(item) for item in results if not item.passed]

    return {
        'label': 'memory_search_practical_v2',
        'total_cases': total,
        'passed_cases': passed,
        'pass_rate': round(passed / total, 4),
        'top1_rate': round(top1 / total, 4),
        'top3_rate': round(top3 / total, 4),
        'by_category': by_category,
        'failures': failures,
        'cases': [asdict(item) for item in results],
    }


def main() -> None:
    report = run_benchmark()
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
