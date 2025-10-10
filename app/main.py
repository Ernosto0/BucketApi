from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status, Body, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Request
from starlette.middleware.sessions import SessionMiddleware
from collections import defaultdict
import asyncio
import requests
import time
import base64
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple
import logging
from .models import (
    User, UserCreate, UserLogin, RegisterResponse, LoginResponse, UserProfile, AuthResponse,
    ProposalRequest, ProposalResponse, ProposalModificationRequest, ProposalModificationResponse,
    APIGenerationRequest, APIGenerationResponse, APIModificationRequest, APIModificationResponse,
    APIExecutionRequest, APIExecutionResponse, SaveAPIRequest, SaveAPIResponse, ListAPIsResponse,
    ChatAnalysisRequest, ChatAnalysisResponse, MessageIntentRequest, MessageIntentResponse, HealthResponse, ChatMessage,
    TestRequest, TestResponse,
    APIKey, CreateAPIKeyRequest, CreateAPIKeyResponse, ListAPIKeysResponse, 
    UpdateAPIKeyRequest, DeleteAPIKeyResponse, APIInputData,
    UsageStatsResponse, UsageLimitsResponse, CreateUsageRequest,
    APIExecutionStatsResponse, APIExecutionLimitsResponse, CreateAPIExecutionUsageRequest,
    EstimateAPIUsageCostRequest, EstimateAPIUsageCostResponse, InternalTokenBalance,
    CreateInternalTokenRequest, SeparatedTokenBalance,
    # Subscription models
    Subscription, SubscriptionTier, CreateSubscriptionRequest, CreateSubscriptionResponse,
    SubscriptionStatusResponse, UpdateSubscriptionRequest, SubscriptionTiersResponse,
    # Logging models
    LogsRequest, LogsResponse, HTTPLogsRequest, HTTPLogsResponse,
    LLMLogsRequest, LLMLogsResponse, ChatLogsRequest, ChatLogsResponse,
    LogStatisticsResponse,
    # Multi-step generation models
    MultiStepGenerationRequest, PipelineInfoResponse
)
from .services.openai_service import openai_service
from .services.claude_service import claude_service
from .services.code_debugger import code_debugger
from .services.security_service import security_service
from .services.file_service import file_service
from .services.auth_service import auth_service
from .services.api_key_service import api_key_service
from .services.usage_service import usage_service
from .services.api_execution_usage_service import api_execution_usage_service
from .services.api_pricing_service import api_pricing_service
from .services.subscription_service import subscription_service
from .services.PromptService import PromptServiceBuild, PromptServiceModify
from .services.mongodb import init_database, mongodb
from .routes.auth_routes import router as auth_router, get_current_user, get_current_user_required, require_auth, require_active_user
from .routes.oauth_routes import router as oauth_router
# MongoDB imports handled through services
from .services.test_service import test_service
from .services.logging_service import logging_service, LogLevel, LogCategory
from .services.exceptions import create_secure_error, SecureHTTPException
from .services.multi_step_generation_service import multi_step_generation_service
from .code_generation_config.multi_step_config import GenerationMode
from .middleware.logging_middleware import LoggingMiddleware, RequestContextMiddleware
from .config import settings

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title="AI-Powered API Generator",
    description="Generate and execute APIs using AI",
    version="1.0.0",
    docs_url=settings.DOCS_URL,
    redoc_url=settings.REDOC_URL
)

@app.on_event("startup")
async def startup_event():
    """Initialize database on startup."""
    init_database()
    logger.info("MongoDB initialized successfully")
    
    # Clean up any orphaned JSON files from old metadata storage
    cleaned_count = file_service.cleanup_orphaned_json_files()
    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} orphaned JSON metadata files")



# Add session middleware for OAuth (required by authlib)
app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    max_age=30 * 24 * 60 * 60,  # 30 days
    same_site=settings.COOKIE_SAMESITE,
    https_only=settings.COOKIE_SECURE
)

# Add CORS middleware with secure configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,  # 🔒 Environment-specific secure origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # 🔒 Specific methods only
    allow_headers=["*"],  # Headers can remain permissive for API flexibility
    max_age=600,  # 🔒 Cache preflight for 10 minutes
)

# Add security headers middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    """Add security headers to all responses."""
    response = await call_next(request)
    
    # 🔒 Security headers for defense in depth
    response.headers["X-Content-Type-Options"] = "nosniff"  # Prevent MIME sniffing
    response.headers["X-Frame-Options"] = "DENY"  # Prevent clickjacking
    response.headers["X-XSS-Protection"] = "1; mode=block"  # XSS protection
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"  # Control referrer info
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"  # Feature policy
    
    # 🔒 Content Security Policy (CSP)
    if settings.ENVIRONMENT == "production":
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"  # HTTPS only
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline'; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data: https:; "
            "connect-src 'self'"
        )
    
    return response

# Add logging middleware (disabled - causes deadlocks with database sessions)
app.add_middleware(RequestContextMiddleware)
# app.add_middleware(
#     LoggingMiddleware,
#     log_request_body=True,
#     log_response_body=True,
#     max_body_size=5000,  # Limit body size for logging
#     exclude_paths=['/health', '/docs', '/redoc', '/openapi.json', '/static', '/logs']
# )

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Include authentication routes
app.include_router(auth_router)
app.include_router(oauth_router)

# Temporary stub functions for backward compatibility (to be replaced)
async def require_auth_hybrid(request: Request) -> User:
    """Temporary stub - use new auth system"""
    user = await get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user

async def get_current_user_and_api_key_hybrid(request: Request) -> Tuple[Optional[User], Optional[str]]:
    """Temporary stub - use new auth system"""
    user = await get_current_user(request)
    return user, None

async def get_current_user_or_api_key(request: Request) -> Optional[User]:
    """Temporary stub - use new auth system"""
    return await get_current_user(request)

async def require_auth_or_api_key(request: Request) -> User:
    """Temporary stub - use new auth system"""
    return await require_auth(request)

async def require_admin_auth(request: Request) -> User:
    """Temporary stub - use new auth system"""
    user = await require_auth(request)
    if not is_admin_user(user.email):
        raise HTTPException(status_code=403, detail="Admin access required")
    return user

def is_admin_user(email: str) -> bool:
    """Check if a user is an admin based on their email."""
    # Simple admin check - I will change this later TODO
    admin_emails = [
        "ernosto20.03@gmail.com",
        "admin@localhost",
        "admin@yourdomain.com"
    ]
    logger.info(f"Checking if {email} is an admin user")
    # Check if email is in admin list or contains 'admin'
    return email.lower() in [e.lower() for e in admin_emails] or 'admin' in email.lower()

def get_or_create_session_id(request: Request) -> str:
    """Get session ID from cookies or create a new one."""
    session_id = request.cookies.get('session_id')
    if not session_id:
        session_id = str(uuid.uuid4())
        logger.debug(f"Generated new session ID: {session_id}")
    return session_id


@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main frontend page for authenticated users, redirect to landing for non-authenticated."""
    user = await get_current_user(request)
    if user:
        return templates.TemplateResponse("index.html", {"request": request, "user": user})
    else:
        return RedirectResponse(url="/landing", status_code=302)

@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Serve the main dashboard page for authenticated users."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("index.html", {"request": request, "user": user})

@app.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Serve the landing page for non-authenticated users."""
    # Check if user is already authenticated
    user = await get_current_user(request)
    return templates.TemplateResponse("landing.html", {"request": request, "user": user})

@app.get("/logout", response_class=HTMLResponse)
async def logout_web(request: Request):
    """Web logout endpoint that redirects to landing page"""
    # Create response that redirects to landing
    response = RedirectResponse(url="/landing", status_code=302)
    
    # Get session ID from cookie and destroy session
    session_id = request.cookies.get("session_id")
    if session_id:
        try:
            auth_service.destroy_session(session_id)
        except Exception as e:
            logger.warning(f"Session destruction failed during web logout: {e}")
    
    # Clear session cookie
    response.delete_cookie("session_id")
    
    return response


@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page."""
    # Check if user is already logged in
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "settings": settings
    })

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve the register page."""
    # Check if user is already logged in
    user = await get_current_user(request)
    if user:
        return RedirectResponse(url="/dashboard", status_code=302)
    return templates.TemplateResponse("auth/register.html", {
        "request": request,
        "settings": settings
    })

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve the profile page."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

@app.get("/subscription", response_class=HTMLResponse)
async def subscription_page(request: Request):
    """Subscription management page."""
    return templates.TemplateResponse("subscription.html", {"request": request})

@app.get("/subscription/success", response_class=HTMLResponse)
async def subscription_success_page(request: Request):
    """Subscription success page after payment."""
    try:
        # Get current user
        user = await get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        
        # Get user's subscription status
        subscription = await subscription_service.get_user_subscription(user.id)
        
        return templates.TemplateResponse("subscription_success.html", {
            "request": request, 
            "user": user,
            "subscription": subscription
        })
    except Exception as e:
        logger.error(f"Failed to load subscription success page: {str(e)}")
        return RedirectResponse(url="/subscription", status_code=302)
    

@app.get("/logs", response_class=HTMLResponse)
async def logs_dashboard_page(request: Request):
    """Serve the logs dashboard page (requires authentication)."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("logs_dashboard.html", {"request": request, "user": user})

@app.get("/admin", response_class=HTMLResponse)
async def admin_panel_page(request: Request):
    """Serve the admin panel page (requires admin authentication)."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    # Check if user is admin
    if not is_admin_user(user.email):
        return RedirectResponse(url="/dashboard", status_code=302)
    
    return templates.TemplateResponse("admin_panel.html", {"request": request, "user": user})

