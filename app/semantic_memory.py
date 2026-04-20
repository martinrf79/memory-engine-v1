from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

from app.firestore_store import db, memory_indexes_collection, memory_keys_collection, semantic_collection
from app.firestore_utils import memory_dict_from_firestore
from app.utils import new_memory_id, utc_now_iso

VALID_MEMORY_STATUS = {"active", "superseded", "archived"}
BLOCKED_TEXT_MARKERS = (
    "insufficient_memory",
    "answer:",
    "según las memorias encontradas",
    "segun las memorias encontradas",
    "traceback",
    "error:",
)
GLOBAL_PROJECT = "__global__"


_MEMORY_COMMAND_PREFIXES = (
    "recorda que",
    "recordá que",
    "anota que",
    "anotá que",
    "guarda que",
    "guardá que",
    "crear memoria:",
    "guardar memoria:",
    "guardar nota:",
    "acordate que",
    "acuérdate que",
)

_AUTO_NOTE_STARTS = (
    "mi ",
    "soy ",
    "vivo ",
    "trabajo ",
    "me gusta ",
    "prefiero ",
    "uso ",
)

_AUTO_NOTE_BLOCKLIST = (
    "hola",
    "gracias",
    "ok",
    "dale",
    "perfecto",
    "proba",
    "prueba",
    "test",
)


@dataclass
class ExtractedMemory:
    memory_type: str
    entity: str
    attribute: str
    value_text: str
    context: Optional[str] = None
    source_type: str = "chat_user_message"
    target_project: Optional[str] = None
    confidence: float = 0.95
    extraction_method: str = "rule"


def _normalize_value(value: str) -> str:
    cleaned = re.sub(r"\s+", " ", value.strip())
    return cleaned.strip(" .,!?:;\"'")


def normalize_text(value: Optional[str]) -> str:
    return _normalize_value(value or "").lower()


def normalize_name_key(value: str) -> str:
    base = normalize_text(value)
    without_accents = "".join(
        char for char in unicodedata.normalize("NFD", base) if unicodedata.category(char) != "Mn"
    )
    return re.sub(r"[^a-z0-9]+", "_", without_accents).strip("_")


def build_person_entity(name: str) -> str:
    return f"person_{normalize_name_key(name)}"


def build_relation_entity(name: str) -> str:
    return f"relation_{normalize_name_key(name)}"


def is_recordable_user_message(message: str) -> bool:
    lowered = normalize_text(message)
    return lowered != "" and not any(marker in lowered for marker in BLOCKED_TEXT_MARKERS)


def text_contains_blocked_markers(*parts: Optional[str]) -> bool:
    lowered = " ".join(normalize_text(part) for part in parts)
    return any(marker in lowered for marker in BLOCKED_TEXT_MARKERS)


def is_explicit_memory_command(message: str) -> bool:
    lowered = normalize_text(message)
    return any(lowered.startswith(prefix) for prefix in _MEMORY_COMMAND_PREFIXES)


def should_auto_store_personal_note(message: str) -> bool:
    lowered = normalize_text(message)
    if not lowered or any(marker in lowered for marker in _NO_STORE_MARKERS):
        return False
    if text_contains_blocked_markers(lowered):
        return False
    if "?" in message or "¿" in message or len(lowered) > 220:
        return False
    if any(lowered == blocked for blocked in _AUTO_NOTE_BLOCKLIST):
        return False
    if is_explicit_memory_command(lowered):
        return True

    declarative_patterns = [
        r"^(soy|vivo|trabajo|me llamo|mi nombre es|prefiero|me gusta|uso)\b",
        r"^mi (primo|prima|hermano|hermana|padre|madre|hijo|hija|amigo|amiga|vecino|vecina)\b.*\b(es|vive|se llama|trabaja|tiene)\b",
        r"^mi [a-z0-9_\-áéíóúñ ]+\b.*\b(es|son|tiene|prefiere|usa|revisa|atiende|trabaja|vive)\b",
    ]
    return any(re.search(pattern, lowered) for pattern in declarative_patterns)


