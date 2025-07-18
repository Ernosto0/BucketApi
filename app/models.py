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