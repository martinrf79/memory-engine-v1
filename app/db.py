from app.config import settings

try:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import declarative_base, sessionmaker
except Exception:  # pragma: no cover - local fallback for environments without SQLAlchemy
    class _DummyMeta:
        def create_all(self, bind=None):  # noqa: ARG002
            return None

    class _DummyBase:
        metadata = _DummyMeta()

    def sessionmaker(*args, **kwargs):  # noqa: ARG001, ANN001
        return None

    engine = None
    SessionLocal = None
    Base = _DummyBase()
else:
    connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
    engine = create_engine(settings.database_url, connect_args=connect_args)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()