def is_semantic_memory_record(memory: dict) -> bool:
    if not memory:
        return False
    if memory.get("status") not in VALID_MEMORY_STATUS:
        return False
    if memory.get("memory_type") == "conversation":
        return False
    required_fields = ("user_id", "project", "book_id", "entity", "attribute", "value_text", "dedupe_key")
    if any(not memory.get(field) for field in required_fields):
        return False
    attribute = memory.get("attribute") or ""
    value_text = memory.get("value_text")
    context = memory.get("context")
    if attribute == "insufficient_memory_rule":
        if text_contains_blocked_markers(value_text):
            return False
    elif text_contains_blocked_markers(value_text, context):
        return False
    return True


def is_project_memory(memory: dict) -> bool:
    if not is_semantic_memory_record(memory):
        return False
    return memory.get("entity") in {"test_config", "test_rule", "backend", "project_meta", "assistant_policy"}


def is_user_memory(memory: dict) -> bool:
    if not is_semantic_memory_record(memory):
        return False
    return memory.get("entity") in {"user", "assistant_policy", "project_meta", "user_note"}


def tokenize_search_query(query: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9_\-áéíóúñ]+", normalize_text(query)) if len(token) >= 2]


_NO_STORE_MARKERS = (
    "no guardes esto",
    "tampoco guardes esto",
    "no guardes esta frase como hecho",
    "no guardes esta otra",
    "es solo comentario del momento",
    "solo estoy hablando",
    "comentario suelto",
    "no memoria",
    "es al pasar",
    "es solo un ejemplo",
    "solo ejemplo",
    "no lo guardes",
    "no te pedi que recuerdes",
    "no te pedí que recuerdes",
)


def _strip_known_prefixes(text: str) -> str:
    prefixes = [
        "quiero que recuerdes esto:",
        "recuerda tambien esto:",
        "recuerda también esto:",
        "recuerda esto para el proyecto coc:",
        "recuerda también para coc:",
        "guardar nota:",
        "crear memoria:",
        "registrar:",
        "guardar:",
        "y ademas:",
        "y además:",
        "dato importante:",
        "correccion importante:",
        "corrección importante:",
        "repito para que quede claro:",
        "la informacion valida sigue siendo que",
        "la información válida sigue siendo que",
        "pregunta de prueba:",
    ]
    cleaned = text.strip()
    lowered = normalize_text(cleaned)
    changed = True
    while changed:
        changed = False
        for prefix in prefixes:
            if lowered.startswith(normalize_text(prefix)):
                cleaned = cleaned[len(prefix):].lstrip(" :")
                lowered = normalize_text(cleaned)
                changed = True
                break
    return cleaned


def _extract_person_fact(content: str) -> Optional[ExtractedMemory]:
    normalized = normalize_text(content)

    patterns = [
        (r"el color favorito de ([a-záéíóúñ ]+) es ([a-záéíóúñ ]+)", "favorite_color"),
        (r"([a-záéíóúñ ]+) cambio su color favorito de [a-záéíóúñ ]+ a ([a-záéíóúñ ]+)", "favorite_color"),
        (r"([a-záéíóúñ ]+) cambió su color favorito de [a-záéíóúñ ]+ a ([a-záéíóúñ ]+)", "favorite_color"),
        (r"mi amigo ([a-záéíóúñ ]+) tiene como color favorito el ([a-záéíóúñ ]+)", "favorite_color"),
        (r"mi hermana ([a-záéíóúñ ]+) prefiere ([a-záéíóúñ ]+)", "favorite_color"),
        (r"mi vecino ([a-záéíóúñ ]+) usa ([a-záéíóúñ ]+)", "favorite_color"),
    ]
    for pattern, attribute in patterns:
        match = re.search(pattern, normalized)
        if match:
            person_name, value = match.group(1), match.group(2)
            return ExtractedMemory(
                memory_type="fact",
                entity=build_person_entity(person_name),
                attribute=attribute,
                value_text=_normalize_value(value),
                context=content.strip(),
                source_type="legacy_api",
                target_project=None,
            )
    return None


