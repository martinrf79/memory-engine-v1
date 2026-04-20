from app.config import settings
from app.firestore_store import projects_collection, users_collection
from app.utils import utc_now_iso


def ensure_user_record(user_id: str) -> None:
    doc = users_collection.document(user_id)
    snapshot = doc.get()
    now = utc_now_iso()
    if snapshot.exists:
        doc.update({"updated_at": now})
        return
    doc.set(
        {
            "id": user_id,
            "user_id": user_id,
            "created_at": now,
            "updated_at": now,
            "memory_enabled": True,
            "panel_mode": settings.panel_mode,
        }
    )


def ensure_project_record(user_id: str, project: str | None) -> None:
    if not project:
        return
    project_id = f"{user_id}:{project}"
    doc = projects_collection.document(project_id)
    snapshot = doc.get()
    now = utc_now_iso()
    if snapshot.exists:
        doc.update({"updated_at": now, "status": "active"})
        return
    doc.set(
        {
            "id": project_id,
            "user_id": user_id,
            "project": project,
            "created_at": now,
            "updated_at": now,
            "status": "active",
        }
    )


def touch_user_project(user_id: str, project: str | None) -> None:
    ensure_user_record(user_id)
    ensure_project_record(user_id, project)
