from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserLLMSettings(BaseModel):
    user_id: str
    provider: str = "mock"
    model_name: str = "mock-model"
    is_enabled: bool = True
    system_prompt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