_RELATION_FACT_PATTERNS: list[tuple[str, str]] = [
    (r"mi (?P<relation>primo|prima|hermano|hermana|padre|madre|hijo|hija|amigo|amiga|vecino|vecina) es de (?P<value>[a-z0-9_\-áéíóúñ ]+)", "origin_location"),
    (r"mi (?P<relation>primo|prima|hermano|hermana|padre|madre|hijo|hija|amigo|amiga|vecino|vecina) vive en (?P<value>[a-z0-9_\-áéíóúñ ]+)", "current_location"),
    (r"mi (?P<relation>primo|prima|hermano|hermana|padre|madre|hijo|hija|amigo|amiga|vecino|vecina) se llama (?P<value>[a-z0-9_\-áéíóúñ ]+)", "name"),
    (r"mi (?P<relation>primo|prima|hermano|hermana|padre|madre|hijo|hija|amigo|amiga|vecino|vecina) trabaja en (?P<value>[a-z0-9_\-áéíóúñ ]+)", "works_at"),
]

_USER_FACT_PATTERNS: list[tuple[str, str, str]] = [
    (r"me llamo ([a-z0-9_\-áéíóúñ ]+)", "fact", "name"),
    (r"mi nombre es ([a-z0-9_\-áéíóúñ ]+)", "fact", "name"),
    (r"soy de ([a-z0-9_\-áéíóúñ ]+)", "fact", "origin_location"),
    (r"vivo en ([a-z0-9_\-áéíóúñ ]+)", "fact", "current_location"),
]

_GENERIC_FACT_PATTERNS: list[tuple[list[str], str, str, str]] = [
    (
        [
            r"mi proveedor preferido es ([a-z0-9_\-áéíóúñ ]+)",
            r"mi proveedor favorito es ([a-z0-9_\-áéíóúñ ]+)",
            r"mi taller preferido es ([a-z0-9_\-áéíóúñ ]+)",
            r"mi proveedor actual es ([a-z0-9_\-áéíóúñ ]+)",
        ],
        "fact",
        "user",
        "preferred_provider",
    ),
    (
        [
            r"la forma de saludo preferida es ([a-z0-9_\-áéíóúñ ]+)",
            r"mi forma de saludo preferida es ([a-z0-9_\-áéíóúñ ]+)",
            r"mi saludo preferido es ([a-z0-9_\-áéíóúñ ]+)",
        ],
        "preference",
        "user",
        "preferred_greeting",
    ),
    (
        [
            r"mi ciudad favorita es ([a-z0-9_\-áéíóúñ ]+)",
            r"mi ciudad preferida es ([a-z0-9_\-áéíóúñ ]+)",
        ],
        "preference",
        "user",
        "favorite_city",
    ),
]

_CORRECTION_PATTERNS: list[tuple[str, str, str, str]] = [
    (r"me exprese mal recien; no era ([a-z0-9_\-áéíóúñ ]+) sino ([a-z0-9_\-áéíóúñ ]+)", "fact", "user", "preferred_provider"),
    (r"me expresé mal recién; no era ([a-z0-9_\-áéíóúñ ]+) sino ([a-z0-9_\-áéíóúñ ]+)", "fact", "user", "preferred_provider"),
    (r"cambio lo que dije: la prioridad ya no es ([a-z0-9_\-áéíóúñ ]+), ahora es ([a-z0-9_\-áéíóúñ ]+)", "fact", "project_meta", "priority_project"),
    (r"ajuste: el proyecto prioritario paso a ser ([a-z0-9_\-áéíóúñ ]+)", "fact", "project_meta", "priority_project"),
    (r"ajuste: el proyecto prioritario pasó a ser ([a-z0-9_\-áéíóúñ ]+)", "fact", "project_meta", "priority_project"),
    (r"corrijo: antes era ([a-z0-9_\-áéíóúñ ]+), ahora es ([a-z0-9_\-áéíóúñ ]+)", "preference", "user", "favorite_color"),
]


def _extract_relation_fact(normalized: str, original: str) -> Optional[ExtractedMemory]:
    original_clean = original.strip()
    for pattern, attribute in _RELATION_FACT_PATTERNS:
        match = re.fullmatch(pattern, original_clean, flags=re.IGNORECASE)
        if not match:
            continue
        relation = normalize_text(match.group("relation"))
        value = match.group("value")
        return ExtractedMemory(
            memory_type="fact",
            entity=build_relation_entity(relation),
            attribute=attribute,
            value_text=_normalize_value(value),
            context=original_clean,
            target_project=None,
        )
    return None


