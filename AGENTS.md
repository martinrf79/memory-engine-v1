# AGENTS.md

## Objetivo del repo
Backend de memoria IA con FastAPI + Firestore, orientado a memoria operativa y recuperación confiable.

## Rama de trabajo
- Trabajar solo sobre `backend-clean`
- No usar `main` para cambios nuevos
- No crear ramas nuevas salvo que se pida explícitamente

## Regla principal
Cada cambio debe mejorar el backend sin romper:
- `tests/test_chat_semantic_memory.py`
- `tests/run_memory_regression.py`
- `app/smoke_test.py`

## Flujo obligatorio
1. Hacer cambio mínimo
2. Correr tests relevantes
3. Ajustar regresión si corresponde
4. Dejar el cambio listo para commit
5. No tocar deploy ni Cloud Run salvo pedido explícito

## Archivos críticos
- `app/chat.py`
- `app/search.py`
- `app/semantic_memory.py`
- `app/manage_memories.py`
- `app/export_memories.py`
- `tests/test_chat_semantic_memory.py`
- `tests/memory_regression_cases.json`
- `tests/run_memory_regression.py`

## Qué no hacer
- No mezclar ramas
- No mover archivos sin necesidad
- No borrar lógica útil existente
- No cambiar workflows salvo pedido explícito
- No tocar Cloud Run
- No inventar resultados de tests

## Qué sí hacer
- Priorizar cambios pequeños y seguros
- Agregar casos de regresión cuando aparezca un nuevo fallo real
- Mejorar primero paráfrasis y recuperación antes que refactors grandes
- Validar por contenido útil, no por texto frágil exacto, salvo que el test lo requiera

## Criterio de aceptación
Un cambio está bien si:
- los tests relevantes quedan verdes
- la regresión pasa
- el cambio es mínimo
- no rompe respuestas ya validadas
- deja el repo listo para push

## Estilo de trabajo esperado
- Explicar breve qué fallaba
- Decir qué archivo tocó
- Decir qué test corrió
- Entregar diff pequeño y claro