@app.get("/api/{user_id}/{api_slug}/details", response_class=HTMLResponse)
async def api_details_page(request: Request, user_id: str, api_slug: str):
    """Serve the API details page."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    
    return templates.TemplateResponse("api_details.html", {
        "request": request,
        "user": user,
        "user_id": user_id,
        "api_slug": api_slug
    })
   
@app.get("/api/{user_id}/{api_slug}/docs", response_class=HTMLResponse)
async def api_documentation_page(request: Request, user_id: str, api_slug: str):
    """Serve the enhanced API documentation page."""
    try:
        # Get API details for documentation
        api_details = file_service.get_api_details(user_id, api_slug)
        
        # Build the base URL for the API
        base_url = f"{settings.API_PREFIX}/{user_id}/{api_slug}"
        
        # Get current user for authentication
        user = await get_current_user(request)
        if not user:
            return RedirectResponse(url="/login", status_code=302)
        
        return templates.TemplateResponse("api_documentation.html", {
            "request": request,
            "user": user,
            "user_id": user_id,
            "api_slug": api_slug,
            "api_name": api_details.get('api_name', f"API {api_slug}"),
            "description": api_details.get('prompt', 'API endpoint for processing requests'),
            "base_url": base_url,
            "curl_example": api_details.get('curl_example', f'curl -X POST "{base_url}" \\\n  -H "Content-Type: application/json" \\\n  -d \'{{\"example\": \"value\"}}\''),
            "documentation": api_details.get('documentation', 'Documentation not available'),
            "openapi_spec": api_details.get('openapi_spec')
        })
    except Exception as e:
        logger.error(f"Failed to load API documentation: {str(e)}")
        raise HTTPException(
            status_code=404,
            detail=f"API documentation not found: {str(e)}"
        )

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(),
        version="1.0.0"
    )

# Authentication endpoints removed - will be replaced with new auth system

# Debug auth endpoint removed

# API Key Management Endpoints
@app.post("/api-keys", response_model=CreateAPIKeyResponse)
async def create_api_key(
    key_request: CreateAPIKeyRequest, 
    request: Request,
    current_user: User = Depends(require_auth_hybrid)
):
    """Create a new API key for the authenticated user."""
    logger.info(f"🎯 POST /api-keys endpoint hit! Creating API key '{key_request.key_name}' for user {current_user.id}")
    result = api_key_service.create_api_key(current_user.id, key_request)
    logger.info(f"🔄 API key creation result: success={result.success}")
    return result

@app.get("/api-keys", response_model=ListAPIKeysResponse)
async def list_api_keys(request: Request, current_user: User = Depends(require_auth_hybrid)):
    logger.info(f"🔑 GET /api-keys endpoint hit! Listing API keys for user {current_user.id}")
    """List all API keys for the authenticated user."""
    api_keys = api_key_service.get_user_api_keys(current_user.id)
    return ListAPIKeysResponse(
        success=True,
        api_keys=api_keys,
        count=len(api_keys)
    )

@app.put("/api-keys/{key_id}")
async def update_api_key(
    key_id: str, 
    update_request: UpdateAPIKeyRequest, 
    request: Request,
    current_user: User = Depends(require_auth_hybrid)
):
    logger.info(f"🔄 PUT /api-keys/{key_id} endpoint hit! Updating API key for user {current_user.id}")
    """Update an API key."""
    success = api_key_service.update_api_key(
        current_user.id, 
        key_id, 
        update_request.key_name, 
        update_request.is_active
    )
    if success:
        return {"success": True, "message": "API key updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="API key not found or update failed")

@app.delete("/api-keys/{key_id}", response_model=DeleteAPIKeyResponse)
async def delete_api_key(key_id: str, request: Request, current_user: User = Depends(require_auth_hybrid)):
    """Delete an API key."""
    logger.info(f"🔄 DELETE /api-keys/{key_id} endpoint hit! Deleting API key for user {current_user.id}")
    success = api_key_service.delete_api_key(current_user.id, key_id)
    if success:
        return DeleteAPIKeyResponse(
            success=True,
            message="API key deleted successfully"
        )
    else:
        raise HTTPException(status_code=404, detail="API key not found")

# Usage Tracking Endpoints

@app.get("/usage/stats", response_model=UsageStatsResponse)
async def get_usage_stats(
    request: Request,
    days: int = 30,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """
    Get usage statistics for the current user.
    """
    logger.info(f"Getting usage stats for user {current_user.id} for {days} days")
    
    try:
        stats = await usage_service.get_usage_stats(
            user_id=current_user.id,
            api_key_id=api_key_id,
            days=days
        )
        return stats
    except Exception as e:
        logger.error(f"Failed to get usage stats: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get usage stats: {str(e)}"
        )

@app.get("/usage/limits", response_model=UsageLimitsResponse)
async def get_usage_limits(
    request: Request,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """
    Check current usage limits for the user.
    """
    logger.info(f"Checking usage limits for user {current_user.id}")
    
    try:
        limits = await usage_service.check_usage_limits(
            user_id=current_user.id,
            api_key_id=api_key_id
        )
        return limits
    except Exception as e:
        logger.error(f"Failed to check usage limits: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to check usage limits: {str(e)}"
        )

@app.post("/usage/record")
async def record_manual_usage(
    request: CreateUsageRequest,
    current_user: User = Depends(get_current_user_required)
):
    """
    Manually record usage (for testing or external integrations).
    """
    logger.info(f"Recording manual usage for user {current_user.id}")
    
    try:
        usage = await usage_service.record_usage(
            user_id=current_user.id,
            api_key_id=None,  # Manual entries don't have API keys
            service_type=request.service_type,
            operation_type=request.operation_type,
            model_name=request.model_name,
            input_tokens=request.input_tokens,
            output_tokens=request.output_tokens,
            prompt_length=request.prompt_length,
            response_length=request.response_length,
            request_duration_ms=request.request_duration_ms,
            operation_context={"manual_entry": True, "context": request.operation_context},
            api_slug=request.api_slug,
            success=request.success,
            error_message=request.error_message
        )
        
        return {"success": True, "message": "Usage recorded successfully", "usage_id": usage.user_id}
    except Exception as e:
        logger.error(f"Failed to record manual usage: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to record usage: {str(e)}"
        )

@app.get("/usage/estimate-cost")
async def estimate_usage_cost(
    model_name: str,
    input_tokens: int,
    output_tokens: int = 1000,
    current_user: User = Depends(get_current_user_required)
):
    """
    Estimate the cost for a given token usage.
    """
    logger.info(f"Estimating cost for {input_tokens} input + {output_tokens} output tokens using {model_name}")
    
    try:
        cost_cents = await usage_service.estimate_request_cost(
            model_name=model_name,
            estimated_input_tokens=input_tokens,
            estimated_output_tokens=output_tokens
        )
        
        return {
            "model_name": model_name,
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
            "estimated_cost_cents": cost_cents,
            "estimated_cost_usd": cost_cents / 100.0
        }
    except Exception as e:
        logger.error(f"Failed to estimate cost: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to estimate cost: {str(e)}"
        )

@app.post("/chat/analyze", response_model=ChatAnalysisResponse)
async def analyze_chat_prompt(request: ChatAnalysisRequest, http_request: Request, response: Response):
    """
    Analyze a chat prompt to determine if it's buildable and provide appropriate response.
    """
    import uuid
    conversation_id = str(uuid.uuid4())
    start_time = time.time()
    
    # Extract session ID from cookies or generate a new one
    session_id = get_or_create_session_id(http_request)
    
    logger.info(f"Analyzing chat prompt for user {request.user_id}: {request.prompt[:100]}... (session: {session_id[:8]})")
    
    # Log user message
    try:
        await logging_service.log_chat_message(
            user_id=request.user_id,
            message_type="user_message",
            content=request.prompt,
            session_id=session_id,
            conversation_id=conversation_id,
            metadata={"endpoint": "/chat/analyze", "operation": "prompt_analysis"}
        )
    except Exception as log_error:
        logger.error(f"Failed to log user chat message: {log_error}")
    
    try:
        # Use PromptService to analyze the prompt
        prompt_service = PromptServiceBuild()
        analysis_result = await prompt_service.CanIBuildThis(request.user_id, request.prompt)
        
        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f"Analysis completed for user {request.user_id}")
        
        # Log AI response
        try:
            await logging_service.log_chat_message(
                user_id=request.user_id,
                message_type="ai_response",
                content=analysis_result,
                session_id=session_id,
                conversation_id=conversation_id,
                ai_model_used="gpt-4o-mini",  # Default model used by PromptService
                response_time_ms=duration_ms,
                metadata={
                    "endpoint": "/chat/analyze", 
                    "operation": "prompt_analysis",
                    "success": True
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log AI chat response: {log_error}")
        
        # Set session ID cookie for future requests (expires in 30 days)
        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=30 * 24 * 60 * 60,  # 30 days
            httponly=True,
            secure=settings.COOKIE_SECURE,  # Secure in production with HTTPS
            samesite=settings.COOKIE_SAMESITE
        )
        
        return {
            "success": True,
            "user_id": request.user_id,
            "prompt": request.prompt,
            "analysis_result": analysis_result,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        duration_ms = int((time.time() - start_time) * 1000)
        logger.error(f"Error analyzing chat prompt: {str(e)}")
        
        error_response = f'{{"status": "error", "message": "Error analyzing prompt: {str(e)}"}}'
        
        # Log error response
        try:
            await logging_service.log_chat_message(
                user_id=request.user_id,
                message_type="ai_response",
                content=error_response,
                session_id=session_id,
                conversation_id=conversation_id,
                response_time_ms=duration_ms,
                metadata={
                    "endpoint": "/chat/analyze", 
                    "operation": "prompt_analysis",
                    "success": False,
                    "error": str(e)
                }
            )
        except Exception as log_error:
            logger.error(f"Failed to log error chat response: {log_error}")
        
        # Set session ID cookie even for error responses
        response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=30 * 24 * 60 * 60,  # 30 days
            httponly=True,
            secure=settings.COOKIE_SECURE,  # Secure in production with HTTPS
            samesite=settings.COOKIE_SAMESITE
        )
        
        return {
            "success": False,
            "user_id": request.user_id,
            "prompt": request.prompt,
            "analysis_result": error_response,
            "timestamp": datetime.now()
        }

@app.post("/classify-message-intent", response_model=MessageIntentResponse)
async def classify_message_intent(request: MessageIntentRequest, http_request: Request):
    """
    Classify the intent of a user message to determine if it's a modification request or conversational.
    Uses a cheap, fast LLM for accurate classification.
    """
    try:
        logger.info(f"Classifying message intent: {request.message[:50]}... (context: {request.context})")
        
        # Use PromptService for classification
        from .services.PromptService import PromptServiceBuild
        prompt_service = PromptServiceBuild()
        
        # Get session ID from cookies to use as user identifier
        session_id = get_or_create_session_id(http_request)
        user_id = f"session_{session_id[:8]}"  # Use session ID as user identifier for logging
        
        # Use the PromptService method for classification
        classification_result = await prompt_service.classify_message_intent(
            user_id=user_id,
            message=request.message,
            context=request.context
        )
        
        return MessageIntentResponse(
            success=classification_result["success"],
            intent=classification_result["intent"],
            confidence=classification_result["confidence"],
            reasoning=classification_result["reasoning"]
        )
            
    except Exception as e:
        logger.error(f"Error classifying message intent: {str(e)}")
        return MessageIntentResponse(
            success=False,
            intent="conversational",  # Safe default
            confidence=0.0,
            reasoning=f"Error during classification: {str(e)}"
        )

@app.post("/test-proposal")
async def test_proposal():
    """Test endpoint to verify proposal response structure"""
    test_proposal = {
        "api_name": "Test API",
        "description": "A test API for debugging",
        "functionality": ["Test functionality 1", "Test functionality 2"],
        "input_format": {"type": "JSON", "fields": ["test_field"]},
        "output_format": {"type": "JSON", "fields": ["test_response"]},
        "endpoints": [{"method": "POST", "path": "/test", "description": "Test endpoint"}]
    }
    
    response_data = {
        "success": True,
        "status": "buildable",
        "message": "Test proposal generated",
        "original_prompt": "test prompt",
        "user_id": "test_user",
        "timestamp": datetime.now(),
        "conversation_state": "proposal",
        "proposal_id": "test_id",
        "proposal": test_proposal
    }
    
    logger.info(f"Test response_data keys: {list(response_data.keys())}")
    logger.info(f"Test response_data: {response_data}")
    
    return response_data

@app.post("/generate-proposal", response_model=ProposalResponse)
async def generate_proposal(
    proposal_request: ProposalRequest,
    request: Request,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Analyze a user prompt and generate a proposal with detailed analysis.
    This endpoint determines if the request is buildable, needs clarification,
    is a modification request, or is not buildable.
    """
    logger.info(f"🎯 generate_proposal endpoint called with user_id: {proposal_request.user_id}")
    logger.info(f"🎯 Request cookies: {list(request.cookies.keys())}")
    logger.info(f"🎯 Request headers Authorization: {request.headers.get('authorization', 'None')}")
    
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    logger.info(f"🎯 Authentication result - current_user: {current_user.email if current_user else 'None'}, api_key_id: {api_key_id}")
    
    if not current_user:
        logger.error("🎯 Authentication failed - raising 401")
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Generating proposal for user {proposal_request.user_id} with prompt: {proposal_request.prompt[:100]}...")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=proposal_request.user_id,
            api_key_id=api_key_id,
            tokens_to_use=1000  # Estimated tokens for analysis
        )
        
        if limits.is_over_limit:
            logger.warning(f"Rate limit exceeded for user {proposal_request.user_id}: {limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=limits.limit_exceeded_reason or f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage service unavailable: {e}")
        # SECURITY FIX: Fail closed instead of open
        raise HTTPException(
            status_code=503,
            detail="Usage tracking service temporarily unavailable. Please try again later."
        )
    
    try:
        # Analyze the prompt using PromptService
        logger.info("Analyzing prompt with PromptServiceBuild...")
        prompt_service = PromptServiceBuild()
        analysis_result = await prompt_service.CanIBuildThis(proposal_request.user_id, proposal_request.prompt)
        
        # Parse the analysis result
        try:
            analysis_data = json.loads(analysis_result)
            status = analysis_data.get("status")
            logger.info(f"Raw analysis result: {analysis_result}")
            logger.info(f"Parsed analysis status: '{status}'")
            logger.info(f"Analysis data keys: {list(analysis_data.keys())}")
            if "proposal" in analysis_data:
                logger.info(f"Proposal data: {analysis_data['proposal']}")
            else:
                logger.info("No 'proposal' key found in analysis_data")
            
            # Generate a unique proposal ID for this session
            import uuid
            proposal_id = str(uuid.uuid4())
            
            # Return appropriate response based on analysis status
            response_data = {
                "success": True,
                "status": status,
                "message": analysis_data.get("message", "Analysis completed."),
                "original_prompt": proposal_request.prompt,
                "user_id": proposal_request.user_id,
                "timestamp": datetime.now(),
                "conversation_state": "proposal",
                "proposal_id": proposal_id
            }
            
            # Add status-specific fields
            if status == "needs_clarification":
                response_data.update({
                    "questions": analysis_data.get("questions", []),
                    "suggestions": analysis_data.get("suggestions", [])
                })
                logger.info(f"Build needs clarification: {analysis_data.get('message')}")
                
            elif status == "modify_request":
                response_data.update({
                    "instructions": analysis_data.get("instructions", []),
                    "next_steps": analysis_data.get("next_steps", [])
                })
                logger.info(f"Detected modify request")
                
            elif status == "not_buildable":
                response_data.update({
                    "reasons": analysis_data.get("reasons", []),
                    "suggestions": analysis_data.get("suggestions", [])
                })
                logger.warning(f"API request not buildable")
                
            elif status == "buildable":
                response_data.update({
                    "confirmation_needed": analysis_data.get("confirmation_needed", True),
                    "next_steps": analysis_data.get("next_steps", [])
                })
                logger.info(f"API request is buildable")
                
            elif status == "proposal_ready":
                # Handle proposal ready status - convert to buildable for frontend
                response_data["status"] = "buildable"  # Frontend expects "buildable"
                response_data.update({
                    "confirmation_needed": analysis_data.get("confirmation_needed", True),
                    "next_steps": analysis_data.get("next_steps", [])
                })
                logger.info(f"Proposal is ready, converted to buildable status")
                
            else:
                logger.warning(f"Unexpected analysis status: {status}")
                response_data["status"] = "unknown"
                response_data["message"] = f"Analysis returned unexpected status: {status}"
            
            # Always preserve proposal data if it exists (regardless of status) - DO THIS LAST
            if "proposal" in analysis_data:
                response_data["proposal"] = analysis_data.get("proposal", {})
                logger.info(f"Preserved proposal data from analysis_data")
            else:
                logger.warning(f"No proposal data found in analysis_data")
                
            logger.info(f"Final response_data keys: {list(response_data.keys())}")
            logger.info(f"Final response_data: {response_data}")
            
            # Create the response object
            response_obj = ProposalResponse(**response_data)
            logger.info(f"ProposalResponse object created successfully")
            logger.info(f"Response object has proposal: {'proposal' in response_obj.__dict__}")
            if hasattr(response_obj, 'proposal'):
                logger.info(f"Response proposal data: {response_obj.proposal}")
            
            return response_obj
            
        except json.JSONDecodeError:
            logger.error("Could not parse analysis result")
            return ProposalResponse(
                success=False,
                status="error",
                message="Failed to analyze the prompt. Please try again.",
                original_prompt=proposal_request.prompt,
                user_id=proposal_request.user_id,
                timestamp=datetime.now()
            )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in generate_proposal: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate proposal: {str(e)}"
        )


