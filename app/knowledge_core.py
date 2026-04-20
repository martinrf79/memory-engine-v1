from __future__ import annotations

import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from app.auth import SessionPrincipal, require_session
from app.dependencies import require_internal_access
from app.firestore_store import (
    access_requests_collection,
    documents_collection,
    producers_collection,
    products_collection,
    retrieval_traces_collection,
    passports_collection,
    semantic_collection,
)
from app.schemas import (
    AccessRequestCreate,
    AccessRequestResponse,
    AccessRequestReview,
    DocumentCreate,
    DocumentResponse,
    PassportResponse,
    PassportSummaryResponse,
    PassportUpsert,
    ProducerCreate,
    ProducerResponse,
    ProductCreate,
    ProductResponse,
)
from app.utils import new_memory_id, utc_now_iso

router = APIRouter(tags=["public"])
internal_router = APIRouter(tags=["internal"], include_in_schema=False)


def _normalize(value: str) -> str:
    return " ".join(value.lower().strip().split())


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", _normalize(value)).strip("-")


def _store_doc(collection, doc_id: str, payload: dict) -> dict:
    collection.document(doc_id).set(payload)
    return payload


def _stream_to_dicts(collection, field: str, value: str) -> list[dict]:
    return [doc.to_dict() or {} for doc in collection.where(field, "==", value).stream()]


def _filter_project(items: list[dict], user_id: str, project: str) -> list[dict]:
    return [item for item in items if item.get("user_id") == user_id and item.get("project") == project]


def _producer_id(payload: ProducerCreate) -> str:
    return payload.producer_id or f"producer-{_slug(payload.name)}"


def _product_id(payload: ProductCreate) -> str:
    return payload.product_id or f"product-{_slug(payload.name)}"


def _passport_id(project: str, product_id: str, passport_type: str) -> str:
    return f"passport:{project}:{product_id}:{passport_type}"


def _trace(user_id: str, project: str, kind: str, ids: list[str], query: str) -> list[str]:
    trace_id = f"trace:{new_memory_id()}"
    retrieval_traces_collection.document(trace_id).set(
        {
            "id": trace_id,
            "user_id": user_id,
            "project": project,
            "kind": kind,
            "query": query,
            "ids": ids,
            "created_at": utc_now_iso(),
        }
    )
    return [trace_id]


def _find_product(user_id: str, project: str, name_or_id: str) -> Optional[dict]:
    candidates = _filter_project(_stream_to_dicts(products_collection, "user_id", user_id), user_id, project)
    needle = _normalize(name_or_id)
    for item in candidates:
        if _normalize(item.get("id", "")) == needle or _normalize(item.get("name", "")) == needle:
            return item
    for item in candidates:
        if needle and needle in _normalize(item.get("name", "")):
            return item
    return None


def _passport_summary(user_id: str, project: str, product_id: str, query: str) -> Optional[PassportSummaryResponse]:
    product = _find_product(user_id, project, product_id)
    if not product:
        return None
    passport_id_prefix = f"passport:{project}:{product['id']}:"
    passport_docs = [
        doc.to_dict() or {}
        for doc in passports_collection.where("user_id", "==", user_id).stream()
        if (doc.to_dict() or {}).get("project") == project and (doc.to_dict() or {}).get("id", "").startswith(passport_id_prefix)
    ]
    if not passport_docs:
        return None
    passport = sorted(passport_docs, key=lambda item: item.get("updated_at", ""))[-1]
    missing = list(dict.fromkeys((passport.get("missing_documents") or []) + [
        field for field in (passport.get("required_fields") or []) if field not in set(passport.get("completed_fields") or [])
    ]))
    traces = _trace(user_id, project, "passport_summary", [passport["id"], product["id"]], query)
    return PassportSummaryResponse(
        product_id=product["id"],
        product_name=product.get("name", product["id"]),
        passport_type=passport.get("passport_type", "product"),
        status=passport.get("status", "draft"),
        export_ready=bool(passport.get("export_ready")),
        missing_items=missing,
        next_step=passport.get("next_step") or product.get("next_step"),
        trace_ids=traces,
    )


