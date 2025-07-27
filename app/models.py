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
class APIGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Description of the API functionality you want")
    sample_input: Optional[str] = Field(None, description="Example input data for the API")
    expected_output: Optional[str] = Field(None, description="Expected output format")
    user_id: str = Field(..., description="Unique user identifier")
    api_name: Optional[str] = Field(None, description="Optional API name (will be auto-generated if not provided)")
    skip_analysis: Optional[bool] = Field(False, description="Skip analysis step if already done")

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

# API Modification Models
class APIModificationRequest(BaseModel):
    prompt: str = Field(..., description="Description of what you want to modify in the API")
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
