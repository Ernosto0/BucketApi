from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import Optional, Dict, Any, List
from datetime import datetime
from enum import Enum

# Authentication Models (moved to models_auth.py for new system)
# Import new auth models
from .models_auth import User, UserLogin, LoginResponse, UserProfile, AuthResponse

# Database Connection Models
class DatabaseType(str, Enum):
    """Supported database types for API generation"""
    POSTGRESQL = "postgresql"
    MONGODB = "mongodb"

class DatabaseConfig(BaseModel):
    """Configuration for database connection in generated APIs"""
    enabled: bool = Field(default=False, description="Whether database integration is enabled")
    db_type: Optional[DatabaseType] = Field(None, description="Type of database (postgresql or mongodb)")
    host: Optional[str] = Field(None, description="Database host address")
    port: Optional[int] = Field(None, description="Database port number")
    database_name: Optional[str] = Field(None, description="Name of the database")
    username: Optional[str] = Field(None, description="Database username")
    password: Optional[str] = Field(None, description="Database password (base64 encoded when stored)")
    connection_string: Optional[str] = Field(None, description="Full connection URL (alternative to individual fields)")

class TestDatabaseConnectionRequest(BaseModel):
    """Request model for testing database connection"""
    db_type: DatabaseType = Field(..., description="Type of database to connect to")
    host: str = Field(..., description="Database host address")
    port: int = Field(..., description="Database port number")
    database_name: str = Field(..., description="Name of the database")
    username: str = Field(..., description="Database username")
    password: str = Field(..., description="Database password")

class TestDatabaseConnectionResponse(BaseModel):
    """Response model for database connection test"""
    success: bool = Field(..., description="Whether the connection was successful")
    message: str = Field(..., description="Connection test result message")
    db_type: DatabaseType = Field(..., description="Type of database tested")
    connection_time_ms: Optional[float] = Field(None, description="Connection time in milliseconds")

# API Generation Models
class ProposalRequest(BaseModel):
    prompt: str = Field(..., description="Description of the API functionality you want")
    user_id: str = Field(..., description="Unique user identifier")
    sample_input: Optional[str] = Field(None, description="Example input data for the API")
    expected_output: Optional[str] = Field(None, description="Expected output format")
    database_config: Optional[DatabaseConfig] = Field(None, description="Optional database configuration for database-aware proposals")

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
    current_proposal: Optional[Dict[str, Any]] = Field(None, description="The current proposal data to be modified")

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
    database_config: Optional[DatabaseConfig] = Field(None, description="Database connection configuration for APIs with database integration")

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
    mongodb_status: Optional[str] = None

class APIVersion(BaseModel):
    version: int
    created_at: datetime
    prompt: str
    endpoint_url: str
    commit_message: Optional[str] = None
    code_path: Optional[str] = None  # Path relative to safe_base_path
    
class SavedAPI(BaseModel):
    api_slug: str
    user_id: str
    api_name: str
    prompt: str
    endpoint_url: str
    documentation: str
    curl_example: str
    openapi_spec: Optional[str] = None  # JSON string of OpenAPI spec
    sample_input: Optional[str] = None
    expected_output: Optional[str] = None
    database_config: Optional[DatabaseConfig] = None  # Database connection configuration
    code: Optional[str] = None  # Full source code of the API (backup for ephemeral storage)
    created_at: datetime
    saved_at: datetime
    is_saved: bool = True
    
    # Versioning
    current_version: int = 1
    versions: List[APIVersion] = []

class SaveAPIRequest(BaseModel):
    user_id: str
    api_slug: str
    api_name: str
    prompt: str
    endpoint_url: str
    documentation: str
    curl_example: str
    openapi_spec: Optional[str] = None  # JSON string of OpenAPI spec
    sample_input: Optional[str] = None
    expected_output: Optional[str] = None
    database_config: Optional[DatabaseConfig] = None  # Database connection configuration
    # Optional: allow callers (like API generation flow) to include the code directly.
    # This is important for deployments where generated_apis/ is ephemeral.
    code: Optional[str] = None

class SaveAPIResponse(BaseModel):
    success: bool
    message: str
    api_slug: str

