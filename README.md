# Memory Engine Product Clean

Backend base para una memoria por LLM, con foco en guardado útil, recuperación estable, conexión agnóstica y una superficie de producto compatible con **frontend público + backend privado**.

## Qué hace esta base
- Guarda mensajes y recuerdos estructurados.
- Recupera recuerdos por `user_id`, `project` y `book_id`.
- Mantiene una memoria canónica simple y un índice semántico controlado.
- Evita contaminar la memoria con respuestas del asistente.
- Separa la superficie **pública** (`/chat`, `/connection/*`, `/panel/me`) de la superficie **interna** de memoria, oculta por defecto en OpenAPI.
- Deja preparada una capa de conexión agnóstica a proveedores (`chatgpt`, `claude`, `gemini`, `deepseek`, `mock`) sin requerir API key del usuario como condición base.
- Usa Firestore como storage real de producción y FakeFirestore para pruebas locales.

## Superficies del producto
### Pública
- `GET /health`
- `POST /chat`
- `GET /connection/status`
- `POST /connection/connect`
- `POST /connection/disconnect`
- `POST /connection/pause`
- `POST /connection/resume`
- `GET /panel/me`

### Interna / técnica
- rutas `/memories*`
- `GET /admin/health`
- `GET /admin/metrics`

> Las rutas internas siguen disponibles para pruebas y soporte técnico, pero quedan ocultas por defecto de la documentación pública.

## Flujo recomendado
1. Trabajar y probar localmente con `USE_FAKE_FIRESTORE=true`.
2. Correr la validación completa local con `./scripts/validate_local.sh`.
3. Recién después subir a GitHub y dejar que corra CI.
4. Si CI queda verde, desplegar en Cloud Run.

## Validación local completa
```bash
export USE_FAKE_FIRESTORE=true
export PYTHONPATH=.
./scripts/validate_local.sh
```

## Qué valida la suite local
- guardado y recuperación semántica base;
- paráfrasis positivas y negativas;
- formato de resumen;
- CRUD local de memorias;
- búsqueda con normalización de acentos;
- auditoría local de memorias contaminadas;
- regresión de casos reales;
- smoke test extremo a extremo;
- ciclo de conexión `/connection/*`;
- ocultamiento de rutas internas en OpenAPI.

## Ejecutar local
```bash
export USE_FAKE_FIRESTORE=true
uvicorn app.main:app --reload
```

## Notas
- Esta base prioriza simplicidad, estabilidad y recuperación útil por encima de complejidad temprana.
- Firestore real queda disponible para producción; en pruebas se usa FakeFirestore.
- Los tests `*_api.py` quedaron marcados como `external_api` y no se ejecutan por defecto en `pytest`; sirven para comprobar un backend ya desplegado.
- La privacidad elegida para esta etapa es: **frontend público + backend privado**, sin visor normal de memoria para usuario ni para administración.


## Frontend público

La versión actual incluye un panel web mínimo en `/ui/` con acceso simple, estado de memoria, conexión de proveedor y una prueba rápida del endpoint `/chat`. El login definitivo queda preparado para conectarse más adelante a un sistema de autenticación real.


## Conectores y bridges

El backend expone una capa de bridge preparada para proveedores de LLM en `/bridge/*`.

- `GET /bridge/providers` lista proveedores previstos.
- `GET /bridge/{provider}/bootstrap` devuelve instrucciones y herramientas.
- `GET /bridge/{provider}/manifest` devuelve un manifiesto simple del bridge.
- `POST /bridge/{provider}/tool-call` ejecuta herramientas como `memory_chat`.

Esta capa deja previsto el uso por MCP, function calling o bridges HTTP sin atar el núcleo de memoria a un proveedor único.
