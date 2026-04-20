from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from typing import Any, Iterable, Optional

from app.firestore_store import (
    db,
    documents_collection,
    event_log_collection,
    facts_collection,
    llm_connections_collection,
    manual_notes_collection,
    retrieval_traces_collection,
    session_summaries_collection,
)
from app.utils import new_memory_id, utc_now_iso

SCHEMA_VERSION = "memory-core-v1"


@dataclass
class MemoryScope:
    tenant_id: str
    project_id: str
    book_id: str
    entity_type: Optional[str] = None
    entity_id: Optional[str] = None
    session_id: Optional[str] = None
    user_id: Optional[str] = None


def _clean(value: Optional[str]) -> str:
    return " ".join((value or "").strip().split())


def _norm(value: Optional[str]) -> str:
    return _clean(value).lower()


def _tokenize(value: Optional[str]) -> list[str]:
    return re.findall(r"[a-z0-9_áéíóúñ-]{2,}", _norm(value))


def _scope_match(data: dict, scope: MemoryScope, include_entity_wildcard: bool = True) -> bool:
    if data.get("tenant_id") != scope.tenant_id:
        return False
    project = data.get("project_id") or data.get("project")
    if project != scope.project_id:
        return False
    if data.get("book_id") != scope.book_id:
        return False
    if scope.entity_type and (data.get("entity_type") or "") != scope.entity_type:
        if not include_entity_wildcard:
            return False
        if data.get("entity_type") not in {None, "", "generic"}:
            return False
    if scope.entity_id and (data.get("entity_id") or "") != scope.entity_id:
        if not include_entity_wildcard:
            return False
        if data.get("entity_id") not in {None, "", "generic"}:
            return False
    if scope.user_id:
        user = data.get("user_id")
        if user and user != scope.user_id:
            return False
    return True


def _hash_parts(*parts: str) -> str:
    joined = "||".join(_norm(part) for part in parts if part is not None)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()[:24]


def _default_scope(arguments: dict[str, Any], principal_user_id: Optional[str] = None, connection_context: Optional[dict] = None) -> MemoryScope:
    ctx = connection_context or {}
    ctx_user = ctx.get("user_id") or ctx.get("tenant_id")
    ctx_project = ctx.get("active_project") or ctx.get("project_id")
    ctx_book = ctx.get("active_book") or ctx.get("book_id")
    tenant_id = str(arguments.get("tenant_id") or principal_user_id or ctx_user or "default")
    user_id = str(arguments.get("user_id") or principal_user_id or ctx_user or tenant_id)
    return MemoryScope(
        tenant_id=tenant_id,
        project_id=str(arguments.get("project_id") or arguments.get("project") or ctx_project or "general"),
        book_id=str(arguments.get("book_id") or ctx_book or "general"),
        entity_type=(str(arguments.get("entity_type")) if arguments.get("entity_type") else None),
        entity_id=(str(arguments.get("entity_id")) if arguments.get("entity_id") else None),
        session_id=(str(arguments.get("session_id")) if arguments.get("session_id") else None),
        user_id=user_id,
    )


def save_event(scope: MemoryScope, role: str, content: str, *, source: str = "mcp", content_format: str = "text", metadata: Optional[dict] = None) -> dict:
    now = utc_now_iso()
    event_id = f"event:{new_memory_id()}"
    payload = {
        "id": event_id,
        "schema_version": SCHEMA_VERSION,
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "book_id": scope.book_id,
        "entity_type": scope.entity_type or "generic",
        "entity_id": scope.entity_id or "generic",
        "session_id": scope.session_id,
        "user_id": scope.user_id,
        "role": role,
        "content": _clean(content),
        "content_format": content_format,
        "source": source,
        "created_at": now,
        "metadata_json": json.dumps(metadata or {}, ensure_ascii=False),
    }
    event_log_collection.document(event_id).set(payload)
    return payload