@app.post("/modify-proposal", response_model=ProposalModificationResponse)
async def modify_proposal(
    modify_request: ProposalModificationRequest,
    request: Request,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Modify an existing proposal by combining the original prompt with modification request.
    This endpoint is for when you're still in the proposal stage and want to refine
    your requirements before generating code.
    """
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Modifying proposal for user {current_user.id} - modification: {modify_request.modification_request[:100]}...")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=current_user.id,
            api_key_id=api_key_id,
            tokens_to_use=1200  # Estimated tokens for proposal modification analysis
        )
        
        if limits.is_over_limit:
            logger.warning(f"Rate limit exceeded for user {current_user.id}: {limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=limits.limit_exceeded_reason or f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage service unavailable: {e}")
        # SECURITY FIX: Fail closed instead of open
        raise HTTPException(
            status_code=503,
            detail="Usage tracking service temporarily unavailable. Please try again later."
        )
    
    try:
        # Skip analysis and go directly to modification - much simpler and faster!
        logger.info("Directly modifying existing proposal (skipping analysis step)...")
        prompt_service = PromptServiceBuild()
        
        # Go directly to modification without analysis
        try:
            # Check if we have the current proposal data
            if modify_request.current_proposal:
                logger.info("Using existing proposal data for direct context-aware modification")
                # Use the ModifyExistingProposal method that preserves context
                modified_proposal_result = await prompt_service.ModifyExistingProposal(
                    current_user.id, 
                    modify_request.current_proposal, 
                    modify_request.modification_request,
                    modify_request.original_prompt
                )
                
                try:
                    analysis_data = json.loads(modified_proposal_result)
                    modified_status = analysis_data.get("status")
                    
                    # If the modification was successful, use it
                    if modified_status in ["buildable", "proposal_ready", "error"]:
                        logger.info(f"Successfully processed proposal modification with status: {modified_status}")
                        status = "buildable" if modified_status != "error" else "error"
                        logger.info(f"Modified proposal data keys: {list(analysis_data.keys())}")
                        if "proposal" in analysis_data:
                            logger.info(f"Modified proposal contains proposal data with keys: {analysis_data['proposal'].keys() if analysis_data['proposal'] else 'None'}")
                    else:
                        logger.warning(f"Unexpected proposal modification status: {modified_status}")
                        status = "buildable"  # Default to buildable
                        
                except json.JSONDecodeError:
                    logger.error("Failed to parse modified proposal result")
                    # Create fallback response
                    analysis_data = {
                        "status": "error",
                        "message": "I had trouble processing your modification request. Please try rephrasing it.",
                        "original_prompt": modify_request.original_prompt,
                        "proposal": modify_request.current_proposal
                    }
                    status = "error"
            else:
                logger.warning("No current proposal data provided, cannot modify existing proposal")
                # Create error response when no proposal data is available
                analysis_data = {
                    "status": "error", 
                    "message": "I need the current proposal data to make modifications. Please try again.",
                    "original_prompt": modify_request.original_prompt
                }
                status = "error"
            
        except Exception as e:
            logger.error(f"Error modifying proposal: {str(e)}")
            # Create fallback response
            analysis_data = {
                "status": "error",
                "message": f"I encountered an issue while modifying the proposal: {str(e)}",
                "original_prompt": modify_request.original_prompt,
                "proposal": modify_request.current_proposal if modify_request.current_proposal else None
            }
            status = "error"
            
        # Return appropriate response based on modification status
        response_data = {
            "success": True if status != "error" else False,
            "message": analysis_data.get("message", "Proposal modification completed."),
            "original_prompt": modify_request.original_prompt,
            "modification_request": modify_request.modification_request,
            "user_id": current_user.id,
            "timestamp": datetime.now(),
            "conversation_state": "proposal",  # Still in proposal state after modification
            "proposal_id": modify_request.proposal_id  # Maintain the same proposal session
        }
        
        # Handle the simplified status (only "buildable" or "error")
        if status == "buildable":
            # Add next steps if available
            if analysis_data.get("next_steps"):
                response_data["next_steps"] = analysis_data.get("next_steps")
            logger.info(f"Modified proposal is buildable")
            
        elif status == "error":
            response_data["success"] = False
            logger.error(f"Error in proposal modification")
            
        else:
            logger.warning(f"Unexpected status: {status}")
            response_data["message"] = f"Unexpected status: {status}"
        
        # Always preserve proposal data if it exists
        if "proposal" in analysis_data:
            response_data["proposal"] = analysis_data.get("proposal", {})
            logger.info(f"Preserved proposal data from modification")
        else:
            logger.warning(f"No proposal data found in modification")
        
        # Set the final status after all processing is complete
        response_data["status"] = status
        
        logger.info(f"Final modification response_data keys: {list(response_data.keys())}")
        logger.info(f"Final modification response_data: {response_data}")
        
        return ProposalModificationResponse(**response_data)
        
    except json.JSONDecodeError:
        logger.error("Could not parse proposal modification analysis result")
        return ProposalModificationResponse(
            success=False,
            status="error",
            message="Failed to analyze the modified proposal. Please try again.",
            original_prompt=modify_request.original_prompt,
            modification_request=modify_request.modification_request,
            user_id=current_user.id,
            timestamp=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in modify_proposal: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to modify proposal: {str(e)}"
        )


@app.post("/generate-api-stream")
async def generate_api_stream(
    api_request: APIGenerationRequest,
    request: Request,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Generate a new API with real-time streaming chat messages.
    
    This endpoint provides real-time updates and chat messages during the API generation process,
    giving users visibility into what's happening at each step.
    """
    from fastapi.responses import StreamingResponse
    
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Starting streaming API generation for user {current_user.id}")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=current_user.id,
            api_key_id=api_key_id,
            tokens_to_use=2000  # Estimated tokens for code generation
        )
        
        if limits.is_over_limit:
            logger.warning(f"Rate limit exceeded for user {current_user.id}: {limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=limits.limit_exceeded_reason or f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage service unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail="Usage tracking service temporarily unavailable. Please try again later."
        )
    
    async def generate_stream():
        """Generator function for streaming API generation"""
        try:
            # Send initial status message
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "🚀 Starting multi-step API generation...",
                    "is_ai": True,
                    "message_type": "greeting"
                }
            }) + "\n\n"
            
            # Start multi-step generation
            session_id = await multi_step_generation_service.start_generation(
                prompt=api_request.prompt,
                user_id=current_user.id,
                sample_input=api_request.sample_input,
                expected_output=api_request.expected_output,
                api_key_id=api_key_id,
                pipeline_name=api_request.pipeline_name or "full_pipeline",
                mode=GenerationMode("streaming")
            )
            
            # Skip session started message - handled by step messages
            
            # Execute streaming generation and yield all messages
            final_result = None
            async for event in multi_step_generation_service.generate_streaming_mode(session_id):
                yield event
                
                # Check if this is the final result
                if '"type": "session_complete"' in event:
                    try:
                        event_data = json.loads(event.replace("data: ", ""))
                        if event_data.get("type") == "session_complete":
                            final_result = event_data.get("data", {})
                    except:
                        pass
            
            # Process the final result for saving and documentation
            if final_result and final_result.get("final_code"):
                try:
                    yield "data: " + json.dumps({
                        "type": "chat_message",
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "message": "🔍 Now I'm validating the code for security and saving your API...",
                            "is_ai": True,
                            "message_type": "post_processing"
                        }
                    }) + "\n\n"
                    
                    raw_code = final_result["final_code"]
                    
                    # Debug and fix the generated code
                    code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
                        raw_code, api_request.prompt, current_user.id, api_key_id
                    )
                    
                    if issues_found:
                        yield "data: " + json.dumps({
                            "type": "chat_message",
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "message": f"🔧 Found and fixed {len(issues_found)} code issues: {', '.join(issues_found)}",
                                "is_ai": True,
                                "message_type": "code_fixing"
                            }
                        }) + "\n\n"
                    
                    # Validate code for security
                    is_safe, violations = security_service.validate_code(code)
                    if not is_safe:
                        yield "data: " + json.dumps({
                            "type": "error",
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "message": f"❌ Code failed security validation: {'; '.join(violations)}",
                                "error_type": "SecurityValidationError"
                            }
                        }) + "\n\n"
                        return
                    
                    yield "data: " + json.dumps({
                        "type": "chat_message",
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "message": "✅ Code passed security validation! Saving your API...",
                            "is_ai": True,
                            "message_type": "security_check"
                        }
                    }) + "\n\n"
                    
                    # Generate API slug and save
                    api_slug = file_service.generate_api_slug(
                        user_id=current_user.id,
                        api_name=api_request.api_name
                    )
                    clean_slug = api_slug.replace(f"{current_user.id}_", "")
                    
                    await file_service.save_api_code(api_slug, code)
                    
                    yield "data: " + json.dumps({
                        "type": "chat_message",
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "message": "📚 Generating comprehensive documentation...",
                            "is_ai": True,
                            "message_type": "documentation"
                        }
                    }) + "\n\n"
                    
                    # Generate documentation
                    documentation, openapi_spec, curl_example = await openai_service.generate_documentation(
                        code=code, 
                        prompt=api_request.prompt,
                        user_id=current_user.id,
                        api_key_id=api_key_id,
                        api_slug=clean_slug
                    )
                    
                    # Build endpoint URL
                    endpoint_url = f"{settings.API_PREFIX}/{current_user.id}/{clean_slug}"
                    
                    # Update curl example with actual endpoint
                    if "your-endpoint-url" in curl_example:
                        curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
                    
                    # Save API documentation and metadata to database
                    try:
                        save_request = SaveAPIRequest(
                            user_id=current_user.id,
                            api_slug=clean_slug,
                            api_name=api_request.api_name or f"API {clean_slug}",
                            prompt=api_request.prompt,
                            endpoint_url=endpoint_url,
                            documentation=documentation,
                            curl_example=curl_example,
                            openapi_spec=json.dumps(openapi_spec) if openapi_spec else None,
                            sample_input=api_request.sample_input,
                            expected_output=api_request.expected_output
                        )
                        file_service.save_api_metadata(save_request)
                        logger.info(f"API documentation saved to database for {clean_slug}")
                    except Exception as e:
                        logger.warning(f"Failed to save API documentation to database: {e}")
                        # Continue without database save if service is unavailable
                    
                    # Save API metadata TODO: Remove this after 
                    try:
                        complexity = 'simple'
                        if len(code) > 2000 or "class" in code or "async def" in code:
                            complexity = 'complex'
                        elif len(code) > 1000 or "try:" in code or "except:" in code:
                            complexity = 'medium'
                        
                        estimated_input_tokens, estimated_output_tokens = usage_service.calculate_estimated_tokens(
                            model_name=settings.CLAUDE_MODEL,
                            system_prompt="",
                            user_prompt=api_request.prompt,
                            response_length=len(code),
                            success=True
                        )
                        
                        await api_pricing_service.save_api_metadata(
                            api_slug=clean_slug,
                            user_id=current_user.id,
                            ai_model_used=settings.CLAUDE_MODEL,
                            estimated_tokens_per_call=estimated_input_tokens + estimated_output_tokens,
                            base_complexity=complexity
                        )
                    except Exception as e:
                        logger.warning(f"Failed to save API metadata: {e}")
                    
                    # Send final success message with results
                    yield "data: " + json.dumps({
                        "type": "generation_complete",
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "success": True,
                            "message": "🎉 Your API has been generated successfully!",
                            "endpoint_url": endpoint_url,
                            "documentation": documentation,
                            "curl_example": curl_example,
                            "api_slug": clean_slug,
                            "user_id": current_user.id,
                            "generated_at": datetime.now().isoformat(),
                            "debug_info": {
                                "issues_found": issues_found,
                                "fixes_applied": fixes_applied,
                                "code_quality": "high" if not issues_found else "improved"
                            }
                        }
                    }) + "\n\n"
                    
                except Exception as e:
                    logger.error(f"Error in post-processing: {str(e)}", exc_info=True)
                    yield "data: " + json.dumps({
                        "type": "error",
                        "timestamp": datetime.now().isoformat(),
                        "data": {
                            "message": f"❌ Error during post-processing: {str(e)}",
                            "error_type": type(e).__name__
                        }
                    }) + "\n\n"
            else:
                yield "data: " + json.dumps({
                    "type": "error",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": "❌ Generation completed but no code was produced",
                        "error_type": "GenerationError"
                    }
                }) + "\n\n"
            
            # Cleanup session
            try:
                await multi_step_generation_service.cleanup_session(session_id)
            except Exception as e:
                logger.warning(f"Failed to cleanup session {session_id}: {e}")
                
        except Exception as e:
            logger.error(f"Streaming generation error: {str(e)}", exc_info=True)
            yield "data: " + json.dumps({
                "type": "error",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": f"❌ Generation failed: {str(e)}",
                    "error_type": type(e).__name__
                }
            }) + "\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
    )

