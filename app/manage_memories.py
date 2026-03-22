from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.dependencies import get_db
from app.models import Memory
from app.schemas import MemoryResponse, MemoryUpdate
from app.utils import utc_now_iso

router = APIRouter()


@router.patch("/memories/{memory_id}", response_model=MemoryResponse)
def update_memory(memory_id: str, payload: MemoryUpdate, db: Session = Depends(get_db)):
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    updates = payload.model_dump(exclude_unset=True)

    if "updated_at" not in updates:
        updates["updated_at"] = utc_now_iso()

    for field, value in updates.items():
        setattr(memory, field, value)

    db.commit()
    db.refresh(memory)
    return memory


@router.post("/memories/{memory_id}/archive", response_model=MemoryResponse)
def archive_memory(memory_id: str, db: Session = Depends(get_db)):
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    memory.status = "archived"
    memory.updated_at = utc_now_iso()

    db.commit()
    db.refresh(memory)
    return memory


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, db: Session = Depends(get_db)):
    memory = db.query(Memory).filter(Memory.id == memory_id).first()
    if not memory:
        raise HTTPException(status_code=404, detail="Memory not found")

    db.delete(memory)
    db.commit()
    return {"status": "deleted", "id": memory_id}