def save_note(scope: MemoryScope, title: str, content: str, *, source_event_id: Optional[str] = None) -> dict:
    now = utc_now_iso()
    title_clean = _clean(title) or "Nota"
    content_clean = _clean(content)
    note_hash = _hash_parts(scope.tenant_id, scope.project_id, scope.book_id, scope.entity_type or "", scope.entity_id or "", title_clean, content_clean)
    existing = None
    for doc in manual_notes_collection.where("tenant_id", "==", scope.tenant_id).stream():
        data = doc.to_dict() or {}
        if not _scope_match(data, scope):
            continue
        if data.get("status") != "active":
            continue
        if data.get("dedupe_hash") == note_hash:
            existing = data
            break
    if existing:
        manual_notes_collection.document(existing["id"]).update({"updated_at": now, "source_event_id": source_event_id or existing.get("source_event_id")})
        return manual_notes_collection.document(existing["id"]).get().to_dict() or existing
    note_id = f"note:{new_memory_id()}"
    payload = {
        "id": note_id,
        "schema_version": SCHEMA_VERSION,
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "book_id": scope.book_id,
        "entity_type": scope.entity_type or "generic",
        "entity_id": scope.entity_id or "generic",
        "session_id": scope.session_id,
        "user_id": scope.user_id,
        "title": title_clean,
        "content": content_clean,
        "status": "active",
        "source_event_id": source_event_id,
        "created_at": now,
        "updated_at": now,
        "dedupe_hash": note_hash,
    }
    manual_notes_collection.document(note_id).set(payload)
    return payload



def save_fact(
    scope: MemoryScope,
    subject: str,
    relation: str,
    object_value: str,
    *,
    confidence: float = 0.9,
    source_event_id: Optional[str] = None,
    evidence_doc_ids: Optional[list[str]] = None,
    value_type: str = "text",
) -> dict:
    now = utc_now_iso()
    subject_clean = _clean(subject)
    relation_clean = _clean(relation)
    object_clean = _clean(object_value)
    identity_hash = _hash_parts(scope.tenant_id, scope.project_id, scope.book_id, scope.entity_type or "", scope.entity_id or "", subject_clean, relation_clean)

    def _write(txn, *_args, **_kwargs):
        active_matches: list[dict] = []
        for doc in facts_collection.where("tenant_id", "==", scope.tenant_id).stream():
            data = doc.to_dict() or {}
            if not _scope_match(data, scope, include_entity_wildcard=False):
                continue
            if data.get("status") != "active":
                continue
            if data.get("identity_hash") == identity_hash:
                active_matches.append(data)
        current_exact = next((item for item in active_matches if _norm(item.get("object")) == _norm(object_clean)), None)
        if current_exact:
            facts_collection.document(current_exact["id"]).update({
                "updated_at": now,
                "confidence": max(float(current_exact.get("confidence") or 0), confidence),
                "source_event_id": source_event_id or current_exact.get("source_event_id"),
            })
            return facts_collection.document(current_exact["id"]).get().to_dict() or current_exact

        fact_id = f"fact:{new_memory_id()}"
        supersedes_id = active_matches[-1]["id"] if active_matches else None
        payload = {
            "id": fact_id,
            "schema_version": SCHEMA_VERSION,
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "book_id": scope.book_id,
            "entity_type": scope.entity_type or "generic",
            "entity_id": scope.entity_id or "generic",
            "session_id": scope.session_id,
            "user_id": scope.user_id,
            "subject": subject_clean,
            "relation": relation_clean,
            "object": object_clean,
            "value_type": value_type,
            "confidence": float(confidence),
            "status": "active",
            "valid_from": now,
            "valid_to": None,
            "source_event_id": source_event_id,
            "supersedes_id": supersedes_id,
            "superseded_by": None,
            "created_at": now,
            "updated_at": now,
            "evidence_doc_ids": evidence_doc_ids or [],
            "keywords_json": json.dumps(sorted(set(_tokenize(f"{subject_clean} {relation_clean} {object_clean}"))), ensure_ascii=False),
            "embedding_json": None,
            "identity_hash": identity_hash,
        }
        facts_collection.document(fact_id).set(payload)
        for item in active_matches:
            facts_collection.document(item["id"]).update({
                "status": "superseded",
                "valid_to": now,
                "updated_at": now,
                "superseded_by": fact_id,
            })
        return payload

    return db.run_transaction(_write)