@app.post("/generate-api", response_model=APIGenerationResponse)
async def generate_api(
    api_request: APIGenerationRequest,
    request: Request,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Generate a new API based on user prompt.
    
    NOTE: It's recommended to use the /generate-proposal endpoint first to analyze
    the prompt and ensure it's buildable before calling this endpoint.
    
    This endpoint focuses on code generation and assumes the prompt has been
    validated through the proposal process.
    """
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Generating API for user {current_user.id} with prompt: {api_request.prompt[:100]}...")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=current_user.id,
            api_key_id=api_key_id,
            tokens_to_use=2000  # Estimated tokens for code generation
        )
        
        if limits.is_over_limit:
            # Log the limit breach for monitoring
            logger.warning(f"Rate limit exceeded for user {current_user.id}: {limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=limits.limit_exceeded_reason or f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage service unavailable: {e}")
        # SECURITY FIX: Fail closed instead of open
        raise HTTPException(
            status_code=503,
            detail="Usage tracking service temporarily unavailable. Please try again later."
        )
    
    try:
        # Analysis is now handled by the separate /generate-proposal endpoint
        # This endpoint assumes the proposal has already been approved and we're ready to build
        logger.info("Starting API code generation (analysis should be done via /generate-proposal)")
        
        # Initialize analysis_result for backward compatibility with debug info
        analysis_result = "Analysis skipped - using dedicated proposal endpoint"
        
        # Validate Claude API key
        if not settings.CLAUDE_API_KEY:
            logger.error("Claude API key not configured")
            raise HTTPException(
                status_code=500, 
                detail="Claude API key not configured"
            )
        
        # Use multi-step generation by default, single-step only if explicitly disabled
        if not api_request.use_multi_step == False:  # Default to multi-step
            logger.info(f"Using multi-step generation for user {current_user.id}")
            
            # Multi-step generation in normal mode
            session_id = await multi_step_generation_service.start_generation(
                prompt=api_request.prompt,
                user_id=current_user.id,
                sample_input=api_request.sample_input,
                expected_output=api_request.expected_output,
                api_key_id=api_key_id,
                pipeline_name=api_request.pipeline_name or "full_pipeline",
                mode=GenerationMode("normal")
            )
            
            # Execute all steps and get final result
            result = await multi_step_generation_service.generate_normal_mode(session_id)
            await multi_step_generation_service.cleanup_session(session_id)
            
            if result["success"]:
                raw_code = result.get("final_code")
                if not raw_code:
                    logger.error("Multi-step generation succeeded but returned no code")
                    raise HTTPException(
                        status_code=500,
                        detail="Multi-step generation completed but no code was generated"
                    )
                logger.info("Multi-step code generation completed successfully")
                logger.debug(f"Generated code preview: {raw_code[:300]}...")
            else:
                logger.error(f"Multi-step generation failed: {result.get('error', 'Unknown error')}")
                raise HTTPException(
                    status_code=500,
                    detail=f"Multi-step generation failed: {result.get('error', 'Unknown error')}"
                )
        
        else:
            # Legacy single-step generation (only when explicitly disabled)
            logger.info("Using legacy single-step generation...")
            raw_code = await claude_service.generate_api_code(
                prompt=api_request.prompt,
                sample_input=api_request.sample_input,
                expected_output=api_request.expected_output,
                user_id=current_user.id,
                api_key_id=api_key_id
            )
            logger.info("Code generation completed successfully")
            logger.debug(f"Generated code preview: {raw_code[:300]}...")
        
        # Debug and fix the generated code
        logger.info("Analyzing and fixing generated code...")
        code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
            raw_code, api_request.prompt, current_user.id, api_key_id
        )
        
        if issues_found:
            logger.info(f"Code debugger found {len(issues_found)} issues: {issues_found}")
        if fixes_applied:
            logger.info(f"Code debugger applied {len(fixes_applied)} fixes: {fixes_applied}")
        
        # Validate code for security
        logger.info("Validating debugged code for security...")
        is_safe, violations = security_service.validate_code(code)
        logger.info(f"Security validation result: safe={is_safe}, violations={len(violations)}")
        if violations:
            logger.warning(f"Security violations found: {violations}")
        if not is_safe:
            logger.error(f"Code failed security validation: {violations}")
            raise HTTPException(
                status_code=400,
                detail=f"Generated code failed security validation: {'; '.join(violations)}"
            )
        
        # Generate API slug
        api_slug = file_service.generate_api_slug(
            user_id=current_user.id,
            api_name=api_request.api_name
        )
        
        # Remove user_id prefix for clean slug
        clean_slug = api_slug.replace(f"{current_user.id}_", "")
        
        # Save the code
        await file_service.save_api_code(api_slug, code)
        
        # Generate documentation
        documentation, openapi_spec, curl_example = await openai_service.generate_documentation(
            code=code, 
            prompt=api_request.prompt,
            user_id=current_user.id,
            api_key_id=api_key_id,
            api_slug=clean_slug
        )
        
        # Build endpoint URL
        endpoint_url = f"{settings.API_PREFIX}/{current_user.id}/{clean_slug}"
        
        # Update curl example with actual endpoint
        if "your-endpoint-url" in curl_example:
            curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
        
        # Save API documentation and metadata to database
        try:
            save_request = SaveAPIRequest(
                user_id=current_user.id,
                api_slug=clean_slug,
                api_name=api_request.api_name or f"API {clean_slug}",
                prompt=api_request.prompt,
                endpoint_url=endpoint_url,
                documentation=documentation,
                curl_example=curl_example,
                openapi_spec=json.dumps(openapi_spec) if openapi_spec else None,
                sample_input=api_request.sample_input,
                expected_output=api_request.expected_output
            )
            await file_service.save_api_metadata(save_request)
            logger.info(f"API documentation saved to database for {clean_slug}")
        except Exception as e:
            logger.warning(f"Failed to save API documentation to database: {e}")
            # Continue without database save if service is unavailable
        
        # Save API metadata for pricing using actual generation data
        try:
            # Use the actual AI model that was used for generation
            ai_model_used = settings.CLAUDE_MODEL  # The model you actually used
            
            # TODO: Add a more sophisticated complexity detection logic
            # Determine complexity based on code analysis
            complexity = 'simple'
            if len(code) > 2000 or "class" in code or "async def" in code:
                complexity = 'complex'
            elif len(code) > 1000 or "try:" in code or "except:" in code:
                complexity = 'medium'
            
            # Use sophisticated token estimation based on the actual prompt and response
            estimated_input_tokens, estimated_output_tokens = usage_service.calculate_estimated_tokens(
                model_name=ai_model_used,
                system_prompt="",  # Add system prompt if you have it
                user_prompt=api_request.prompt,
                response_length=len(code),
                success=True
            )
            estimated_tokens_per_call = estimated_input_tokens + estimated_output_tokens
            
            logger.info(f"AI model used: {ai_model_used}, estimated tokens: {estimated_tokens_per_call}, complexity: {complexity}")
            
            await api_pricing_service.save_api_metadata(
                api_slug=clean_slug,
                user_id=current_user.id,
                ai_model_used=ai_model_used,
                estimated_tokens_per_call=estimated_tokens_per_call,
                base_complexity=complexity
            )
        except Exception as e:
            logger.warning(f"Failed to save API metadata: {e}")
            # Continue without metadata if service is unavailable
        
        return APIGenerationResponse(
            success=True,
            message="API generated successfully!",
            endpoint_url=endpoint_url,
            documentation=documentation,
            curl_example=curl_example,
            api_slug=clean_slug,
            user_id=current_user.id,
            generated_at=datetime.now(),
            debug_info={
                "issues_found": issues_found,
                "fixes_applied": fixes_applied,
                "code_quality": "high" if not issues_found else "improved",
                "chat_analysis": analysis_result
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in generate_api: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate API: {str(e)}"
        )

@app.post("/modify-api", response_model=APIModificationResponse)
async def modify_api(
    modification_request: APIModificationRequest,
    request: Request,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Modify an existing API's code based on user prompt.
    
    This endpoint focuses on modifying the actual generated code of an existing API.
    For proposal-level modifications, use the /modify-proposal endpoint instead.
    
    The endpoint assumes the modification request has been validated and is ready
    to be applied to the existing code.
    """
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Modifying API {request.api_slug} for user {request.user_id} with prompt: {request.prompt[:100]}...")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=request.user_id,
            api_key_id=api_key_id,
            tokens_to_use=1500  # Estimated tokens for code modification
        )
        
        if limits.is_over_limit:
            # Log the limit breach for monitoring
            logger.warning(f"Rate limit exceeded for user {request.user_id}: {limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=limits.limit_exceeded_reason or f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Usage service unavailable: {e}")
        # SECURITY FIX: Fail closed instead of open
        raise HTTPException(
            status_code=503,
            detail="Usage tracking service temporarily unavailable. Please try again later."
        )
    
    try:
        # Check if API exists
        if not file_service.api_exists(request.user_id, request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {request.user_id}/{request.api_slug}"
            )
        
        # Load existing code
        existing_code = file_service.load_api_code(request.user_id, request.api_slug)
        
        # Analysis is now handled by the separate /modify-proposal endpoint
        # This endpoint focuses on applying validated modifications to existing code
        logger.info("Starting API code modification (analysis should be done via /modify-proposal)")
        
        # Initialize analysis_result for backward compatibility with debug info
        analysis_result = "Analysis skipped - using dedicated proposal modification endpoint"
        
        # Validate Claude API key
        if not settings.CLAUDE_API_KEY:
            logger.error("Claude API key not configured")
            raise HTTPException(
                status_code=500, 
                detail="Claude API key not configured"
            )
        
        # Generate modified code using Claude
        logger.info("Calling Claude service to modify existing code...")
        raw_code = await claude_service.modify_api_code(
            prompt=request.prompt,
            sample_input=request.sample_input,
            expected_output=request.expected_output,
            existing_code=existing_code,
            user_id=request.user_id,
            api_key_id=api_key_id,
            api_slug=request.api_slug
        )
        logger.info("Code generation completed successfully")
        logger.debug(f"Generated code preview: {raw_code[:300]}...")
        
        # Debug and fix the generated code
        logger.info("Analyzing and fixing generated code...")
        code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
            raw_code, request.prompt, request.user_id, api_key_id
        )
        
        if issues_found:
            logger.info(f"Code debugger found {len(issues_found)} issues: {issues_found}")
        if fixes_applied:
            logger.info(f"Code debugger applied {len(fixes_applied)} fixes: {fixes_applied}")
        
        # Validate code for security
        logger.info("Validating debugged code for security...")
        is_safe, violations = security_service.validate_code(code)
        logger.info(f"Security validation result: safe={is_safe}, violations={len(violations)}")
        if violations:
            logger.warning(f"Security violations found: {violations}")
        if not is_safe:
            logger.error(f"Code failed security validation: {violations}")
            raise HTTPException(
                status_code=400,
                detail=f"Generated code failed security validation: {'; '.join(violations)}"
            )
        
        # Save the new code
        full_slug = f"{request.user_id}_{request.api_slug}"
        await file_service.save_api_code(full_slug, code)
        
        # Generate documentation

        if settings.GENERATE_DOCS_SERVICE == "OPENAI_SERVICE":
            doc_service = openai_service
        else:
            doc_service = claude_service

        documentation, openapi_spec, curl_example = await doc_service.generate_documentation(
            code=code, 
            prompt=request.prompt,
            user_id=request.user_id,
            api_key_id=api_key_id,
            api_slug=request.api_slug
        )
        logger.info(f"Documentation generated with {doc_service}")
        # Build endpoint URL
        endpoint_url = f"{settings.API_PREFIX}/{request.user_id}/{request.api_slug}"
        
        # Update curl example with actual endpoint
        if "your-endpoint-url" in curl_example:
            curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
        
        return APIModificationResponse(
            success=True,
            message="API modified successfully!",
            endpoint_url=endpoint_url,
            documentation=documentation,
            curl_example=curl_example,
            api_slug=request.api_slug,
            user_id=request.user_id,
            modified_at=datetime.now(),
            debug_info={
                "issues_found": issues_found,
                "fixes_applied": fixes_applied,
                "code_quality": "high" if not issues_found else "improved",
                "chat_analysis": analysis_result
            }
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in modify_api: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to modify API: {str(e)}"
        )

