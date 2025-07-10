from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime

class APIGenerationRequest(BaseModel):
    prompt: str = Field(..., description="Description of the API functionality you want")
    sample_input: Optional[str] = Field(None, description="Example input data for the API")
    expected_output: Optional[str] = Field(None, description="Expected output format")
    user_id: str = Field(..., description="Unique user identifier")
    api_name: Optional[str] = Field(None, description="Optional API name (will be auto-generated if not provided)")

class APIGenerationResponse(BaseModel):
    success: bool
    message: str
    endpoint_url: Optional[str] = None
    documentation: Optional[str] = None
    curl_example: Optional[str] = None
    api_slug: Optional[str] = None
    user_id: Optional[str] = None
    generated_at: Optional[datetime] = None

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