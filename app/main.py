from fastapi import FastAPI

from app.db import Base, engine
from app.manage_memories import router as manage_memories_router
from app.memories import router as memories_router
from app.search import router as search_router

app = FastAPI(
    title="Memory Engine V1",
    version="0.1.0",
)


@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok"}


app.include_router(memories_router)
app.include_router(search_router)
app.include_router(manage_memories_router)