class GenerateDocumentationRequest(BaseModel):
    user_id: str
    api_slug: str

class GenerateDocumentationResponse(BaseModel):
    success: bool
    message: str
    api_slug: str
    documentation: Optional[str] = None

class ListAPIsResponse(BaseModel):
    success: bool
    user_id: str
    apis: List['SavedAPI']
    count: int

# Authentication Response Models
# Auth response models moved to models_auth.py 

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

class MessageIntentRequest(BaseModel):
    message: str = Field(..., description="The message to classify")
    context: str = Field(default="general", description="Context for classification (e.g., 'user_has_api_proposal')")

class MessageIntentResponse(BaseModel):
    success: bool
    intent: str  # "modification", "conversational", "unclear"
    confidence: float = Field(default=0.0, description="Confidence score from 0.0 to 1.0")
    reasoning: Optional[str] = Field(None, description="Brief explanation of the classification")

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
    estimated_cost_cents: float
    
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
    estimated_cost_cents: float = 0
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

# API Generation Usage Models
class APIGenerationUsage(BaseModel):
    id: str
    user_id: str
    api_key_id: Optional[str]
    api_slug: str
    generation_model: str
    prompt: str
    success: bool
    error_message: Optional[str]
    created_at: datetime

class APIGenerationLimitsResponse(BaseModel):
    is_over_limit: bool
    monthly_generation_limit: int
    monthly_generations_used: int
    monthly_generations_remaining: int
    limit_reset_time: datetime
    limit_exceeded_reason: Optional[str]
    subscription_tier: str
    # Additional token limit information
    daily_token_limit: Optional[int] = None
    daily_tokens_used: Optional[int] = None
    daily_tokens_remaining: Optional[int] = None
    token_limit_exceeded: Optional[bool] = None

# API Pricing and Internal Token Models
class APIMetadata(BaseModel):
    api_slug: str
    user_id: str
    ai_model_used: str  # DEPRECATED: Use execution_model_used instead
    estimated_tokens_per_call: int  # Average tokens used per API call
    estimated_cost_per_call_cents: float  # Cost in cents per API call (fractional cents supported)
    base_complexity: str  # 'simple', 'medium', 'complex'
    created_at: datetime
    last_updated: datetime
    
    # New fields to separate generation vs execution models
    generation_model_used: Optional[str] = None  # Model used to generate the API code
    execution_model_used: Optional[str] = None   # Model used by the API when it executes
    
    # Real usage data fields
    real_avg_tokens_per_call: Optional[int] = None
    real_avg_cost_per_call_cents: Optional[float] = None
    real_model_used: Optional[str] = None
    total_executions: Optional[int] = None
    successful_executions: Optional[int] = None
    usage_last_updated: Optional[datetime] = None
    has_real_usage_data: Optional[bool] = False

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
    estimated_cost_cents: Optional[float] = None
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

class SeparatedTokenBalance(BaseModel):
    """Separated token balance for generation vs execution"""
    user_id: str
    api_key_id: Optional[str] = None
    
    # Generation tokens (for AI model usage)
    generation_tokens_total: int
    generation_tokens_used: int
    generation_tokens_remaining: int
    generation_monthly_allocation: int
    
    # Execution tokens (for running APIs)
    execution_tokens_total: int
    execution_tokens_used: int
    execution_tokens_remaining: int
    execution_monthly_allocation: int
    
    # Combined totals
    total_tokens: int
    total_used: int
    total_remaining: int
    
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

# Subscription Models
class SubscriptionTier(BaseModel):
    name: str  # free, starter, professional, enterprise
    display_name: str
    monthly_tokens: int  # Legacy field for backwards compatibility
    price_cents: int  # Price in cents per month (0 for free)
    features: List[str]
    ai_models: List[str]  # Available AI models for this tier
    
    # Separated token allocations
    monthly_generation_tokens: int  # Tokens for API generation (AI model usage)
    monthly_execution_tokens: int   # Tokens for API execution (running generated APIs)
    generation_token_ratio: float = 0.3  # 30% for generation, 70% for execution by default
    
    # API generation limits
    monthly_api_generations: int  # Number of APIs that can be generated per month

