"""
Vector store con dos backends:

1. InMemoryVectorStore: para tests y desarrollo. Similitud coseno en Python puro.
2. FirestoreVectorStore: usa Firestore Vector Search (GA en firestore). Cada documento
   tiene un campo 'embedding' de tipo Vector y un campo de scope para filtrar.

El store guarda "MemoryEntry" (unidad mínima): id, scope, kind, content, facts, embedding,
created_at, status.

Por qué no uso la colección de facts_collection / manual_notes_collection existentes:
- Las quiero reemplazar por un único schema unificado.
- Mantengo las anteriores para retrocompatibilidad pero el motor nuevo escribe en una
  colección nueva: "memory_entries".
"""
from __future__ import annotations

import math
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, Protocol


@dataclass
class MemoryEntry:
    id: str
    tenant_id: str
    user_id: str
    project_id: str
    book_id: str
    kind: str  # "fact" | "note" | "task" | "summary"
    content: str  # texto original
    # Hechos estructurados extraídos (puede ser [])
    facts: list[dict] = field(default_factory=list)
    # Clave de entidad principal asociada ("sobrino", "user", etc.) para agrupar
    entity_key: str = ""
    # Vector denso del content
    embedding: list[float] = field(default_factory=list)
    status: str = "active"  # "active" | "superseded" | "archived"
    superseded_by: Optional[str] = None
    source: str = "panel_manual"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class VectorStore(Protocol):
    def save(self, entry: MemoryEntry) -> None: ...
    def get(self, entry_id: str) -> Optional[MemoryEntry]: ...
    def update_status(self, entry_id: str, status: str, superseded_by: Optional[str] = None) -> None: ...
    def search(
        self,
        *,
        tenant_id: str,
        user_id: str,
        project_id: str,
        book_id: str,
        query_embedding: list[float],
        top_k: int = 5,
        entity_key: Optional[str] = None,
        include_superseded: bool = False,
    ) -> list[tuple[float, MemoryEntry]]: ...
    def list_for_entity(
        self,
        *,
        tenant_id: str,
        user_id: str,
        project_id: str,
        book_id: str,
        entity_key: str,
        include_superseded: bool = False,
    ) -> list[MemoryEntry]: ...


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)


class InMemoryVectorStore:
    """Store en memoria, thread-safe. Usado en tests y como fallback absoluto."""
    backend = "memory"

    def __init__(self):
        self._lock = threading.Lock()
        self._by_id: dict[str, MemoryEntry] = {}

    def _matches_scope(self, e: MemoryEntry, tenant_id, user_id, project_id, book_id) -> bool:
        return (
            e.tenant_id == tenant_id
            and e.user_id == user_id
            and e.project_id == project_id
            and e.book_id == book_id
        )

    def save(self, entry: MemoryEntry) -> None:
        with self._lock:
            self._by_id[entry.id] = entry

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        with self._lock:
            return self._by_id.get(entry_id)

    def update_status(self, entry_id: str, status: str, superseded_by: Optional[str] = None) -> None:
        with self._lock:
            e = self._by_id.get(entry_id)
            if not e:
                return
            e.status = status
            if superseded_by is not None:
                e.superseded_by = superseded_by

    def search(self, *, tenant_id, user_id, project_id, book_id, query_embedding,
               top_k=5, entity_key=None, include_superseded=False):
        with self._lock:
            candidates = [
                e for e in self._by_id.values()
                if self._matches_scope(e, tenant_id, user_id, project_id, book_id)
                and (include_superseded or e.status == "active")
                and (entity_key is None or e.entity_key == entity_key)
            ]
        scored = [(_cosine(query_embedding, e.embedding), e) for e in candidates]
        scored.sort(key=lambda p: p[0], reverse=True)
        return scored[: max(1, top_k)]

    def list_for_entity(self, *, tenant_id, user_id, project_id, book_id,
                         entity_key, include_superseded=False):
        with self._lock:
            res = [
                e for e in self._by_id.values()
                if self._matches_scope(e, tenant_id, user_id, project_id, book_id)
                and e.entity_key == entity_key
                and (include_superseded or e.status == "active")
            ]
        res.sort(key=lambda e: e.updated_at or e.created_at, reverse=True)
        return res


