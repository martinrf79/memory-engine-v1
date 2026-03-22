from fastapi import FastAPI

from app.db import Base, engine
from app.memories import router as memories_router

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
