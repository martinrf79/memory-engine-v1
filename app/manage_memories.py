from fastapi import APIRouter, Depends

from app.config import settings
from app.core_legacy_adapter import archive_legacy_memory, delete_legacy_memory, update_legacy_memory
from app.dependencies import require_internal_access
from app.seed_operational_memories import seed_operational_memories
from app.semantic_memory import audit_semantic_memories
from app.schemas import MemoryUpdate

router = APIRouter(include_in_schema=settings.expose_internal_routes, tags=["internal"], dependencies=[Depends(require_internal_access)])


@router.patch("/memories/{memory_id}")
def update_memory(memory_id: str, payload: MemoryUpdate):
    return update_legacy_memory(memory_id, payload.model_dump(exclude_unset=True))


@router.post("/memories/{memory_id}/archive")
def archive_memory(memory_id: str):
    return archive_legacy_memory(memory_id)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str):
    return delete_legacy_memory(memory_id)


@router.post("/memories/audit")
def audit_memories(dry_run: bool = True):
    findings = audit_semantic_memories(dry_run=dry_run)
    return {"dry_run": dry_run, "findings": findings}


@router.post("/memories/seed-operational")
def seed_memories(user_id: str = "martin", project: str = "memoria-guia", book_id: str = "general"):
    items = seed_operational_memories(user_id=user_id, project=project, book_id=book_id)
    return {"count": len(items), "items": items}
