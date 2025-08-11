from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status, Body
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi import Request
import requests
import time
import base64
from datetime import datetime, timedelta
from typing import Optional, Tuple
import logging
from .models import (
    User, UserCreate, UserLogin, UserProfile, Token, TokenData,
    APIGenerationRequest, APIGenerationResponse, APIModificationRequest, APIModificationResponse,
    APIExecutionRequest, APIExecutionResponse, SaveAPIRequest, SaveAPIResponse, ListAPIsResponse,
    ChatAnalysisRequest, ChatAnalysisResponse, HealthResponse, ChatMessage,
    RegisterResponse, LoginResponse, TestRequest, TestResponse,
    APIKey, CreateAPIKeyRequest, CreateAPIKeyResponse, ListAPIKeysResponse, 
    UpdateAPIKeyRequest, DeleteAPIKeyResponse, APIInputData,
    UsageStatsResponse, UsageLimitsResponse, CreateUsageRequest,
    APIExecutionStatsResponse, APIExecutionLimitsResponse, CreateAPIExecutionUsageRequest,
    EstimateAPIUsageCostRequest, EstimateAPIUsageCostResponse, InternalTokenBalance,
    CreateInternalTokenRequest
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
from .services.PromptService import PromptServiceBuild, PromptServiceModify
from .services.database import init_database
from .services.test_service import test_service
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
    await init_database()
    logger.info("Database initialized successfully")
    
    # Clean up any orphaned JSON files from old metadata storage
    cleaned_count = file_service.cleanup_orphaned_json_files()
    if cleaned_count > 0:
        logger.info(f"Cleaned up {cleaned_count} orphaned JSON metadata files")



# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify actual origins
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Authentication setup
security = HTTPBearer(auto_error=False)

async def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[User]:
    """Get current authenticated user from JWT token."""
    logger.info(f"🔑 get_current_user called, credentials: {bool(credentials)}")
    if not credentials:
        logger.warning("❌ No credentials provided")
        return None
    
    logger.info(f"🔍 Processing credentials: {credentials.credentials[:20]}...")
    try:
        token_data = auth_service.verify_token(credentials.credentials)
        logger.info(f"🎫 Token verified successfully, username: {token_data.username}")
        # The token contains email in the 'sub' field (stored as username for compatibility)
        user = await auth_service.get_user_by_email(token_data.username)
        logger.info(f"✅ User authenticated: {user.email if user else 'None'}")
        return user
    except HTTPException as e:
        logger.error(f"❌ Authentication failed: {e.detail}")
        return None
    except Exception as e:
        logger.error(f"❌ Unexpected authentication error: {str(e)}")
        return None

async def get_current_user_and_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Tuple[Optional[User], Optional[str]]:
    """Get current authenticated user and API key ID if applicable."""
    if not credentials:
        return None, None
    
    # First try JWT token authentication
    try:
        token_data = auth_service.verify_token(credentials.credentials)
        user = await auth_service.get_user_by_email(token_data.username)
        if user:
            return user, None  # No API key for JWT auth
    except HTTPException:
        pass
    
    # If JWT fails, try API key authentication
    try:
        api_key_info = await api_key_service.validate_api_key(credentials.credentials)
        if api_key_info:
            # Get user by user_id from API key
            user = await auth_service.get_user_by_id(api_key_info.user_id)
            return user, api_key_info.id  # Return both user and API key ID
    except Exception:
        pass
    
    return None, None

async def get_current_user_or_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)) -> Optional[User]:
    """Get current authenticated user from JWT token or API key."""
    user, _ = await get_current_user_and_api_key(credentials)
    return user

async def require_auth(current_user: User = Depends(get_current_user)) -> User:
    """Require authentication for protected endpoints."""
    logger.info(f"🔐 require_auth called, user: {current_user.email if current_user else 'None'}")
    if not current_user:
        logger.warning("❌ Authentication failed - no current user")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user