class FirestoreVectorStore:
    """
    Store respaldado por Firestore Vector Search (GA).
    Colección: "memory_entries".

    Requiere que el índice vectorial exista sobre el campo 'embedding' con
    dim=EMBEDDING_DIM y distance_measure='COSINE'. Lo creamos con gcloud.
    """
    backend = "firestore"

    def __init__(self, firestore_client):
        self._db = firestore_client
        self._collection = firestore_client.collection("memory_entries")

    def _matches_scope_query(self, tenant_id, user_id, project_id, book_id):
        q = (
            self._collection
            .where("tenant_id", "==", tenant_id)
            .where("user_id", "==", user_id)
            .where("project_id", "==", project_id)
            .where("book_id", "==", book_id)
        )
        return q

    def save(self, entry: MemoryEntry) -> None:
        data = entry.to_dict()
        # En Firestore real, envolveríamos embedding con Vector() para habilitar
        # vector search. Si la librería no está disponible, lo guardamos como list
        # y hacemos fallback a cosine en Python (aún funcional, solo menos escalable).
        try:
            from google.cloud.firestore_v1.vector import Vector  # type: ignore
            data["embedding"] = Vector(entry.embedding)
        except Exception:  # noqa: BLE001
            pass
        self._collection.document(entry.id).set(data)

    def get(self, entry_id: str) -> Optional[MemoryEntry]:
        snap = self._collection.document(entry_id).get()
        if not snap.exists:
            return None
        data = snap.to_dict() or {}
        return _entry_from_dict(data)

    def update_status(self, entry_id: str, status: str, superseded_by: Optional[str] = None) -> None:
        updates = {"status": status}
        if superseded_by is not None:
            updates["superseded_by"] = superseded_by
        self._collection.document(entry_id).update(updates)

    def search(self, *, tenant_id, user_id, project_id, book_id, query_embedding,
               top_k=5, entity_key=None, include_superseded=False):
        q = self._matches_scope_query(tenant_id, user_id, project_id, book_id)
        if entity_key is not None:
            q = q.where("entity_key", "==", entity_key)
        if not include_superseded:
            q = q.where("status", "==", "active")

        # Intento 1: Firestore vector search nativo
        try:
            from google.cloud.firestore_v1.base_vector_query import DistanceMeasure  # type: ignore
            from google.cloud.firestore_v1.vector import Vector  # type: ignore
            vq = q.find_nearest(
                vector_field="embedding",
                query_vector=Vector(query_embedding),
                distance_measure=DistanceMeasure.COSINE,
                limit=max(top_k, 1),
            )
            results: list[tuple[float, MemoryEntry]] = []
            for doc in vq.stream():
                data = doc.to_dict() or {}
                e = _entry_from_dict(data)
                # Firestore no devuelve el score directo en stream(); aproximamos con cosine local
                score = _cosine(query_embedding, e.embedding) if e.embedding else 0.0
                results.append((score, e))
            return results
        except Exception:  # noqa: BLE001
            # Fallback: traer todos, scorear en Python (aceptable para <1000 memories por scope).
            results = []
            for doc in q.stream():
                data = doc.to_dict() or {}
                e = _entry_from_dict(data)
                score = _cosine(query_embedding, e.embedding) if e.embedding else 0.0
                results.append((score, e))
            results.sort(key=lambda p: p[0], reverse=True)
            return results[: max(1, top_k)]

    def list_for_entity(self, *, tenant_id, user_id, project_id, book_id,
                         entity_key, include_superseded=False):
        q = self._matches_scope_query(tenant_id, user_id, project_id, book_id).where(
            "entity_key", "==", entity_key
        )
        if not include_superseded:
            q = q.where("status", "==", "active")
        results = []
        for doc in q.stream():
            data = doc.to_dict() or {}
            results.append(_entry_from_dict(data))
        results.sort(key=lambda e: e.updated_at or e.created_at, reverse=True)
        return results


def _entry_from_dict(data: dict) -> MemoryEntry:
    emb = data.get("embedding") or []
    # Si vino como Vector de Firestore, convertir a list
    if hasattr(emb, "to_map_value"):  # Vector type
        try:
            emb = list(emb)
        except Exception:  # noqa: BLE001
            emb = []
    elif not isinstance(emb, list):
        try:
            emb = list(emb)
        except Exception:  # noqa: BLE001
            emb = []
    return MemoryEntry(
        id=data.get("id", ""),
        tenant_id=data.get("tenant_id", ""),
        user_id=data.get("user_id", ""),
        project_id=data.get("project_id", ""),
        book_id=data.get("book_id", ""),
        kind=data.get("kind", "note"),
        content=data.get("content", ""),
        facts=list(data.get("facts") or []),
        entity_key=data.get("entity_key", ""),
        embedding=list(emb),
        status=data.get("status", "active"),
        superseded_by=data.get("superseded_by"),
        source=data.get("source", "panel_manual"),
        created_at=data.get("created_at", ""),
        updated_at=data.get("updated_at", ""),
    )


_singleton: VectorStore | None = None


def get_vector_store() -> VectorStore:
    """Resuelve el store según env y disponibilidad de Firestore."""
    global _singleton
    if _singleton is not None:
        return _singleton

    import os
    backend = os.getenv("VECTOR_STORE_BACKEND", "auto").lower()
    if backend == "memory":
        _singleton = InMemoryVectorStore()
        return _singleton
    # auto o "firestore": intentar Firestore, con fallback a memoria si no disponible
    try:
        from app.firestore_store import get_firestore_client  # type: ignore
        client = get_firestore_client()
        _singleton = FirestoreVectorStore(client)
    except Exception:  # noqa: BLE001
        _singleton = InMemoryVectorStore()
    return _singleton


def set_vector_store(store: VectorStore) -> None:
    global _singleton
    _singleton = store


def reset_vector_store_singleton() -> None:
    global _singleton
    _singleton = None