def save_session_summary(scope: MemoryScope, summary: str, *, new_facts: Optional[list[dict]] = None, updated_facts: Optional[list[dict]] = None, open_questions: Optional[list[str]] = None, decisions: Optional[list[str]] = None) -> dict:
    now = utc_now_iso()
    summary_id = f"summary:{new_memory_id()}"
    payload = {
        "id": summary_id,
        "schema_version": SCHEMA_VERSION,
        "tenant_id": scope.tenant_id,
        "project_id": scope.project_id,
        "book_id": scope.book_id,
        "entity_type": scope.entity_type or "generic",
        "entity_id": scope.entity_id or "generic",
        "session_id": scope.session_id,
        "user_id": scope.user_id,
        "summary": _clean(summary),
        "new_facts_json": json.dumps(new_facts or [], ensure_ascii=False),
        "updated_facts_json": json.dumps(updated_facts or [], ensure_ascii=False),
        "open_questions_json": json.dumps(open_questions or [], ensure_ascii=False),
        "decisions_json": json.dumps(decisions or [], ensure_ascii=False),
        "created_at": now,
    }
    session_summaries_collection.document(summary_id).set(payload)
    return payload



_SEARCH_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "para", "por", "con", "que", "qué", "cual", "cuál",
    "como", "cómo", "donde", "dónde", "esta", "está", "es", "al", "mi", "me", "mas", "más",
    "siempre", "ahora", "nuestra", "nuestras", "nuestro", "nuestros",
    "en", "the", "what", "which", "did", "for", "not", "again", "actually", "left", "about",
    "fue", "quedo", "quedó", "quedaron", "cuál", "cual", "what", "left", "about", "sobre",
    "pasame", "pasás", "pasas", "rápido", "rapido", "perdón", "perdon", "necesito", "ya",
}


_SEARCH_SYNONYMS = {
    "tomo": ["bebida", "favorita"],
    "vivo": ["ciudad", "base"],
    "sigue": ["prioridad", "actual"],
    "numeros": ["metricas", "dashboard"],
    "números": ["metricas", "dashboard"],
    "hosting": ["cloud", "run", "backend", "principal"],
    "codigo": ["repositorio"],
    "código": ["repositorio"],
    "oficial": ["canónico", "canonico", "github"],
    "taller": ["proveedor", "facturación"],
    "trabajamos": ["proveedor", "preferido"],
    "normalmente": ["preferido"],
    "preferimos": ["preferido"],
    "despues": ["postergada"],
    "después": ["postergada"],
    "adelante": ["postergada"],
    "quedo": ["postergada"],
    "quedó": ["postergada"],
    "meta": ["objetivo"],
    "hito": ["objetivo"],
    "saludar": ["saludo", "preferido"],
    "soy": ["ciudad", "base"],
    "gusta": ["favorito", "favorita"],
    "url": ["enlace", "link", "canonical", "canonico", "canónico"],
    "definitiva": ["canonico", "canónico", "final"],
    "final": ["canonico", "canónico", "definitiva"],
    "reference": ["canonical", "link", "final"],
    "visible": ["display", "name", "nombre"],
    "customers": ["display", "name"],
    "see": ["display", "name", "visible"],
    "branch": ["rama", "despliegue", "deployment"],
    "deployment": ["rama", "despliegue", "branch"],
    "origen": ["origin", "pool"],
    "origin": ["origen", "pool"],
    "pool": ["origen", "origin"],
    "shortened": ["shortlink", "link"],
    "shortlink": ["atajo", "link"],
    "atajo": ["shortlink", "link"],
    "abrir": ["open", "link", "shortlink"],
    "summary": ["resumen"],
    "decision": ["decisión", "decision"],
}


def _normalize_search_text(value: Optional[str]) -> str:
    base = _clean(value).lower()
    return "".join(char for char in unicodedata.normalize("NFD", base) if unicodedata.category(char) != "Mn")


def _search_terms(value: Optional[str]) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_-]{2,}", _normalize_search_text(value)) if token not in _SEARCH_STOPWORDS]


