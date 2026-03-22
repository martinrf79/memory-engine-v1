from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Memory
from app.schemas import MemoryCreate, MemoryResponse
from app.utils import utc_now_iso

router = APIRouter()


@router.post("/memories", response_model=MemoryResponse)
def create_memory(payload: MemoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Memory).filter(Memory.id == payload.id).first()
    if existing:
        raise HTTPException(status_code=400, detail="Memory with this id already exists")

    data = payload.model_dump()

    if not data.get("created_at"):
        data["created_at"] = utc_now_iso()

    memory = Memory(**data)
    db.add(memory)
    db.commit()
    db.refresh(memory)
    return memory


@router.get("/memories", response_model=list[MemoryResponse])
def list_memories(db: Session = Depends(get_db)):
    return db.query(Memory).all()
