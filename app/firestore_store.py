from google.cloud import firestore


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


class FakeDocumentReference:
    def __init__(self, store: dict[str, dict], doc_id: str):
        self._store = store
        self.id = doc_id

    def get(self) -> FakeDocumentSnapshot:
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


def build_collection():
    import os

    if os.getenv("GITHUB_ACTIONS") == "true":
        return FakeCollection()

    client = firestore.Client()
    return client.collection("memories")


collection = build_collection()