def _expand_search_term(term: str) -> set[str]:
    normalized = _normalize_search_text(term)
    values = {normalized}
    values.update(_normalize_search_text(item) for item in _SEARCH_SYNONYMS.get(normalized, []))
    return {item for item in values if item}


def _expanded_search_terms(value: Optional[str]) -> list[str]:
    expanded: list[str] = []
    seen: set[str] = set()
    for term in _search_terms(value):
        for item in [term, *(_normalize_search_text(alias) for alias in _SEARCH_SYNONYMS.get(term, []))]:
            if not item or item in _SEARCH_STOPWORDS or item in seen:
                continue
            expanded.append(item)
            seen.add(item)
    return expanded


_GENERIC_ANCHOR_TERMS = {
    "cloudflare", "zona", "origin", "origen", "pool", "google", "calendar", "evento", "meet", "url",
    "zoom", "webinar", "modo", "sala", "espera", "solo", "usuarios", "autenticados", "linear", "issue",
    "assignee", "github", "repositorio", "rama", "despliegue", "deployment", "branch", "grafana", "dashboard",
    "umbral", "alerta", "notion", "pagina", "página", "shortlink", "slack", "canal", "runbook", "fijado",
    "vercel", "proyecto", "dominio", "produccion", "producción", "hubspot", "workflow", "trigger", "enrolamiento",
    "confluence", "dataset", "bigquery", "scheduled", "query", "nota", "interna", "internal", "note", "decision",
    "decisión", "vigente", "resumen", "session", "summary", "pregunta", "abierta", "open", "question", "owner",
    "visible", "what", "which", "left", "about", "cual", "cuál", "fue", "quedo", "quedó", "quedaron",
    "pasame", "pasás", "pasas", "deployment", "repository", "repositorio", "link", "real", "corto",
    "before", "close", "rule", "gets", "people", "into", "half", "remembering", "thanks", "thing",
    "sale", "produccion", "producción", "condicion", "condición", "contactos",
}

_SPECIAL_TOKEN_PATTERNS = [
    r"https?://[^\s]+",
    r"#[A-Za-z0-9_-]{2,}",
    r"\bgo/[A-Za-z0-9._/-]+\b",
    r"\b[A-Za-z]{2,}-\d{2,}\b",
    r"\b[A-Za-z0-9]+_[A-Za-z0-9_]+\b",
    r"\b[a-z0-9]+(?:-[a-z0-9]+){2,}\b",
    r"\b[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b",
]


def _extract_special_tokens(value: Optional[str]) -> list[str]:
    text = value or ""
    found: list[str] = []
    seen: set[str] = set()
    for pattern in _SPECIAL_TOKEN_PATTERNS:
        for token in re.findall(pattern, text):
            normalized = _normalize_search_text(token)
            if not normalized or normalized in seen:
                continue
            found.append(normalized)
            seen.add(normalized)
    return found


def _extract_anchor_terms(value: Optional[str]) -> list[str]:
    anchors: list[str] = []
    seen: set[str] = set()
    for token in _search_terms(value):
        if token in _GENERIC_ANCHOR_TERMS:
            continue
        if token.isdigit():
            continue
        if len(token) < 4 and not re.search(r"\d", token):
            continue
        if token in seen:
            continue
        anchors.append(token)
        seen.add(token)
    return anchors


def _detect_requested_memory_type(query: str) -> Optional[str]:
    query_norm = _normalize_search_text(query)
    if "nota interna" in query_norm or "internal note" in query_norm:
        return "note"
    if "resumen de sesion" in query_norm or "session summary" in query_norm:
        return "session_summary"
    if "pregunta abierta" in query_norm or "open question" in query_norm:
        return "open_question"
    if re.search(r"decision", query_norm) or "decisión" in query.lower() or "decision" in query.lower():
        return "decision"
    return None


def _candidate_type(kind: str, data: dict) -> str:
    original_type = _normalize_search_text(data.get("original_type"))
    if original_type in {"note", "decision", "session_summary", "open_question", "fact"}:
        return original_type
    if kind == "note":
        return "note"
    if kind == "summary":
        return "session_summary"
    return "fact"


