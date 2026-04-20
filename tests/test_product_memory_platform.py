import os

os.environ["GITHUB_ACTIONS"] = "true"

from fastapi.testclient import TestClient

from app.firestore_store import (
    access_requests_collection,
    documents_collection,
    passports_collection,
    producers_collection,
    products_collection,
    projects_collection,
    retrieval_traces_collection,
    semantic_collection,
    sessions_collection,
    users_collection,
)
from app.main import app

client = TestClient(app)


ALL_COLLECTIONS = [
    access_requests_collection,
    documents_collection,
    passports_collection,
    producers_collection,
    products_collection,
    projects_collection,
    retrieval_traces_collection,
    semantic_collection,
    sessions_collection,
    users_collection,
]


def _clear_all():
    for collection in ALL_COLLECTIONS:
        collection.clear()


def _register(user_id: str, project: str):
    res = client.post(
        "/auth/register",
        json={"user_id": user_id, "password": "clave-segura-123", "project": project},
    )
    assert res.status_code == 200


def test_product_and_passport_flow_is_reusable_and_traceable():
    _clear_all()
    _register("martin", "exporta")

    producer = client.post(
        "/panel/producers",
        json={"project": "exporta", "name": "Bodega Norte", "segment": "premium", "country": "AR"},
    )
    assert producer.status_code == 200
    producer_id = producer.json()["id"]

    product = client.post(
        "/panel/products",
        json={
            "project": "exporta",
            "producer_id": producer_id,
            "name": "Aceite Reserva",
            "category": "aceite",
            "export_target": "UE",
            "next_step": "pedir ficha técnica",
        },
    )
    assert product.status_code == 200
    product_id = product.json()["id"]

    passport = client.post(
        "/panel/passports",
        json={
            "project": "exporta",
            "product_id": product_id,
            "passport_type": "export",
            "status": "in_progress",
            "required_fields": ["origen", "materiales", "certificados"],
            "completed_fields": ["origen"],
            "missing_documents": ["ficha técnica", "certificado orgánico"],
            "next_step": "subir certificado orgánico",
            "export_ready": False,
        },
    )
    assert passport.status_code == 200

    summary = client.get(f"/panel/passports/{product_id}/summary", params={"project": "exporta"})
    assert summary.status_code == 200
    body = summary.json()
    assert body["status"] == "in_progress"
    assert "certificados" in body["missing_items"]
    assert "ficha técnica" in body["missing_items"]
    assert body["trace_ids"]


def test_chat_can_answer_from_structured_passport_state():
    _clear_all()
    _register("martin", "exporta")

    producer_id = client.post("/panel/producers", json={"project": "exporta", "name": "Bodega Norte"}).json()["id"]
    product_id = client.post(
        "/panel/products",
        json={"project": "exporta", "producer_id": producer_id, "name": "Aceite Reserva", "next_step": "pedir ficha técnica"},
    ).json()["id"]
    client.post(
        "/panel/passports",
        json={
            "project": "exporta",
            "product_id": product_id,
            "passport_type": "product",
            "status": "draft",
            "required_fields": ["origen", "materiales"],
            "completed_fields": ["origen"],
            "missing_documents": ["foto frontal"],
            "next_step": "subir foto frontal",
        },
    )

    response = client.post(
        "/panel/chat",
        json={"project": "exporta", "book_id": "general", "message": "¿Qué falta para el pasaporte de Aceite Reserva?"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["mode"] == "answer"
    assert "foto frontal" in body["answer"]


def test_user_and_project_isolation_for_product_memory():
    _clear_all()
    _register("martin", "exporta")
    producer_id = client.post("/panel/producers", json={"project": "exporta", "name": "Bodega Norte"}).json()["id"]
    client.post(
        "/panel/products",
        json={"project": "exporta", "producer_id": producer_id, "name": "Aceite Reserva"},
    )
    client.post("/auth/logout")

    _register("ana", "otro")
    products = client.get("/panel/products", params={"project": "exporta"})
    assert products.status_code == 200
    assert products.json() == []


def test_raw_memory_requires_explicit_support_approval():
    _clear_all()
    _register("martin", "memoria-guia")
    client.post(
        "/panel/chat",
        json={"project": "memoria-guia", "book_id": "general", "message": "Mi color favorito es verde"},
    )
    request = client.post(
        "/panel/support/request",
        json={
            "project": "memoria-guia",
            "target_type": "memory",
            "target_id": "martin:memoria-guia",
            "reason": "depurar inconsistencia",
            "scope": "raw",
        },
    )
    assert request.status_code == 200
    request_id = request.json()["id"]

    denied_before = client.get("/support/raw-memory", params={"request_id": request_id})
    assert denied_before.status_code == 403

    review = client.post(
        "/support/review",
        json={"request_id": request_id, "approved": True, "reviewer": "support-1", "note": "caso especial"},
    )
    assert review.status_code == 200
    assert review.json()["status"] == "approved"

    granted = client.get("/support/raw-memory", params={"request_id": request_id})
    assert granted.status_code == 200
    body = granted.json()
    assert body["target_type"] == "memory"
    assert any(item.get("attribute") == "favorite_color" for item in body["records"])
