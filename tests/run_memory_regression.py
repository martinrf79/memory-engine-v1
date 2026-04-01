import json
import os
import sys
from pathlib import Path

from fastapi.testclient import TestClient

os.environ["USE_FAKE_FIRESTORE"] = "true"

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app


def clear_all():
    for col in (semantic_collection, chat_events_collection, memory_keys_collection):
        if hasattr(col, "clear"):
            col.clear()


def seed_operational(client: TestClient):
    response = client.post(
        "/memories/seed-operational",
        params={"user_id": "martin", "project": "memoria-guia", "book_id": "general"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["count"] == 6, body


def main():
    cases_path = Path("tests/memory_regression_cases.json")
    cases = json.loads(cases_path.read_text(encoding="utf-8"))

    clear_all()

    with TestClient(app) as client:
        health = client.get("/health")
        assert health.status_code == 200, health.text

        seed_operational(client)

        failures = []

        for case in cases:
            response = client.post("/chat", json=case["payload"])
            if response.status_code != 200:
                failures.append(f'{case["name"]}: status {response.status_code} body={response.text}')
                continue

            body = response.json()
            answer = body.get("answer", "")
            mode = body.get("mode", "")

            if mode != case["expected_mode"]:
                failures.append(f'{case["name"]}: expected_mode={case["expected_mode"]} got={mode}')

            for snippet in case.get("expected_contains", []):
                if snippet not in answer:
                    failures.append(f'{case["name"]}: missing expected snippet -> {snippet!r} in answer={answer!r}')

            for snippet in case.get("forbidden_contains", []):
                if snippet in answer:
                    failures.append(f'{case["name"]}: found forbidden snippet -> {snippet!r} in answer={answer!r}')

        if failures:
            print("MEMORY REGRESSION FAIL")
            for item in failures:
                print("-", item)
            sys.exit(1)

        print("MEMORY REGRESSION OK")


if __name__ == "__main__":
    main()