def answer_product_query(user_id: str, project: str, message: str) -> Optional[dict]:
    query = _normalize(message)
    if "pasaporte" not in query and "export" not in query and "producto" not in query:
        return None

    product = None
    products = _filter_project(_stream_to_dicts(products_collection, "user_id", user_id), user_id, project)
    for item in products:
        name = _normalize(item.get("name", ""))
        if name and name in query:
            product = item
            break
    if not product and len(products) == 1:
        product = products[0]
    if not product:
        return None

    summary = _passport_summary(user_id, project, product["id"], message)
    if not summary:
        return None

    if "falta" in query or "faltan" in query:
        if summary.missing_items:
            answer = f"Para {summary.product_name}, faltan: {', '.join(summary.missing_items)}."
        else:
            answer = f"Para {summary.product_name}, no veo faltantes pendientes."
    elif "proximo paso" in query or "próximo paso" in query or "sigue" in query:
        answer = f"Para {summary.product_name}, el próximo paso es: {summary.next_step or 'definir el siguiente avance.'}"
    elif "estado" in query or "como va" in query or "cómo va" in query:
        answer = f"El pasaporte de {summary.product_name} está en estado {summary.status}."
    else:
        faltan = ', '.join(summary.missing_items) if summary.missing_items else 'nada crítico'
        answer = f"Para {summary.product_name}, el pasaporte está en estado {summary.status}. Faltan: {faltan}."

    used = [{"id": trace_id, "summary": f"trace={trace_id}"} for trace_id in summary.trace_ids]
    return {"mode": "answer", "answer": answer, "used_memories": used, "options": []}


@router.post("/panel/producers", response_model=ProducerResponse)
def create_producer(payload: ProducerCreate, principal: SessionPrincipal = Depends(require_session)):
    now = utc_now_iso()
    producer_id = _producer_id(payload)
    data = {
        "id": producer_id,
        "user_id": principal.user_id,
        "project": payload.project,
        "name": payload.name,
        "segment": payload.segment,
        "country": payload.country,
        "consent_scope": payload.consent_scope or "base_directory",
        "onboarding_status": payload.onboarding_status or "lead",
        "notes": payload.notes,
        "created_at": now,
        "updated_at": now,
    }
    _store_doc(producers_collection, producer_id, data)
    return ProducerResponse(**data)


@router.get("/panel/producers", response_model=list[ProducerResponse])
def list_producers(project: str, principal: SessionPrincipal = Depends(require_session)):
    items = _filter_project(_stream_to_dicts(producers_collection, "user_id", principal.user_id), principal.user_id, project)
    return [ProducerResponse(**item) for item in sorted(items, key=lambda x: x["name"])]


@router.post("/panel/products", response_model=ProductResponse)
def create_product(payload: ProductCreate, principal: SessionPrincipal = Depends(require_session)):
    now = utc_now_iso()
    producer = producers_collection.document(payload.producer_id).get().to_dict()
    if not producer or producer.get("user_id") != principal.user_id or producer.get("project") != payload.project:
        raise HTTPException(status_code=404, detail="producer_not_found")
    product_id = _product_id(payload)
    data = {
        "id": product_id,
        "user_id": principal.user_id,
        "project": payload.project,
        "producer_id": payload.producer_id,
        "name": payload.name,
        "category": payload.category,
        "premium_tier": payload.premium_tier,
        "export_target": payload.export_target,
        "next_step": payload.next_step,
        "notes": payload.notes,
        "created_at": now,
        "updated_at": now,
    }
    _store_doc(products_collection, product_id, data)
    return ProductResponse(**data)


@router.get("/panel/products", response_model=list[ProductResponse])
def list_products(project: str, principal: SessionPrincipal = Depends(require_session)):
    items = _filter_project(_stream_to_dicts(products_collection, "user_id", principal.user_id), principal.user_id, project)
    return [ProductResponse(**item) for item in sorted(items, key=lambda x: x["name"])]


@router.post("/panel/passports", response_model=PassportResponse)
def upsert_passport(payload: PassportUpsert, principal: SessionPrincipal = Depends(require_session)):
    now = utc_now_iso()
    product = products_collection.document(payload.product_id).get().to_dict()
    if not product or product.get("user_id") != principal.user_id or product.get("project") != payload.project:
        raise HTTPException(status_code=404, detail="product_not_found")
    passport_id = _passport_id(payload.project, payload.product_id, payload.passport_type)
    existing = passports_collection.document(passport_id).get().to_dict() or {}
    created_at = existing.get("created_at", now)
    data = {
        "id": passport_id,
        "user_id": principal.user_id,
        "project": payload.project,
        "product_id": payload.product_id,
        "passport_type": payload.passport_type,
        "status": payload.status,
        "required_fields": payload.required_fields,
        "completed_fields": payload.completed_fields,
        "missing_documents": payload.missing_documents,
        "next_step": payload.next_step,
        "export_ready": payload.export_ready,
        "notes": payload.notes,
        "created_at": created_at,
        "updated_at": now,
    }
    _store_doc(passports_collection, passport_id, data)
    return PassportResponse(**data)