class Subscription(BaseModel):
    id: str
    user_id: str
    lemonsqueezy_subscription_id: str
    lemonsqueezy_customer_id: str
    lemonsqueezy_product_id: str
    lemonsqueezy_variant_id: str
    tier: str
    status: str
    current_period_start: Optional[datetime] = None
    current_period_end: Optional[datetime] = None
    trial_start: Optional[datetime] = None
    trial_end: Optional[datetime] = None
    monthly_token_allocation: int
    created_at: datetime
    updated_at: datetime

class CreateSubscriptionRequest(BaseModel):
    tier: str = Field(..., description="Subscription tier: starter, professional, enterprise")
    lemonsqueezy_checkout_url: Optional[str] = Field(None, description="LemonSqueezy checkout URL")

class CreateSubscriptionResponse(BaseModel):
    success: bool
    message: str
    checkout_url: Optional[str] = None
    subscription: Optional[Subscription] = None

class SubscriptionStatusResponse(BaseModel):
    success: bool
    subscription: Optional[Subscription] = None
    current_tier: Optional[SubscriptionTier] = None
    current_usage: Optional[Dict[str, Any]] = None
    days_until_renewal: Optional[int] = None

class UpdateSubscriptionRequest(BaseModel):
    tier: Optional[str] = None
    action: Optional[str] = None  # cancel, pause, resume

class SubscriptionEvent(BaseModel):
    id: str
    subscription_id: str
    user_id: str
    event_type: str
    lemonsqueezy_event_id: str
    event_data: Optional[str] = None
    processed: bool = False
    created_at: datetime

class SubscriptionTiersResponse(BaseModel):
    success: bool
    tiers: List[SubscriptionTier]
    current_tier: Optional[str] = None

# Report Models
class ReportCategory(str):
    """Report category enumeration"""
    BUG = "bug"
    INAPPROPRIATE = "inappropriate"
    SECURITY = "security"
    DOCUMENTATION = "documentation"
    PERFORMANCE = "performance"
    OTHER = "other"

