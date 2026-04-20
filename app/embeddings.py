"""
Embeddings provider con tres niveles:

1. Si GEMINI_API_KEY está configurada y google-generativeai disponible → embeddings reales.
2. Si no hay API key, usa un embedding determinístico basado en hashing de n-gramas (DHE).
   Esto no es tan bueno como un modelo real, pero es mejor que nada para desarrollo y tests,
   y permite que el sistema funcione sin dependencias externas.
3. Para tests, se puede inyectar un provider fake.

El objetivo es que el resto del sistema no tenga que conocer qué backend se usa.
"""
from __future__ import annotations

import hashlib
import math
import os
import re
from typing import Iterable, Protocol

# Dimensión fija para que el sistema sea consistente entre modos.
# 768 es la dimensión de text-embedding-004 de Gemini.
EMBEDDING_DIM = 768


class EmbeddingProvider(Protocol):
    def embed(self, text: str) -> list[float]: ...
    def embed_many(self, texts: Iterable[str]) -> list[list[float]]: ...
    @property
    def backend(self) -> str: ...


_WORD_RE = re.compile(r"[a-záéíóúñü0-9]+", re.IGNORECASE)


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _WORD_RE.findall(text or "")]


def _normalize(vec: list[float]) -> list[float]:
    norm = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / norm for x in vec]


class HashingEmbedder:
    """
    Distributed Hashing Embedder (DHE): genera un vector denso determinístico
    a partir de n-gramas del texto. Útil como fallback sin LLM.

    No es semántico (no conoce sinónimos), pero captura solapamiento léxico bien,
    que es suficiente para los casos de uso del panel (preguntas directas sobre
    hechos guardados).
    """
    backend = "hashing"

    def __init__(self, dim: int = EMBEDDING_DIM, ngram_range: tuple[int, int] = (1, 2)):
        self.dim = dim
        self.ngram_range = ngram_range

    def _features(self, text: str) -> list[str]:
        tokens = _tokenize(text)
        feats: list[str] = list(tokens)
        lo, hi = self.ngram_range
        for n in range(max(lo, 2), hi + 1):
            for i in range(len(tokens) - n + 1):
                feats.append(" ".join(tokens[i : i + n]))
        return feats

    def embed(self, text: str) -> list[float]:
        vec = [0.0] * self.dim
        feats = self._features(text)
        if not feats:
            return vec
        for f in feats:
            h = hashlib.blake2b(f.encode("utf-8"), digest_size=8).digest()
            idx = int.from_bytes(h[:4], "little") % self.dim
            sign = 1.0 if (h[4] & 1) else -1.0
            vec[idx] += sign
        return _normalize(vec)

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


class GeminiEmbedder:
    """Embeddings reales vía Google Generative AI (text-embedding-004)."""
    backend = "gemini"

    def __init__(self, api_key: str, model: str = "models/text-embedding-004"):
        import google.generativeai as genai  # lazy import
        genai.configure(api_key=api_key)
        self._genai = genai
        self.model = model
        self.dim = EMBEDDING_DIM

    def embed(self, text: str) -> list[float]:
        text = (text or "").strip() or " "
        res = self._genai.embed_content(
            model=self.model,
            content=text,
            task_type="RETRIEVAL_DOCUMENT",
        )
        vec = list(res["embedding"])
        return _normalize(vec)

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        return [self.embed(t) for t in texts]


_singleton: EmbeddingProvider | None = None


def get_embedder() -> EmbeddingProvider:
    """Devuelve el embedder activo, inicializándolo una vez."""
    global _singleton
    if _singleton is not None:
        return _singleton

    backend = os.getenv("EMBEDDING_BACKEND", "auto").lower()
    api_key = os.getenv("GEMINI_API_KEY", "").strip()

    if backend == "hashing" or (backend == "auto" and not api_key):
        _singleton = HashingEmbedder()
        return _singleton

    if backend in {"gemini", "auto"} and api_key:
        try:
            _singleton = GeminiEmbedder(api_key=api_key)
            return _singleton
        except Exception:  # noqa: BLE001
            # Si google-generativeai no está instalado o falla, caemos a hashing.
            _singleton = HashingEmbedder()
            return _singleton

    _singleton = HashingEmbedder()
    return _singleton


def reset_embedder_singleton() -> None:
    """Útil en tests para forzar reinicialización."""
    global _singleton
    _singleton = None


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Similitud coseno entre dos vectores (asume normalizados o no)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1.0
    nb = math.sqrt(sum(x * x for x in b)) or 1.0
    return dot / (na * nb)
