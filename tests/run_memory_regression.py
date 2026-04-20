import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from app.firestore_store import chat_events_collection, memory_keys_collection, semantic_collection
from app.main import app

CASES_PATH = Path(__file__).with_name("memory_regression_cases.json")
client = TestClient(app)


def _clear_collections():
    semantic_collection.clear()
    chat_events_collection.clear()
    memory_keys_collection.clear()


def run_case(case: dict) -> None:
    _clear_collections()
    payload_base = {"user_id": "martin", "project": "memoria-guia", "book_id": "general"}

    if case.get("seed_operational"):
        seed = client.post("/memories/seed-operational", params=payload_base)
        assert seed.status_code == 200, f"seed failed in {case['name']}: {seed.text}"

    setup_message = case.get("setup_message")
    if setup_message:
        save = client.post("/chat", json={**payload_base, "message": setup_message})
        assert save.status_code == 200, f"setup failed in {case['name']}: {save.text}"

    ask = client.post("/chat", json={**payload_base, "message": case["ask_message"]})
    assert ask.status_code == 200, f"ask failed in {case['name']}: {ask.text}"
    body = ask.json()
    assert body["mode"] == case["expected_mode"], f"unexpected mode in {case['name']}: {body}"
    for expected in case.get("answer_must_contain", []):
        assert expected.lower() in body["answer"].lower(), f"missing '{expected}' in {case['name']}: {body['answer']}"


def main() -> None:
    cases = json.loads(CASES_PATH.read_text())
    for case in cases:
        run_case(case)
    print("MEMORY REGRESSION OK")


if __name__ == "__main__":
    main()