# Multi-Step Generation Endpoints

# Removed streaming endpoints - using normal mode multi-step generation instead

@app.get("/generation-pipelines", response_model=PipelineInfoResponse)
async def get_available_pipelines():
    """
    Get information about available generation pipelines.
    """
    logger.info("Getting available generation pipelines")
    
    pipeline_info = await multi_step_generation_service.get_available_pipelines()
    return PipelineInfoResponse(
        success=True,
        **pipeline_info
    )

@app.post("/save-api", response_model=SaveAPIResponse)
async def save_api(request: SaveAPIRequest):
    """
    Save an API with its metadata for later access.
    """
    logger.info(f"Saving API {request.api_slug} for user {request.user_id}")
    try:
        # Check if API exists
        if not file_service.api_exists(request.user_id, request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {request.user_id}/{request.api_slug}"
            )
        
        # Check if already saved
        if file_service.is_api_saved(request.user_id, request.api_slug):
            return SaveAPIResponse(
                success=True,
                message="API is already saved",
                api_slug=request.api_slug
            )
        
        # Save the metadata
        saved_api = await file_service.save_api_metadata(request)
        
        return SaveAPIResponse(
            success=True,
            message="API saved successfully!",
            api_slug=request.api_slug
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error saving API: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to save API: {str(e)}"
        )

@app.post("/api/{user_id}/{api_slug}", response_model=APIExecutionResponse)
async def execute_api(
    user_id: str, 
    api_slug: str,
    input_data: Optional[APIInputData] = Body(None),
    current_user: Optional[User] = Depends(get_current_user_or_api_key),
):
    logger.info(f"Executing API {api_slug} for user {user_id}")
    logger.info(f"Input data: {input_data}")
    logger.info(f"Current user: {current_user}")
    """
    Execute a generated API.
    """
    start_time = time.time()
    
    try:
        # Check if API exists
        if not file_service.api_exists(user_id, api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {user_id}/{api_slug}"
            )
        
        # Prepare input data
        file_bytes = None
        parsed_input_data = None
        
        if input_data:
            parsed_input_data = input_data.dict()
        else:
            raise HTTPException(
                status_code=400,
                detail="Missing input data"
            )

        api_key = input_data.apikey
        
        validated_key = api_key_service.validate_api_key(api_key)
        if not validated_key:
            raise HTTPException(
                status_code=401,
                detail="Invalid API key"
            )

        # Calculate input data size for limits check
        input_data_size = api_execution_usage_service._calculate_data_size(parsed_input_data)
        
        # Get API execution cost and check token balance
        try:
            api_cost = await api_pricing_service.get_api_execution_cost(
                api_slug=api_slug,
                user_id=user_id
            )
            
            # Check internal token balance
            token_balance = await api_pricing_service.get_token_balance(
                user_id=user_id,  # Use API owner's user ID, not the API key's user ID
                api_key_id=None
            )
            
            if token_balance.remaining_tokens < api_cost.internal_tokens_per_call:
                raise HTTPException(
                    status_code=402,  # Payment Required
                    detail=f"Insufficient internal tokens. Need {api_cost.internal_tokens_per_call}, have {token_balance.remaining_tokens}"
                )
                
        except HTTPException:
            raise
        except Exception as e:
            logger.warning(f"Failed to check API pricing: {e}")
            # Use default pricing if service is unavailable
            api_cost = None
        
        # Check execution limits before proceeding
        try:
            limits = await api_execution_usage_service.check_execution_limits(
                user_id=validated_key.user_id,
                api_key_id=validated_key.id,
                data_size_to_use=input_data_size
            )
            
            if limits.is_over_execution_limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Daily execution limit exceeded: {limits.daily_executions_used}/{limits.daily_execution_limit}"
                )
            
            if limits.is_over_data_limit:
                raise HTTPException(
                    status_code=429,
                    detail=f"Daily data limit exceeded: {limits.daily_data_used_bytes}/{limits.daily_data_limit_bytes} bytes"
                )
        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"Execution limits service unavailable: {e}")
            # SECURITY FIX: Fail closed instead of open
            raise HTTPException(
                status_code=503,
                detail="Rate limiting service temporarily unavailable. Please try again later."
            )

        # Execute the API with timeout
        try:
            result = await file_service.load_and_execute_api(
                user_id=user_id,
                api_slug=api_slug,
                file_bytes=file_bytes,
                input_data=parsed_input_data
            )
        except HTTPException as e:
            if e.status_code == 408:  # Timeout
                execution_time = time.time() - start_time
                execution_time_ms = int(execution_time * 1000)
                
                # Record timeout in usage stats
                await api_execution_usage_service.record_execution_usage(
                    user_id=validated_key.user_id,
                    api_key_id=validated_key.id,
                    api_slug=api_slug,
                    execution_time_ms=execution_time_ms,
                    input_data_size=input_data_size,
                    output_data_size=0,
                    success=False,
                    error_message="Execution timeout"
                )
                
                raise HTTPException(
                    status_code=408,
                    detail="API execution timed out"
                )
            raise
        
        execution_time = time.time() - start_time
        execution_time_ms = int(execution_time * 1000)
        output_data_size = api_execution_usage_service._calculate_data_size(result)
        
        # Record successful execution usage and deduct internal tokens
        try:
            await api_execution_usage_service.record_execution_usage(
                user_id=validated_key.user_id,
                api_key_id=validated_key.id,
                api_slug=api_slug,
                execution_time_ms=execution_time_ms,
                input_data_size=input_data_size,
                output_data_size=output_data_size,
                success=True
            )
            
            # Deduct internal tokens if pricing is available
            if api_cost:
                await api_pricing_service.deduct_tokens_for_execution(
                    user_id=user_id,  # Use API owner's user ID
                    api_key_id=None,
                    api_slug=api_slug,
                    internal_tokens_needed=api_cost.internal_tokens_per_call,
                    cost_cents=api_cost.cost_per_call_cents,
                    execution_successful=True
                )
        except Exception as e:
            logger.warning(f"Failed to record execution usage: {e}")
        
        return APIExecutionResponse(
            success=True,
            result=result,
            execution_time=execution_time
        )
        
    except HTTPException:
        raise
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"API not found: {user_id}/{api_slug}"
        )
    except Exception as e:
        execution_time = time.time() - start_time
        execution_time_ms = int(execution_time * 1000)
        logger.error(f"API execution error: {str(e)}", exc_info=True)
        
        # Record failed execution usage if we have validated key
        try:
            if 'validated_key' in locals() and validated_key:
                input_size = api_execution_usage_service._calculate_data_size(parsed_input_data) if 'parsed_input_data' in locals() else 0
                await api_execution_usage_service.record_execution_usage(
                    user_id=validated_key.user_id,
                    api_key_id=validated_key.id,
                    api_slug=api_slug,
                    execution_time_ms=execution_time_ms,
                    input_data_size=input_size,
                    output_data_size=0,
                    success=False,
                    error_message=str(e)
                )
        except Exception as usage_error:
            logger.warning(f"Failed to record failed execution usage: {usage_error}")
        
        return APIExecutionResponse(
            success=False,
            error=str(e),
            execution_time=execution_time
        )

@app.get("/api/{user_id}", response_model=ListAPIsResponse)
async def list_user_apis(user_id: str):
    """
    List all saved APIs with full metadata for a specific user.
    """
    try:
        saved_apis = file_service.get_user_apis(user_id)
        return ListAPIsResponse(
            success=True,
            user_id=user_id,
            apis=saved_apis,
            count=len(saved_apis)
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list APIs: {str(e)}"
        )
        
@app.get("/api/{user_id}/basic")
async def list_user_apis_basic(user_id: str):
    """
    List basic API info for a specific user (legacy endpoint).
    """
    try:
        apis = file_service.get_user_apis_basic(user_id)
        return {
            "success": True,
            "user_id": user_id,
            "apis": apis,
            "count": len(apis)
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list APIs: {str(e)}"
        )

@app.delete("/api/{user_id}/{api_slug}")
async def delete_api(user_id: str, api_slug: str):
    """
    Delete a specific API.
    """
    try:
        success = file_service.delete_api(user_id, api_slug)
        if success:
            return {
                "success": True,
                "message": f"API {user_id}/{api_slug} deleted successfully"
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {user_id}/{api_slug}"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete API: {str(e)}"
        )

@app.delete("/saved-apis/{api_slug}")
async def delete_saved_api(api_slug: str, current_user: User = Depends(require_active_user)):
    """
    Delete a specific saved API for the current authenticated user.
    This endpoint is used by the profile page.
    """
    try:
        success = file_service.delete_api(current_user.id, api_slug)
        if success:
            return {
                "success": True,
                "message": f"API {api_slug} deleted successfully"
            }
        else:
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {api_slug}"
            )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete API: {str(e)}"
        )

@app.get("/api/{user_id}/{api_slug}/apidetails")
async def apidetails(user_id: str, api_slug: str):
    """
    Get details of a specific API.
    """
    try:
        api_details = file_service.get_api_details(user_id, api_slug)
        return api_details
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get API details: {str(e)}"
        )

