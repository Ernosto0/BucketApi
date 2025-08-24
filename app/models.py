from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime

# Authentication Models
class UserCreate(BaseModel):
    email: EmailStr = Field(..., description="Valid email address")
    password: str = Field(..., min_length=6, description="Password must be at least 6 characters")
    password_confirm: str = Field(..., description="Password confirmation")

    @model_validator(mode='after')
    def validate_passwords_match(self):
        if self.password != self.password_confirm:
            raise ValueError('Passwords do not match')
        return self

class UserLogin(BaseModel):
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password")

class User(BaseModel):
    id: str
    email: str
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None

class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: User

class RegisterResponse(BaseModel):
    success: bool
    message: str
    user: User

class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Token

class TokenData(BaseModel):
    username: Optional[str] = None

class UserProfile(BaseModel):
    user: User
    total_apis: int
    saved_apis: List['SavedAPI']
    recent_activity: List[Dict[str, Any]]

# API Generation Models
class ProposalRequest(BaseModel):
    prompt: str = Field(..., description="Description of the API functionality you want")
    user_id: str = Field(..., description="Unique user identifier")
    sample_input: Optional[str] = Field(None, description="Example input data for the API")
    expected_output: Optional[str] = Field(None, description="Expected output format")

class ProposalResponse(BaseModel):
    success: bool
    status: str  # "buildable", "needs_clarification", "modify_request", "not_buildable"
    message: str
    questions: Optional[List[str]] = None
    suggestions: Optional[List[str]] = None
    instructions: Optional[List[str]] = None
    next_steps: Optional[List[str]] = None
    reasons: Optional[List[str]] = None
    original_prompt: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    # Proposal data
    proposal: Optional[Dict[str, Any]] = Field(None, description="The API proposal details including api_name, description, functionality, etc.")
    # Conversation state tracking
    conversation_state: Optional[str] = Field(default="proposal", description="Current conversation state: proposal, code_generated, etc.")
    proposal_id: Optional[str] = Field(None, description="Unique identifier for this proposal session")

class ProposalModificationRequest(BaseModel):
    original_prompt: str = Field(..., description="The original prompt that was analyzed")
    modification_request: str = Field(..., description="What you want to modify about the proposal")
    user_id: str = Field(..., description="Unique user identifier")
    previous_analysis: Optional[str] = Field(None, description="Previous analysis result for context")
    proposal_id: Optional[str] = Field(None, description="Unique identifier for the proposal session being modified")

class ProposalModificationResponse(BaseModel):
    success: bool
    status: str  # "buildable", "needs_clarification", "modify_request", "not_buildable"
    message: str
    modified_prompt: Optional[str] = None
    questions: Optional[List[str]] = None
    suggestions: Optional[List[str]] = None
    instructions: Optional[List[str]] = None
    next_steps: Optional[List[str]] = None
    reasons: Optional[List[str]] = None
    original_prompt: Optional[str] = None
    modification_request: Optional[str] = None
    user_id: Optional[str] = None
    timestamp: Optional[datetime] = None
    # Proposal data (updated proposal after modification)
    proposal: Optional[Dict[str, Any]] = Field(None, description="The updated API proposal details including api_name, description, functionality, etc.")
    # Conversation state tracking
    conversation_state: Optional[str] = Field(default="proposal", description="Current conversation state after modification")
    proposal_id: Optional[str] = Field(None, description="Unique identifier for this proposal session")

class APIGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Description of the API functionality you want")
    sample_input: Optional[str] = Field(None, description="Example input data for the API")
    expected_output: Optional[str] = Field(None, description="Expected output format")
    user_id: str = Field(..., description="Unique user identifier")
    api_name: Optional[str] = Field(None, description="Optional API name (will be auto-generated if not provided)")
    skip_analysis: Optional[bool] = Field(True, description="Skip analysis step (should be done via /generate-proposal endpoint first)")
    use_multi_step: Optional[bool] = Field(True, description="Use multi-step generation process (default: True, returns final code)")
    pipeline_name: Optional[str] = Field("full_pipeline", description="Pipeline to use for multi-step generation")
    proposal_id: Optional[str] = Field(None, description="Proposal ID from which this generation request originates")