class ReportSeverity(str):
    """Report severity enumeration"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"

class ReportStatus(str):
    """Report status enumeration"""
    PENDING = "pending"
    REVIEWED = "reviewed"
    RESOLVED = "resolved"
    DISMISSED = "dismissed"

class CreateReportRequest(BaseModel):
    """Request model for creating a report"""
    api_user_id: str = Field(..., description="User ID of the API owner")
    api_slug: str = Field(..., description="API slug being reported")
    category: str = Field(..., description="Report category: bug, inappropriate, security, documentation, performance, other")
    severity: str = Field(..., description="Report severity: low, medium, high")
    description: str = Field(..., min_length=10, max_length=2000, description="Detailed description of the issue")
    endpoint_url: Optional[str] = Field(None, description="API endpoint URL")

class Report(BaseModel):
    """Report data model"""
    report_id: str
    api_user_id: str  # Owner of the API
    api_slug: str
    endpoint_url: Optional[str] = None
    reporter_user_id: str  # User who reported
    reporter_email: str
    category: str
    severity: str
    description: str
    status: str = "pending"
    created_at: datetime
    updated_at: datetime

class CreateReportResponse(BaseModel):
    """Response model for creating a report"""
    success: bool
    message: str
    report_id: Optional[str] = None

class ListReportsResponse(BaseModel):
    """Response model for listing reports"""
    success: bool
    reports: List[Report]
    total: int

# Settings Management Models
class SettingValue(BaseModel):
    """Individual setting value"""
    key: str
    value: Any
    value_type: str  # 'string', 'int', 'float', 'bool', 'list', 'dict'
    category: str  # 'ai', 'security', 'application', 'authentication', 'features'
    description: Optional[str] = None
    is_sensitive: bool = False  # If true, value is masked in responses
    requires_restart: bool = True  # If true, requires service restart
    last_updated: Optional[datetime] = None
    updated_by: Optional[str] = None  # Admin user ID

class UpdateSettingRequest(BaseModel):
    """Request to update a setting"""
    key: str
    value: Any
    
class UpdateSettingsRequest(BaseModel):
    """Request to update multiple settings"""
    settings: List[UpdateSettingRequest]

class SettingsResponse(BaseModel):
    """Response with all settings"""
    success: bool
    settings: List[SettingValue]
    categories: List[str]

class UpdateSettingResponse(BaseModel):
    """Response after updating a setting"""
    success: bool
    message: str
    setting: Optional[SettingValue] = None
    requires_restart: bool = False


# Custom Domain Models
class DomainStatus(str, Enum):
    """Domain verification and activation status"""
    PENDING = "pending"           # Domain registered, waiting for DNS setup
    VERIFYING = "verifying"       # DNS check in progress
    VERIFIED = "verified"         # DNS verified, ready for Caddy
    ACTIVATING = "activating"     # Adding to Caddy, generating SSL
    ACTIVE = "active"             # Fully operational
    FAILED = "failed"             # Verification or activation failed


class VerificationMethod(str, Enum):
    """Domain verification methods"""
    DNS_TXT = "dns_txt"
    HTTP_FILE = "http_file"


class SSLCertificateStatus(str, Enum):
    """SSL certificate status"""
    PENDING = "pending"
    ISSUED = "issued"
    FAILED = "failed"


class CustomDomain(BaseModel):
    """Custom domain configuration for a user (can serve multiple APIs)"""
    id: str
    user_id: str
    api_slug: Optional[str] = None  # Optional: Default API slug for root path "/"
    domain: str  # e.g., "api.example.com"
    status: DomainStatus = DomainStatus.PENDING
    verification_token: str  # For DNS TXT record verification
    verification_method: VerificationMethod = VerificationMethod.DNS_TXT
    ssl_certificate_status: Optional[SSLCertificateStatus] = None
    caddy_route_id: Optional[str] = None  # Caddy route identifier
    created_at: datetime
    verified_at: Optional[datetime] = None
    last_verified_at: Optional[datetime] = None
    activated_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    error_message: Optional[str] = None
    verification_attempts: int = 0
    last_verification_attempt: Optional[datetime] = None
    
    # Note: api_slug is optional. If set, it's the default API for root path "/"
    # All user's APIs are accessible via: http://domain/api/{api_slug}


class CreateDomainRequest(BaseModel):
    """Request to create/register a custom domain"""
    domain: str = Field(..., description="The domain to register (e.g., api.example.com)")
    api_slug: Optional[str] = Field(None, description="Optional: Default API slug for root path. If not set, root path will not route to any API. All APIs accessible via /api/{api_slug}")
    verification_method: Optional[VerificationMethod] = Field(
        VerificationMethod.DNS_TXT, 
        description="Verification method: dns_txt or http_file"
    )


class CreateDomainResponse(BaseModel):
    """Response after creating a domain"""
    success: bool
    message: str
    domain: Optional[CustomDomain] = None
    verification_instructions: Optional[str] = None
    dns_record: Optional[str] = None  # TXT record to add


class VerifyDomainRequest(BaseModel):
    """Request to verify domain ownership"""
    domain_id: str = Field(..., description="Domain ID to verify")


class VerifyDomainResponse(BaseModel):
    """Response after domain verification attempt"""
    success: bool
    status: DomainStatus
    message: str
    verification_token: Optional[str] = None
    dns_record: Optional[str] = None
    next_retry_at: Optional[datetime] = None


class DomainStatusResponse(BaseModel):
    """Response for domain status check"""
    success: bool
    domain: Optional[CustomDomain] = None
    ssl_status: Optional[SSLCertificateStatus] = None
    message: str


class ListDomainsResponse(BaseModel):
    """Response for listing user's domains"""
    success: bool
    domains: List[CustomDomain]
    total: int


class DeleteDomainResponse(BaseModel):
    """Response after deleting a domain"""
    success: bool
    message: str


class DomainMapping(BaseModel):
    """Domain mapping for routing (api_slug is optional - default API)"""
    domain: str
    user_id: str
    api_slug: Optional[str] = None  # Optional: Default API slug for root path
    status: DomainStatus
   