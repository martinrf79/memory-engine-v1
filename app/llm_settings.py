from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserLLMSettings(BaseModel):
    user_id: str
    provider: str = "mock"
    model_name: str = "mock-model"
    bridge_mode: str = "internal"
    connection_status: str = "not_connected"
    is_enabled: bool = True
    requires_user_api_key: bool = False
    supports_remote_chat: bool = False
    supports_mcp: bool = False
    supports_function_calling: bool = False
    system_prompt: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)