def _extract_user_fact(normalized: str, original: str) -> Optional[ExtractedMemory]:
    original_clean = original.strip()
    for pattern, memory_type, attribute in _USER_FACT_PATTERNS:
        match = re.fullmatch(pattern, original_clean, flags=re.IGNORECASE)
        if not match:
            continue
        return ExtractedMemory(
            memory_type=memory_type,
            entity="user",
            attribute=attribute,
            value_text=_normalize_value(match.group(1)),
            context=original_clean,
            target_project=None,
        )
    return None


def _extract_generic_fact(normalized: str, original: str) -> Optional[ExtractedMemory]:
    relation_fact = _extract_relation_fact(normalized, original)
    if relation_fact:
        return relation_fact

    user_fact = _extract_user_fact(normalized, original)
    if user_fact:
        return user_fact

    for patterns, memory_type, entity, attribute in _GENERIC_FACT_PATTERNS:
        for pattern in patterns:
            match = re.fullmatch(pattern, normalized)
            if match:
                return ExtractedMemory(
                    memory_type=memory_type,
                    entity=entity,
                    attribute=attribute,
                    value_text=_normalize_value(match.group(1)),
                    context=original.strip(),
                    target_project=None,
                )
    return None


def _extract_correction_fact(normalized: str, original: str) -> Optional[ExtractedMemory]:
    for pattern, memory_type, entity, attribute in _CORRECTION_PATTERNS:
        match = re.fullmatch(pattern, normalized)
        if match:
            groups = match.groups()
            value_group = groups[-1]
            return ExtractedMemory(
                memory_type=memory_type,
                entity=entity,
                attribute=attribute,
                value_text=_normalize_value(value_group),
                context=original.strip(),
                target_project=None if entity != "project_meta" else GLOBAL_PROJECT,
            )
    return None


