"""
Memory Engine V2 — núcleo unificado de memoria semántica.

Pipeline de `remember(content)`:
  1. Extraer hechos con el FactExtractor.
  2. Calcular embedding del content.
  3. Detectar contradicciones con hechos existentes del mismo entity_key + relation:
     si hay un hecho anterior con la misma relation pero distinto object, marcarlo
     como superseded y apuntar al nuevo.
  4. Guardar MemoryEntry en el VectorStore.
  5. Devolver resumen de la acción.

Pipeline de `recall(query)`:
  1. Detectar si es pregunta. Si no lo es, devolver None (el caller decide qué hacer).
  2. Identificar entity_key de la pregunta (si existe) para filtrar la búsqueda.
  3. Embed de la query, search top-K.
  4. Construir respuesta natural a partir del mejor hecho / contenido.

Scoping: todo pasa por (tenant_id, user_id, project_id, book_id). Preparado para
multi-tenant desde el día uno.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

from app.embeddings import get_embedder, cosine_similarity
from app.llm_extractor import get_extractor, ExtractedFact
from app.vector_store import MemoryEntry, get_vector_store
from app.utils import utc_now_iso


# ---------- Scope ----------

@dataclass(frozen=True)
class Scope:
    tenant_id: str
    user_id: str
    project_id: str
    book_id: str = "general"

    @classmethod
    def from_panel(cls, *, user_id: str, project: str, book_id: str = "general") -> "Scope":
        return cls(
            tenant_id=user_id,
            user_id=user_id,
            project_id=project or "general",
            book_id=book_id or "general",
        )


# ---------- Utilidades ----------

_QUESTION_WORDS = {
    "cual", "cuál", "cuales", "cuáles",
    "que", "qué",
    "como", "cómo",
    "donde", "dónde", "adonde", "adónde",
    "cuando", "cuándo",
    "quien", "quién", "quienes", "quiénes",
    "cuanto", "cuánto", "cuanta", "cuánta",
    "cuantos", "cuántos", "cuantas", "cuántas",
    "porque", "porqué",
}

_QUESTION_TOKEN_RE = re.compile(
    r"(?:^|[^a-záéíóúñ])(" + "|".join(re.escape(w) for w in _QUESTION_WORDS) + r")(?:[^a-záéíóúñ]|$)",
    re.IGNORECASE,
)


def is_question(text: str) -> bool:
    if not text:
        return False
    t = text.strip()
    if not t:
        return False
    if "?" in t or "¿" in t:
        return True
    if _QUESTION_TOKEN_RE.search(t.lower()):
        return True
    low = t.lower()
    if low.startswith("por qué") or " por qué " in low:
        return True
    return False


# Tokens comunes en español que probablemente identifican una "entidad personal"
# en preguntas. Si aparece "mi sobrino" en la pregunta, entity_key="sobrino".
_ENTITY_FROM_QUESTION_RE = re.compile(
    r"\b(?:mi|mis|tu|tus|su|sus|el|la|los|las|del|de)\s+([a-záéíóúñ]+)",
    re.IGNORECASE,
)

_STOP_ENTITIES = {
    "gato", "perro", "casa", "auto", "coche", "trabajo", "estudio",
    # Mantenemos estos — son entidades válidas. El stop real es muy corto:
}
_ENTITY_STOPWORDS = {
    "donde", "dónde", "cuando", "cuándo", "quien", "quién", "como", "cómo",
    "que", "qué", "cual", "cuál", "cuales", "cuáles",
}


def detect_entity_in_query(text: str) -> Optional[str]:
    """
    Busca una entidad personal en la pregunta, ej: "¿dónde trabaja mi sobrino?" → "sobrino".
    Devuelve la clave normalizada (singular probable, sin artículo) o None.
    """
    if not text:
        return None
    for m in _ENTITY_FROM_QUESTION_RE.finditer(text):
        cand = m.group(1).lower().strip()
        if cand in _ENTITY_STOPWORDS or len(cand) < 3:
            continue
        return cand
    # Primera persona: "¿dónde vivo?" → "user"
    first_person = ["vivo", "trabajo", "estudio", "nací", "me llamo", "cumplo"]
    low = text.lower()
    if any(fp in low for fp in first_person):
        return "user"
    return None


# ---------- Formateo de respuestas ----------

# Mapeo de relaciones canonicales a verbos conjugados (tercera persona).
_RELATION_PHRASE_OTHER = {
    "se_llama": "se llama",
    "vive_en": "vive en",
    "trabaja_en": "trabaja en",
    "trabaja_para": "trabaja para",
    "trabaja_de": "trabaja de",
    "trabaja_como": "trabaja como",
    "estudia_en": "estudia en",
    "estudia": "estudia",
    "es_de": "es de",
    "tiene_edad": "tiene",
    "cumple_el": "cumple años el",
    "nacio_en": "nació en",
    "es": "es",
}

# Para sujeto=user, usamos segunda persona (vos/tú).
_RELATION_PHRASE_USER = {
    "se_llama": "Te llamás",
    "vive_en": "Vivís en",
    "trabaja_en": "Trabajás en",
    "trabaja_para": "Trabajás para",
    "trabaja_de": "Trabajás de",
    "trabaja_como": "Trabajás como",
    "estudia_en": "Estudiás en",
    "estudia": "Estudiás",
    "es_de": "Sos de",
    "tiene_edad": "Tenés",
    "nacio_en": "Naciste en",
}


def _format_fact_answer(fact: dict) -> Optional[str]:
    subject = (fact.get("subject") or "").strip()
    entity_key = (fact.get("entity_key") or "").strip().lower()
    relation = (fact.get("relation") or "").strip().lower()
    obj = (fact.get("object") or "").strip()

    if not obj:
        return None

    if entity_key == "user" or subject.lower() == "user":
        phrase = _RELATION_PHRASE_USER.get(relation)
        if phrase:
            if relation == "tiene_edad":
                return f"{phrase} {obj} años."
            return f"{phrase} {obj}."
        # Fallback genérico para user
        if "_favorito" in relation or "_preferido" in relation:
            topic = relation.replace("_favorito", "").replace("_preferido", "").replace("_", " ")
            qualifier = "favorito" if "_favorito" in relation else "preferido"
            return f"Tu {topic} {qualifier} es {obj}."
        return f"Tu {relation.replace('_', ' ')}: {obj}."

    phrase = _RELATION_PHRASE_OTHER.get(relation)
    subject_display = subject if subject else entity_key
    if phrase:
        if relation == "tiene_edad":
            return f"Tu {subject_display} {phrase} {obj} años."
        return f"Tu {subject_display} {phrase} {obj}."
    # Fallback genérico
    nice_rel = relation.replace("_", " ")
    return f"Tu {subject_display} {nice_rel} {obj}."


def _format_content_answer(content: str) -> str:
    content = (content or "").strip().rstrip(".!?¿¡")
    return f"Según tu memoria: {content}."


# ---------- API pública ----------

@dataclass
class RememberResult:
    entry_id: str
    facts_extracted: int
    superseded_ids: list[str]
    mode: str  # "saved" | "updated"
    message: str


@dataclass
class RecallResult:
    answer: Optional[str]
    mode: str  # "answer" | "no_match" | "not_a_question"
    used_entries: list[dict]  # para transparencia


class MemoryEngine:
    """Orquestador principal. No mantiene estado global salvo los singletons de sus deps."""

    def __init__(
        self,
        *,
        extractor=None,
        embedder=None,
        store=None,
        contradiction_threshold: float = 0.70,
    ):
        self.extractor = extractor or get_extractor()
        self.embedder = embedder or get_embedder()
        self.store = store or get_vector_store()
        self.contradiction_threshold = contradiction_threshold

    # -------- Remember --------

    def remember(self, scope: Scope, content: str, *, source: str = "panel_manual") -> RememberResult:
        content = (content or "").strip()
        if not content:
            raise ValueError("content_empty")
        if is_question(content):
            # No guardamos preguntas. El caller decide qué hacer con eso.
            raise ValueError("content_is_question")

        # 1. Extraer hechos
        facts = self.extractor.extract(content)
        facts_as_dicts = [f.as_dict() for f in facts]

        # 2. Determinar entity_key principal (el primer fact si hay, si no genérico)
        entity_key = facts[0].entity_key if facts else _guess_entity_key_from_text(content)

        # 3. Embedding
        embedding = self.embedder.embed(content)

        # 4. Detectar contradicciones — para cada fact nuevo, buscar el mismo
        #    (entity_key, relation) en memoria y marcarlo superseded si difiere.
        superseded_ids: list[str] = []
        if facts:
            for f in facts:
                existing = self.store.list_for_entity(
                    tenant_id=scope.tenant_id,
                    user_id=scope.user_id,
                    project_id=scope.project_id,
                    book_id=scope.book_id,
                    entity_key=f.entity_key,
                    include_superseded=False,
                )
                for e in existing:
                    for ef in e.facts or []:
                        if (
                            (ef.get("relation") or "").lower() == f.relation.lower()
                            and (ef.get("object") or "").strip().lower()
                            != f.object.strip().lower()
                        ):
                            superseded_ids.append(e.id)
                            break

        # 5. Crear nueva entry
        now = utc_now_iso()
        entry = MemoryEntry(
            id=f"mem_{uuid4().hex}",
            tenant_id=scope.tenant_id,
            user_id=scope.user_id,
            project_id=scope.project_id,
            book_id=scope.book_id,
            kind="fact" if facts else "note",
            content=content,
            facts=facts_as_dicts,
            entity_key=entity_key or "",
            embedding=embedding,
            status="active",
            source=source,
            created_at=now,
            updated_at=now,
        )
        self.store.save(entry)

        # 6. Marcar superseded
        for sid in superseded_ids:
            self.store.update_status(sid, status="superseded", superseded_by=entry.id)

        mode = "updated" if superseded_ids else "saved"
        if superseded_ids:
            msg = f"Memoria actualizada ({len(superseded_ids)} hecho(s) anterior(es) reemplazados)."
        else:
            msg = "Memoria guardada."

        return RememberResult(
            entry_id=entry.id,
            facts_extracted=len(facts),
            superseded_ids=superseded_ids,
            mode=mode,
            message=msg,
        )

    # -------- Recall --------

    def recall(self, scope: Scope, query: str, *, top_k: int = 5) -> RecallResult:
        if not is_question(query):
            return RecallResult(answer=None, mode="not_a_question", used_entries=[])

        entity_key = detect_entity_in_query(query)
        query_emb = self.embedder.embed(query)

        # 1. Si detectamos entidad, buscamos filtrando por ella (más preciso)
        results: list[tuple[float, MemoryEntry]] = []
        if entity_key:
            results = self.store.search(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                project_id=scope.project_id,
                book_id=scope.book_id,
                query_embedding=query_emb,
                top_k=top_k,
                entity_key=entity_key,
                include_superseded=False,
            )
            # Si el filtro por entidad no dio resultados, relajamos y buscamos global.
            if not results or (results and results[0][0] < 0.15):
                results = self.store.search(
                    tenant_id=scope.tenant_id,
                    user_id=scope.user_id,
                    project_id=scope.project_id,
                    book_id=scope.book_id,
                    query_embedding=query_emb,
                    top_k=top_k,
                    include_superseded=False,
                )
        else:
            results = self.store.search(
                tenant_id=scope.tenant_id,
                user_id=scope.user_id,
                project_id=scope.project_id,
                book_id=scope.book_id,
                query_embedding=query_emb,
                top_k=top_k,
                include_superseded=False,
            )

        if not results:
            return RecallResult(answer=None, mode="no_match", used_entries=[])

        best_score, best_entry = results[0]
        # Umbral mínimo: con hashing el coseno es menor; con gemini es más alto.
        # Usamos un umbral suave; si la entidad fue detectada y matcheamos por ella,
        # el resultado es relevante aunque el coseno sea modesto.
        min_score = 0.05 if entity_key else 0.12
        if best_score < min_score:
            return RecallResult(answer=None, mode="no_match", used_entries=[])

        # 2. Construir respuesta
        # Prioridad 1: si hay facts y la query tiene relación identificable, buscar el
        # fact que mejor corresponda (por ejemplo, la query pregunta "donde trabaja"
        # y el fact tiene relation="trabaja_en").
        answer = _build_answer(best_entry, query)
        if not answer:
            # Fallback: usar content crudo
            answer = _format_content_answer(best_entry.content)

        used = [
            {"id": e.id, "content": e.content, "score": round(score, 3), "kind": e.kind}
            for score, e in results[: min(3, len(results))]
        ]
        return RecallResult(answer=answer, mode="answer", used_entries=used)


# ---------- Helpers internos ----------

# Palabras clave en la query que mapean a relaciones. Permite "afinar" qué fact devolver
# cuando una entrada tiene múltiples hechos.
_QUERY_RELATION_HINTS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\btrabaja\b|\btrabajás\b|\btrabajas\b|\btrabajo\b", re.IGNORECASE), "trabaja_"),
    (re.compile(r"\bvive\b|\bvivís\b|\bvives\b|\bvivo\b|\bdónde\s+es(tá|ta)\b", re.IGNORECASE), "vive_en"),
    (re.compile(r"\bestudia\b|\bestudiás\b|\bestudio\b", re.IGNORECASE), "estudia"),
    (re.compile(r"\bllama\b|\bllamás\b|\bnombre\b", re.IGNORECASE), "se_llama"),
    (re.compile(r"\bedad\b|\baños\b|\bcuánto[s]?\s+años\b", re.IGNORECASE), "tiene_edad"),
    (re.compile(r"\bnació\b|\bnació\s+en\b|\bde\s+dónde\b", re.IGNORECASE), "nacio_en|es_de"),
    (re.compile(r"\bfavorit[oa]\b|\bpreferid[oa]\b", re.IGNORECASE), "_favorito|_preferido"),
]


def _build_answer(entry: MemoryEntry, query: str) -> Optional[str]:
    """Elige el fact más pertinente para la query y lo formatea como frase."""
    facts = entry.facts or []
    if facts:
        # Tratar de matchear por hint de la query
        hint_keys: list[str] = []
        for pat, key in _QUERY_RELATION_HINTS:
            if pat.search(query):
                hint_keys.extend(key.split("|"))
        if hint_keys:
            for f in facts:
                rel = (f.get("relation") or "").lower()
                for hk in hint_keys:
                    if hk in rel:
                        ans = _format_fact_answer(f)
                        if ans:
                            return ans
        # Si no hubo hint o no matcheó, usar el primer fact
        for f in facts:
            ans = _format_fact_answer(f)
            if ans:
                return ans
    return None


_ENTITY_HINTS = ["sobrino", "sobrina", "hermano", "hermana", "primo", "prima",
                 "papá", "mamá", "tío", "tía", "abuelo", "abuela",
                 "hijo", "hija", "novio", "novia", "esposo", "esposa",
                 "amigo", "amiga", "gato", "perro", "jefe", "jefa"]


def _guess_entity_key_from_text(text: str) -> str:
    low = (text or "").lower()
    for hint in _ENTITY_HINTS:
        if re.search(rf"\b{hint}s?\b", low):
            return hint
    # Primera persona
    if re.search(r"\b(vivo|trabajo|estudio|me\s+llamo|mi\s+nombre|nací|soy)\b", low):
        return "user"
    return "user"


# ---------- Singleton ----------

_engine: MemoryEngine | None = None


def get_engine() -> MemoryEngine:
    global _engine
    if _engine is None:
        _engine = MemoryEngine()
    return _engine


def set_engine(engine: MemoryEngine) -> None:
    global _engine
    _engine = engine


def reset_engine_singleton() -> None:
    global _engine
    _engine = None
