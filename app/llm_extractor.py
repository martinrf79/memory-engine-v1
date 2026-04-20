"""
Extractor de hechos estructurados desde texto libre.

Arquitectura:
- ExtractedFact: triple (subject, relation, object) con canonicalización básica.
- RegexExtractor: fallback offline sin LLM, cubre los patrones comunes en español.
- GeminiExtractor: usa Gemini para extraer triples desde frases complejas.
- ClaudeExtractor / OpenAIExtractor: stubs cableados, activables por env var cuando
  se provean las API keys.
- get_extractor(): singleton configurable por env var.

Filosofía:
- El output es siempre una lista de hechos (puede haber múltiples hechos en una frase).
- Si la extracción LLM falla por cualquier razón (rate limit, timeout, json inválido),
  se cae al extractor regex automáticamente. No rompemos al usuario.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Optional, Protocol


@dataclass(frozen=True)
class ExtractedFact:
    subject: str
    relation: str
    object: str
    # Qué entidad referencia el sujeto dentro del scope del usuario
    # Ej: "sobrino", "papa", "user" (para frases en primera persona)
    entity_key: str
    confidence: float = 1.0

    def as_dict(self) -> dict:
        return {
            "subject": self.subject,
            "relation": self.relation,
            "object": self.object,
            "entity_key": self.entity_key,
            "confidence": self.confidence,
        }


class FactExtractor(Protocol):
    def extract(self, text: str) -> list[ExtractedFact]: ...
    @property
    def backend(self) -> str: ...


def _clean(value: str) -> str:
    return " ".join((value or "").strip().split())


# ----------------------------------------------------------------------------- 
# Regex extractor: fallback determinístico sin LLM.
# Cubre los patrones más comunes en español argentino/neutro.
# -----------------------------------------------------------------------------

_PATTERNS: list[tuple[str, callable]] = [
    # "mi X [relación] Y" → subject=X normalizado
    (r"^mi\s+(.+?)\s+se\s+llama\s+(.+)$",       lambda m: (m.group(1), "se_llama", m.group(2))),
    (r"^mi\s+(.+?)\s+vive\s+en\s+(.+)$",        lambda m: (m.group(1), "vive_en", m.group(2))),
    (r"^mi\s+(.+?)\s+trabaja\s+en\s+(.+)$",     lambda m: (m.group(1), "trabaja_en", m.group(2))),
    (r"^mi\s+(.+?)\s+trabaja\s+para\s+(.+)$",   lambda m: (m.group(1), "trabaja_para", m.group(2))),
    (r"^mi\s+(.+?)\s+trabaja\s+de\s+(.+)$",     lambda m: (m.group(1), "trabaja_de", m.group(2))),
    (r"^mi\s+(.+?)\s+trabaja\s+como\s+(.+)$",   lambda m: (m.group(1), "trabaja_como", m.group(2))),
    (r"^mi\s+(.+?)\s+estudia\s+en\s+(.+)$",     lambda m: (m.group(1), "estudia_en", m.group(2))),
    (r"^mi\s+(.+?)\s+estudia\s+(.+)$",          lambda m: (m.group(1), "estudia", m.group(2))),
    (r"^mi\s+(.+?)\s+es\s+de\s+(.+)$",          lambda m: (m.group(1), "es_de", m.group(2))),
    (r"^mi\s+(.+?)\s+tiene\s+(\d+)\s+años?$",   lambda m: (m.group(1), "tiene_edad", m.group(2))),
    (r"^mi\s+(.+?)\s+cumple\s+años?\s+el\s+(.+)$", lambda m: (m.group(1), "cumple_el", m.group(2))),
    (r"^mi\s+(.+?)\s+nació\s+en\s+(.+)$",       lambda m: (m.group(1), "nacio_en", m.group(2))),
    (r"^mi\s+(.+?)\s+favorit[oa]\s+es\s+(.+)$", lambda m: ("user", f"{_clean(m.group(1))}_favorito", m.group(2))),
    (r"^mi\s+(.+?)\s+preferid[oa]\s+es\s+(.+)$",lambda m: ("user", f"{_clean(m.group(1))}_preferido", m.group(2))),
    # Primera persona
    (r"^soy\s+de\s+(.+)$",                      lambda m: ("user", "es_de", m.group(1))),
    (r"^vivo\s+en\s+(.+)$",                     lambda m: ("user", "vive_en", m.group(1))),
    (r"^trabajo\s+en\s+(.+)$",                  lambda m: ("user", "trabaja_en", m.group(1))),
    (r"^trabajo\s+para\s+(.+)$",                lambda m: ("user", "trabaja_para", m.group(1))),
    (r"^trabajo\s+de\s+(.+)$",                  lambda m: ("user", "trabaja_de", m.group(1))),
    (r"^trabajo\s+como\s+(.+)$",                lambda m: ("user", "trabaja_como", m.group(1))),
    (r"^estudio\s+en\s+(.+)$",                  lambda m: ("user", "estudia_en", m.group(1))),
    (r"^estudio\s+(.+)$",                       lambda m: ("user", "estudia", m.group(1))),
    (r"^me\s+llamo\s+(.+)$",                    lambda m: ("user", "se_llama", m.group(1))),
    (r"^mi\s+nombre\s+es\s+(.+)$",              lambda m: ("user", "se_llama", m.group(1))),
    (r"^tengo\s+(\d+)\s+años?$",                lambda m: ("user", "tiene_edad", m.group(1))),
    (r"^nací\s+en\s+(.+)$",                     lambda m: ("user", "nacio_en", m.group(1))),
    # Patrón genérico último (menos confiable)
    (r"^mi\s+(.+?)\s+es\s+(.+)$",               lambda m: (m.group(1), "es", m.group(2))),
]


class RegexExtractor:
    backend = "regex"

    def extract(self, text: str) -> list[ExtractedFact]:
        raw = _clean(text).rstrip(" .!?¿")
        if not raw:
            return []
        low = raw.lower()
        for pattern, builder in _PATTERNS:
            m = re.match(pattern, low, flags=re.IGNORECASE)
            if m:
                subj_raw, relation, obj_raw = builder(m)
                subj_clean = _clean(subj_raw)
                obj_clean = _clean(obj_raw)
                # Recuperar capitalización original del objeto si estaba capitalizado
                # (útil para nombres propios: "Madrid", "Google")
                obj_original = _recover_case(raw, obj_clean)
                entity_key = subj_clean.lower() if subj_clean != "user" else "user"
                # Confianza moderada (0.75) para regex; el LLM daría mayor si acierta.
                return [
                    ExtractedFact(
                        subject=subj_clean,
                        relation=relation,
                        object=obj_original or obj_clean,
                        entity_key=entity_key,
                        confidence=0.75,
                    )
                ]
        return []


def _recover_case(original: str, needle_lower: str) -> str:
    """Busca needle_lower en original (case-insensitive) y devuelve la porción
    con su capitalización real."""
    idx = original.lower().find(needle_lower.lower())
    if idx == -1:
        return needle_lower
    return original[idx : idx + len(needle_lower)]


# -----------------------------------------------------------------------------
# LLM extractors: Gemini (primary), Claude, OpenAI.
# Todos devuelven JSON estructurado y caen a [] si el parseo falla
# (el sistema llama a RegexExtractor como segunda capa).
# -----------------------------------------------------------------------------

_LLM_SYSTEM_PROMPT = """Sos un extractor de hechos. Recibís una frase en español y devolvés SOLO un array JSON con los hechos que contenga, sin explicaciones, sin markdown.