async def require_auth_or_api_key(current_user: User = Depends(get_current_user_or_api_key)) -> User:
    """Require authentication via JWT token or API key for API endpoints."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required (Bearer token or API key)",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return current_user

@app.get("/landing", response_class=HTMLResponse)
async def landing_page(request: Request):
    """Serve the landing page."""
    return templates.TemplateResponse("landing.html", {"request": request})

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main frontend page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Serve the login page."""
    return templates.TemplateResponse("login.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    """Serve the register page."""
    return templates.TemplateResponse("register.html", {"request": request})

@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve the profile page."""
    return templates.TemplateResponse("profile.html", {"request": request})

@app.get("/api/{user_id}/{api_slug}/details", response_class=HTMLResponse)
async def api_details_page(request: Request, user_id: str, api_slug: str):
    """Serve the API details page."""
    return templates.TemplateResponse("api_details.html", {
        "request": request,
        "user_id": user_id,
        "api_slug": api_slug
    })

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(),
        version="1.0.0"
    )

# Authentication Endpoints
@app.post("/auth/register", response_model=RegisterResponse)
async def register(user_data: UserCreate):
    """Register a new user."""
    try:
        # Hash the password
        hashed_password = auth_service.get_password_hash(user_data.password)
        
        # Save the user
        user = await auth_service.save_user(user_data, hashed_password)
        
        # Allocate starter tokens (1000 tokens) for new users
        try:
            logger.info(f"Allocating starter tokens for new user: {user.id}")
            await api_pricing_service.allocate_monthly_tokens(
                user_id=user.id, 
                amount=1000, 
                source="new_user_bonus"
            )
            logger.info(f"✅ Successfully allocated 1000 starter tokens to user: {user.email}")
        except Exception as token_error:
            logger.warning(f"Failed to allocate starter tokens to user {user.email}: {token_error}")
            # Don't fail registration if token allocation fails
        
        return RegisterResponse(
            success=True,
            message="User registered successfully! You've received 1000 starter tokens to test your APIs.",
            user=user
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )

@app.post("/auth/login", response_model=LoginResponse)
async def login(login_data: UserLogin):
    """Authenticate user and return JWT token."""
    try:
        # Authenticate user
        user = await auth_service.authenticate_user(login_data.email, login_data.password)
        
        if not user:
            raise HTTPException(
                status_code=401,
                detail="Invalid email or password"
            )
        
        # Create access token
        access_token = auth_service.create_access_token(
            data={"sub": user.email},
            expires_delta=timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
        )
        
        # Create token response
        token = Token(
            access_token=access_token,
            token_type="bearer",
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            user=user
        )
        
        return LoginResponse(
            success=True,
            message="Login successful!",
            token=token
        )
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Login failed: {str(e)}"
        )

@app.get("/auth/profile", response_model=UserProfile)
async def get_profile(current_user: User = Depends(require_auth)):
    """Get user profile with API statistics."""
    try:
        # Get user's saved APIs
        saved_apis = await file_service.get_user_apis(current_user.id)
        
        # Create recent activity (simplified)
        recent_activity = []
        for api in saved_apis[:5]:  # Last 5 activities
            recent_activity.append({
                "action": "API Created",
                "api_name": api.api_name,
                "timestamp": api.created_at.isoformat()
            })
        
        return UserProfile(
            user=current_user,
            total_apis=len(saved_apis),
            saved_apis=saved_apis,
            recent_activity=recent_activity
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get profile: {str(e)}"
        )

@app.get("/auth/me")
async def get_current_user_info(current_user: Optional[User] = Depends(get_current_user)):
    """Get current user information (no auth required)."""
    if current_user:
        return {"authenticated": True, "user": current_user}
    else:
        return {"authenticated": False, "user": None}

# API Key Management Endpoints
@app.post("/api-keys", response_model=CreateAPIKeyResponse)
async def create_api_key(request: CreateAPIKeyRequest, current_user: User = Depends(require_auth)):
    """Create a new API key for the authenticated user."""
    logger.info(f"🎯 POST /api-keys endpoint hit! Creating API key '{request.key_name}' for user {current_user.id}")
    result = await api_key_service.create_api_key(current_user.id, request)
    logger.info(f"🔄 API key creation result: success={result.success}")
    return result

