"""
Modern Authentication Models for AI API Generator
Clean, secure, and simple authentication models.
"""
from pydantic import BaseModel, Field, EmailStr, model_validator
from typing import Optional
from datetime import datetime

# Core User Models

class UserLogin(BaseModel):
    """User login data"""
    email: EmailStr = Field(..., description="Email address")
    password: str = Field(..., description="Password")
    remember_me: bool = Field(default=False, description="Keep me logged in")

class User(BaseModel):
    """User data model"""
    id: str
    email: str
    is_active: bool = True
    created_at: datetime
    last_login: Optional[datetime] = None
    # OAuth fields
    oauth_provider: Optional[str] = None  # 'google', 'github', etc.
    oauth_id: Optional[str] = None  # User ID from OAuth provider
    profile_picture: Optional[str] = None  # Profile picture URL
    full_name: Optional[str] = None  # Full name from OAuth
    # Subscription fields
    subscription_tier: str = "free"
    subscription_status: str = "active"
    monthly_token_allocation: int = 10000

class UserProfile(BaseModel):
    """User profile with statistics"""
    user: User
    total_apis: int
    saved_apis: list  # Will be properly typed when SavedAPI is available
    recent_activity: list

# Authentication Response Models
class AuthResponse(BaseModel):
    """Generic authentication response"""
    success: bool
    message: str
    user: Optional[User] = None


class LoginResponse(AuthResponse):
    """Login response"""
    pass

# Session Models
class UserSession(BaseModel):
    """User session data"""
    session_id: str
    user_id: str
    created_at: datetime
    last_accessed: datetime
    expires_at: datetime
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    is_active: bool = True