Cada hecho tiene esta forma:
{"subject": "...", "relation": "...", "object": "...", "entity_key": "...", "confidence": 0.0-1.0}

Reglas:
- "subject" es la entidad de la que se habla, ej: "sobrino", "gato", "hermana", "user" (si es sobre el hablante).
- "relation" es un verbo o frase corta normalizada con guiones bajos: "trabaja_en", "vive_en", "se_llama", "estudia_en", "tiene_edad", "es_de", etc.
- "object" es el valor: el lugar, nombre, edad, etc. Preservá capitalización de nombres propios.
- "entity_key" es una clave corta para identificar la entidad dentro del usuario, en minúsculas y sin artículos: "sobrino", "hermana", "gato", "user".
- Si la frase no contiene hechos útiles, devolvé [].
- Si hay varios hechos, devolvé varios objetos en el array.
- Ignorá preguntas: si la frase es una pregunta, devolvé [].

Ejemplos:
"Mi sobrino trabaja en seguridad" → [{"subject":"sobrino","relation":"trabaja_en","object":"seguridad","entity_key":"sobrino","confidence":0.95}]
"Mi hermana Ana vive en Madrid y es médica" → [{"subject":"hermana Ana","relation":"vive_en","object":"Madrid","entity_key":"hermana","confidence":0.9},{"subject":"hermana Ana","relation":"es","object":"médica","entity_key":"hermana","confidence":0.9}]
"¿dónde vive mi hermana?" → []
"Hola" → []
"""


def _parse_llm_json(raw: str) -> list[ExtractedFact]:
    """Parsea la respuesta del LLM y devuelve ExtractedFact list. Robusto a basura alrededor."""
    if not raw:
        return []
    # Limpiar code fences si aparecen
    raw = raw.strip()
    raw = re.sub(r"^```(?:json)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)
    # Encontrar el primer '[' y el último ']'
    start = raw.find("[")
    end = raw.rfind("]")
    if start == -1 or end == -1 or end < start:
        return []
    try:
        data = json.loads(raw[start : end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    out: list[ExtractedFact] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        subj = _clean(str(item.get("subject", "")))
        rel = _clean(str(item.get("relation", "")))
        obj = _clean(str(item.get("object", "")))
        ek = _clean(str(item.get("entity_key", "") or subj)).lower()
        try:
            conf = float(item.get("confidence", 0.8))
        except (TypeError, ValueError):
            conf = 0.8
        if subj and rel and obj:
            out.append(ExtractedFact(subj, rel, obj, ek or "user", conf))
    return out


class GeminiExtractor:
    backend = "gemini"

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        import google.generativeai as genai  # lazy
        genai.configure(api_key=api_key)
        self._model = genai.GenerativeModel(
            model_name=model,
            system_instruction=_LLM_SYSTEM_PROMPT,
        )

    def extract(self, text: str) -> list[ExtractedFact]:
        try:
            resp = self._model.generate_content(
                text,
                generation_config={"temperature": 0.0, "response_mime_type": "application/json"},
            )
            return _parse_llm_json(resp.text or "")
        except Exception:  # noqa: BLE001
            return []


class ClaudeExtractor:
    backend = "claude"

    def __init__(self, api_key: str, model: str = "claude-3-5-haiku-20241022"):
        import anthropic  # lazy
        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def extract(self, text: str) -> list[ExtractedFact]:
        try:
            resp = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=_LLM_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": text}],
                temperature=0.0,
            )
            raw = ""
            for block in resp.content:
                if getattr(block, "type", None) == "text":
                    raw += block.text
            return _parse_llm_json(raw)
        except Exception:  # noqa: BLE001
            return []


class OpenAIExtractor:
    backend = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4o-mini"):
        from openai import OpenAI  # lazy
        self._client = OpenAI(api_key=api_key)
        self._model = model

    def extract(self, text: str) -> list[ExtractedFact]:
        try:
            resp = self._client.chat.completions.create(
                model=self._model,
                temperature=0.0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": _LLM_SYSTEM_PROMPT + '\nRespondé con un objeto {"facts": [...]}.'},
                    {"role": "user", "content": text},
                ],
            )
            raw = resp.choices[0].message.content or ""
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and isinstance(data.get("facts"), list):
                    raw = json.dumps(data["facts"])
            except json.JSONDecodeError:
                pass
            return _parse_llm_json(raw)
        except Exception:  # noqa: BLE001
            return []


# -----------------------------------------------------------------------------
# Compound extractor: prueba LLM y cae a regex si falla o devuelve vacío.
# -----------------------------------------------------------------------------


class CompoundExtractor:
    """Intenta LLM primero; si no extrajo nada o falló, prueba regex."""
    def __init__(self, llm: Optional[FactExtractor], regex: RegexExtractor):
        self._llm = llm
        self._regex = regex

    @property
    def backend(self) -> str:
        return f"{self._llm.backend}+regex" if self._llm else "regex"

    def extract(self, text: str) -> list[ExtractedFact]:
        if self._llm:
            facts = self._llm.extract(text)
            if facts:
                return facts
        return self._regex.extract(text)


_singleton: FactExtractor | None = None


def get_extractor() -> FactExtractor:
    global _singleton
    if _singleton is not None:
        return _singleton

    backend = os.getenv("LLM_EXTRACTOR_BACKEND", "auto").lower()
    regex = RegexExtractor()

    # Resolver según backend requerido
    llm: FactExtractor | None = None
    if backend in {"auto", "gemini"}:
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if key:
            try:
                llm = GeminiExtractor(api_key=key)
            except Exception:  # noqa: BLE001
                llm = None
    if llm is None and backend in {"auto", "claude"}:
        key = os.getenv("ANTHROPIC_API_KEY", "").strip()
        if key:
            try:
                llm = ClaudeExtractor(api_key=key)
            except Exception:  # noqa: BLE001
                llm = None
    if llm is None and backend in {"auto", "openai"}:
        key = os.getenv("OPENAI_API_KEY", "").strip()
        if key:
            try:
                llm = OpenAIExtractor(api_key=key)
            except Exception:  # noqa: BLE001
                llm = None

    if backend == "regex" or llm is None:
        _singleton = regex
    else:
        _singleton = CompoundExtractor(llm=llm, regex=regex)
    return _singleton


def reset_extractor_singleton() -> None:
    global _singleton
    _singleton = None


def set_extractor(provider: FactExtractor) -> None:
    """Inyección manual, útil en tests."""
    global _singleton
    _singleton = provider