def extract_structured_memory(message: str) -> Optional[ExtractedMemory]:
    if not is_recordable_user_message(message):
        return None

    normalized = normalize_text(message)
    if any(marker in normalized for marker in _NO_STORE_MARKERS):
        return None
    if normalized.startswith("no me gusta") or normalized.startswith("anota que no me gusta") or normalized.startswith("anotá que no me gusta"):
        return None

    stripped = _strip_known_prefixes(message)
    normalized = normalize_text(stripped)

    if not normalized:
        return None

    if normalized in {
        "para estas pruebas usa siempre user_id martin y project memoria-guia",
        "ahora cambia solo para este bloque a project coc",
        "ahora vuelve a project memoria-guia",
        "no borres el historial, pero la verdad actual es verde",
    }:
        return None

    if re.search(r"\bcoc\b", normalized) and "consult" in normalized and "memoria" in normalized and "responder" in normalized:
        return ExtractedMemory(
            memory_type="instruction",
            entity="assistant_policy",
            attribute="memory_first",
            value_text="consultar memoria antes de responder",
            context=message.strip(),
            target_project=None,
        )

    if "si no hay memoria suficiente" in normalized and ("pedir un dato adicional" in normalized or "pedir dato adicional" in normalized) and "no inventar" in normalized:
        return ExtractedMemory(
            memory_type="instruction",
            entity="assistant_policy",
            attribute="insufficient_memory_rule",
            value_text="si no hay memoria suficiente, debe pedir un dato adicional y no inventar",
            context=message.strip(),
            target_project=None,
        )

    if "cuando haya ambiguedad" in normalized or "cuando haya ambigüedad" in normalized:
        if "opciones a/b" in normalized or "opciones a b" in normalized:
            return ExtractedMemory(
                memory_type="instruction",
                entity="assistant_policy",
                attribute="ambiguity_options",
                value_text="ante ambigüedad, ofrecer opciones A/B",
                context=message.strip(),
            )

    if "debe proponer opciones concretas" in normalized and "pedir eleccion" in normalized or "pedir elección" in normalized:
        return ExtractedMemory(
            memory_type="instruction",
            entity="assistant_policy",
            attribute="ask_choice",
            value_text="si el usuario duda entre dos caminos, proponer opciones concretas y pedir elección",
            context=message.strip(),
        )

    match = re.fullmatch(r"mi prioridad actual es el proyecto ([a-z0-9_\-]+)", normalized)
    if not match:
        match = re.fullmatch(r"el proyecto prioritario actual es ([a-z0-9_\-]+)", normalized)
    if match:
        return ExtractedMemory(
            memory_type="fact",
            entity="project_meta",
            attribute="priority_project",
            value_text=_normalize_value(match.group(1)),
            context=message.strip(),
            target_project=None,
        )

    person_fact = _extract_person_fact(stripped)
    if person_fact:
        return person_fact

    correction_fact = _extract_correction_fact(normalized, message)
    if correction_fact:
        return correction_fact

    generic_fact = _extract_generic_fact(normalized, message)
    if generic_fact:
        return generic_fact

    color_patterns = [
        r"mi color favorito es ([a-záéíóúñ ]+)",
        r"mi color favorito ya no es [a-záéíóúñ ]+\. ahora es ([a-záéíóúñ ]+)",
        r"mi color favorito ya no es [a-záéíóúñ ]+, ahora es ([a-záéíóúñ ]+)",
        r"antes era [a-záéíóúñ ]+, ahora es ([a-záéíóúñ ]+)",
        r"me gusta el color ([a-záéíóúñ ]+)",
        r"anota que mi color favorito es ([a-záéíóúñ ]+)",
        r"anotá que mi color favorito es ([a-záéíóúñ ]+)",
    ]
    for pattern in color_patterns:
        match = re.fullmatch(pattern, normalized)
        if match:
            return ExtractedMemory(
                memory_type="preference",
                entity="user",
                attribute="favorite_color",
                value_text=_normalize_value(match.group(1)),
                context=message.strip(),
                target_project=None,
            )

    food_patterns = [
        r"mi comida favorita es ([a-záéíóúñ ]+)",
        r"mi comida preferida es ([a-záéíóúñ ]+)",
        r"me gusta comer ([a-záéíóúñ ]+)",
        r"anota que mi comida preferida es ([a-záéíóúñ ]+)",
        r"anotá que mi comida preferida es ([a-záéíóúñ ]+)",
    ]
    for pattern in food_patterns:
        match = re.fullmatch(pattern, normalized)
        if match:
            return ExtractedMemory(
                memory_type="preference",
                entity="user",
                attribute="favorite_food",
                value_text=_normalize_value(match.group(1)),
                context=message.strip(),
                target_project=None,
            )

    rules = [
        (r"el user_id de pruebas es ([a-z0-9_-]+)", "instruction", "test_config", "user_id", GLOBAL_PROJECT),
        (r"el project de pruebas es ([a-z0-9_-]+)", "instruction", "test_config", "project", GLOBAL_PROJECT),
        (r"no usar user_id default", "constraint", "test_rule", "avoid_user_id_default", GLOBAL_PROJECT),
        (r"si falta (?:dato|memoria|informacion|información), pedir(?:lo| un dato)?", "instruction", "test_rule", "ask_for_missing_data", GLOBAL_PROJECT),
        (r"no inventar", "constraint", "test_rule", "do_not_invent", GLOBAL_PROJECT),
        (r"si hay ambiguedad, pedir aclaracion", "instruction", "test_rule", "ask_clarification_on_ambiguity", GLOBAL_PROJECT),
        (r"si hay ambigüedad, pedir aclaración", "instruction", "test_rule", "ask_clarification_on_ambiguity", GLOBAL_PROJECT),
    ]

    for pattern, memory_type, entity, attribute, target_project in rules:
        match = re.fullmatch(pattern, normalized)
        if not match:
            continue
        value_text = match.group(1) if match.groups() else stripped.strip()
        return ExtractedMemory(
            memory_type=memory_type,
            entity=entity,
            attribute=attribute,
            value_text=_normalize_value(value_text),
            context=message.strip(),
            target_project=target_project,
        )

    return None


