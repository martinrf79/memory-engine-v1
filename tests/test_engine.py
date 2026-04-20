"""
Tests del Memory Engine V2.
No dependen de Firestore ni de Gemini: usan InMemoryVectorStore y RegexExtractor/embedder hash.
"""
from __future__ import annotations

import sys
import os

# Asegurar que el package 'app' sea importable desde la raíz del repo.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Forzar modo sin LLM / sin Firestore
os.environ["GEMINI_API_KEY"] = ""
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["OPENAI_API_KEY"] = ""
os.environ["LLM_EXTRACTOR_BACKEND"] = "regex"
os.environ["EMBEDDING_BACKEND"] = "hashing"
os.environ["VECTOR_STORE_BACKEND"] = "memory"

from app.memory_engine import (  # noqa: E402
    MemoryEngine, Scope, is_question, detect_entity_in_query,
    reset_engine_singleton, set_engine,
)
from app.vector_store import InMemoryVectorStore, set_vector_store, reset_vector_store_singleton  # noqa: E402
from app.embeddings import HashingEmbedder, reset_embedder_singleton  # noqa: E402
from app.llm_extractor import RegexExtractor, reset_extractor_singleton, set_extractor  # noqa: E402


def fresh_engine() -> MemoryEngine:
    reset_vector_store_singleton()
    reset_embedder_singleton()
    reset_extractor_singleton()
    reset_engine_singleton()
    store = InMemoryVectorStore()
    set_vector_store(store)
    set_extractor(RegexExtractor())
    engine = MemoryEngine(store=store, embedder=HashingEmbedder(), extractor=RegexExtractor())
    set_engine(engine)
    return engine


def scope() -> Scope:
    return Scope(tenant_id="t1", user_id="u1", project_id="general", book_id="general")


# ---------- Detectores ----------

def test_is_question():
    assert is_question("donde trabaja mi sobrino")
    assert is_question("¿dónde trabaja mi sobrino?")
    assert is_question("cuál es mi color favorito")
    assert is_question("quien vive en Madrid")
    assert is_question("cuando cumple años mi hermana")
    assert is_question("¿cómo se llama mi gato?")
    assert not is_question("Mi sobrino trabaja en seguridad")
    assert not is_question("Me gusta el fútbol")
    assert not is_question("hola")
    assert not is_question("")


def test_detect_entity_in_query():
    assert detect_entity_in_query("donde trabaja mi sobrino") == "sobrino"
    assert detect_entity_in_query("¿cómo se llama mi gato?") == "gato"
    assert detect_entity_in_query("donde vivo") == "user"
    assert detect_entity_in_query("qué hora es") is None
    assert detect_entity_in_query("dónde trabaja mi hermana") == "hermana"


# ---------- Remember: casos felices ----------

def test_remember_simple_fact():
    e = fresh_engine()
    r = e.remember(scope(), "Mi sobrino trabaja en seguridad")
    assert r.mode == "saved"
    assert r.facts_extracted == 1
    assert not r.superseded_ids


def test_remember_primera_persona():
    e = fresh_engine()
    r = e.remember(scope(), "Trabajo en Anthropic")
    assert r.facts_extracted == 1


def test_remember_nota_sin_hechos():
    e = fresh_engine()
    r = e.remember(scope(), "Me gusta el otoño")
    # No matchea ningún patrón regex, se guarda como note pura
    assert r.mode == "saved"
    assert r.facts_extracted == 0


def test_remember_rechaza_preguntas():
    e = fresh_engine()
    try:
        e.remember(scope(), "¿dónde trabaja mi sobrino?")
        assert False, "debería haber levantado ValueError"
    except ValueError as ex:
        assert str(ex) == "content_is_question"


# ---------- Recall: caso del sobrino (el bug original) ----------

def test_recall_caso_sobrino():
    e = fresh_engine()
    e.remember(scope(), "Mi sobrino trabaja en seguridad")

    r = e.recall(scope(), "donde trabaja mi sobrino")
    assert r.mode == "answer", f"modo={r.mode}, answer={r.answer}"
    assert r.answer is not None
    assert "sobrino" in r.answer.lower()
    assert "seguridad" in r.answer.lower()


def test_recall_caso_sobrino_con_signos():
    e = fresh_engine()
    e.remember(scope(), "Mi sobrino trabaja en seguridad")
    r = e.recall(scope(), "¿dónde trabaja mi sobrino?")
    assert r.mode == "answer"
    assert "seguridad" in r.answer.lower()


def test_recall_no_pregunta_devuelve_none():
    e = fresh_engine()
    e.remember(scope(), "Mi sobrino trabaja en seguridad")
    r = e.recall(scope(), "Hola claude")
    assert r.mode == "not_a_question"
    assert r.answer is None


def test_recall_sin_memoria_devuelve_no_match():
    e = fresh_engine()
    r = e.recall(scope(), "¿dónde trabaja mi sobrino?")
    assert r.mode == "no_match"


# ---------- Contradicciones ----------