@app.get("/api-keys", response_model=ListAPIKeysResponse)
async def list_api_keys(current_user: User = Depends(require_auth)):
    logger.info(f"🔑 GET /api-keys endpoint hit! Listing API keys for user {current_user.id}")
    """List all API keys for the authenticated user."""
    api_keys = await api_key_service.get_user_api_keys(current_user.id)
    return ListAPIKeysResponse(
        success=True,
        api_keys=api_keys,
        count=len(api_keys)
    )

@app.put("/api-keys/{key_id}")
async def update_api_key(
    key_id: str, 
    request: UpdateAPIKeyRequest, 
    current_user: User = Depends(require_auth)
):
    logger.info(f"🔄 PUT /api-keys/{key_id} endpoint hit! Updating API key for user {current_user.id}")
    """Update an API key."""
    success = await api_key_service.update_api_key(
        current_user.id, 
        key_id, 
        request.key_name, 
        request.is_active
    )
    if success:
        return {"success": True, "message": "API key updated successfully"}
    else:
        raise HTTPException(status_code=404, detail="API key not found or update failed")

@app.delete("/api-keys/{key_id}", response_model=DeleteAPIKeyResponse)
async def delete_api_key(key_id: str, current_user: User = Depends(require_auth)):
    """Delete an API key."""
    logger.info(f"🔄 DELETE /api-keys/{key_id} endpoint hit! Deleting API key for user {current_user.id}")
    success = await api_key_service.delete_api_key(current_user.id, key_id)
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
    days: int = 30,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(get_current_user)
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
    api_key_id: Optional[str] = None,
    current_user: User = Depends(get_current_user)
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
    current_user: User = Depends(get_current_user)
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
    current_user: User = Depends(get_current_user)
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
async def analyze_chat_prompt(request: ChatAnalysisRequest):
    """
    Analyze a chat prompt to determine if it's buildable and provide appropriate response.
    """
    logger.info(f"Analyzing chat prompt for user {request.user_id}: {request.prompt[:100]}...")
    try:
        # Use PromptService to analyze the prompt
        prompt_service = PromptServiceBuild()
        analysis_result = await prompt_service.CanIBuildThis(request.user_id, request.prompt)
        
        logger.info(f"Analysis completed for user {request.user_id}")
        return {
            "success": True,
            "user_id": request.user_id,
            "prompt": request.prompt,
            "analysis_result": analysis_result,
            "timestamp": datetime.now()
        }
        
    except Exception as e:
        logger.error(f"Error analyzing chat prompt: {str(e)}")
        return {
            "success": False,
            "user_id": request.user_id,
            "prompt": request.prompt,
            "analysis_result": f'{{"status": "error", "message": "Error analyzing prompt: {str(e)}"}}',
            "timestamp": datetime.now()
        }