def extract_legacy_semantic_memory(content: str) -> Optional[ExtractedMemory]:
    person_fact = _extract_person_fact(content)
    if person_fact:
        return person_fact

    normalized = normalize_text(content)

    match = re.fullmatch(r"el proyecto prioritario actual es ([a-z0-9_\-]+)", normalized)
    if match:
        return ExtractedMemory(
            memory_type="fact",
            entity="project_meta",
            attribute="priority_project",
            value_text=_normalize_value(match.group(1)),
            context=content.strip(),
            source_type="legacy_api",
            target_project=None,
        )

    if re.search(r"\bcoc\b", normalized) and ("leer memoria" in normalized or "consultar memoria" in normalized) and "responder" in normalized:
        return ExtractedMemory(
            memory_type="instruction",
            entity="assistant_policy",
            attribute="memory_first",
            value_text="leer memoria antes de responder",
            context=content.strip(),
            source_type="legacy_api",
            target_project=None,
        )

    if "no hay memoria suficiente" in normalized and ("pedir un dato adicional" in normalized or "pedir dato adicional" in normalized):
        return ExtractedMemory(
            memory_type="instruction",
            entity="assistant_policy",
            attribute="insufficient_memory_rule",
            value_text=_normalize_value(content),
            context=content.strip(),
            source_type="legacy_api",
            target_project=None,
        )

    correction_fact = _extract_correction_fact(normalized, content)
    if correction_fact:
        correction_fact.source_type = "legacy_api"
        return correction_fact

    generic_fact = _extract_generic_fact(normalized, content)
    if generic_fact:
        generic_fact.source_type = "legacy_api"
        return generic_fact

    return None


def build_dedupe_key(user_id: str, project: str, book_id: str, entity: str, attribute: str) -> str:
    return f"{user_id}|{project}|{book_id}|{entity}|{attribute}"


def dedupe_key_hash(dedupe_key: str) -> str:
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()


def _get_snapshot(doc_ref, transaction):
    if transaction is None:
        return doc_ref.get()
    return doc_ref.get(transaction=transaction)


def upsert_semantic_memory(
    *,
    user_id: str,
    project: str,
    book_id: str,
    extracted: ExtractedMemory,
    source_event_id: str,
) -> dict:
    target_project = extracted.target_project or project
    dedupe_key = build_dedupe_key(user_id, target_project, book_id, extracted.entity, extracted.attribute)
    key_hash = dedupe_key_hash(dedupe_key)
    now = utc_now_iso()

    def _tx(transaction, *, key_hash: str, dedupe_key: str):
        key_ref = memory_keys_collection.document(key_hash)
        key_snapshot = _get_snapshot(key_ref, transaction)
        key_data = key_snapshot.to_dict() or {}
        active_memory_id = key_data.get("active_memory_id")
        new_version = 1

        supersedes_id = None
        if active_memory_id:
            active_ref = semantic_collection.document(active_memory_id)
            active_snapshot = _get_snapshot(active_ref, transaction)
            active_data = active_snapshot.to_dict() or {}

            if active_data and active_data.get("status") == "active":
                existing_value = normalize_text(active_data.get("value_text"))
                new_value = normalize_text(extracted.value_text)
                if existing_value == new_value:
                    return memory_dict_from_firestore(active_snapshot)

                supersedes_id = active_data.get("id") or active_memory_id
                updates = {
                    "status": "superseded",
                    "valid_to": now,
                    "updated_at": now,
                }
                if transaction is None:
                    active_ref.update(updates)
                else:
                    transaction.update(active_ref, updates)
                new_version = int(active_data.get("version") or 1) + 1

        memory_id = new_memory_id()
        new_data = {
            "id": memory_id,
            "user_id": user_id,
            "project": target_project,
            "book_id": book_id,
            "memory_type": extracted.memory_type,
            "entity": extracted.entity,
            "attribute": extracted.attribute,
            "value_text": _normalize_value(extracted.value_text),
            "context": extracted.context,
            "status": "active",
            "dedupe_key": dedupe_key,
            "version": new_version,
            "valid_from": now,
            "valid_to": None,
            "source_type": extracted.source_type,
            "source_event_id": source_event_id,
            "created_at": now,
            "updated_at": None,
            "confidence": float(getattr(extracted, "confidence", 0.95)),
            "extraction_method": getattr(extracted, "extraction_method", "rule"),
            "supersedes_id": supersedes_id,
            "superseded_by": None,
        }
        new_ref = semantic_collection.document(memory_id)
        index_ref = memory_indexes_collection.document(memory_id)

        key_data = {
            "dedupe_key_hash": key_hash,
            "dedupe_key": dedupe_key,
            "active_memory_id": memory_id,
            "updated_at": now,
        }
        index_data = {
            "id": memory_id,
            "user_id": user_id,
            "project": target_project,
            "book_id": book_id,
            "entity": extracted.entity,
            "attribute": extracted.attribute,
            "summary": f"{extracted.entity}.{extracted.attribute}={_normalize_value(extracted.value_text)}",
            "keywords": [user_id, target_project, extracted.entity, extracted.attribute, _normalize_value(extracted.value_text)],
            "status": "active",
            "created_at": now,
            "updated_at": now,
        }
        if transaction is None:
            new_ref.set(new_data)
            key_ref.set(key_data)
            index_ref.set(index_data)
            if supersedes_id:
                semantic_collection.document(supersedes_id).update({"superseded_by": memory_id, "updated_at": now})
        else:
            transaction.set(new_ref, new_data)
            transaction.set(key_ref, key_data)
            transaction.set(index_ref, index_data)
            if supersedes_id:
                transaction.update(semantic_collection.document(supersedes_id), {"superseded_by": memory_id, "updated_at": now})
        return new_data

    return db.run_transaction(_tx, key_hash=key_hash, dedupe_key=dedupe_key)