def test_contradiccion_marca_superseded():
    e = fresh_engine()
    r1 = e.remember(scope(), "Mi sobrino trabaja en seguridad")
    r2 = e.remember(scope(), "Mi sobrino trabaja en Google")
    assert r2.mode == "updated"
    assert r1.entry_id in r2.superseded_ids

    # Al preguntar, debe devolver el valor nuevo (Google), no el viejo
    r = e.recall(scope(), "donde trabaja mi sobrino")
    assert r.mode == "answer"
    assert "google" in r.answer.lower()
    assert "seguridad" not in r.answer.lower()


def test_sin_contradiccion_entre_entidades_distintas():
    e = fresh_engine()
    e.remember(scope(), "Mi sobrino trabaja en seguridad")
    r = e.remember(scope(), "Mi hermana trabaja en Google")
    # "trabaja_en" existe en ambos pero son entity_keys distintos (sobrino vs hermana),
    # no hay contradicción.
    assert r.mode == "saved"
    assert not r.superseded_ids


def test_preguntas_cruzadas_no_mezclan_entidades():
    e = fresh_engine()
    e.remember(scope(), "Mi sobrino trabaja en seguridad")
    e.remember(scope(), "Mi hermana trabaja en Google")

    r_sobrino = e.recall(scope(), "donde trabaja mi sobrino")
    r_hermana = e.recall(scope(), "donde trabaja mi hermana")

    assert r_sobrino.mode == "answer" and "seguridad" in r_sobrino.answer.lower()
    assert r_hermana.mode == "answer" and "google" in r_hermana.answer.lower()


# ---------- Scoping multi-usuario ----------

def test_scope_aislado_entre_usuarios():
    e = fresh_engine()
    sc_a = Scope(tenant_id="user_a", user_id="user_a", project_id="general", book_id="general")
    sc_b = Scope(tenant_id="user_b", user_id="user_b", project_id="general", book_id="general")
    e.remember(sc_a, "Mi sobrino trabaja en seguridad")
    e.remember(sc_b, "Mi sobrino trabaja en Google")

    r_a = e.recall(sc_a, "donde trabaja mi sobrino")
    r_b = e.recall(sc_b, "donde trabaja mi sobrino")
    assert "seguridad" in r_a.answer.lower()
    assert "google" in r_b.answer.lower()
    # Cross-check: user A no ve la memoria de B
    assert "google" not in r_a.answer.lower()
    assert "seguridad" not in r_b.answer.lower()


def test_scope_aislado_entre_proyectos():
    e = fresh_engine()
    sc1 = Scope(tenant_id="t1", user_id="u1", project_id="proj_a", book_id="general")
    sc2 = Scope(tenant_id="t1", user_id="u1", project_id="proj_b", book_id="general")
    e.remember(sc1, "Mi sobrino trabaja en seguridad")
    r1 = e.recall(sc1, "donde trabaja mi sobrino")
    r2 = e.recall(sc2, "donde trabaja mi sobrino")
    assert r1.mode == "answer"
    assert r2.mode == "no_match"


# ---------- Múltiples facts por entry ----------

def test_recall_primera_persona():
    e = fresh_engine()
    e.remember(scope(), "Vivo en Buenos Aires")
    r = e.recall(scope(), "donde vivo")
    assert r.mode == "answer"
    assert "buenos aires" in r.answer.lower()


def test_recall_usa_content_crudo_si_no_hay_facts():
    e = fresh_engine()
    e.remember(scope(), "Me gustan mucho los atardeceres en la playa")
    # Pregunta vagamente relacionada
    r = e.recall(scope(), "qué me gusta")
    # Puede matchear o no según el embedding hash, pero si matchea debe usar content
    if r.mode == "answer":
        assert "atardeceres" in r.answer.lower() or "playa" in r.answer.lower() or "gustan" in r.answer.lower()


# ---------- Wrapper compatible ----------

def test_panel_memory_core_wrapper():
    fresh_engine()
    from app.panel_memory_core import store_panel_manual_memory, panel_chat_fallback

    res = store_panel_manual_memory(
        user_id="u1", project="general", book_id="general",
        content="Mi sobrino trabaja en seguridad",
    )
    assert res["mode"] == "saved"
    assert res["fact"] is not None  # hubo facts

    ans = panel_chat_fallback(
        user_id="u1", project="general", book_id="general",
        message="donde trabaja mi sobrino",
    )
    assert ans is not None
    assert ans["mode"] == "answer"
    assert "seguridad" in ans["answer"].lower()


if __name__ == "__main__":
    # Runner simple sin pytest para CI-less
    import traceback
    tests = [v for k, v in list(globals().items()) if k.startswith("test_")]
    passed = 0
    failed: list[tuple[str, str]] = []
    for t in tests:
        try:
            t()
            print(f"✓ {t.__name__}")
            passed += 1
        except Exception as e:  # noqa: BLE001
            print(f"✗ {t.__name__}: {e}")
            traceback.print_exc()
            failed.append((t.__name__, str(e)))
    print(f"\n{passed}/{len(tests)} pasados")
    if failed:
        raise SystemExit(1)
