from __future__ import annotations

import os
from collections import defaultdict
from collections.abc import Callable
from typing import Any


class FakeDocumentSnapshot:
    def __init__(self, doc_id: str, data: dict | None):
        self.id = doc_id
        self._data = data

    @property
    def exists(self) -> bool:
        return self._data is not None

    def to_dict(self) -> dict | None:
        if self._data is None:
            return None
        return dict(self._data)


class FakeTransaction:
    def set(self, doc_ref: "FakeDocumentReference", data: dict) -> None:
        doc_ref.set(data)

    def update(self, doc_ref: "FakeDocumentReference", updates: dict) -> None:
        doc_ref.update(updates)

    def delete(self, doc_ref: "FakeDocumentReference") -> None:
        doc_ref.delete()


class FakeDocumentReference:
    def __init__(self, store: dict[str, dict], doc_id: str):
        self._store = store
        self.id = doc_id

    def get(self, transaction=None) -> FakeDocumentSnapshot:  # noqa: ARG002 - compatibility with firestore API
        return FakeDocumentSnapshot(self.id, self._store.get(self.id))

    def set(self, data: dict) -> None:
        self._store[self.id] = dict(data)

    def update(self, updates: dict) -> None:
        if self.id not in self._store:
            raise KeyError(f"Document {self.id} not found")
        self._store[self.id].update(dict(updates))

    def delete(self) -> None:
        self._store.pop(self.id, None)


class FakeCollection:
    def __init__(self):
        self._store: dict[str, dict] = {}

    def document(self, doc_id: str) -> FakeDocumentReference:
        return FakeDocumentReference(self._store, doc_id)

    def stream(self) -> list[FakeDocumentSnapshot]:
        return [FakeDocumentSnapshot(doc_id, data) for doc_id, data in self._store.items()]

    def clear(self) -> None:
        self._store.clear()


class FakeFirestoreDB:
    def __init__(self):
        self._collections: dict[str, FakeCollection] = defaultdict(FakeCollection)

    def collection(self, name: str) -> FakeCollection:
        return self._collections[name]

    def run_transaction(self, callback: Callable[..., Any], *args, **kwargs) -> Any:
        return callback(FakeTransaction(), *args, **kwargs)


class FirestoreDB:
    def __init__(self):
        try:
            from google.cloud import firestore  # type: ignore
        except Exception as exc:  # pragma: no cover - runtime safeguard only
            raise RuntimeError("google-cloud-firestore is not available") from exc

        self._firestore = firestore
        self._client = firestore.Client()

    def collection(self, name: str):
        return self._client.collection(name)

    def run_transaction(self, callback: Callable[..., Any], *args, **kwargs) -> Any:
        transaction = self._client.transaction()

        @self._firestore.transactional
        def wrapped(txn):
            return callback(txn, *args, **kwargs)

        return wrapped(transaction)


USE_FAKE_FIRESTORE = os.getenv("GITHUB_ACTIONS") == "true" or os.getenv("USE_FAKE_FIRESTORE") == "true"


def build_db():
    if USE_FAKE_FIRESTORE:
        return FakeFirestoreDB()

    try:
        return FirestoreDB()
    except Exception:
        # Local fallback so the repo stays testable even when the Firestore SDK
        # or credentials are unavailable. Production should rely on the real SDK.
        return FakeFirestoreDB()


db = build_db()


def get_collection(name: str):
    return db.collection(name)


semantic_collection = get_collection("semantic_memories")
chat_events_collection = get_collection("chat_events")
memory_keys_collection = get_collection("memory_keys")

# Backward-compatible alias.
collection = semantic_collection