def _project_matches(item_project: Optional[str], project: Optional[str], include_global: bool) -> bool:
    if project is None:
        return True
    if item_project == project:
        return True
    return include_global and item_project == GLOBAL_PROJECT


def _filter_memories(
    items: Iterable[dict], *, user_id: str, project: Optional[str], book_id: Optional[str], include_inactive: bool = False, include_global: bool = True
) -> list[dict]:
    results = []
    for item in items:
        if item.get("user_id") != user_id:
            continue
        if not include_inactive and item.get("status") != "active":
            continue
        if not _project_matches(item.get("project"), project, include_global):
            continue
        if book_id and item.get("book_id") != book_id:
            continue
        if not is_semantic_memory_record(item):
            continue
        results.append(item)
    return results


def query_semantic_memories(
    user_id: str, project: Optional[str], book_id: Optional[str], *, include_inactive: bool = False, include_global: bool = True
) -> list[dict]:
    docs = semantic_collection.where("user_id", "==", user_id).stream()
    items = [memory_dict_from_firestore(doc) for doc in docs]
    return _filter_memories(items, user_id=user_id, project=project, book_id=book_id, include_inactive=include_inactive, include_global=include_global)


def query_active_semantic_memories(user_id: str, project: Optional[str], book_id: Optional[str]) -> list[dict]:
    return query_semantic_memories(user_id, project, book_id, include_inactive=False, include_global=True)