def _candidate_blob(kind: str, data: dict) -> str:
    if kind == "fact":
        return " ".join(str(part or "") for part in [data.get("subject"), data.get("relation"), data.get("object"), data.get("original_type")])
    if kind == "note":
        return " ".join(str(part or "") for part in [data.get("title"), data.get("content"), data.get("original_type")])
    if kind == "summary":
        return " ".join(str(part or "") for part in [data.get("summary"), data.get("original_type")])
    return " ".join(str(part or "") for part in [data.get("title"), data.get("content_text"), data.get("notes"), data.get("entity"), data.get("attribute"), data.get("value_text")])


def _match_details(query: str, text: str) -> tuple[int, int, int]:
    text_norm = _normalize_search_text(text)
    text_terms = set(_search_terms(text_norm))
    text_expanded = set(_expanded_search_terms(text_norm))
    special_tokens = _extract_special_tokens(query)
    anchor_terms = _extract_anchor_terms(query)
    matched_special = sum(1 for token in special_tokens if token in text_norm)
    matched_anchor = 0
    for token in anchor_terms:
        variants = _expand_search_term(token)
        if token in text_norm or variants & text_terms or variants & text_expanded:
            matched_anchor += 1
    return matched_special, len(special_tokens), matched_anchor if anchor_terms else 0


def _score_candidate(query: str, kind: str, data: dict, preview: str) -> Optional[float]:
    blob = _candidate_blob(kind, data)
    matched_special, total_special, matched_anchor = _match_details(query, blob)
    anchor_terms = _extract_anchor_terms(query)
    score = _rank_text(query, blob)
    if score <= 0:
        if matched_special:
            score = 2.8 + (1.1 * matched_special)
        elif matched_anchor >= 2:
            score = 2.4 + (0.8 * matched_anchor)
        else:
            return None
    query_type = _detect_requested_memory_type(query)
    candidate_type = _candidate_type(kind, data)
    if query_type:
        if candidate_type == query_type:
            score += 4.0
        else:
            score -= 2.25
    if total_special:
        if matched_special == 0:
            return None
        score += 1.6 * matched_special
    if anchor_terms:
        if matched_anchor == 0 and total_special == 0:
            return None
        score += min(2.5, 0.9 * matched_anchor)
        if len(anchor_terms) >= 5 and matched_anchor == 0 and total_special == 0:
            return None
    if _should_reject_partial_match(query, f"{preview} {blob}"):
        return None
    return score


def _trim_ranked_results(query: str, scored_results: list[tuple[float, dict]], top_k: int) -> list[dict]:
    if not scored_results:
        return []
    desired_type = _detect_requested_memory_type(query)
    ranked_pairs = sorted(scored_results, key=lambda pair: (pair[0], pair[1].get("updated_at") or pair[1].get("created_at") or ""), reverse=True)
    if desired_type:
        typed_pairs = [pair for pair in ranked_pairs if _candidate_type(pair[1].get("kind", "memory"), pair[1].get("payload") or {}) == desired_type]
        if typed_pairs:
            ranked_pairs = typed_pairs
    top_score = ranked_pairs[0][0]
    min_keep = max(3.25, top_score * 0.66)
    if top_score >= 8:
        min_keep = max(min_keep, top_score - 1.6)
    elif top_score >= 6:
        min_keep = max(min_keep, top_score - 1.25)
    elif top_score >= 4.5:
        min_keep = max(min_keep, top_score - 0.9)
    strong_special = bool(_extract_special_tokens(query))
    kept: list[dict] = []
    for score, item in ranked_pairs:
        if score < min_keep:
            continue
        if strong_special:
            matched_special, total_special, matched_anchor = _match_details(query, _candidate_blob(item.get("kind", "memory"), item.get("payload") or {}))
            if total_special and matched_special == 0:
                continue
        kept.append(item)
        if len(kept) >= max(1, top_k):
            break
    return kept