@app.get("/api/{user_id}/{api_slug}/openapi")
async def get_openapi_spec(request: Request, user_id: str, api_slug: str):
    """
    Get OpenAPI specification for a specific API.
    """
    try:
        api_details = file_service.get_api_details(user_id, api_slug)
        
        # Check if we have OpenAPI spec in the details
        if 'openapi_spec' in api_details and api_details['openapi_spec']:
            try:
                # Parse the JSON string back to dict
                openapi_spec = json.loads(api_details['openapi_spec'])
                return openapi_spec
            except (json.JSONDecodeError, TypeError):
                logger.warning(f"Failed to parse stored OpenAPI spec for {api_slug}, falling back to basic spec")
                pass  # Fall through to generate basic spec
        
        # If not available, generate a basic OpenAPI spec
        base_url = f"{settings.API_PREFIX}/{user_id}/{api_slug}"
        basic_spec = {
            "openapi": "3.0.0",
            "info": {
                "title": api_details.get('api_name', f"API {api_slug}"),
                "description": api_details.get('prompt', 'API endpoint for processing requests'),
                "version": "1.0.0"
            },
            "servers": [
                {
                    "url": str(request.base_url).rstrip('/'),
                    "description": "Production server"
                }
            ],
            "paths": {
                f"/{user_id}/{api_slug}": {
                    "post": {
                        "summary": "Process API request",
                        "description": api_details.get('prompt', 'API endpoint for processing requests'),
                        "requestBody": {
                            "required": True,
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "data": {
                                                "type": "object",
                                                "description": "Request payload"
                                            }
                                        }
                                    }
                                }
                            }
                        },
                        "responses": {
                            "200": {
                                "description": "Successful response",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "success": {
                                                    "type": "boolean"
                                                },
                                                "data": {
                                                    "type": "object"
                                                }
                                            }
                                        }
                                    }
                                }
                            },
                            "400": {
                                "description": "Bad request",
                                "content": {
                                    "application/json": {
                                        "schema": {
                                            "type": "object",
                                            "properties": {
                                                "error": {
                                                    "type": "string"
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        
        return basic_spec
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get OpenAPI specification: {str(e)}"
        )

@app.get("/api/{user_id}/{api_slug}/code")
async def get_api_code(user_id: str, api_slug: str):
    """
    Get the source code of a specific API.
    """
    try:
        code = file_service.load_api_code(user_id, api_slug)
        return {"success": True, "code": code}
    except FileNotFoundError:
        raise HTTPException(
            status_code=404,
            detail=f"API not found: {user_id}/{api_slug}"
        )
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get API code: {str(e)}"
        )

@app.post("/test-api", response_model=TestResponse)
async def test_api(request: TestRequest):
    """
    Test a specific API with the provided test data.
    This endpoint provides structured testing functionality with proper error handling.
    """
    import uuid
    print("=== TEST-API ENDPOINT CALLED ===")
    print(f"Request: {request}")
    print(f"User ID: {request.user_id}")
    print(f"API Slug: {request.api_slug}")
    print("testing function")
    logger.info("=== TEST-API ENDPOINT REACHED ===")
    logger.info(f"Testing API {request.api_slug} for user {request.user_id}")
    start_time = time.time()
    test_id = str(uuid.uuid4())
    debugged = False
    try:
        # Check if API exists
        if not file_service.api_exists(request.user_id, request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {request.user_id}/{request.api_slug}"
            )
        
        # Prepare input data
        file_bytes = None
        parsed_input_data = request.test_data
        
        # Handle file data if provided
        if request.file_data:
            try:
                file_bytes = base64.b64decode(request.file_data)
                
                # Validate file size
                if len(file_bytes) > settings.MAX_FILE_SIZE:
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE} bytes"
                    )
            except Exception as e:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid file data: {str(e)}"
                )
        
        # Execute the API
        try:
            result = await file_service.load_and_execute_api(
                user_id=request.user_id,
                api_slug=request.api_slug,
                file_bytes=file_bytes,
                input_data=parsed_input_data,
            )
            
            execution_time = time.time() - start_time
            
            # Format response data
            if isinstance(result, dict):
                response_data = result
                status_code = 200
            else:
                response_data = {"result": result}
                status_code = 200
                
        except Exception as api_error:
            execution_time = time.time() - start_time
            print(f"API execution failed with error: {api_error}")
            print(f"Error type: {type(api_error)}")
            logger.error(f"API execution error: {str(api_error)}", exc_info=True)
            
            # Create error response
            error_response = TestResponse(
                success=False,
                test_id=test_id,
                api_slug=request.api_slug,
                user_id=request.user_id,
                request_data=parsed_input_data,
                response_data=None,
                error=str(api_error),
                execution_time=execution_time,
                status_code=500,
                response_headers={},
                timestamp=datetime.now(),
                test_type=request.test_type or "manual",
                validation=None,
                debugged=debugged
            )
            
            # Automatically attempt to fix the code when there's an execution error
            "TODO CHANGE THIS WITH SPECIFIC DEBUGER FUNCTION"
            logger.info(f"API execution failed, attempting automatic code fix...")
            try:
                # Load current API code
                current_code = file_service.load_api_code(request.user_id, request.api_slug)
                
                # Use comprehensive debug functionality to fix the code
                debug_result = await code_debugger.validate_and_fix_test_result(
                    code=current_code,
                    test_request=request.dict(),
                    test_response=error_response.dict(),
                    user_id=request.user_id,
                    api_slug=request.api_slug
                )
                
                # If code was fixed, save it automatically with backup
                if debug_result.get("fixed_code"):
                    logger.info(f"Code fixes found for execution error: {debug_result.get('fixes_applied', [])}")
                    debugged = True
                    # Create backup of current code
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_slug = f"{request.api_slug}_backup_{timestamp}"
                    
                    # Save backup
                    await file_service.save_api_code(f"{request.user_id}_{backup_slug}", current_code)
                    
                    # Save fixed code
                    await file_service.save_api_code(f"{request.user_id}_{request.api_slug}", debug_result["fixed_code"])
                    
                    # Add debug information to the error response
                    error_response.validation = {
                        "is_valid": False,
                        "confidence": debug_result.get("validation_confidence", 0.0),
                        "validation_message": debug_result.get("validation_message", "Execution error automatically fixed"),
                        "issues_found": debug_result.get("issues_found", []),
                        "auto_fix_applied": True,
                        "fixes_applied": debug_result.get("fixes_applied", []),
                        "backup_slug": backup_slug,
                        "debug_info": debug_result.get("debug_info"),
                        "code_fixed_at": datetime.now().isoformat(),
                        "validator": "code_debugger"
                    }
                    
                    logger.info(f"Code automatically fixed for execution error. Backup: {backup_slug}")
                    
                else:
                    logger.info("No code fixes were generated for execution error")
                    error_response.validation = {
                        "is_valid": False,
                        "confidence": 0.0,
                        "validation_message": "Execution error occurred but no fixes available",
                        "auto_fix_applied": False,
                        "auto_fix_reason": "No fixable issues detected",
                        "validator": "code_debugger"
                    }
            
            except Exception as debug_error:
                logger.error(f"Automatic code fix failed for execution error: {str(debug_error)}")
                error_response.validation = {
                    "is_valid": False,
                    "confidence": 0.0,
                    "validation_message": "Execution error occurred and auto-fix failed",
                    "auto_fix_applied": False,
                    "auto_fix_error": str(debug_error),
                    "validator": "code_debugger"
                }
            
            return error_response
        
        # Build response headers
        response_headers = {
            "content-type": "application/json",
            "x-execution-time": f"{execution_time:.3f}s",
            "x-test-id": test_id
        }
        
        # Get cost estimation for this API execution
        cost_estimation = None
        try:
            api_cost = await api_pricing_service.get_api_execution_cost(
                api_slug=request.api_slug,
                user_id=request.user_id
            )
            cost_estimation = {
                "cost_per_call_cents": api_cost.cost_per_call_cents,
                "internal_tokens_per_call": api_cost.internal_tokens_per_call,
                "ai_model_used": api_cost.ai_model_used,
                "complexity_multiplier": api_cost.complexity_multiplier,
                "estimated_tokens_used": api_cost.estimated_tokens_used
            }
        except Exception as e:
            logger.warning(f"Failed to get cost estimation for test: {e}")
            # Provide default cost estimation during testing
            cost_estimation = {
                "cost_per_call_cents": 2,  # Default 2 cents
                "internal_tokens_per_call": 20,  # Default 20 internal tokens
                "ai_model_used": "estimated",
                "complexity_multiplier": 1.5,
                "estimated_tokens_used": 1000
            }
        
        # Prepare the basic test response
        test_response = TestResponse(
            success=True,
            test_id=test_id,
            api_slug=request.api_slug,
            user_id=request.user_id,
            request_data=parsed_input_data,
            response_data=response_data,
            error=None,
            execution_time=execution_time,
            status_code=status_code,
            response_headers=response_headers,
            timestamp=datetime.now(),
            test_type=request.test_type or "manual",
            validation=None,
            debugged=debugged
        )
        
        # Add cost estimation to response headers for display
        if cost_estimation:
            response_headers.update({
                "x-cost-per-call-cents": str(cost_estimation["cost_per_call_cents"]),
                "x-internal-tokens-per-call": str(cost_estimation["internal_tokens_per_call"]),
                "x-ai-model-used": cost_estimation["ai_model_used"]
            })
            test_response.response_headers = response_headers
        
        # Automatically validate successful responses (200 status code)
        if status_code == 200:
            try:
                logger.info(f"Automatically validating successful test result for test {test_id}")
                validation_result = await test_service.validate_test_result(request, test_response)
                test_response.validation = validation_result
                logger.info(f"Test result: {test_response}")
                logger.info(f"Validation completed. Valid: {validation_result.get('is_valid', False)}, Confidence: {validation_result.get('confidence', 0.0)}")

                # If test result is invalid, automatically attempt to fix the code
                if not validation_result.get('is_valid', False) and settings.ENABLE_TEST_VALIDATION_DEBUGGING:
                    logger.info(f"Test result is invalid, attempting automatic code fix...")
                    
                    try:
                        # Load current API code
                        current_code = file_service.load_api_code(request.user_id, request.api_slug)
                        
                        # Use comprehensive debug functionality to fix the code
                        debug_result = await code_debugger.validate_and_fix_test_result(
                            code=current_code,
                            test_request=request.dict(),
                            test_response=test_response.dict(),
                            user_id=request.user_id,
                            api_slug=request.api_slug
                        )
                        
                        # If code was fixed, save it automatically with backup
                        if debug_result.get("fixed_code"):
                            logger.info(f"Code fixes found: {debug_result.get('fixes_applied', [])}")
                            
                            # Create backup of current code
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            backup_slug = f"{request.api_slug}_backup_{timestamp}"
                            
                            # Save backup
                            await file_service.save_api_code(f"{request.user_id}_{backup_slug}", current_code)
                            
                            # Save fixed code
                            await file_service.save_api_code(f"{request.user_id}_{request.api_slug}", debug_result["fixed_code"])
                            
                            # Add debug information to the test response
                            test_response.validation.update({
                                "auto_fix_applied": True,
                                "fixes_applied": debug_result.get("fixes_applied", []),
                                "backup_slug": backup_slug,
                                "debug_info": debug_result.get("debug_info"),
                                "code_fixed_at": datetime.now().isoformat()
                            })
                            
                            logger.info(f"Code automatically fixed and saved. Backup: {backup_slug}")
                            
                        else:
                            logger.info("No code fixes were generated")
                            test_response.validation.update({
                                "auto_fix_applied": False,
                                "auto_fix_reason": "No fixable issues detected"
                            })
                    
                    except Exception as debug_error:
                        logger.error(f"Automatic code fix failed: {str(debug_error)}")
                        test_response.validation.update({
                            "auto_fix_applied": False,
                            "auto_fix_error": str(debug_error)
                        })

                return test_response

            except Exception as validation_error:
                logger.error(f"Validation failed: {str(validation_error)}")
                test_response.validation = {
                    "is_valid": False,
                    "confidence": 0.0,
                    "validation_message": f"Validation failed: {str(validation_error)}",
                    "issues_found": [f"Validation error: {str(validation_error)}"],
                    "suggestions": ["Check OpenAI service and retry"],
                    "reasoning": "Validation process encountered an error",
                    "validated_at": datetime.now().isoformat(),
                    "validator": "openai",
                    "test_id": test_id,
                    "error": str(validation_error)
                }
        
        return test_response
        
    except HTTPException:
        raise
    except Exception as e:
        execution_time = time.time() - start_time
        logger.error(f"Test endpoint error: {str(e)}", exc_info=True)
        
        return TestResponse(
            success=False,
            test_id=test_id,
            api_slug=request.api_slug,
            user_id=request.user_id,
            request_data=parsed_input_data,
            response_data=None,
            error=f"Test execution failed: {str(e)}",
            execution_time=execution_time,
            status_code=500,
            response_headers={},
            timestamp=datetime.now(),
            test_type=request.test_type or "manual",
            validation=None
        )

@app.get("/generate-test-data/{user_id}/{api_slug}")
async def generate_test_data(user_id: str, api_slug: str):
    """
    Generate intelligent test data for an API using AI based on its documentation.
    Uses a cheap model (gpt-4o-mini) to generate realistic test scenarios.
    """
    try:
        logger.info(f"Generating test data for API {api_slug} of user {user_id}")
        
        # Check if API exists
        if not file_service.api_exists(user_id, api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {user_id}/{api_slug}"
            )
        
        # Generate test data using the test service
        test_scenarios = await test_service.generate_test_data(user_id, api_slug)
        
        logger.info(f"Generated {len(test_scenarios)} test scenarios for {api_slug}")
        
        return {
            "success": True,
            "api_slug": api_slug,
            "user_id": user_id,
            "test_scenarios": test_scenarios,
            "count": len(test_scenarios),
            "generated_at": datetime.now().isoformat(),
            "model_used": "gpt-4o-mini"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate test data for {api_slug}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate test data: {str(e)}"
        )

# API Execution Usage Endpoints

@app.get("/api-execution-stats", response_model=APIExecutionStatsResponse)
async def get_api_execution_stats(
    request: Request,
    days: int = 30,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """Get API execution statistics for the current user."""
    try:
        stats = await api_execution_usage_service.get_execution_stats(
            user_id=current_user.id,
            api_key_id=api_key_id,
            days=days
        )
        return stats
    except Exception as e:
        secure_error = create_secure_error(
            status_code=500,
            category='api',
            internal_error=e,
            user_message='Unable to retrieve execution statistics at this time.',
            user_id=current_user.id,
            context={'endpoint': '/api-execution-stats'}
        )
        raise secure_error.to_http_exception()

@app.get("/api-execution-limits", response_model=APIExecutionLimitsResponse)
async def get_api_execution_limits(
    request: Request,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """Get API execution limits and current usage for the current user."""
    try:
        limits = await api_execution_usage_service.check_execution_limits(
            user_id=current_user.id,
            api_key_id=api_key_id
        )
        return limits
    except Exception as e:
        logger.error(f"Failed to get API execution limits: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution limits: {str(e)}")

@app.get("/api-execution-stats/{api_slug}", response_model=APIExecutionStatsResponse)
async def get_api_execution_stats_by_slug(
    api_slug: str,
    days: int = 30,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Get API execution statistics for a specific API."""
    try:
        # Get all stats first, then filter by API slug
        stats = await api_execution_usage_service.get_execution_stats(
            user_id=current_user.id,
            api_key_id=api_key_id,
            days=days
        )
        
        # Filter stats for specific API
        if api_slug in stats.by_api:
            api_stats = stats.by_api[api_slug]
            # Filter recent executions for this API
            filtered_recent = [
                execution for execution in stats.recent_executions 
                if execution.api_slug == api_slug
            ]
            
            return APIExecutionStatsResponse(
                user_id=stats.user_id,
                api_key_id=stats.api_key_id,
                total_executions=api_stats['executions'],
                successful_executions=api_stats['successful'],
                failed_executions=api_stats['failed'],
                total_execution_time_ms=api_stats['total_time_ms'],
                average_execution_time_ms=api_stats['total_time_ms'] / api_stats['executions'] if api_stats['executions'] > 0 else 0,
                total_data_processed_bytes=api_stats['data_bytes'],
                by_api={api_slug: api_stats},
                recent_executions=filtered_recent,
                period_start=stats.period_start,
                period_end=stats.period_end
            )
        else:
            # No usage found for this API
            return APIExecutionStatsResponse(
                user_id=current_user.id,
                api_key_id=api_key_id,
                total_executions=0,
                successful_executions=0,
                failed_executions=0,
                total_execution_time_ms=0,
                average_execution_time_ms=0,
                total_data_processed_bytes=0,
                by_api={},
                recent_executions=[],
                period_start=stats.period_start,
                period_end=stats.period_end
            )
    except Exception as e:
        logger.error(f"Failed to get API execution stats for {api_slug}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution stats: {str(e)}")

# Internal Token and Pricing Endpoints

@app.get("/internal-token-balance", response_model=InternalTokenBalance)
async def get_internal_token_balance(
    request: Request,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """Get current internal token balance for the user."""
    try:
        balance = await api_pricing_service.get_token_balance(
            user_id=current_user.id,
            api_key_id=api_key_id
        )
        return balance
    except Exception as e:
        logger.error(f"Failed to get token balance: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get token balance: {str(e)}")

@app.get("/separated-token-balance", response_model=SeparatedTokenBalance)
async def get_separated_token_balance(
    request: Request,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """Get separated token balance (generation vs execution) for the user."""
    try:
        balance = await api_pricing_service.get_separated_token_balance(
            user_id=current_user.id,
            api_key_id=api_key_id
        )
        return balance
    except Exception as e:
        logger.error(f"Failed to get separated token balance: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get separated token balance: {str(e)}")

@app.post("/allocate-monthly-tokens")
async def allocate_monthly_tokens(
    monthly_request: CreateInternalTokenRequest,
    request: Request,
    current_user: User = Depends(require_auth_hybrid)
):
    """Allocate monthly tokens to the user (admin function or monthly allocation)."""
    try:
        token = await api_pricing_service.allocate_monthly_tokens(
            user_id=current_user.id,
            api_key_id=None,
            amount=monthly_request.amount,
            source=monthly_request.source
        )
        return {"success": True, "message": f"Allocated {token.amount} tokens", "token_id": token.id}
    except Exception as e:
        logger.error(f"Failed to allocate tokens: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to allocate tokens: {str(e)}")

@app.post("/estimate-api-cost", response_model=EstimateAPIUsageCostResponse)
async def estimate_api_usage_cost(
    request: EstimateAPIUsageCostRequest,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Estimate the cost and tokens needed for API usage."""
    try:
        estimate = await api_pricing_service.estimate_api_usage_cost(request)
        return estimate
    except Exception as e:
        logger.error(f"Failed to estimate API cost: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to estimate API cost: {str(e)}")

@app.get("/api-cost/{api_slug}")
async def get_api_execution_cost(
    api_slug: str,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Get the execution cost for a specific API."""
    try:
        cost = await api_pricing_service.get_api_execution_cost(
            api_slug=api_slug,
            user_id=current_user.id
        )
        return {
            "api_slug": cost.api_slug,
            "cost_per_call_cents": cost.cost_per_call_cents,
            "internal_tokens_per_call": cost.internal_tokens_per_call,
            "ai_model_used": cost.ai_model_used,
            "complexity_multiplier": cost.complexity_multiplier,
            "estimated_tokens_used": cost.estimated_tokens_used,
            "last_calculated": cost.last_calculated
        }
    except Exception as e:
        logger.error(f"Failed to get API cost: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get API cost: {str(e)}")

# Logging Endpoints
@app.post("/logs/system", response_model=LogsResponse)
async def get_system_logs(
    request: LogsRequest,
    current_user: User = Depends(require_auth)
):
    """Get system logs with filters"""
    try:
        logs = await logging_service.get_logs(
            level=LogLevel(request.level) if request.level else None,
            category=LogCategory(request.category) if request.category else None,
            user_id=request.user_id,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset
        )
        
        return LogsResponse(
            success=True,
            logs=[],  # Convert to pydantic models
            total_count=len(logs),
            has_more=len(logs) == request.limit
        )
        
    except Exception as e:
        logger.error(f"Failed to get system logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get system logs: {str(e)}")

@app.post("/logs/http-requests", response_model=HTTPLogsResponse)
async def get_http_request_logs(
    request: HTTPLogsRequest,
    current_user: User = Depends(require_auth)
):
    """Get HTTP request logs with filters"""
    try:
        logs = await logging_service.get_http_request_logs(
            endpoint=request.endpoint,
            method=request.method,
            status_code=request.status_code,
            user_id=request.user_id,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset
        )
        
        return HTTPLogsResponse(
            success=True,
            logs=[],  # Convert to pydantic models
            total_count=len(logs),
            has_more=len(logs) == request.limit
        )
        
    except Exception as e:
        logger.error(f"Failed to get HTTP request logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get HTTP request logs: {str(e)}")

@app.post("/logs/llm-calls", response_model=LLMLogsResponse)
async def get_llm_call_logs(
    request: LLMLogsRequest,
    current_user: User = Depends(require_auth)
):
    """Get LLM call logs with filters"""
    try:
        logs = await logging_service.get_llm_call_logs(
            service_type=request.service_type,
            model_name=request.model_name,
            operation_type=request.operation_type,
            user_id=request.user_id,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset
        )
        
        return LLMLogsResponse(
            success=True,
            logs=[],  # Convert to pydantic models
            total_count=len(logs),
            has_more=len(logs) == request.limit
        )
        
    except Exception as e:
        logger.error(f"Failed to get LLM call logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get LLM call logs: {str(e)}")

@app.post("/logs/chat-messages", response_model=ChatLogsResponse)
async def get_chat_message_logs(
    request: ChatLogsRequest,
    current_user: User = Depends(require_auth)
):
    """Get chat message logs with filters"""
    try:
        logs = await logging_service.get_chat_message_logs(
            user_id=request.user_id,
            message_type=request.message_type,
            conversation_id=request.conversation_id,
            start_time=request.start_time,
            end_time=request.end_time,
            limit=request.limit,
            offset=request.offset
        )
        
        return ChatLogsResponse(
            success=True,
            logs=[],  # Convert to pydantic models
            total_count=len(logs),
            has_more=len(logs) == request.limit
        )
        
    except Exception as e:
        logger.error(f"Failed to get chat message logs: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get chat message logs: {str(e)}")

@app.get("/logs/statistics", response_model=LogStatisticsResponse)
async def get_log_statistics(
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
    current_user: User = Depends(require_auth)
):
    """Get logging statistics"""
    try:
        stats = await logging_service.get_log_statistics(
            start_time=start_time,
            end_time=end_time
        )
        
        return LogStatisticsResponse(
            success=True,
            period_start=stats.get("period_start", ""),
            period_end=stats.get("period_end", ""),
            total_logs=stats.get("total_logs", {}),
            error_count=stats.get("error_count", 0),
            statistics=stats
        )
        
    except Exception as e:
        logger.error(f"Failed to get log statistics: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get log statistics: {str(e)}")


# Admin Panel API Endpoints
@app.get("/admin/auth/check")
async def check_admin_auth(request: Request):
    """Check if the current user has admin privileges."""
    try:
        user = await require_admin_auth(request)
        return {
            "success": True,
            "is_admin": True,
            "user": {
                "email": user.email,
                "id": user.id
            }
        }
    except HTTPException as e:
        if e.status_code == 403:
            return {"success": False, "is_admin": False, "message": "Admin access required"}
        else:
            raise HTTPException(status_code=401, detail="Authentication required")

@app.get("/admin/system/status")
async def get_system_status(request: Request, admin_user: User = Depends(require_admin_auth)):
    """Get system status information."""
    return {
        "success": True,
        "environment": settings.ENVIRONMENT,
        "security_enabled": settings.SECURITY_SERVICE_ENABLED,
        "max_file_size": settings.MAX_FILE_SIZE,
        "host": settings.HOST,
        "port": settings.PORT
    }

@app.get("/admin/system/stats")
async def get_system_stats(request: Request, admin_user: User = Depends(require_admin_auth)):
    """Get system statistics."""
    try:
        # Get user count
        total_users = mongodb.users.count_documents({})
        active_users = mongodb.users.count_documents({"is_active": True})
        
        # Get API count
        total_apis = mongodb.saved_apis.count_documents({})
        
        # Get usage stats (rough estimation)
        total_tokens = 0
        try:
            # This would require aggregating from usage service
            pass
        except:
            pass
        
        return {
            "success": True,
            "total_users": total_users,
            "active_users": active_users,
            "total_apis": total_apis,
            "total_tokens": total_tokens
        }
    except Exception as e:
        logger.error(f"Failed to get system stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get system stats: {str(e)}")

@app.get("/admin/config")
async def get_admin_config(request: Request, admin_user: User = Depends(require_admin_auth)):
    """Get current system configuration (without sensitive data)."""
    return {
        "success": True,
        "openai_model": settings.OPENAI_MODEL,
        "claude_model": settings.CLAUDE_MODEL,
        "security_enabled": settings.SECURITY_SERVICE_ENABLED,
        "max_file_size": settings.MAX_FILE_SIZE,
        "environment": settings.ENVIRONMENT,
        "docs_service": settings.GENERATE_DOCS_SERVICE
    }

@app.post("/admin/config/ai")
async def update_ai_config(
    request: Request,
    config: dict = Body(...),
    admin_user: User = Depends(require_admin_auth)
):
    """Update AI service configuration."""
    try:
        # In a real implementation, you would update environment variables
        # or configuration files. For now, we'll just validate the input
        
        updated_fields = []
        
        if "openai_api_key" in config and config["openai_api_key"]:
            # In production, store this securely
            updated_fields.append("OpenAI API Key")
            
        if "openai_model" in config:
            # settings.OPENAI_MODEL = config["openai_model"]
            updated_fields.append("OpenAI Model")
            
        if "claude_api_key" in config and config["claude_api_key"]:
            # In production, store this securely
            updated_fields.append("Claude API Key")
            
        if "claude_model" in config:
            # settings.CLAUDE_MODEL = config["claude_model"]
            updated_fields.append("Claude Model")
        
        return {
            "success": True,
            "message": f"Updated: {', '.join(updated_fields)}",
            "note": "Configuration changes require service restart to take effect"
        }
    except Exception as e:
        logger.error(f"Failed to update AI config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update AI config: {str(e)}")

@app.post("/admin/config/security")
async def update_security_config(
    request: Request,
    config: dict = Body(...),
    admin_user: User = Depends(require_admin_auth)
):
    """Update security configuration."""
    try:
        updated_fields = []
        
        if "security_enabled" in config:
            # settings.SECURITY_SERVICE_ENABLED = config["security_enabled"]
            updated_fields.append("Security Service")
            
        if "max_file_size" in config:
            # settings.MAX_FILE_SIZE = config["max_file_size"]
            updated_fields.append("Max File Size")
        
        return {
            "success": True,
            "message": f"Updated: {', '.join(updated_fields)}",
            "note": "Configuration changes require service restart to take effect"
        }
    except Exception as e:
        logger.error(f"Failed to update security config: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update security config: {str(e)}")

@app.get("/admin/api-keys")
async def list_all_api_keys(
    request: Request,
    search: Optional[str] = None,
    status: Optional[str] = None,
    admin_user: User = Depends(require_admin_auth)
):
    """List all API keys in the system (admin only)."""
    try:
        # Build MongoDB query
        query = {}
        if status == "active":
            query["is_active"] = True
        elif status == "inactive":
            query["is_active"] = False
        
        # Get all API keys with filtering
        all_keys = list(mongodb.api_keys.find(query))
        
        # Filter by search if provided
        if search:
            filtered_keys = []
            for key in all_keys:
                # Check key name
                if search.lower() in key.get("key_name", "").lower():
                    filtered_keys.append(key)
                    continue
                # Check user email
                user = mongodb.users.find_one({"_id": key["user_id"]})
                if user and search.lower() in user.get("email", "").lower():
                    filtered_keys.append(key)
            all_keys = filtered_keys
        
        # Get user emails for each key
        api_keys = []
        for db_key in all_keys:
            user = mongodb.users.find_one({"_id": db_key["user_id"]})
            
            api_keys.append({
                "id": db_key["_id"],
                "key_name": db_key["key_name"],
                "user_id": db_key["user_id"],
                "user_email": user["email"] if user else "Unknown",
                "full_key": db_key["full_key"],
                "is_active": db_key["is_active"],
                "created_at": db_key["created_at"].isoformat(),
                "last_used": db_key["last_used"].isoformat() if db_key.get("last_used") else None,
                "usage_count": db_key.get("usage_count", 0),
                "expires_at": db_key["expires_at"].isoformat() if db_key.get("expires_at") else None
            })
            
            return {
                "success": True,
                "api_keys": api_keys,
                "count": len(api_keys)
            }
    except Exception as e:
        logger.error(f"Failed to list API keys: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list API keys: {str(e)}")

@app.post("/admin/api-keys")
async def create_admin_api_key(
    request: Request,
    key_data: dict = Body(...),
    admin_user: User = Depends(require_admin_auth)
):
    """Create an API key for any user (admin only)."""
    try:
        user_email = key_data.get("user_email")
        key_name = key_data.get("key_name")
        expires_at = key_data.get("expires_at")
        
        if not user_email or not key_name:
            raise HTTPException(status_code=400, detail="user_email and key_name are required")
        
        # Find user by email
        user = mongodb.users.find_one({"email": user_email})
            
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
    
        # Create API key request
        create_request = CreateAPIKeyRequest(
            key_name=key_name,
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None
        )
        
        result = api_key_service.create_api_key(user.id, create_request)
        
        return {
            "success": True,
            "api_key": result.api_key,
            "message": "API key created successfully"
        }
    except Exception as e:
        logger.error(f"Failed to create admin API key: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create admin API key: {str(e)}")

@app.get("/admin/users")
async def list_all_users(
    request: Request,
    search: Optional[str] = None,
    status: Optional[str] = None,
    admin_user: User = Depends(require_admin_auth)
):
    """List all users in the system (admin only)."""
    try:
        # Build MongoDB query
        query = {}
        if status == "active":
            query["is_active"] = True
        elif status == "inactive":
            query["is_active"] = False
        
        if search:
            query["email"] = {"$regex": search, "$options": "i"}
        
        # Get all users with filtering
        db_users = list(mongodb.users.find(query))
        
        users = [
            {
                "id": user["_id"],
                "email": user["email"],
                "is_active": user.get("is_active", True),
                "created_at": user["created_at"].isoformat(),
                "last_login": user["last_login"].isoformat() if user.get("last_login") else None,
                "subscription_tier": user.get("subscription_tier", "free"),
                "subscription_status": user.get("subscription_status", "active"),
                "oauth_provider": user.get("oauth_provider")
            }
            for user in db_users
        ]
            
        return {
            "success": True,
            "users": users,
            "count": len(users)
        }
    except Exception as e:
        logger.error(f"Failed to list users: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list users: {str(e)}")

# ===================================
# SUBSCRIPTION ENDPOINTS
# ===================================

@app.get("/subscription/tiers")
async def get_subscription_tiers(
    current_user: Optional[User] = Depends(get_current_user_or_api_key)
):
    """Get available subscription tiers."""
    try:
        user_id = current_user.id if current_user else None
        return await subscription_service.get_available_tiers(user_id)
    except Exception as e:
        logger.error(f"Failed to get subscription tiers: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get subscription tiers: {str(e)}")

@app.get("/subscription/status")
async def get_subscription_status(
    current_user: User = Depends(require_active_user)
):
    """Get current user's subscription status."""
    try:
        subscription = await subscription_service.get_user_subscription(current_user.id)
        
        # Get current tier details
        current_tier = None
        if subscription:
            tier_name = subscription.tier
            current_tier = subscription_service.SUBSCRIPTION_TIERS.get(tier_name)
        else:
            # If no subscription, user is on free tier
            current_tier = subscription_service.SUBSCRIPTION_TIERS.get("free")
        
        # Get current usage
        current_usage = None
        if subscription:
            token_balance = await api_pricing_service.get_token_balance(current_user.id)
            current_usage = {
                "tokens_used": token_balance.used_tokens,
                "tokens_remaining": token_balance.remaining_tokens,
                "monthly_allocation": token_balance.monthly_allocation
            }
        
        # Calculate days until renewal
        days_until_renewal = None
        if subscription and subscription.current_period_end:
            days_until_renewal = (subscription.current_period_end - datetime.utcnow()).days
        
        return SubscriptionStatusResponse(
            success=True,
            subscription=subscription,
            current_tier=current_tier,
            current_usage=current_usage,
            days_until_renewal=days_until_renewal
        )
    except Exception as e:
        logger.error(f"Failed to get subscription status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get subscription status: {str(e)}")

@app.post("/subscription/create")
async def create_subscription(
    request: CreateSubscriptionRequest,
    current_user: User = Depends(require_active_user)
):
    """Create a new subscription (generates LemonSqueezy checkout URL)."""
    try:
        # Check if user already has an active subscription
        existing_subscription = await subscription_service.get_user_subscription(current_user.id)
        if existing_subscription and existing_subscription.status == "active":
            raise HTTPException(
                status_code=400,
                detail="User already has an active subscription"
            )
        
        # Create LemonSqueezy checkout URL
        checkout_url = await subscription_service.create_lemonsqueezy_checkout(
            user_id=current_user.id,
            tier=request.tier
        )
        
        return CreateSubscriptionResponse(
            success=True,
            message="Checkout URL created successfully",
            checkout_url=checkout_url
        )
    except Exception as e:
        logger.error(f"Failed to create subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create subscription: {str(e)}")

@app.post("/subscription/webhook")
async def handle_subscription_webhook(
    request: Request
):
    """Handle LemonSqueezy webhook events."""
    try:
        # Get raw body and signature
        body = await request.body()
        signature = request.headers.get("X-LemonSqueezy-Signature", "")
        
        # Log all headers for debugging
        logger.info(f"All webhook headers: {dict(request.headers)}")
        logger.info(f"Received webhook with signature: {signature}")
        logger.info(f"Webhook body: {body.decode()}")
        
        # Parse JSON payload
        payload = json.loads(body.decode())
        
        # Process webhook with raw body for signature verification
        success = await subscription_service.handle_subscription_webhook(payload, signature, body)
        
        if success:
            return {"success": True, "message": "Webhook processed successfully"}
        else:
            raise HTTPException(status_code=400, detail="Failed to process webhook")
            
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    except Exception as e:
        logger.error(f"Failed to handle webhook: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to handle webhook: {str(e)}")

@app.post("/subscription/manual-activate")
async def manual_activate_subscription(
    tier: str,
    current_user: User = Depends(require_active_user)
):
    """Temporary endpoint to manually activate subscription for testing."""
    try:
        # Get tier info
        tier_info = subscription_service.SUBSCRIPTION_TIERS.get(tier)
        if not tier_info:
            raise HTTPException(status_code=400, detail=f"Invalid tier: {tier}")
        
        # Create subscription record manually
        subscription_id = str(uuid.uuid4())
        subscription_doc = {
            "_id": subscription_id,
            "user_id": current_user.id,
            "lemonsqueezy_subscription_id": f"manual_{subscription_id}",
            "lemonsqueezy_customer_id": f"manual_customer_{current_user.id}",
            "lemonsqueezy_product_id": "manual",
            "lemonsqueezy_variant_id": "manual",
            "tier": tier,
            "status": "active",
            "current_period_start": datetime.utcnow(),
            "current_period_end": datetime.utcnow() + timedelta(days=30),
            "monthly_token_allocation": tier_info.monthly_tokens,
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Insert subscription
        mongodb.subscriptions.insert_one(subscription_doc)
        
        # Update user's subscription info
        mongodb.users.update_one(
            {"_id": current_user.id},
            {
                "$set": {
                    "subscription_tier": tier,
                    "subscription_status": "active",
                    "monthly_token_allocation": tier_info.monthly_tokens
                }
            }
        )
        
        # Allocate tokens
        await api_pricing_service.allocate_separated_monthly_tokens(
            user_id=current_user.id,
            generation_tokens=tier_info.monthly_generation_tokens,
            execution_tokens=tier_info.monthly_execution_tokens,
            source="manual_activation"
        )
        
        return {"success": True, "message": f"Subscription {tier} activated manually"}
        
    except Exception as e:
        logger.error(f"Failed to manually activate subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to activate subscription: {str(e)}")

@app.post("/subscription/update")
async def update_subscription(
    request: UpdateSubscriptionRequest,
    current_user: User = Depends(require_active_user)
):
    """Update user's subscription (cancel, pause, change tier)."""
    try:
        subscription = await subscription_service.get_user_subscription(current_user.id)
        if not subscription:
            raise HTTPException(status_code=404, detail="No active subscription found")
        
        # For now, this is a placeholder - you'll implement the actual LemonSqueezy API calls
        # to update/cancel subscriptions
        
        return {
            "success": True,
            "message": "Subscription update requested",
            "note": "You'll need to implement LemonSqueezy API integration for this endpoint"
        }
    except Exception as e:
        logger.error(f"Failed to update subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update subscription: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 