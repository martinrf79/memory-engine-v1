# Validation Report — v9 product hardening

## Technical adjustments completed
1. Product docs disabled by default in production (`/docs`, `/openapi.json`, `/redoc`).
2. Internal memory routes protected; visible in local/testing only.
3. Admin panel disabled by default unless explicitly enabled.
4. Session upgraded to HttpOnly cookie with rolling refresh on authenticated requests.
5. Frontend no longer depends on localStorage/sessionStorage for session state.
6. Frontend route guard added (`#/login` / `#/dashboard`) with safe fallback after logout and pageshow.
7. Connector UX hardened with `connecting`, `connected`, `paused`, `timeout`, `error`, `unavailable`, `session_expired` states.
8. Public bridge tool calls protected with per-connection bridge token.
9. Security headers tightened (`CSP`, `Permissions-Policy`, `Cache-Control`, `Vary`, `X-Frame-Options`, `nosniff`).
10. Product bootstrap endpoint added to reduce brittle client orchestration and keep project/provider loading server-backed.

## Local validation
- `pytest -q` → **79 passed, 7 deselected**
- `python tests/run_memory_regression.py` → **OK**
- `python app/smoke_test.py` → **OK**
- `python -m compileall -q app tests frontend` → **OK**

## Remaining items before final real-world frontend test
- Deploy with **frontend public + backend private** in Cloud Run.
- Wire a production identity provider if desired (Firebase Auth or equivalent), replacing the current built-in auth when ready.
- Run browser/devtools/mobile checks against the deployed build.
- Integrate real provider authorization/OAuth where the chosen LLM flow requires it.