@app.post("/generate-api", response_model=APIGenerationResponse)
async def generate_api(
    request: APIGenerationRequest,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key)
):
    """
    Generate a new API based on user prompt.
    Optionally analyzes the prompt first, then generates if buildable.
    """
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Generating API for user {request.user_id} with prompt: {request.prompt[:100]}...")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=request.user_id,
            api_key_id=api_key_id,
            tokens_to_use=2000  # Estimated tokens for code generation
        )
        
        if limits.is_over_limit:
            raise HTTPException(
                status_code=429,
                detail=f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to check usage limits: {e}")
        # Continue without limits check if service is unavailable
    
    try:
        # Initialize analysis_result
        analysis_result = None
        
        # Only analyze if skip_analysis is False (default behavior for backward compatibility)
        if not request.skip_analysis:
            # First analyze the prompt using PromptService
            logger.info("Analyzing prompt with PromptServiceBuild...")
            prompt_service = PromptServiceBuild()
            analysis_result = await prompt_service.CanIBuildThis(request.user_id, request.prompt)
            
            # Parse the analysis result to check if it's buildable
            import json
            try:
                analysis_data = json.loads(analysis_result)
                status = analysis_data.get("status")
                
                # If build needs clarification, return the questions to the frontend
                if status == "needs_clarification":
                    logger.info(f"Build needs clarification: {analysis_data.get('message')}")
                    return {
                        "success": False,
                        "status": "needs_clarification",
                        "message": analysis_data.get("message", "I need more information to build this API."),
                        "questions": analysis_data.get("questions", []),
                        "suggestions": analysis_data.get("suggestions", []),
                        "original_prompt": request.prompt
                    }
                
                # If it's a modify request, redirect to modify endpoint
                if status == "modify_request":
                    logger.info(f"Detected modify request, redirecting")
                    return {
                        "success": False,
                        "status": "modify_request",
                        "message": analysis_data.get("message", "This appears to be a modification request."),
                        "instructions": analysis_data.get("instructions", []),
                        "next_steps": analysis_data.get("next_steps", [])
                    }
                
                # If not buildable, return appropriate message
                if status == "not_buildable":
                    logger.warning(f"API request not buildable")
                    return {
                        "success": False,
                        "status": "not_buildable", 
                        "message": analysis_data.get("message", "I'm sorry, but I can't build this API."),
                        "reasons": analysis_data.get("reasons", []),
                        "suggestions": analysis_data.get("suggestions", [])
                    }
                    
                # If not buildable status, proceed with generation
                if status != "buildable":
                    logger.warning(f"Unexpected build status: {status}, proceeding anyway")
                    
            except json.JSONDecodeError:
                logger.warning("Could not parse analysis result, proceeding with generation")
        else:
            logger.info("Skipping analysis step as requested")
        
        # Validate Claude API key
        if not settings.CLAUDE_API_KEY:
            logger.error("Claude API key not configured")
            raise HTTPException(
                status_code=500, 
                detail="Claude API key not configured"
            )
        
        # Generate API code using Claude
        logger.info("Calling Claude service to generate code...")
        raw_code = await claude_service.generate_api_code(
            prompt=request.prompt,
            sample_input=request.sample_input,
            expected_output=request.expected_output,
            user_id=request.user_id,
            api_key_id=api_key_id
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
        
        # Generate API slug
        api_slug = file_service.generate_api_slug(
            user_id=request.user_id,
            api_name=request.api_name
        )
        
        # Remove user_id prefix for clean slug
        clean_slug = api_slug.replace(f"{request.user_id}_", "")
        
        # Save the code
        await file_service.save_api_code(api_slug, code)
        
        # Generate documentation
        documentation, curl_example = await claude_service.generate_documentation(
            code=code, 
            prompt=request.prompt,
            user_id=request.user_id,
            api_key_id=api_key_id,
            api_slug=clean_slug
        )
        
        # Build endpoint URL
        endpoint_url = f"{settings.API_PREFIX}/{request.user_id}/{clean_slug}"
        
        # Update curl example with actual endpoint
        if "your-endpoint-url" in curl_example:
            curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
        
        # Save API metadata for pricing (detect AI model from generated code)
        try:
            # Analyze the generated code to detect which AI service it uses
            ai_model_used = "claude-3-sonnet"  # Default to the generation service
            estimated_tokens = 500  # Default estimate
            
            # Check if the generated code uses OpenAI
            if "openai" in code.lower() or "gpt-" in code.lower():
                if "gpt-4" in code.lower():
                    ai_model_used = "gpt-4"
                    estimated_tokens = 800  # GPT-4 typically uses more tokens
                else:
                    ai_model_used = "gpt-3.5-turbo"
                    estimated_tokens = 400  # GPT-3.5 is more efficient
            # Check if it uses Claude API directly
            elif "anthropic" in code.lower() or "claude" in code.lower():
                if "opus" in code.lower():
                    ai_model_used = "claude-3-opus"
                    estimated_tokens = 600
                elif "haiku" in code.lower():
                    ai_model_used = "claude-3-haiku"
                    estimated_tokens = 300
                else:
                    ai_model_used = "claude-3-sonnet"
                    estimated_tokens = 500
            # If no AI service detected, it's a simple processing API
            elif not any(keyword in code.lower() for keyword in ["openai", "anthropic", "claude", "gpt"]):
                ai_model_used = "none"  # No AI service used
                estimated_tokens = 0
            
            # Determine complexity based on code analysis
            complexity = 'simple'
            if len(code) > 2000 or "class" in code or "async def" in code:
                complexity = 'complex'
            elif len(code) > 1000 or "try:" in code or "except:" in code:
                complexity = 'medium'
            
            logger.info(f"Detected AI model: {ai_model_used}, estimated tokens: {estimated_tokens}, complexity: {complexity}")
            
            await api_pricing_service.save_api_metadata(
                api_slug=clean_slug,
                user_id=request.user_id,
                ai_model_used=ai_model_used,
                estimated_tokens_per_call=estimated_tokens,
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
            user_id=request.user_id,
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
    request: APIModificationRequest,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key)
):
    """
    Modify an existing API based on user prompt.
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
            raise HTTPException(
                status_code=429,
                detail=f"Usage limit exceeded. Daily tokens used: {limits.daily_tokens_used}/{limits.daily_token_limit}"
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Failed to check usage limits: {e}")
        # Continue without limits check if service is unavailable
    
    try:
        # Check if API exists
        if not file_service.api_exists(request.user_id, request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {request.user_id}/{request.api_slug}"
            )
        
        # Load existing code
        existing_code = file_service.load_api_code(request.user_id, request.api_slug)
        
        # Analyze the prompt using PromptService to determine if it's Modifyable
        logger.info("Analyzing prompt with PromptServiceModify for modification...")
        prompt_service_modify = PromptServiceModify()
        analysis_result = await prompt_service_modify.CanIModifyThis(request.user_id, request.prompt)
        
        # Parse the analysis result to check if it's Modifyable
        import json
        try:
            analysis_data = json.loads(analysis_result)
            status = analysis_data.get("status")
            
            # If modification needs clarification, return the questions to the frontend
            if status == "needs_clarification":
                logger.info(f"Modification needs clarification: {analysis_data.get('message')}")
                return {
                    "success": False,
                    "status": "needs_clarification",
                    "message": analysis_data.get("message", "I need more information to modify this API."),
                    "questions": analysis_data.get("questions", []),
                    "suggestions": analysis_data.get("suggestions", []),
                    "original_prompt": request.prompt
                }
            
            # If modification has questions even though it's ready, show them first
            if status == "modification_ready" and analysis_data.get("questions"):
                logger.info(f"Modification ready but has clarification questions")
                return {
                    "success": False,
                    "status": "needs_clarification", 
                    "message": "I can modify this API, but I have some questions to ensure I do it correctly:",
                    "questions": analysis_data.get("questions", []),
                    "modification_type": analysis_data.get("modification_type"),
                    "complexity": analysis_data.get("complexity"),
                    "planned_changes": analysis_data.get("planned_changes", []),
                    "original_prompt": request.prompt
                }
                
            # If modification is ready and no questions, proceed
            if status != "modification_ready":
                logger.warning(f"Unexpected modification status: {status}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Cannot proceed with modification. Analysis result: {analysis_result}"
                )
                
        except json.JSONDecodeError:
            logger.warning("Could not parse analysis result, proceeding with modification")
        
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
        if await file_service.is_api_saved(request.user_id, request.api_slug):
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
        
        validated_key = await api_key_service.validate_api_key(api_key)
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
            logger.warning(f"Failed to check execution limits: {e}")
            # Continue without limits check if service is unavailable

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
        saved_apis = await file_service.get_user_apis(user_id)
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
        success = await file_service.delete_api(user_id, api_slug)
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

@app.get("/api/{user_id}/{api_slug}/apidetails")
async def apidetails(user_id: str, api_slug: str):
    """
    Get details of a specific API.
    """
    try:
        api_details = await file_service.get_api_details(user_id, api_slug)
        return api_details
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get API details: {str(e)}"
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
    import json
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

# API Execution Usage Endpoints

@app.get("/api-execution-stats", response_model=APIExecutionStatsResponse)
async def get_api_execution_stats(
    days: int = 30,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_or_api_key)
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
        logger.error(f"Failed to get API execution stats: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get execution stats: {str(e)}")

@app.get("/api-execution-limits", response_model=APIExecutionLimitsResponse)
async def get_api_execution_limits(
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_or_api_key)
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
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_or_api_key)
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

@app.post("/allocate-monthly-tokens")
async def allocate_monthly_tokens(
    request: CreateInternalTokenRequest,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Allocate monthly tokens to the user (admin function or monthly allocation)."""
    try:
        token = await api_pricing_service.allocate_monthly_tokens(
            user_id=current_user.id,
            api_key_id=None,
            amount=request.amount,
            source=request.source
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




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 