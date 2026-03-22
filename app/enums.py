from enum import Enum


class MemoryType(str, Enum):
    note = "note"
    fact = "fact"
    conversation = "conversation"
    task = "task"
    decision = "decision"
    product = "product"
    producer = "producer"


class MemoryStatus(str, Enum):
    active = "active"
    archived = "archived"
