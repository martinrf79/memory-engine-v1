from datetime import datetime, timezone
from uuid import uuid4


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_memory_id() -> str:
    return str(uuid4())
