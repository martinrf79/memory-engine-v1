# Generalized Memory Backend

Esta versión amplía el backend para que el mismo núcleo sirva tanto para memoria conversacional como para flujos de producto/pasaporte.

## Capas nuevas
- `producers`: productores / fabricantes con consentimiento y estado de onboarding.
- `products`: productos asociados al productor, con objetivo de exportación y próximo paso.
- `passports`: estado estructurado del pasaporte digital o de exportación.
- `documents`: documentos por producto.
- `retrieval_traces`: rastros explicables de cómo se armó una respuesta estructurada.
- `access_requests`: circuito de acceso excepcional a memoria o pasaporte en modo soporte.

## Privacidad
- El uso normal del panel no expone memoria cruda.
- El acceso a memoria cruda requiere:
  1. solicitud explícita
  2. aprobación interna
  3. scope `raw`

## Chat
El endpoint `/chat` y el panel ahora pueden responder de forma determinista preguntas sobre:
- faltantes de pasaporte
- estado del pasaporte
- próximo paso del producto

Estas respuestas se construyen desde estado estructurado, no desde memoria difusa.

## Validación
- Suite base local: `93 passed, 7 deselected`
- Nuevas pruebas: flujo productor/producto/pasaporte, trazas y acceso excepcional.