class APIGenerationResponse(BaseModel):
    success: bool
    message: str
    endpoint_url: Optional[str] = None
    documentation: Optional[str] = None
    curl_example: Optional[str] = None
    api_slug: Optional[str] = None
    user_id: Optional[str] = None
    generated_at: Optional[datetime] = None
    debug_info: Optional[Dict[str, Any]] = None
    # Conversation state tracking
    conversation_state: Optional[str] = Field(default="code_generated", description="Conversation state after API generation")
    proposal_id: Optional[str] = Field(None, description="Original proposal ID that led to this generation")

# API Modification Models
class APIModificationRequest(BaseModel):
    prompt: str = Field(..., description="Description of what you want to modify in the API (should be validated via /modify-proposal first)")
    api_slug: str = Field(..., description="Slug of the existing API to modify")
    user_id: str = Field(..., description="Unique user identifier")
    sample_input: Optional[str] = Field(None, description="Example input data for the modified API")
    expected_output: Optional[str] = Field(None, description="Expected output format for the modified API")

class APIModificationResponse(BaseModel):
    success: bool
    message: str
    endpoint_url: Optional[str] = None
    documentation: Optional[str] = None
    curl_example: Optional[str] = None
    api_slug: Optional[str] = None
    user_id: Optional[str] = None
    modified_at: Optional[datetime] = None
    original_prompt: Optional[str] = None
    modification_prompt: Optional[str] = None
    debug_info: Optional[Dict[str, Any]] = None

class APIInputData(BaseModel):
    apikey: str
    text: Optional[str] = None


class APIExecutionRequest(BaseModel):
    file_data: Optional[str] = Field(None, description="Base64 encoded file data")
    input_data: Optional[Dict[str, Any]] = Field(None, description="JSON input data")

class APIExecutionResponse(BaseModel):
    success: bool
    result: Optional[Any] = None
    error: Optional[str] = None
    execution_time: Optional[float] = None

class HealthResponse(BaseModel):
    status: str = "healthy"
    timestamp: datetime
    version: str = "1.0.0"

class SavedAPI(BaseModel):
    api_slug: str
    user_id: str
    api_name: str
    prompt: str
    endpoint_url: str
    documentation: str
    curl_example: str
    sample_input: Optional[str] = None
    expected_output: Optional[str] = None
    created_at: datetime
    saved_at: datetime
    is_saved: bool = True

class SaveAPIRequest(BaseModel):
    user_id: str
    api_slug: str
    api_name: str
    prompt: str
    endpoint_url: str
    documentation: str
    curl_example: str
    sample_input: Optional[str] = None
    expected_output: Optional[str] = None

class SaveAPIResponse(BaseModel):
    success: bool
    message: str
    api_slug: str

class ListAPIsResponse(BaseModel):
    success: bool
    user_id: str
    apis: List['SavedAPI']
    count: int

# Authentication Response Models
class AuthResponse(BaseModel):
    success: bool
    message: str
    user: Optional[User] = None

class LoginResponse(BaseModel):
    success: bool
    message: str
    token: Optional[Token] = None

class RegisterResponse(BaseModel):
    success: bool
    message: str
    user: Optional[User] = None 

# Chat Models
class ChatMessage(BaseModel):
    id: str
    user_id: str
    message: str
    response: str
    timestamp: datetime
    analysis_result: Optional[str] = None

class ChatAnalysisRequest(BaseModel):
    user_id: str = Field(..., description="User identifier")
    prompt: str = Field(..., description="User's API request prompt")

class ChatAnalysisResponse(BaseModel):
    success: bool
    user_id: str
    prompt: str
    analysis_result: str
    timestamp: datetime 


# API Key Models
class APIKey(BaseModel):
    id: str
    user_id: str
    key_name: str
    full_key: str 
    is_active: bool = True
    created_at: datetime
    last_used: Optional[datetime] = None
    usage_count: int = 0
    expires_at: Optional[datetime] = None