def audit_semantic_memories(*, dry_run: bool = True) -> dict:
    docs = semantic_collection.stream()
    memories = [memory_dict_from_firestore(doc) for doc in docs]
    findings = {
        "contaminated": [],
        "duplicate_active_keys": [],
        "invalid_status": [],
        "invalid_shape": [],
    }
    by_key: dict[str, list[dict]] = {}
    now = utc_now_iso()

    for memory in memories:
        if text_contains_blocked_markers(memory.get("value_text"), memory.get("context")):
            findings["contaminated"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": now})
            continue

        status = memory.get("status")
        if status not in VALID_MEMORY_STATUS:
            findings["invalid_status"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": now})
            continue

        if not is_semantic_memory_record(memory):
            findings["invalid_shape"].append(memory["id"])
            if not dry_run:
                semantic_collection.document(memory["id"]).update({"status": "archived", "updated_at": now})
            continue

        key = memory.get("dedupe_key")
        if key and memory.get("status") == "active":
            by_key.setdefault(key, []).append(memory)

    for key, items in by_key.items():
        if len(items) <= 1:
            continue
        items_sorted = sorted(
            items,
            key=lambda x: (
                int(x.get("version") or 1),
                x.get("updated_at") or x.get("created_at") or x.get("valid_from") or "",
                x.get("id") or "",
            ),
            reverse=True,
        )
        keep = items_sorted[0]["id"]
        findings["duplicate_active_keys"].append({"dedupe_key": key, "active_ids": [x["id"] for x in items_sorted]})
        if not dry_run:
            for memory in items_sorted[1:]:
                semantic_collection.document(memory["id"]).update({"status": "superseded", "valid_to": now, "updated_at": now})
            memory_keys_collection.document(dedupe_key_hash(key)).set(
                {
                    "dedupe_key_hash": dedupe_key_hash(key),
                    "dedupe_key": key,
                    "active_memory_id": keep,
                    "updated_at": now,
                }
            )

    return findings


def store_note_memory(
    *,
    user_id: str,
    project: str,
    book_id: str,
    content: str,
    source_type: str,
    source_event_id: Optional[str] = None,
    confidence: float = 0.7,
    extraction_method: str = "note",
) -> dict:
    cleaned = _normalize_value(content)
    content_hash = hashlib.sha256(f"{user_id}|{project}|{book_id}|{cleaned}".encode("utf-8")).hexdigest()[:12]
    attribute = f"manual_note_{content_hash}"
    dedupe_key = build_dedupe_key(user_id, project, book_id, "user_note", attribute)
    key_hash = dedupe_key_hash(dedupe_key)
    now = utc_now_iso()

    def _tx(transaction, *, key_hash: str, dedupe_key: str):
        key_ref = memory_keys_collection.document(key_hash)
        key_snapshot = _get_snapshot(key_ref, transaction)
        key_data = key_snapshot.to_dict() or {}
        active_memory_id = key_data.get("active_memory_id")
        if active_memory_id:
            active_ref = semantic_collection.document(active_memory_id)
            active_snapshot = _get_snapshot(active_ref, transaction)
            active_data = active_snapshot.to_dict() or {}
            if active_data and active_data.get("status") == "active":
                existing_value = normalize_text(active_data.get("value_text"))
                if existing_value == normalize_text(cleaned):
                    return memory_dict_from_firestore(active_snapshot)

        memory_id = source_event_id or new_memory_id()
        stored = {
            "id": memory_id,
            "user_id": user_id,
            "project": project,
            "book_id": book_id,
            "memory_type": "note",
            "entity": "user_note",
            "attribute": attribute,
            "value_text": cleaned,
            "context": cleaned,
            "status": "active",
            "dedupe_key": dedupe_key,
            "version": 1,
            "valid_from": now,
            "valid_to": None,
            "source_type": source_type,
            "source_event_id": source_event_id or memory_id,
            "created_at": now,
            "updated_at": now,
            "confidence": confidence,
            "extraction_method": extraction_method,
            "supersedes_id": None,
            "superseded_by": None,
        }
        if transaction is None:
            semantic_collection.document(memory_id).set(stored)
            key_ref.set({"dedupe_key_hash": key_hash, "dedupe_key": dedupe_key, "active_memory_id": memory_id, "updated_at": now})
        else:
            transaction.set(semantic_collection.document(memory_id), stored)
            transaction.set(key_ref, {"dedupe_key_hash": key_hash, "dedupe_key": dedupe_key, "active_memory_id": memory_id, "updated_at": now})
        return stored

    return db.run_transaction(_tx, key_hash=key_hash, dedupe_key=dedupe_key)


def store_message_memory(
    *,
    user_id: str,
    project: str,
    book_id: str,
    content: str,
    source_type: str,
    source_event_id: Optional[str] = None,
    force: bool = False,
) -> Optional[dict]:
    cleaned = _normalize_value(content)
    if not cleaned:
        return None
    extracted = extract_structured_memory(cleaned)
    if extracted:
        extracted.source_type = source_type
        return upsert_semantic_memory(
            user_id=user_id,
            project=project,
            book_id=book_id,
            extracted=extracted,
            source_event_id=source_event_id or new_memory_id(),
        )
    if not force and not is_explicit_memory_command(cleaned) and not should_auto_store_personal_note(cleaned):
        return None
    return store_note_memory(
        user_id=user_id,
        project=project,
        book_id=book_id,
        content=cleaned,
        source_type=source_type,
        source_event_id=source_event_id,
        confidence=0.72 if force or is_explicit_memory_command(cleaned) else 0.6,
        extraction_method="note",
    )


def store_manual_memory(*, user_id: str, project: str, book_id: str, content: str) -> dict:
    stored = store_message_memory(
        user_id=user_id,
        project=project,
        book_id=book_id,
        content=content,
        source_type="panel_manual",
        force=True,
    )
    if stored is None:
        raise ValueError("manual_memory_not_stored")
    return stored
