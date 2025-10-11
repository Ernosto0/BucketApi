"""
Modern Authentication Routes for AI API Generator
Clean, secure, session-based authentication endpoints.
"""
import logging
from fastapi import APIRouter, HTTPException, Request, Response, Depends
from fastapi.responses import RedirectResponse
from typing import Optional

from ..models_auth import UserLogin, LoginResponse, AuthResponse, User
from ..services.auth_service import auth_service
from ..services.api_pricing_service import api_pricing_service

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/auth", tags=["authentication"])

# Rate limiting (simple in-memory implementation)
from collections import defaultdict
import time

rate_limit_storage = defaultdict(list)
RATE_LIMIT_REQUESTS = 5  # requests per minute for auth endpoints
RATE_LIMIT_WINDOW = 60  # seconds

def check_rate_limit(request: Request) -> bool:
    """Simple rate limiting for auth endpoints"""
    client_ip = request.client.host if request.client else "unknown"
    current_time = time.time()
    
    # Clean old entries
    rate_limit_storage[client_ip] = [
        timestamp for timestamp in rate_limit_storage[client_ip] 
        if current_time - timestamp < RATE_LIMIT_WINDOW
    ]
    
    # Check if rate limit exceeded
    if len(rate_limit_storage[client_ip]) >= RATE_LIMIT_REQUESTS:
        return False
    
    # Add current request
    rate_limit_storage[client_ip].append(current_time)
    return True


@router.post("/login", response_model=LoginResponse)
async def login(login_data: UserLogin, request: Request, response: Response):
    """Authenticate user and create session"""
    # Rate limiting
    if not check_rate_limit(request):
        raise HTTPException(
            status_code=429,
            detail="Too many login attempts. Please try again later."
        )
    
    try:
        # Authenticate user
        user = auth_service.authenticate_user(login_data.email, login_data.password)
        
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Create session
        session_id = auth_service.create_session(
            user_id=user.id,
            request=request,
            remember_me=login_data.remember_me
        )
        
        # Set session cookie
        max_age = 30 * 24 * 60 * 60 if login_data.remember_me else 24 * 60 * 60  # 30 days or 24 hours
        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=max_age,
            httponly=True,
            secure=False,  # Set to True in production with HTTPS
            samesite="lax"
        )
        
        return LoginResponse(
            success=True,
            message="Login successful!",
            user=user
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Login failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Login failed. Please try again later."
        )

@router.post("/logout", response_model=AuthResponse)
async def logout(request: Request, response: Response):
    """Logout user and destroy session (API endpoint)"""
    try:
        # Get session ID from cookie
        session_id = request.cookies.get("session_id")
        
        if session_id:
            # Destroy session
            auth_service.destroy_session(session_id)
        
        # Clear session cookie
        response.delete_cookie("session_id")
        
        return AuthResponse(
            success=True,
            message="Logout successful"
        )
        
    except Exception as e:
        logger.error(f"Logout failed: {e}")
        # Still clear the cookie even if session destruction fails
        response.delete_cookie("session_id")
        return AuthResponse(
            success=True,
            message="Logout successful"
        )

@router.get("/me")
async def get_current_user_info(request: Request):
    """Get current user information"""
    session_id = request.cookies.get("session_id")
    
    if not session_id:
        return {"authenticated": False, "user": None}
    
    user = auth_service.validate_session(session_id)
    
    if user:
        return {"authenticated": True, "user": user}
    else:
        return {"authenticated": False, "user": None}

@router.post("/logout-all", response_model=AuthResponse)
async def logout_all_sessions(request: Request, response: Response):
    """Logout from all sessions (security feature)"""
    try:
        # Get current user
        session_id = request.cookies.get("session_id")
        if not session_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        user = auth_service.validate_session(session_id)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid session")
        
        # Destroy all user sessions
        count = auth_service.destroy_all_user_sessions(user.id)
        
        # Clear session cookie
        response.delete_cookie("session_id")
        
        return AuthResponse(
            success=True,
            message=f"Logged out from {count} sessions"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Logout all failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to logout from all sessions"
        )

# Authentication dependency for protected routes
async def get_current_user(request: Request) -> Optional[User]:
    """Get current authenticated user from session"""
    session_id = request.cookies.get("session_id")
    if not session_id:
        return None
    
    user = auth_service.validate_session(session_id)
    return user

async def get_current_user_required(request: Request) -> User:
    """Get current authenticated user from session, raise exception if not authenticated"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

async def require_auth(request: Request) -> User:
    """Require authentication for protected routes"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    return user

async def require_active_user(request: Request) -> User:
    """Require authentication and active user"""
    user = await require_auth(request)
    if not user.is_active:
        raise HTTPException(
            status_code=403,
            detail="Account is deactivated"
        )
    return user
