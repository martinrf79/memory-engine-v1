from datetime import datetime
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from app.enums import MemoryStatus, MemoryType

NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
OptionalNonEmptyStr = Annotated[Optional[str], StringConstraints(strip_whitespace=True, min_length=1)]


class MemoryBase(BaseModel):
    user_id: NonEmptyStr
    project: NonEmptyStr
    book_id: NonEmptyStr
    memory_type: MemoryType
    status: MemoryStatus = MemoryStatus.active
    content: NonEmptyStr
    summary: NonEmptyStr
    user_message: NonEmptyStr
    assistant_answer: NonEmptyStr
    trigger_query: NonEmptyStr
    importance: Optional[int] = None
    keywords_json: Optional[str] = None
    embedding_json: Optional[str] = None
    source: Optional[str] = None
    created_at: str
    updated_at: Optional[str] = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def validate_datetime_string(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be a valid ISO 8601 datetime") from exc

        return parsed.isoformat().replace("+00:00", "Z")


class MemoryCreate(MemoryBase):
    id: NonEmptyStr


class MemoryUpdate(BaseModel):
    project: OptionalNonEmptyStr = None
    book_id: OptionalNonEmptyStr = None
    memory_type: Optional[MemoryType] = None
    status: Optional[MemoryStatus] = None
    content: OptionalNonEmptyStr = None
    summary: OptionalNonEmptyStr = None
    user_message: OptionalNonEmptyStr = None
    assistant_answer: OptionalNonEmptyStr = None
    trigger_query: OptionalNonEmptyStr = None
    importance: Optional[int] = None
    keywords_json: Optional[str] = None
    embedding_json: Optional[str] = None
    source: Optional[str] = None
    updated_at: Optional[str] = None

    @field_validator("updated_at")
    @classmethod
    def validate_updated_at(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return value

        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("must be a valid ISO 8601 datetime") from exc

        return parsed.isoformat().replace("+00:00", "Z")


class MemoryResponse(MemoryBase):
    id: str

    model_config = ConfigDict(from_attributes=True)


class SemanticMemoryBase(BaseModel):
    user_id: NonEmptyStr
    project: NonEmptyStr
    book_id: NonEmptyStr
    memory_type: NonEmptyStr
    entity: NonEmptyStr
    attribute: NonEmptyStr
    value_text: NonEmptyStr
    context: Optional[str] = None
    status: MemoryStatus = MemoryStatus.active
    dedupe_key: NonEmptyStr
    version: int = 1
    valid_from: NonEmptyStr
    valid_to: Optional[str] = None
    source_type: NonEmptyStr
    source_event_id: NonEmptyStr
    created_at: NonEmptyStr
    updated_at: Optional[str] = None


class SemanticMemoryResponse(SemanticMemoryBase):
    id: str


class ChatEventBase(BaseModel):
    user_id: NonEmptyStr
    project: NonEmptyStr
    book_id: NonEmptyStr
    user_message: NonEmptyStr
    assistant_answer: NonEmptyStr
    llm_provider: NonEmptyStr
    llm_model: NonEmptyStr
    created_at: NonEmptyStr
    ttl_at: Optional[str] = None


class ChatEventResponse(ChatEventBase):
    id: str


class ConnectionRequest(BaseModel):
    user_id: NonEmptyStr
    provider: NonEmptyStr
    project: OptionalNonEmptyStr = None
    bridge_mode: OptionalNonEmptyStr = None
    model_name: OptionalNonEmptyStr = None


class ConnectionStatusResponse(BaseModel):
    user_id: str
    provider: str
    model_name: str
    bridge_mode: str
    status: str
    requires_user_api_key: bool
    supports_remote_chat: bool
    supports_mcp: bool
    supports_function_calling: bool
    bridge_token: Optional[str] = None
    mcp_connector_url: Optional[str] = None
    mcp_sse_url: Optional[str] = None
    mcp_http_url: Optional[str] = None
    mcp_messages_url: Optional[str] = None
    bridge_manifest_url: Optional[str] = None
    bridge_tool_call_url: Optional[str] = None
    tool_calling_manifest_url: Optional[str] = None
    tool_calling_call_url: Optional[str] = None




class ProviderMetadata(BaseModel):
    provider: str
    default_model: str
    bridge_mode: str
    requires_user_api_key: bool
    supports_remote_chat: bool
    supports_mcp: bool
    supports_function_calling: bool


class ProviderCatalogResponse(BaseModel):
    providers: list[ProviderMetadata]

class PanelMeResponse(BaseModel):
    user_id: str
    panel_mode: str
    memory_enabled: bool
    connection: ConnectionStatusResponse


class ProjectSummary(BaseModel):
    id: str
    project: str
    status: str


class PanelBootstrapResponse(BaseModel):
    me: PanelMeResponse
    projects: list[ProjectSummary]
    providers: list[ProviderMetadata]


class AdminHealthResponse(BaseModel):
    status: str
    panel_mode: str
    counts: dict[str, int]


class AdminMetricsResponse(BaseModel):
    counts: dict[str, int]
    public_surface: list[str]
    private_surface: list[str]


class ConnectorCheckEntry(BaseModel):
    provider: str
    supports_mcp: bool
    supports_function_calling: bool
    bridge_mode: str
    active_connection: bool
    connection_status: str | None = None
    status: str
    issues: list[str]
    urls: dict[str, str]


class ConnectorSelfCheckResponse(BaseModel):
    status: str
    user_id: str | None = None
    checks: list[ConnectorCheckEntry]


class MaintenanceIssue(BaseModel):
    kind: str
    collection: str
    doc_id: str
    severity: str
    provider: str | None = None
    missing: list[str] | None = None


class MaintenanceVerifyResponse(BaseModel):
    status: str
    counts: dict[str, int]
    issues: list[MaintenanceIssue]
    safe_actions: list[str]


class BridgeToolParameter(BaseModel):
    name: str
    type: str
    required: bool
    description: str


class BridgeToolDefinition(BaseModel):
    name: str
    description: str
    parameters: list[BridgeToolParameter]


class BridgeInstruction(BaseModel):
    step: int
    title: str
    detail: str


class BridgeProviderInfo(BaseModel):
    provider: str
    display_name: str
    bridge_mode: str
    supports_remote_chat: bool
    supports_mcp: bool
    supports_function_calling: bool
    requires_user_api_key: bool
    default_model: str
    connection_summary: str


class BridgeBootstrapResponse(BridgeProviderInfo):
    instructions: list[BridgeInstruction]
    tools: list[BridgeToolDefinition]
    bridge_endpoint: str
    manifest_endpoint: str


class BridgeToolCallRequest(BaseModel):
    user_id: NonEmptyStr
    tool_name: NonEmptyStr
    arguments: dict = {}


class BridgeToolCallResponse(BaseModel):
    provider: str
    tool_name: str
    ok: bool
    result: Optional[dict] = None
    error: Optional[str] = None


class ProducerCreate(BaseModel):
    project: NonEmptyStr
    name: NonEmptyStr
    producer_id: OptionalNonEmptyStr = None
    segment: Optional[str] = None
    country: Optional[str] = None
    consent_scope: Optional[str] = "base_directory"
    onboarding_status: Optional[str] = "lead"
    notes: Optional[str] = None


class ProducerResponse(BaseModel):
    id: str
    user_id: str
    project: str
    name: str
    segment: Optional[str] = None
    country: Optional[str] = None
    consent_scope: str
    onboarding_status: str
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class ProductCreate(BaseModel):
    project: NonEmptyStr
    producer_id: NonEmptyStr
    name: NonEmptyStr
    product_id: OptionalNonEmptyStr = None
    category: Optional[str] = None
    premium_tier: Optional[str] = None
    export_target: Optional[str] = None
    next_step: Optional[str] = None
    notes: Optional[str] = None


class ProductResponse(BaseModel):
    id: str
    user_id: str
    project: str
    producer_id: str
    name: str
    category: Optional[str] = None
    premium_tier: Optional[str] = None
    export_target: Optional[str] = None
    next_step: Optional[str] = None
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class PassportUpsert(BaseModel):
    project: NonEmptyStr
    product_id: NonEmptyStr
    passport_type: str = "product"
    status: str = "draft"
    required_fields: list[str] = Field(default_factory=list)
    completed_fields: list[str] = Field(default_factory=list)
    missing_documents: list[str] = Field(default_factory=list)
    next_step: Optional[str] = None
    export_ready: bool = False
    notes: Optional[str] = None


class PassportResponse(BaseModel):
    id: str
    user_id: str
    project: str
    product_id: str
    passport_type: str
    status: str
    required_fields: list[str]
    completed_fields: list[str]
    missing_documents: list[str]
    next_step: Optional[str] = None
    export_ready: bool
    notes: Optional[str] = None
    created_at: str
    updated_at: str


class DocumentCreate(BaseModel):
    project: NonEmptyStr
    product_id: NonEmptyStr
    document_type: NonEmptyStr
    title: NonEmptyStr
    status: str = "missing"
    url: Optional[str] = None


class DocumentResponse(BaseModel):
    id: str
    user_id: str
    project: str
    product_id: str
    document_type: str
    title: str
    status: str
    url: Optional[str] = None
    created_at: str
    updated_at: str


class PassportSummaryResponse(BaseModel):
    product_id: str
    product_name: str
    passport_type: str
    status: str
    export_ready: bool
    missing_items: list[str]
    next_step: Optional[str] = None
    trace_ids: list[str] = Field(default_factory=list)


class AccessRequestCreate(BaseModel):
    project: NonEmptyStr
    target_type: str = Field(pattern="^(memory|passport)$")
    target_id: NonEmptyStr
    reason: NonEmptyStr
    scope: str = Field(default="masked", pattern="^(masked|raw)$")


class AccessRequestReview(BaseModel):
    request_id: NonEmptyStr
    approved: bool
    reviewer: NonEmptyStr
    note: Optional[str] = None


class AccessRequestResponse(BaseModel):
    id: str
    user_id: str
    project: str
    target_type: str
    target_id: str
    reason: str
    scope: str
    status: str
    created_at: str
    updated_at: str
    reviewed_by: Optional[str] = None
    review_note: Optional[str] = None


class MCPToolArgumentSchema(BaseModel):
    name: str
    type: str
    required: bool
    description: str


class MCPToolSchema(BaseModel):
    name: str
    description: str
    arguments: list[MCPToolArgumentSchema]


class MCPManifestResponse(BaseModel):
    server_name: str
    server_version: str
    protocol: str
    auth: str
    tools: list[MCPToolSchema]


class MCPToolCallRequest(BaseModel):
    tool_name: NonEmptyStr
    arguments: dict = {}


class MCPToolCallResponse(BaseModel):
    ok: bool
    tool_name: str
    result: Optional[dict] = None
    error: Optional[str] = None


class MemoryCoreSearchResponse(BaseModel):
    items: list[dict]
    trace_id: str


class MemoryCoreFetchResponse(BaseModel):
    items: list[dict]


class MemoryCoreBooksResponse(BaseModel):
    books: list[str]