def _rank_text(query: str, *texts: Optional[str]) -> float:
    query_norm = _normalize_search_text(query)
    query_tokens = set(_expanded_search_terms(query))
    score = 0.0
    for text in texts:
        text_norm = _normalize_search_text(text)
        if not text_norm:
            continue
        if query_norm and len(query_norm) >= 5 and query_norm in text_norm:
            score += 4.0
        tokens = set(_expanded_search_terms(text_norm))
        if query_tokens and tokens:
            overlap = query_tokens & tokens
            if overlap:
                score += len(overlap) / max(1, min(len(query_tokens), 4))
                if len(overlap) >= 2:
                    score += 0.75
    return score


def _should_reject_partial_match(query: str, preview: str) -> bool:
    query_terms = _search_terms(query)
    if not query_terms:
        return False
    preview_norm = _normalize_search_text(preview)
    preview_terms = set(_search_terms(preview))
    preview_expanded = set(_expanded_search_terms(preview))

    for token in _extract_special_tokens(query):
        if token not in preview_norm:
            return True

    original_parts = re.findall(r"[A-Za-zÁÉÍÓÚáéíóúÑñ0-9-]{2,}", query or "")
    ignored_upper = {"URL", "SLA", "API", "UI", "ID", "HTTP", "HTTPS", "ARS"}
    for token in original_parts[1:]:
        if token in ignored_upper:
            continue
        if token[:1].isupper() and _normalize_search_text(token) not in preview_norm:
            return True

    if len(query_terms) == 2:
        first, second = query_terms
        if first in preview_terms and not (_expand_search_term(second) & preview_expanded) and len(second) >= 4:
            return True

    if len(query_terms) == 3:
        matched_prefix = sum(1 for item in query_terms[:-1] if item in preview_terms or (_expand_search_term(item) & preview_expanded))
        if matched_prefix >= 2 and not (_expand_search_term(query_terms[-1]) & preview_expanded):
            return True

    return False


def _memory_item(kind: str, data: dict, preview: str) -> dict:
    return {
        "id": data.get("id"),
        "kind": kind,
        "tenant_id": data.get("tenant_id"),
        "project_id": data.get("project_id") or data.get("project"),
        "book_id": data.get("book_id"),
        "entity_type": data.get("entity_type") or data.get("entity"),
        "entity_id": data.get("entity_id") or data.get("entity"),
        "status": data.get("status", "active"),
        "created_at": data.get("created_at") or data.get("updated_at"),
        "updated_at": data.get("updated_at"),
        "preview": preview,
        "payload": data,
    }



def search_memory(scope: MemoryScope, query: str, *, top_k: int = 8, include_history: bool = False) -> dict:
    results: list[tuple[float, dict]] = []
    for doc in facts_collection.where("tenant_id", "==", scope.tenant_id).stream():
        data = doc.to_dict() or {}
        if not _scope_match(data, scope):
            continue
        if not include_history and data.get("status") != "active":
            continue
        preview = f"{data.get('subject')} {data.get('relation')} {data.get('object')}"
        score = _score_candidate(query, "fact", data, preview)
        if score is not None:
            results.append((score + (1.5 if data.get("status") == "active" else 0), _memory_item("fact", data, preview)))

    for doc in manual_notes_collection.where("tenant_id", "==", scope.tenant_id).stream():
        data = doc.to_dict() or {}
        if not _scope_match(data, scope):
            continue
        if not include_history and data.get("status") != "active":
            continue
        preview = data.get("content") or data.get("title") or ""
        score = _score_candidate(query, "note", data, preview)
        if score is not None:
            results.append((score + 0.5, _memory_item("note", data, preview)))

    for doc in session_summaries_collection.where("tenant_id", "==", scope.tenant_id).stream():
        data = doc.to_dict() or {}
        if not _scope_match(data, scope):
            continue
        score = _score_candidate(query, "summary", data, data.get("summary") or "")
        if score is not None:
            results.append((score, _memory_item("summary", data, data.get("summary") or "")))

    for doc in documents_collection.where("user_id", "==", scope.user_id).stream() if scope.user_id else []:
        data = doc.to_dict() or {}
        if (data.get("project") or data.get("project_id")) != scope.project_id:
            continue
        if data.get("id") and scope.entity_id and scope.entity_id not in {data.get("entity_id"), data.get("product_id"), data.get("producer_id")}:
            continue
        preview = data.get("title") or data.get("document_type") or "document"
        score = _score_candidate(query, "document", data, f"{preview} {data.get('content_text') or ''} {data.get('notes') or ''}")
        if score is not None:
            results.append((score, _memory_item("document", data, preview)))

    ranked = _trim_ranked_results(query, results, top_k)
    trace_id = f"trace:{new_memory_id()}"
    retrieval_traces_collection.document(trace_id).set(
        {
            "id": trace_id,
            "schema_version": SCHEMA_VERSION,
            "tenant_id": scope.tenant_id,
            "project_id": scope.project_id,
            "book_id": scope.book_id,
            "entity_type": scope.entity_type or "generic",
            "entity_id": scope.entity_id or "generic",
            "session_id": scope.session_id,
            "user_id": scope.user_id,
            "query": _clean(query),
            "retrieved_ids_json": json.dumps([item["id"] for item in ranked], ensure_ascii=False),
            "retrieved_types_json": json.dumps([item["kind"] for item in ranked], ensure_ascii=False),
            "ranking_json": json.dumps(ranked, ensure_ascii=False),
            "final_context": "\n".join(item["preview"] for item in ranked),
            "created_at": utc_now_iso(),
        }
    )
    return {"items": ranked, "trace_id": trace_id}



