from sqlalchemy import Column, Integer, String, Text

from app.db import Base


class Memory(Base):
    __tablename__ = "memories"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, nullable=False, index=True)
    project = Column(String, nullable=False, index=True)
    book_id = Column(String, nullable=False, index=True)
    memory_type = Column(String, nullable=False, index=True)
    status = Column(String, nullable=False, default="active", index=True)

    content = Column(Text, nullable=False)
    summary = Column(Text, nullable=False)
    user_message = Column(Text, nullable=False)
    assistant_answer = Column(Text, nullable=False)
    trigger_query = Column(Text, nullable=False)

    importance = Column(Integer, nullable=True)
    keywords_json = Column(Text, nullable=True)
    embedding_json = Column(Text, nullable=True)
    source = Column(String, nullable=True)
    created_at = Column(String, nullable=False, index=True)
    updated_at = Column(String, nullable=True)
