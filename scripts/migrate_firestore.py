"""
Migración one-shot de datos existentes al schema V2.

Lee:
  - facts (colección 'facts')
  - manual_notes (colección 'manual_notes')
  - session_summaries (colección 'session_summaries')

Escribe en la colección 'memory_entries' con el nuevo schema unificado.

Es IDEMPOTENTE: si una entry ya existe en memory_entries con el mismo id, la sobrescribe.

Uso (desde Cloud Shell):
    cd ~/memoria_engine_produccion
    python3 -m scripts.migrate_firestore

Opciones por env var:
    DRY_RUN=true        → solo imprime, no escribe nada
    LIMIT=100           → limita el número de docs a migrar (debug)
    FROM_TENANT=xxx     → solo migra ese tenant_id

Importante: este script asume que ya deployaste el código V2 en el mismo proyecto
(para que las colecciones y env vars estén correctamente resueltas).
"""
from __future__ import annotations

import os
import sys
from typing import Optional
from uuid import uuid4

# Hacer importable el paquete 'app' desde la raíz
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.embeddings import get_embedder  # noqa: E402
from app.llm_extractor import get_extractor  # noqa: E402
from app.vector_store import MemoryEntry, get_vector_store  # noqa: E402
from app.firestore_store import (  # noqa: E402
    facts_collection,
    manual_notes_collection,
    session_summaries_collection,
)
from app.utils import utc_now_iso  # noqa: E402


DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
LIMIT = int(os.getenv("LIMIT", "0"))
FROM_TENANT = os.getenv("FROM_TENANT", "").strip() or None


def _maybe_limit(iterable, n: int):
    if n <= 0:
        return iterable
    acc = []
    for i, x in enumerate(iterable):
        if i >= n:
            break
        acc.append(x)
    return acc


def migrate_facts(store, embedder, extractor) -> int:
    count = 0
    docs = list(facts_collection.stream())
    docs = _maybe_limit(docs, LIMIT)
    for snap in docs:
        data = snap.to_dict() or {}
        tenant_id = data.get("tenant_id") or data.get("user_id")
        if FROM_TENANT and tenant_id != FROM_TENANT:
            continue
        subj = data.get("subject") or data.get("entity") or "user"
        rel = data.get("relation") or data.get("attribute") or "dato"
        obj = data.get("object") or data.get("value_text") or ""
        if not obj:
            continue
        content = f"{subj} {rel.replace('_', ' ')} {obj}".strip()
        entity_key = (subj if subj != "user" else "user").lower()

        entry = MemoryEntry(
            id=data.get("id") or f"mem_{uuid4().hex}",
            tenant_id=tenant_id or "unknown",
            user_id=data.get("user_id") or tenant_id or "unknown",
            project_id=data.get("project_id") or data.get("project") or "general",
            book_id=data.get("book_id") or "general",
            kind="fact",
            content=content,
            facts=[{
                "subject": subj,
                "relation": rel,
                "object": obj,
                "entity_key": entity_key,
                "confidence": 0.9,
            }],
            entity_key=entity_key,
            embedding=embedder.embed(content),
            status=data.get("status", "active"),
            source="migrated_from_facts",
            created_at=data.get("created_at") or utc_now_iso(),
            updated_at=data.get("updated_at") or utc_now_iso(),
        )
        if not DRY_RUN:
            store.save(entry)
        count += 1
    return count


def migrate_notes(store, embedder, extractor) -> int:
    count = 0
    docs = list(manual_notes_collection.stream())
    docs = _maybe_limit(docs, LIMIT)
    for snap in docs:
        data = snap.to_dict() or {}
        tenant_id = data.get("tenant_id") or data.get("user_id")
        if FROM_TENANT and tenant_id != FROM_TENANT:
            continue
        content = data.get("content") or data.get("title") or ""
        if not content:
            continue

        # Intentar re-extraer hechos del contenido con el extractor nuevo.
        facts = [f.as_dict() for f in extractor.extract(content)]
        entity_key = facts[0]["entity_key"] if facts else "user"

        entry = MemoryEntry(
            id=data.get("id") or f"mem_{uuid4().hex}",
            tenant_id=tenant_id or "unknown",
            user_id=data.get("user_id") or tenant_id or "unknown",
            project_id=data.get("project_id") or data.get("project") or "general",
            book_id=data.get("book_id") or "general",
            kind="fact" if facts else "note",
            content=content,
            facts=facts,
            entity_key=entity_key,
            embedding=embedder.embed(content),
            status=data.get("status", "active"),
            source="migrated_from_notes",
            created_at=data.get("created_at") or utc_now_iso(),
            updated_at=data.get("updated_at") or utc_now_iso(),
        )
        if not DRY_RUN:
            store.save(entry)
        count += 1
    return count


def migrate_summaries(store, embedder, extractor) -> int:
    count = 0
    docs = list(session_summaries_collection.stream())
    docs = _maybe_limit(docs, LIMIT)
    for snap in docs:
        data = snap.to_dict() or {}
        tenant_id = data.get("tenant_id") or data.get("user_id")
        if FROM_TENANT and tenant_id != FROM_TENANT:
            continue
        content = data.get("summary") or ""
        if not content:
            continue

        entry = MemoryEntry(
            id=data.get("id") or f"mem_{uuid4().hex}",
            tenant_id=tenant_id or "unknown",
            user_id=data.get("user_id") or tenant_id or "unknown",
            project_id=data.get("project_id") or data.get("project") or "general",
            book_id=data.get("book_id") or "general",
            kind="summary",
            content=content,
            facts=[],
            entity_key="user",
            embedding=embedder.embed(content),
            status=data.get("status", "active"),
            source="migrated_from_summaries",
            created_at=data.get("created_at") or utc_now_iso(),
            updated_at=data.get("updated_at") or utc_now_iso(),
        )
        if not DRY_RUN:
            store.save(entry)
        count += 1
    return count


def main() -> None:
    print(f"▶ DRY_RUN={DRY_RUN}  LIMIT={LIMIT}  FROM_TENANT={FROM_TENANT or '(todos)'}")
    store = get_vector_store()
    embedder = get_embedder()
    extractor = get_extractor()
    print(f"  store={store.backend}  embedder={embedder.backend}  extractor={extractor.backend}")

    total = 0
    print("▶ Migrando facts…")
    n = migrate_facts(store, embedder, extractor)
    print(f"  facts: {n}")
    total += n

    print("▶ Migrando manual_notes…")
    n = migrate_notes(store, embedder, extractor)
    print(f"  manual_notes: {n}")
    total += n

    print("▶ Migrando session_summaries…")
    n = migrate_summaries(store, embedder, extractor)
    print(f"  session_summaries: {n}")
    total += n

    print(f"\n✓ Total migrado: {total} entries")
    if DRY_RUN:
        print("  (DRY_RUN activo: ninguno de estos docs fue escrito)")


if __name__ == "__main__":
    main()