@router.get("/panel/passports", response_model=list[PassportResponse])
def list_passports(project: str, principal: SessionPrincipal = Depends(require_session)):
    items = _filter_project(_stream_to_dicts(passports_collection, "user_id", principal.user_id), principal.user_id, project)
    return [PassportResponse(**item) for item in sorted(items, key=lambda x: x["updated_at"], reverse=True)]


@router.post("/panel/documents", response_model=DocumentResponse)
def create_document(payload: DocumentCreate, principal: SessionPrincipal = Depends(require_session)):
    now = utc_now_iso()
    product = products_collection.document(payload.product_id).get().to_dict()
    if not product or product.get("user_id") != principal.user_id or product.get("project") != payload.project:
        raise HTTPException(status_code=404, detail="product_not_found")
    doc_id = f"doc:{payload.project}:{payload.product_id}:{_slug(payload.document_type)}:{_slug(payload.title)}"
    data = {
        "id": doc_id,
        "user_id": principal.user_id,
        "project": payload.project,
        "product_id": payload.product_id,
        "document_type": payload.document_type,
        "title": payload.title,
        "status": payload.status,
        "url": payload.url,
        "created_at": now,
        "updated_at": now,
    }
    _store_doc(documents_collection, doc_id, data)
    return DocumentResponse(**data)


@router.get("/panel/documents", response_model=list[DocumentResponse])
def list_documents(project: str, product_id: Optional[str] = None, principal: SessionPrincipal = Depends(require_session)):
    items = _filter_project(_stream_to_dicts(documents_collection, "user_id", principal.user_id), principal.user_id, project)
    if product_id:
        items = [item for item in items if item.get("product_id") == product_id]
    return [DocumentResponse(**item) for item in sorted(items, key=lambda x: x["title"])]


@router.get("/panel/passports/{product_id}/summary", response_model=PassportSummaryResponse)
def passport_summary(product_id: str, project: str, principal: SessionPrincipal = Depends(require_session)):
    summary = _passport_summary(principal.user_id, project, product_id, f"summary:{product_id}")
    if not summary:
        raise HTTPException(status_code=404, detail="passport_not_found")
    return summary


@router.post("/panel/support/request", response_model=AccessRequestResponse)
def create_access_request(payload: AccessRequestCreate, principal: SessionPrincipal = Depends(require_session)):
    now = utc_now_iso()
    request_id = f"access:{new_memory_id()}"
    data = {
        "id": request_id,
        "user_id": principal.user_id,
        "project": payload.project,
        "target_type": payload.target_type,
        "target_id": payload.target_id,
        "reason": payload.reason,
        "scope": payload.scope,
        "status": "pending",
        "created_at": now,
        "updated_at": now,
    }
    _store_doc(access_requests_collection, request_id, data)
    return AccessRequestResponse(**data)


@internal_router.post("/support/review", response_model=AccessRequestResponse, dependencies=[Depends(require_internal_access)])
def review_access_request(payload: AccessRequestReview):
    existing = access_requests_collection.document(payload.request_id).get().to_dict()
    if not existing:
        raise HTTPException(status_code=404, detail="request_not_found")
    existing.update(
        {
            "status": "approved" if payload.approved else "rejected",
            "updated_at": utc_now_iso(),
            "reviewed_by": payload.reviewer,
            "review_note": payload.note,
        }
    )
    _store_doc(access_requests_collection, payload.request_id, existing)
    return AccessRequestResponse(**existing)


@internal_router.get("/support/raw-memory", dependencies=[Depends(require_internal_access)])
def support_raw_memory(request_id: str):
    request_doc = access_requests_collection.document(request_id).get().to_dict()
    if not request_doc:
        raise HTTPException(status_code=404, detail="request_not_found")
    if request_doc.get("status") != "approved" or request_doc.get("scope") != "raw":
        raise HTTPException(status_code=403, detail="raw_access_not_granted")

    if request_doc.get("target_type") == "passport":
        passport = passports_collection.document(request_doc["target_id"]).get().to_dict()
        if not passport:
            raise HTTPException(status_code=404, detail="passport_not_found")
        return {"request_id": request_id, "target_type": "passport", "record": passport}

    memories = [
        doc.to_dict() or {}
        for doc in semantic_collection.where("user_id", "==", request_doc["user_id"]).stream()
        if (doc.to_dict() or {}).get("project") == request_doc.get("project")
    ]
    return {
        "request_id": request_id,
        "target_type": "memory",
        "records": sorted(memories, key=lambda item: item.get("updated_at") or item.get("created_at") or ""),
    }