class CreateAPIKeyRequest(BaseModel):
    key_name: str = Field(..., min_length=1, max_length=100, description="Name for the API key")
    expires_in_days: Optional[int] = Field(None, ge=1, le=365, description="Days until expiration (optional)")

class CreateAPIKeyResponse(BaseModel):
    success: bool
    message: str
    api_key: Optional[str] = None  # Full key only returned once during creation
    key_info: Optional[APIKey] = None

class ListAPIKeysResponse(BaseModel):
    success: bool
    api_keys: List[APIKey]
    count: int

class ListAPIsResponse(BaseModel):
    success: bool
    user_id: str
    apis: List['SavedAPI']
    count: int

class UpdateAPIKeyRequest(BaseModel):
    key_name: Optional[str] = Field(None, min_length=1, max_length=100, description="New name for the API key")
    is_active: Optional[bool] = Field(None, description="Whether the key is active")

class DeleteAPIKeyResponse(BaseModel):
    success: bool
    message: str


# Test Models
class TestRequest(BaseModel):
    user_id: str = Field(..., description="User identifier")
    api_slug: str = Field(..., description="API slug to test")
    test_data: Optional[Dict[str, Any]] = Field(None, description="JSON test data")
    file_data: Optional[str] = Field(None, description="Base64 encoded file data for file uploads")
    file_name: Optional[str] = Field(None, description="Original filename for uploaded file")
    test_type: Optional[str] = Field("manual", description="Type of test: manual, auto, performance")

class TestResponse(BaseModel):
    success: bool
    test_id: str = Field(..., description="Unique test execution ID")
    api_slug: str
    user_id: str
    request_data: Optional[Dict[str, Any]] = None
    response_data: Any = None
    error: Optional[str] = None
    execution_time: float
    status_code: int
    response_headers: Dict[str, str]
    timestamp: datetime
    test_type: str = "manual"
    validation: Optional[Dict[str, Any]] = Field(None, description="AI validation results if validation was requested")

class TestHistoryEntry(BaseModel):
    test_id: str
    api_slug: str
    user_id: str
    test_type: str
    success: bool
    execution_time: float
    status_code: int
    timestamp: datetime
    request_summary: Optional[str] = None
    response_summary: Optional[str] = None

class TestHistoryResponse(BaseModel):
    success: bool
    user_id: str
    api_slug: Optional[str] = None
    tests: List[TestHistoryEntry]
    total_tests: int
    success_rate: float
    average_execution_time: float

class PerformanceTestRequest(BaseModel):
    user_id: str = Field(..., description="User identifier")
    api_slug: str = Field(..., description="API slug to test")
    test_data: Optional[Dict[str, Any]] = Field(None, description="JSON test data")
    iterations: int = Field(10, ge=1, le=100, description="Number of test iterations (1-100)")
    concurrent: bool = Field(False, description="Run tests concurrently")

class PerformanceTestResponse(BaseModel):
    success: bool
    test_id: str
    api_slug: str
    user_id: str
    iterations: int
    concurrent: bool
    total_time: float
    average_time: float
    min_time: float
    max_time: float
    success_rate: float
    failed_tests: int
    timestamp: datetime
    detailed_results: List[Dict[str, Any]]