def fetch_memory(scope: MemoryScope, memory_ids: Iterable[str]) -> list[dict]:
    ids = list(dict.fromkeys(str(item) for item in memory_ids if item))
    found: list[dict] = []
    collections = [facts_collection, manual_notes_collection, session_summaries_collection, documents_collection, event_log_collection]
    seen: set[str] = set()
    for memory_id in ids:
        for collection in collections:
            snapshot = collection.document(memory_id).get().to_dict()
            if not snapshot:
                continue
            if memory_id in seen:
                continue
            if collection is documents_collection:
                if scope.user_id and snapshot.get("user_id") not in {None, scope.user_id}:
                    continue
                project = snapshot.get("project") or snapshot.get("project_id")
                if project != scope.project_id:
                    continue
            else:
                if not _scope_match(snapshot, scope):
                    continue
            kind = "memory"
            if collection is facts_collection:
                kind = "fact"
            elif collection is manual_notes_collection:
                kind = "note"
            elif collection is session_summaries_collection:
                kind = "summary"
            elif collection is documents_collection:
                kind = "document"
            elif collection is event_log_collection:
                kind = "event"
            preview = snapshot.get("summary") or snapshot.get("content") or snapshot.get("title") or snapshot.get("value_text") or snapshot.get("object") or memory_id
            found.append(_memory_item(kind, snapshot, preview))
            seen.add(memory_id)
            break
    return found



def list_books(tenant_id: str, project_id: str, *, user_id: Optional[str] = None) -> list[str]:
    books: set[str] = set()
    for collection in [facts_collection, manual_notes_collection, session_summaries_collection, event_log_collection]:
        for doc in collection.where("tenant_id", "==", tenant_id).stream():
            data = doc.to_dict() or {}
            if data.get("project_id") != project_id:
                continue
            if user_id and data.get("user_id") not in {None, user_id}:
                continue
            if data.get("book_id"):
                books.add(data["book_id"])
    return sorted(books)



def resolve_mcp_auth(user_id: Optional[str], token: Optional[str]) -> bool:
    if not user_id or not token:
        return False
    for doc in llm_connections_collection.where("user_id", "==", user_id).stream():
        data = doc.to_dict() or {}
        if data.get("bridge_mode") != "mcp":
            continue
        if data.get("bridge_token") == token and data.get("status") in {"connected", "paused"}:
            return True
    return False



def build_scope(arguments: dict[str, Any], principal_user_id: Optional[str] = None, connection_context: Optional[dict] = None) -> MemoryScope:
    return _default_scope(arguments, principal_user_id=principal_user_id, connection_context=connection_context)
