from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.auth import router as auth_router
from app.bridges import router as bridges_router
from app.chat import router as chat_router
from app.config import settings
from app.connections import admin_router, router as connections_router
from app.knowledge_core import internal_router as knowledge_internal_router, router as knowledge_router
from app.db import Base, engine
from app.export_memories import router as export_memories_router
from app.manage_memories import router as manage_memories_router
from app.memories import router as memories_router
from app.mcp import router as mcp_router
from app.search import router as search_router
from app.tool_calling import router as tool_calling_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    yield


def create_app() -> FastAPI:
    docs_url = "/docs" if settings.expose_product_docs else None
    openapi_url = "/openapi.json" if settings.expose_product_docs else None
    redoc_url = "/redoc" if settings.expose_product_docs else None

    app = FastAPI(
        title="Memory Engine V1",
        version="0.4.0",
        lifespan=lifespan,
        docs_url=docs_url,
        openapi_url=openapi_url,
        redoc_url=redoc_url,
        openapi_tags=[
            {"name": "public", "description": "Superficie pública del producto."},
            {"name": "admin", "description": "Superficie técnica interna."},
            {"name": "internal", "description": "Rutas internas de memoria, ocultas por defecto."},
        ],
    )

    @app.middleware("http")
    async def add_safe_headers(request: Request, call_next):
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/ui") or path.startswith("/auth") or path.startswith("/panel"):
            response.headers.setdefault("Cache-Control", "no-store, max-age=0")
            response.headers.setdefault("Pragma", "no-cache")
            response.headers.setdefault("Expires", "0")
            response.headers.setdefault("Vary", "Cookie")
        if getattr(request.state, "session_clear", False):
            response.delete_cookie(key=settings.session_cookie_name, path="/")
        session_refresh = getattr(request.state, "session_refresh", None)
        if session_refresh:
            response.set_cookie(
                key=settings.session_cookie_name,
                value=session_refresh["session_id"],
                httponly=True,
                secure=settings.session_cookie_secure,
                samesite="lax",
                max_age=settings.session_duration_seconds,
                expires=settings.session_duration_seconds,
                path="/",
            )
        response.headers.setdefault("Referrer-Policy", "same-origin")
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'",
        )
        return response

    @app.get("/health", tags=["public"])
    def health():
        return {"status": "ok", "surface": "public", "env": settings.app_env}

    app.include_router(auth_router)
    app.include_router(connections_router)
    app.include_router(bridges_router)
    app.include_router(admin_router)
    app.include_router(memories_router)
    app.include_router(search_router)
    app.include_router(manage_memories_router)
    app.include_router(export_memories_router)
    app.include_router(chat_router)
    app.include_router(mcp_router)
    app.include_router(tool_calling_router)
    app.include_router(knowledge_router)
    app.include_router(knowledge_internal_router)

    @app.get("/", include_in_schema=False)
    def root_redirect():
        return RedirectResponse(url="/ui/")

    frontend_dir = Path("frontend")
    if frontend_dir.exists():
        app.mount("/ui", StaticFiles(directory=str(frontend_dir), html=True), name="ui")

    return app


app = create_app()

app.add_middleware(CORSMiddleware, allow_origins=["https://chatgpt.com"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])