class Usage(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    service_type: str  # 'claude', 'openai', etc.
    operation_type: str  # 'code_generation', 'code_modification', 'documentation', 'analysis'
    model_name: str  # e.g., 'claude-3-sonnet', 'gpt-4'
    
    # Token usage
    input_tokens: int
    output_tokens: int
    total_tokens: int
    
    # Cost tracking (in USD cents)
    estimated_cost_cents: int
    
    # Request metadata
    prompt_length: int
    response_length: int
    request_duration_ms: int
    
    # Context and debugging
    operation_context: Optional[str] = None  # JSON string with additional context
    api_slug: Optional[str] = None  # Related API if applicable
    
    # Timestamps
    created_at: datetime
    completed_at: Optional[datetime] = None
    
    # Status
    success: bool = True
    error_message: Optional[str] = None

class UsageStatsResponse(BaseModel):
    user_id: str
    total_requests: int
    total_tokens: int
    total_cost_cents: int
    by_service: Dict[str, Dict[str, int]]  # service_type -> stats
    by_operation: Dict[str, Dict[str, int]]  # operation_type -> stats
    recent_usage: List[Usage]
    period_start: datetime
    period_end: datetime

class UsageLimitsResponse(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    daily_token_limit: int
    daily_tokens_used: int
    daily_tokens_remaining: int
    monthly_token_limit: int
    monthly_tokens_used: int
    monthly_tokens_remaining: int
    daily_cost_limit_cents: int
    daily_cost_used_cents: int
    daily_cost_remaining_cents: int
    limit_reset_time: datetime
    is_over_limit: bool
    # New short-term rate limiting fields
    hourly_token_limit: int
    hourly_tokens_used: int
    hourly_tokens_remaining: int
    minutely_request_limit: int
    minutely_requests_used: int
    minutely_requests_remaining: int
    limit_exceeded_reason: Optional[str] = None

class CreateUsageRequest(BaseModel):
    service_type: str
    operation_type: str
    model_name: str
    input_tokens: int = 0
    output_tokens: int = 0
    estimated_cost_cents: int = 0
    prompt_length: int = 0
    response_length: int = 0
    request_duration_ms: int = 0
    operation_context: Optional[str] = None
    api_slug: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None

# API Execution Usage Models
class APIExecutionUsage(BaseModel):
    id: str
    user_id: str
    api_key_id: Optional[str] = None
    api_slug: str
    execution_time_ms: int
    input_data_size: int  # Size of input data in bytes
    output_data_size: int  # Size of output data in bytes
    success: bool
    error_message: Optional[str] = None
    created_at: datetime
    
class APIExecutionUsageRequest(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    api_slug: str
    execution_time_ms: int
    input_data_size: int = 0
    output_data_size: int = 0
    success: bool = True
    error_message: Optional[str] = None

class APIExecutionStatsResponse(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    total_executions: int
    successful_executions: int
    failed_executions: int
    total_execution_time_ms: int
    average_execution_time_ms: float
    total_data_processed_bytes: int
    by_api: Dict[str, Dict[str, int]]  # api_slug -> stats
    recent_executions: List[APIExecutionUsage]
    period_start: datetime
    period_end: datetime

class APIExecutionLimitsResponse(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    daily_execution_limit: int
    daily_executions_used: int
    daily_executions_remaining: int
    monthly_execution_limit: int
    monthly_executions_used: int
    monthly_executions_remaining: int
    daily_data_limit_bytes: int
    daily_data_used_bytes: int
    daily_data_remaining_bytes: int
    limit_reset_time: datetime
    is_over_execution_limit: bool
    is_over_data_limit: bool

class CreateAPIExecutionUsageRequest(BaseModel):
    api_slug: str
    execution_time_ms: int
    input_data_size: int = 0
    output_data_size: int = 0
    success: bool = True
    error_message: Optional[str] = None

# API Pricing and Internal Token Models
class APIMetadata(BaseModel):
    api_slug: str
    user_id: str
    ai_model_used: str  # e.g., 'gpt-3.5-turbo', 'claude-3-sonnet'
    estimated_tokens_per_call: int  # Average tokens used per API call
    estimated_cost_per_call_cents: int  # Cost in cents per API call
    base_complexity: str  # 'simple', 'medium', 'complex'
    created_at: datetime
    last_updated: datetime

# Logging Models
class SystemLog(BaseModel):
    id: str
    timestamp: datetime
    level: str  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    category: str  # HTTP_REQUEST, LLM_CALL, CHAT_MESSAGE, etc.
    message: str
    details: Optional[Dict[str, Any]] = None
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    session_id: Optional[str] = None
    request_id: Optional[str] = None
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    duration_ms: Optional[int] = None
    memory_usage_mb: Optional[float] = None
    error_type: Optional[str] = None
    error_traceback: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None

class HTTPRequestLog(BaseModel):
    id: str
    timestamp: datetime
    request_id: str
    method: str
    endpoint: str
    full_url: Optional[str] = None
    headers: Optional[Dict[str, str]] = None
    query_params: Optional[Dict[str, Any]] = None
    body: Optional[Any] = None
    body_size: Optional[int] = None
    status_code: Optional[int] = None
    response_headers: Optional[Dict[str, str]] = None
    response_body: Optional[Any] = None
    response_size: Optional[int] = None
    duration_ms: Optional[int] = None
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    success: Optional[bool] = None
    error_message: Optional[str] = None

class LLMCallLog(BaseModel):
    id: str
    timestamp: datetime
    request_id: Optional[str] = None
    service_type: str  # 'openai', 'claude'
    model_name: str
    operation_type: str  # 'code_generation', 'documentation', etc.
    system_prompt: Optional[str] = None
    user_prompt: Optional[str] = None
    prompt_length: Optional[int] = None
    response_content: Optional[str] = None
    response_length: Optional[int] = None
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    estimated_cost_cents: Optional[int] = None
    duration_ms: Optional[int] = None
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    api_slug: Optional[str] = None
    success: bool = True
    error_message: Optional[str] = None
    operation_context: Optional[Dict[str, Any]] = None

class ChatMessageLog(BaseModel):
    id: str
    timestamp: datetime
    user_id: str
    session_id: Optional[str] = None
    message_type: str  # 'user_message', 'ai_response', 'system_message'
    content: str
    content_length: Optional[int] = None
    ai_model_used: Optional[str] = None
    response_time_ms: Optional[int] = None
    confidence_score: Optional[float] = None
    conversation_id: Optional[str] = None
    parent_message_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

# Logging API Request/Response Models
class LogsRequest(BaseModel):
    level: Optional[str] = None
    category: Optional[str] = None
    user_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    offset: int = 0

class LogsResponse(BaseModel):
    success: bool
    logs: List[SystemLog]
    total_count: int
    has_more: bool

class HTTPLogsRequest(BaseModel):
    endpoint: Optional[str] = None
    method: Optional[str] = None
    status_code: Optional[int] = None
    user_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    offset: int = 0

class HTTPLogsResponse(BaseModel):
    success: bool
    logs: List[HTTPRequestLog]
    total_count: int
    has_more: bool

class LLMLogsRequest(BaseModel):
    service_type: Optional[str] = None
    model_name: Optional[str] = None
    operation_type: Optional[str] = None
    user_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    offset: int = 0

class LLMLogsResponse(BaseModel):
    success: bool
    logs: List[LLMCallLog]
    total_count: int
    has_more: bool

class ChatLogsRequest(BaseModel):
    user_id: Optional[str] = None
    message_type: Optional[str] = None
    conversation_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    offset: int = 0

class ChatLogsResponse(BaseModel):
    success: bool
    logs: List[ChatMessageLog]
    total_count: int
    has_more: bool

class LogStatisticsResponse(BaseModel):
    success: bool
    period_start: str
    period_end: str
    total_logs: Dict[str, int]
    error_count: int
    statistics: Dict[str, Any]

class InternalToken(BaseModel):
    """Internal tokens for API usage - different from AI model tokens"""
    id: str
    user_id: str
    api_key_id: Optional[str] = None
    token_type: str = "api_execution"  # Type of internal token
    amount: int  # Amount of tokens
    source: str  # 'purchase', 'monthly_allocation', 'bonus'
    expires_at: Optional[datetime] = None
    created_at: datetime
    used_at: Optional[datetime] = None
    is_used: bool = False

class InternalTokenBalance(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    total_tokens: int
    used_tokens: int
    remaining_tokens: int
    monthly_allocation: int
    expires_soon_tokens: int  # Tokens expiring in next 7 days
    last_updated: datetime

class APIExecutionCost(BaseModel):
    api_slug: str
    user_id: str
    cost_per_call_cents: int  # Cost in cents
    internal_tokens_per_call: int  # Internal tokens deducted per call
    ai_model_used: str
    complexity_multiplier: float
    base_cost_cents: int
    estimated_tokens_used: int  # AI model tokens
    last_calculated: datetime

class APIExecutionTokenUsage(BaseModel):
    id: str
    user_id: str
    api_key_id: Optional[str] = None
    api_slug: str
    internal_tokens_used: int
    cost_cents: int
    execution_successful: bool
    created_at: datetime

class EstimateAPIUsageCostRequest(BaseModel):
    api_slug: str
    sample_input: Optional[str] = None
    expected_calls_per_month: int = 100

class EstimateAPIUsageCostResponse(BaseModel):
    api_slug: str
    cost_per_call_cents: int
    internal_tokens_per_call: int
    estimated_monthly_cost_cents: int
    estimated_monthly_tokens: int
    ai_model_used: str
    complexity_rating: str
    breakdown: Dict[str, Any]

class CreateInternalTokenRequest(BaseModel):
    amount: int
    token_type: str = "api_execution"
    source: str = "monthly_allocation"
    expires_in_days: Optional[int] = None

class InternalTokenUsageStatsResponse(BaseModel):
    user_id: str
    api_key_id: Optional[str] = None
    current_balance: InternalTokenBalance
    usage_this_month: int
    cost_this_month_cents: int
    by_api: Dict[str, Dict[str, int]]  # api_slug -> stats
    recent_usage: List[APIExecutionTokenUsage]
    period_start: datetime
    period_end: datetime


class ErrorLog(BaseModel):
    timestamp: datetime
    error_type: str
    error_message: str
    user_id: str
    request_id: str
    api_slug: Optional[str] = None
    model_name: str
    details: Optional[Dict[str, Any]] = None
    success: bool = False

# Retry Logging Models
class RetryLog(BaseModel):
    id: str
    timestamp: datetime
    request_id: str
    original_error_type: str
    original_error_message: str
    attempt_number: int
    max_attempts: int
    retry_delay_seconds: Optional[float] = None
    user_id: Optional[str] = None
    api_key_id: Optional[str] = None
    api_slug: Optional[str] = None
    service_type: str
    model_name: Optional[str] = None
    operation_type: str
    details: Optional[Dict[str, Any]] = None

class RetryLogsRequest(BaseModel):
    service_type: Optional[str] = None
    operation_type: Optional[str] = None
    user_id: Optional[str] = None
    request_id: Optional[str] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
    limit: int = 100
    offset: int = 0

class RetryLogsResponse(BaseModel):
    success: bool
    logs: List[RetryLog]
    total_count: int
    has_more: bool

class RetryStatsResponse(BaseModel):
    success: bool
    period_start: str
    period_end: str
    total_retries: int
    recent_retries_24h: int
    average_attempts_per_request: float
    retries_by_service: Dict[str, int]
    retries_by_operation: Dict[str, int]
    retries_by_error_type: Dict[str, int]
    statistics: Dict[str, Any]

# Multi-Step Generation Models
class MultiStepGenerationRequest(BaseModel):
    user_id: str = Field(..., description="User ID")
    prompt: str = Field(..., description="API description prompt")
    api_name: Optional[str] = Field(None, description="Optional API name")
    sample_input: Optional[str] = Field(None, description="Sample input data")
    expected_output: Optional[str] = Field(None, description="Expected output format")
    pipeline_name: str = Field("full_pipeline", description="Pipeline to use (full_pipeline, simple, analysis_implementation)")
    skip_analysis: bool = Field(False, description="Skip the analysis step")

# MultiStepGenerationResponse removed - multi-step always returns SSE stream

# Removed MultiStepSessionStatusRequest/Response - not needed since streaming is handled directly

class PipelineInfoResponse(BaseModel):
    success: bool
    available_pipelines: Dict[str, Any]
    default_pipeline: str
    step_types: List[str]
    generation_modes: List[str]
   