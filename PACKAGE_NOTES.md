# Package Notes

Este paquete fue limpiado y adaptado para subirse como base más estable del backend.

## Cambios incluidos
- Remoción de `__pycache__` y `.pytest_cache` del paquete final.
- Workflow de CI alineado con la validación local real.
- `README.md` ampliado con validación local completa y flujo recomendado.
- `.env.example` agregado.
- `scripts/validate_local.sh` agregado como punto único de validación.
- `pytest.ini` agregado para separar pruebas locales y externas.
- `tests/conftest.py` agregado para que el paquete sea portable en pruebas.
- `tests/test_robustness.py` agregado para paráfrasis y negaciones.
- `tests/test_summary_format.py` agregado para formato de resumen.
- `tests/test_hardening_suite.py` agregado para CRUD local, búsqueda, auditoría e idempotencia.
- `tests/test_generated_matrix.py` agregado para matriz generada de lenguaje.
- `tests/run_memory_regression.py` y `tests/memory_regression_cases.json` ampliados.
- Mejoras de extracción, consulta semántica y búsqueda accent-insensitive.
- Soporte de `.where()` en FakeFirestore para pruebas más realistas.
- Tests externos de Cloud Run marcados como `external_api` para no mezclarlos con la suite local.

## Validación ejecutada
```bash
PYTHONPATH=. USE_FAKE_FIRESTORE=true ./scripts/validate_local.sh
PYTHONPATH=. USE_FAKE_FIRESTORE=true python -m compileall -q app tests
```

## Estado de la suite local
- 64 pruebas locales pasando
- 7 pruebas externas excluidas por defecto
- regresión local OK
- smoke test OK
- compileall OK
