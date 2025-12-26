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
from typing import Optional, Tuple, List
import logging
import os
import warnings

# Suppress transformers library warnings about PyTorch/TensorFlow not being installed. I dont even remember what that does.
os.environ['TRANSFORMERS_VERBOSITY'] = 'error'
warnings.filterwarnings("ignore", category=UserWarning, module="transformers")
from .models import (
    User, UserLogin, LoginResponse, UserProfile, AuthResponse,
    ProposalRequest, ProposalResponse, ProposalModificationRequest, ProposalModificationResponse,
    APIGenerationRequest, APIGenerationResponse, APIModificationRequest, APIModificationResponse,
    APIExecutionRequest, APIExecutionResponse, SaveAPIRequest, SaveAPIResponse, ListAPIsResponse,
    GenerateDocumentationRequest, GenerateDocumentationResponse,
    ChatAnalysisRequest, ChatAnalysisResponse, MessageIntentRequest, MessageIntentResponse, HealthResponse, ChatMessage,
    TestRequest, TestResponse,
    APIKey, CreateAPIKeyRequest, CreateAPIKeyResponse, ListAPIKeysResponse, 
    UpdateAPIKeyRequest, DeleteAPIKeyResponse, APIInputData,
    UsageStatsResponse, UsageLimitsResponse, CreateUsageRequest,
    APIExecutionStatsResponse, APIExecutionLimitsResponse, CreateAPIExecutionUsageRequest,
    EstimateAPIUsageCostResponse, InternalTokenBalance,
    CreateInternalTokenRequest, SeparatedTokenBalance,
    APIGenerationUsage, APIGenerationLimitsResponse,
    # Subscription models
    Subscription, SubscriptionTier, CreateSubscriptionRequest, CreateSubscriptionResponse,
    SubscriptionStatusResponse, UpdateSubscriptionRequest, SubscriptionTiersResponse,
    # Logging models
    LogsRequest, LogsResponse, HTTPLogsRequest, HTTPLogsResponse,
    LLMLogsRequest, LLMLogsResponse, ChatLogsRequest, ChatLogsResponse,
    LogStatisticsResponse,
    # Multi-step generation models
    MultiStepGenerationRequest, PipelineInfoResponse,
    APIVersion,
    # Report models
    CreateReportRequest, CreateReportResponse, Report, ListReportsResponse,
    # Database connection models
    DatabaseType, DatabaseConfig, TestDatabaseConnectionRequest, TestDatabaseConnectionResponse,
    # Custom domain models
    CustomDomain, DomainStatus, VerificationMethod, SSLCertificateStatus,
    CreateDomainRequest, CreateDomainResponse, VerifyDomainRequest, VerifyDomainResponse,
    DomainStatusResponse, ListDomainsResponse, DeleteDomainResponse, DomainMapping
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
from .services.api_generation_usage_service import api_generation_usage_service
from .services.PromptService import PromptServiceBuild, PromptServiceModify
from .services.mongodb import init_database, mongodb
from .routes.auth_routes import router as auth_router, get_current_user, get_current_user_required, require_auth, require_active_user
from .routes.oauth_routes import router as oauth_router
from .services.test_service import test_service
from .services.database_connection_service import database_connection_service
from .services.logging_service import logging_service, LogLevel, LogCategory
from .services.exceptions import create_secure_error, SecureHTTPException
from .services.domain_service import domain_service
from .services.domain_verification_service import domain_verification_service
from .services.caddy_service import caddy_service
from .services.multi_step_generation_service import multi_step_generation_service
from .code_generation_config.multi_step_config import GenerationMode
from .middleware.logging_middleware import LoggingMiddleware, RequestContextMiddleware
from .middleware.redis_session_middleware import RedisSessionMiddleware, get_session
from .config import settings
from .logging_config import setup_logging
import os

# Configure logging
setup_logging()
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
# Use Redis-backed sessions in multi-worker environments for proper OAuth state management
if settings.USE_REDIS_SESSIONS:
    logger.info("🔄 Using Redis-backed session storage for multi-worker support")
    app.add_middleware(
        RedisSessionMiddleware,
        redis_url=settings.REDIS_URL,
        secret_key=settings.SECRET_KEY,
        max_age=1800,  # 30 minutes for OAuth state
        session_cookie="session",
        domain=settings.SESSION_COOKIE_DOMAIN,  # For reverse proxy support
        https_only=settings.COOKIE_SECURE  # Use HTTPS in production
    )
else:
    # Starlette's SessionMiddleware stores session data in a signed cookie (not in-memory),
    # so it works fine with multiple workers. The main OAuth requirement is SameSite != Strict.
    logger.info("🔄 Using cookie-backed SessionMiddleware for OAuth state")
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.SECRET_KEY,
        max_age=30 * 24 * 60 * 60,  # 30 days
        # OAuth requires the temporary session cookie (used to store `state`)
        # to be sent back after the cross-site redirect from the provider.
        # `SameSite=Strict` will break that flow, so we force at least Lax here.
        same_site="lax",
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


# Custom domain routing middleware
# This middleware intercepts requests from custom domains and routes them to the correct API
MAIN_DOMAIN = os.getenv("MAIN_DOMAIN", "bucketapi.com")
SKIP_DOMAIN_ROUTING_PATHS = {"/health", "/api/caddy/check-domain", "/api/caddy/health", "/.well-known"}


@app.middleware("http")
async def custom_domain_routing_middleware(request: Request, call_next):
    """
    Route custom domain requests to the appropriate API endpoint.
    
    Supports multiple APIs per domain via path-based routing:
    - http://loopfeedback.dev/api/{api_slug} → /api/{user_id}/{api_slug}
    - http://loopfeedback.dev/ → /api/{user_id}/{default_api_slug} (if default set)
    """
    try:
        # Get the host header
        host = request.headers.get("host", "").split(":")[0].lower()  # Remove port
        path = request.url.path
        
        # Skip routing for main domain, localhost, and certain paths
        if (host in {MAIN_DOMAIN, f"www.{MAIN_DOMAIN}", "localhost", "127.0.0.1"} or
            any(path.startswith(skip_path) for skip_path in SKIP_DOMAIN_ROUTING_PATHS)):
            return await call_next(request)
        
        # Check if this is a custom domain by looking up in database
        domain_doc = mongodb.custom_domains.find_one({
            "domain": host,
            # Allow routing for domains that are already active, or in the middle of
            # certificate issuance/activation (on-demand TLS).
            "status": {"$in": ["active", "activating", "verified"]}
        })
        
        if domain_doc:
            # If the domain is in the process of activation and this request came in over HTTPS
            # (as reported by the reverse proxy), mark it active.
            #
            # Note: FastAPI sees the proxied request as HTTP from Caddy -> backend.
            # We rely on X-Forwarded-Proto being set by Caddy.
            forwarded_proto = (request.headers.get("x-forwarded-proto") or "").lower()
            if domain_doc.get("status") in {"verified", "activating"} and forwarded_proto == "https":
                try:
                    mongodb.custom_domains.update_one(
                        {"_id": domain_doc["_id"]},
                        {"$set": {
                            "status": "active",
                            "ssl_certificate_status": "issued",
                            "activated_at": datetime.utcnow()
                        }}
                    )
                    domain_doc["status"] = "active"
                    domain_doc["ssl_certificate_status"] = "issued"
                    domain_doc["activated_at"] = datetime.utcnow()
                    logger.info(f"✅ Domain {host} activated after HTTPS request")
                except Exception as activate_err:
                    logger.warning(f"Failed to auto-activate domain {host}: {activate_err}")

            # Found custom domain - route based on path
            user_id = domain_doc["user_id"]
            original_path = path.rstrip("/")
            
            # Check if path starts with /api/{api_slug}
            # Pattern: /api/{api_slug} or /api/{api_slug}/...
            if original_path.startswith("/api/"):
                # Extract api_slug from path: /api/{api_slug}/...
                path_parts = original_path.split("/")
                if len(path_parts) >= 3:  # /api/{api_slug}
                    api_slug = path_parts[2]  # Get api_slug from /api/{api_slug}
                    
                    # Verify API belongs to this user
                    api_exists = mongodb.saved_apis.find_one({
                        "user_id": user_id,
                        "api_slug": api_slug
                    })
                    
                    if api_exists:
                        # Build remaining path after /api/{api_slug}
                        remaining_path = "/" + "/".join(path_parts[3:]) if len(path_parts) > 3 else ""
                        
                        # Rewrite: /api/{api_slug}/... → /api/{user_id}/{api_slug}/...
                        new_path = f"/api/{user_id}/{api_slug}{remaining_path}"
                        
                        # Preserve query string
                        query_string = request.url.query
                        if query_string:
                            new_path += f"?{query_string}"
                        
                        # Log the routing
                        logger.debug(f"Custom domain routing: {host}{path} → {new_path}")
                        
                        # Create a new scope with the rewritten path
                        scope = dict(request.scope)
                        scope["path"] = new_path
                        scope["raw_path"] = new_path.encode()
                        scope["path_info"] = new_path.split("?")[0]
                        scope["query_string"] = query_string.encode() if query_string else b""
                        
                        # Add custom headers
                        headers = list(request.scope.get("headers", []))
                        headers.append((b"x-custom-domain", host.encode()))
                        headers.append((b"x-original-path", path.encode()))
                        scope["headers"] = headers
                        
                        # Create a new request with the modified scope
                        from starlette.requests import Request as StarletteRequest
                        modified_request = StarletteRequest(scope, request.receive)
                        
                        return await call_next(modified_request)
                    else:
                        # API not found for this user
                        logger.warning(f"API {api_slug} not found for user {user_id} on domain {host}")
                        # Return 404 - let FastAPI handle it
                        return await call_next(request)
                else:
                    # Invalid path format: /api/ without slug
                    return await call_next(request)
            elif original_path in ("", "/"):
                # Check if domain has a default API (api_slug field)
                default_api_slug = domain_doc.get("api_slug")
                
                if default_api_slug:
                    # Route to default API
                    new_path = f"/api/{user_id}/{default_api_slug}"
                    
                    # Preserve query string
                    query_string = request.url.query
                    if query_string:
                        new_path += f"?{query_string}"
                    
                    logger.debug(f"Custom domain root routing: {host}/ → {new_path}")
                    
                    # Create a new scope with the rewritten path
                    scope = dict(request.scope)
                    scope["path"] = new_path
                    scope["raw_path"] = new_path.encode()
                    scope["path_info"] = new_path.split("?")[0]
                    scope["query_string"] = query_string.encode() if query_string else b""
                    
                    # Add custom headers
                    headers = list(request.scope.get("headers", []))
                    headers.append((b"x-custom-domain", host.encode()))
                    headers.append((b"x-original-path", path.encode()))
                    scope["headers"] = headers
                    
                    # Create a new request with the modified scope
                    from starlette.requests import Request as StarletteRequest
                    modified_request = StarletteRequest(scope, request.receive)
                    
                    return await call_next(modified_request)
                else:
                    # No default API - could return list of available APIs or 404
                    logger.debug(f"Custom domain {host} has no default API, path: {path}")
                    # For now, proceed normally (could add endpoint to list APIs)
                    return await call_next(request)
            else:
                # Other paths - proceed normally (could be static files, etc.)
                return await call_next(request)
        
        # Not a custom domain, proceed normally
        return await call_next(request)
        
    except Exception as e:
        # Log error but don't fail the request - just proceed normally
        logger.error(f"Custom domain routing error: {str(e)}", exc_info=True)
        return await call_next(request)


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
    admin_emails_str = os.getenv("ADMIN_EMAILS", "admin@localhost,admin@yourdomain.com")
    admin_emails = [e.strip() for e in admin_emails_str.split(',')]
    
    # Check if email is in admin list
    email_in_list = email.lower() in [e.lower() for e in admin_emails]
    
    # Check if email contains 'admin' (case-insensitive)
    email_contains_admin = 'admin' in email.lower()
    
    is_admin = email_in_list or email_contains_admin
    
    logger.info(f"Admin check for {email}: in_list={email_in_list}, contains_admin={email_contains_admin}, result={is_admin}")
    logger.debug(f"Admin emails from env: {admin_emails}")
    
    return is_admin

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


@app.get("/profile", response_class=HTMLResponse)
async def profile_page(request: Request):
    """Serve the profile page."""
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=302)
    return templates.TemplateResponse("profile.html", {"request": request, "user": user})

    

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
    is_admin = is_admin_user(user.email)
    logger.info(f"Admin check for {user.email}: {is_admin}")
    
    if not is_admin:
        logger.warning(f"Access denied to admin panel for user: {user.email}")
        # Redirect with a message parameter that can be shown on dashboard
        return RedirectResponse(url="/dashboard?admin_access_denied=true", status_code=302)
    
    return templates.TemplateResponse("admin_panel.html", {"request": request, "user": user})

@app.get("/privacy_policy", response_class=HTMLResponse)
async def privacy_policy_page(request: Request):
    """Serve the privacy policy page (publicly accessible)."""
    user = await get_current_user(request)
    return templates.TemplateResponse("privacy_policy.html", {"request": request, "user": user})

@app.get("/terms_of_use", response_class=HTMLResponse)
async def terms_of_use_page(request: Request):
    """Serve the terms of use page (publicly accessible)."""
    user = await get_current_user(request)
    return templates.TemplateResponse("terms_of_use.html", {"request": request, "user": user})

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
    """Health check endpoint with MongoDB status."""
    mongodb_status = "healthy" if mongodb.health_check() else "unhealthy"
    
    return HealthResponse(
        status="healthy" if mongodb_status == "healthy" else "degraded",
        timestamp=datetime.now(),
        version="1.0.0",
        mongodb_status=mongodb_status
    )

@app.get("/health/mongodb")
async def mongodb_health_check():
    """Detailed MongoDB health check endpoint."""
    try:
        is_healthy = mongodb.health_check()
        
        if is_healthy:
            return {
                "status": "healthy",
                "timestamp": datetime.now(),
                "connection": "active",
                "database": settings.MONGODB_DB_NAME,
                "message": "MongoDB connection is working properly"
            }
        else:
            return {
                "status": "unhealthy", 
                "timestamp": datetime.now(),
                "connection": "failed",
                "database": settings.MONGODB_DB_NAME,
                "message": "MongoDB connection failed",
                "suggestion": "Check network connectivity and MongoDB Atlas status"
            }
    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.now(), 
            "connection": "error",
            "database": settings.MONGODB_DB_NAME,
            "error": str(e),
            "message": "MongoDB health check encountered an error"
        }

@app.post("/health/mongodb/reconnect")
async def mongodb_reconnect():
    """Attempt to reconnect to MongoDB."""
    try:
        success = mongodb.reconnect()
        if success:
            return {
                "status": "success",
                "timestamp": datetime.now(),
                "message": "Successfully reconnected to MongoDB"
            }
        else:
            return {
                "status": "failed",
                "timestamp": datetime.now(), 
                "message": "Failed to reconnect to MongoDB"
            }
    except Exception as e:
        return {
            "status": "error",
            "timestamp": datetime.now(),
            "error": str(e),
            "message": "Reconnection attempt encountered an error"
        }

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
    result = api_key_service.create_api_key(current_user.id, key_request)
    return result

@app.get("/api-keys", response_model=ListAPIKeysResponse)
async def list_api_keys(request: Request, current_user: User = Depends(require_auth_hybrid)):
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
    
    # Log database configuration if provided
    if proposal_request.database_config and proposal_request.database_config.enabled:
        logger.info(f"📊 Database configuration provided: {proposal_request.database_config.db_type} at {proposal_request.database_config.host}:{proposal_request.database_config.port}/{proposal_request.database_config.database_name}")
    else:
        logger.info(f"ℹ️ No database configuration provided for this proposal")
    
    # Check API generation limits before allowing proposal generation
    # This prevents users from even starting the generation process if they've hit their limit
    try:
        generation_limits = await api_generation_usage_service.check_generation_limits(
            user_id=proposal_request.user_id,
            api_key_id=api_key_id,
            tokens_to_use=1000  # Estimated tokens for analysis
        )
        
        if generation_limits.is_over_limit:
            logger.warning(f"API generation limit exceeded for user {proposal_request.user_id}: {generation_limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=generation_limits.limit_exceeded_reason or f"API generation limit exceeded. You have used {generation_limits.monthly_generations_used}/{generation_limits.monthly_generation_limit} generations this month."
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
        
        # Pass database configuration if provided
        database_config = proposal_request.database_config if hasattr(proposal_request, 'database_config') else None
        analysis_result = await prompt_service.CanIBuildThis(
            proposal_request.user_id, 
            proposal_request.prompt,
            database_config=database_config
        )
        
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
# We use a pipline to generate the api for lower cost and faster response time.
# TODO Implement Pydantic AI agent future, replace with pipeline sysmtem.
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
    
    # Check API generation limits and daily token limits before proceeding
    try:
        generation_limits = await api_generation_usage_service.check_generation_limits(
            user_id=current_user.id,
            api_key_id=api_key_id,
            tokens_to_use=2000  # Estimated tokens for API generation
        )
        
        if generation_limits.is_over_limit:
            logger.warning(f"API generation or token limit exceeded for user {current_user.id}: {generation_limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=generation_limits.limit_exceeded_reason or f"API generation limit exceeded. You have used {generation_limits.monthly_generations_used}/{generation_limits.monthly_generation_limit} generations this month."
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API generation usage service unavailable: {e}")
        raise HTTPException(
            status_code=503,
            detail="API generation tracking service temporarily unavailable. Please try again later."
        )
    
    async def generate_stream():
        """Generator function for streaming API generation"""
        try:
            # Send initial status message
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Starting API generation...",
                    "is_ai": True,
                    "message_type": "greeting"
                }
            }) + "\n\n"
            
            # Send database configuration message if enabled
            if api_request.database_config and api_request.database_config.enabled:
                logger.info(f"Database configuration enabled: {api_request.database_config}")
                db_type = api_request.database_config.db_type.value if api_request.database_config.db_type else "unknown"
                yield "data: " + json.dumps({
                    "type": "chat_message",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": f"Database integration enabled ({db_type.upper()}). Your API will include database connectivity.",
                        "is_ai": True,
                        "message_type": "info"
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
                mode=GenerationMode("streaming"),
                database_config=api_request.database_config
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
                            "message": "Now I'm validating the code for security and saving your API...",
                            "is_ai": True,
                            "message_type": "post_processing"
                        }
                    }) + "\n\n"
                    
                    raw_code = final_result["final_code"]
                    
                    # Debug and fix the generated code
                    try:
                        code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
                            raw_code, api_request.prompt, current_user.id, api_key_id
                        )
                    except Exception as debug_error:
                        logger.warning(f"Code debugger failed: {debug_error}. Using raw code.")
                        # Fallback to raw code if debugger fails
                        code = raw_code
                        issues_found = [f"Code debugger failed: {str(debug_error)}"]
                        fixes_applied = []
                        
                        yield "data: " + json.dumps({
                            "type": "chat_message",
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "message": f"⚠️ Code debugging failed, proceeding with raw code: {str(debug_error)}",
                                "is_ai": True,
                                "message_type": "warning"
                            }
                        }) + "\n\n"
                    
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
                    
                    try:
                        await file_service.save_api_code(api_slug, code)
                    except Exception as save_error:
                        # Don't hard-fail generation when disk is read-only or permissions are restricted.
                        # We'll still persist the code in MongoDB (see SaveAPIRequest.code below).
                        logger.warning(f"Failed to save API code to disk (continuing with DB persistence): {save_error}")
                        yield "data: " + json.dumps({
                            "type": "chat_message",
                            "timestamp": datetime.now().isoformat(),
                            "data": {
                                "message": "⚠️ Could not write API file to disk (permissions). Continuing by saving the API in the database.",
                                "is_ai": True,
                                "message_type": "warning"
                            }
                        }) + "\n\n"
                    
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
                        api_slug=clean_slug,
                        api_name=api_request.api_name
                    )
                    
                    # Build endpoint URL
                    endpoint_url = f"{settings.API_PREFIX}/{current_user.id}/{clean_slug}"
                    
                    # Update curl example with actual endpoint
                    if "your-endpoint-url" in curl_example:
                        curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
                    
                    # Save API documentation and metadata to database
                    try:
                        # Encode database credentials before saving
                        encoded_db_config = None
                        if api_request.database_config and api_request.database_config.enabled:
                            encoded_db_config = database_connection_service.encode_credentials(api_request.database_config)
                        
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
                            expected_output=api_request.expected_output,
                            database_config=encoded_db_config,
                            code=code
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
                    
                    # Record API generation usage
                    try:
                        generation_model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-latest')
                        await api_generation_usage_service.record_api_generation(
                            user_id=current_user.id,
                            api_key_id=api_key_id,
                            api_slug=clean_slug,
                            generation_model=generation_model,
                            prompt=api_request.prompt,
                            success=True
                        )
                        logger.info(f"Recorded API generation usage for user {current_user.id}: {clean_slug}")
                    except Exception as e:
                        logger.warning(f"Failed to record API generation usage: {e}")
                        # Continue without recording - this shouldn't block the response
                    
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
    
    # Check API generation limits and daily token limits before proceeding
    try:
        generation_limits = await api_generation_usage_service.check_generation_limits(
            user_id=current_user.id,
            api_key_id=api_key_id,
            tokens_to_use=2000  # Estimated tokens for API generation
        )
        
        if generation_limits.is_over_limit:
            logger.warning(f"API generation or token limit exceeded for user {current_user.id}: {generation_limits.limit_exceeded_reason}")
            raise HTTPException(
                status_code=429,
                detail=generation_limits.limit_exceeded_reason or f"API generation limit exceeded. You have used {generation_limits.monthly_generations_used}/{generation_limits.monthly_generation_limit} generations this month."
            )
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"API generation usage service unavailable: {e}")
        # SECURITY FIX: Fail closed instead of open
        raise HTTPException(
            status_code=503,
            detail="API generation tracking service temporarily unavailable. Please try again later."
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
        try:
            await file_service.save_api_code(api_slug, code)
        except Exception as save_error:
            # Don't hard-fail generation when disk is read-only or permissions are restricted.
            # The API source is persisted in MongoDB via SaveAPIRequest.code below.
            logger.warning(f"Failed to save API code to disk (continuing with DB persistence): {save_error}")
        
        # Generate documentation
        documentation, openapi_spec, curl_example = await openai_service.generate_documentation(
            code=code, 
            prompt=api_request.prompt,
            user_id=current_user.id,
            api_key_id=api_key_id,
            api_slug=clean_slug,
            api_name=api_request.api_name
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
                expected_output=api_request.expected_output,
                code=code
            )
            await file_service.save_api_metadata(save_request)
            logger.info(f"API documentation saved to database for {clean_slug}")
        except Exception as e:
            logger.warning(f"Failed to save API documentation to database: {e}")
            # Continue without database save if service is unavailable
        
        # Analyze the generated code immediately to detect execution model and calculate pricing
        try:
            logger.info(f"Analyzing generated code for {clean_slug} to detect execution model and calculate pricing")
            
            # Get the generation model used
            generation_model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-latest')
            
            # Analyze the code to detect LLM usage and calculate pricing
            metadata = await api_pricing_service.analyze_and_price_api_code(
                api_slug=clean_slug,
                user_id=current_user.id,
                api_code=code,
                original_prompt=api_request.prompt,
                generation_model_used=generation_model
            )
            
            logger.info(f"API {clean_slug} analysis complete: execution_model={metadata.execution_model_used or metadata.ai_model_used}, generation_model={generation_model}")
            
        except Exception as e:
            logger.warning(f"Failed to analyze API code during generation: {e}")
            # Continue without analysis - it will be done during first test as fallback
            logger.info(f"API {clean_slug} generated successfully. Pricing analysis will be retried during first test.")
        
        # Record API generation usage
        try:
            generation_model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-latest')
            await api_generation_usage_service.record_api_generation(
                user_id=current_user.id,
                api_key_id=api_key_id,
                api_slug=clean_slug,
                generation_model=generation_model,
                prompt=api_request.prompt,
                success=True
            )
            logger.info(f"Recorded API generation usage for user {current_user.id}: {clean_slug}")
        except Exception as e:
            logger.warning(f"Failed to record API generation usage: {e}")
            # Continue without recording - this shouldn't block the response
        
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


@app.get("/api/{user_id}/{api_slug}/versions", response_model=List[APIVersion])
async def get_api_versions(
    user_id: str,
    api_slug: str,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Get list of versions for an API."""
    # Verify the user owns this API
    if user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    metadata = file_service.get_api_metadata(user_id, api_slug)
    if not metadata:
        raise HTTPException(status_code=404, detail="API not found")
    
    # Serialize versions to dicts
    versions_list = []
    for v in metadata.versions:
        if hasattr(v, 'model_dump'):
            versions_list.append(v.model_dump())
        elif hasattr(v, 'dict'):
            versions_list.append(v.dict())
        elif isinstance(v, dict):
            versions_list.append(v)
        else:
            # Fallback
            versions_list.append({
                "version": v.version,
                "created_at": v.created_at.isoformat() if isinstance(v.created_at, datetime) else v.created_at,
                "prompt": v.prompt,
                "endpoint_url": v.endpoint_url,
                "commit_message": v.commit_message,
                "code_path": v.code_path
            })
    
    return versions_list

@app.post("/api/{user_id}/{api_slug}/restore/{version}", response_model=APIModificationResponse)
async def restore_api_version(
    user_id: str,
    api_slug: str,
    version: int,
    request: Request,
    user: User = Depends(get_current_user)
):
    """Restore a specific version of the API."""
    # Verify the user owns this API
    if user.id != user_id:
        raise HTTPException(status_code=403, detail="Access denied")
    
    try:
        code = file_service.restore_version(user_id, api_slug, version)
        
        # Return response similar to modify_api so frontend can update
        endpoint_url = f"{settings.API_PREFIX}/{user_id}/{api_slug}"
        return APIModificationResponse(
            success=True,
            message=f"Restored version {version}",
            endpoint_url=endpoint_url,
            api_slug=api_slug,
            user_id=user_id,
            modified_at=datetime.now(),
            documentation="Documentation restored (please refresh)", 
            curl_example=f"curl {endpoint_url}",
            prompt="Restored version", 
            modification_prompt=f"Restore version {version}"
        )
    except Exception as e:
        logger.error(f"Failed to restore version: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# modify the existing api code based on the user prompt and create a new version
@app.post("/modify-api")
async def modify_api(
    modification_request: APIModificationRequest,
    request: Request,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Modify an existing API's code based on user prompt with real-time streaming chat messages.
    
    This endpoint focuses on modifying the actual generated code of an existing API.
    For proposal-level modifications, use the /modify-proposal endpoint instead.
    
    The endpoint assumes the modification request has been validated and is ready
    to be applied to the existing code and creates a new version of the API.
    """
    from fastapi.responses import StreamingResponse
    
    # Extract user and API key info
    current_user, api_key_id = user_and_key
    if not current_user:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    logger.info(f"Starting streaming API modification for user {current_user.id}")
    
    # Check usage limits before proceeding
    try:
        limits = await usage_service.check_usage_limits(
            user_id=modification_request.user_id,
            api_key_id=api_key_id,
            tokens_to_use=1500  # Estimated tokens for code modification
        )
        
        if limits.is_over_limit:
            # Log the limit breach for monitoring
            logger.warning(f"Rate limit exceeded for user {modification_request.user_id}: {limits.limit_exceeded_reason}")
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
    
    async def modify_stream():
        """Generator function for streaming API modification"""
        try:
            # Send initial status message
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Starting API modification...",
                    "is_ai": True,
                    "message_type": "greeting"
                }
            }) + "\n\n"
            
            # Check if API exists
            if not file_service.api_exists(modification_request.user_id, modification_request.api_slug):
                yield "data: " + json.dumps({
                    "type": "error",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": f"API not found: {modification_request.user_id}/{modification_request.api_slug}",
                        "error_type": "NotFoundError"
                    }
                }) + "\n\n"
                return
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Loading existing API code...",
                    "is_ai": True,
                    "message_type": "loading"
                }
            }) + "\n\n"
            
            # Load existing code
            existing_code = file_service.load_api_code(modification_request.user_id, modification_request.api_slug)
            
            # Ensure we have a version history started before modifying
            file_service.create_initial_version_if_needed(modification_request.user_id, modification_request.api_slug)
            
            # Initialize analysis_result for backward compatibility with debug info
            analysis_result = "Analysis skipped - using dedicated proposal modification endpoint"
            issues_found = []
            fixes_applied = []
            
            # Validate Claude API key
            if not settings.CLAUDE_API_KEY:
                yield "data: " + json.dumps({
                    "type": "error",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": "Claude API key not configured",
                        "error_type": "ConfigurationError"
                    }
                }) + "\n\n"
                return
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Generating modified code using AI...",
                    "is_ai": True,
                    "message_type": "code_generation"
                }
            }) + "\n\n"
            
            # Generate modified code using Claude
            raw_code = await claude_service.modify_api_code(
                prompt=modification_request.prompt,
                sample_input=modification_request.sample_input,
                expected_output=modification_request.expected_output,
                existing_code=existing_code,
                user_id=modification_request.user_id,
                api_key_id=api_key_id,
                api_slug=modification_request.api_slug
            )

            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Code generation completed! Now analyzing and fixing any issues...",
                    "is_ai": True,
                    "message_type": "code_generation"
                }
            }) + "\n\n"
            
            # Debug and fix the generated code
            try:
                code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
                    raw_code, modification_request.prompt, modification_request.user_id, api_key_id
                )
            except Exception as debug_error:
                logger.warning(f"Code debugger failed: {debug_error}. Using raw code.")
                # Fallback to raw code if debugger fails
                code = raw_code
                issues_found = [f"Code debugger failed: {str(debug_error)}"]
                fixes_applied = []
                
                yield "data: " + json.dumps({
                    "type": "chat_message",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": f"Code debugging failed, proceeding with raw code: {str(debug_error)}",
                        "is_ai": True,
                        "message_type": "warning"
                    }
                }) + "\n\n"
            
            if issues_found:
                yield "data: " + json.dumps({
                    "type": "chat_message",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": f"Found and fixed {len(issues_found)} code issues: {', '.join(issues_found)}",
                        "is_ai": True,
                        "message_type": "code_fixing"
                    }
                }) + "\n\n"
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Validating code for security...",
                    "is_ai": True,
                    "message_type": "security_check"
                }
            }) + "\n\n"
            
            # Validate code for security
            is_safe, violations = security_service.validate_code(code)
            if violations:
                logger.warning(f"Security violations found: {violations}")
            if not is_safe:
                yield "data: " + json.dumps({
                    "type": "error",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": f"Code failed security validation: {'; '.join(violations)}",
                        "error_type": "SecurityValidationError"
                    }
                }) + "\n\n"
                return
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Code passed security validation! Saving your API...",
                    "is_ai": True,
                    "message_type": "security_check"
                }
            }) + "\n\n"
            
            # Save the new code
            full_slug = f"{modification_request.user_id}_{modification_request.api_slug}"
            try:
                await file_service.save_api_code(full_slug, code)
            except Exception as save_error:
                # Don't hard-fail modification when disk is read-only/permissions are restricted.
                # We'll persist the updated code to MongoDB below.
                logger.warning(f"Failed to save modified API code to disk (continuing with DB persistence): {save_error}")
                yield "data: " + json.dumps({
                    "type": "chat_message",
                    "timestamp": datetime.now().isoformat(),
                    "data": {
                        "message": "⚠️ Could not write modified API file to disk (permissions). Continuing by saving the updated code in the database.",
                        "is_ai": True,
                        "message_type": "warning"
                    }
                }) + "\n\n"

            # Persist updated code in DB for environments where generated_apis/ is ephemeral.
            try:
                mongodb.saved_apis.update_one(
                    {"user_id": modification_request.user_id, "api_slug": modification_request.api_slug},
                    {"$set": {"code": code}}
                )
            except Exception as db_err:
                logger.warning(f"Failed to persist modified API code to database: {db_err}")
            
            # Save new version
            endpoint_url = f"{settings.API_PREFIX}/{modification_request.user_id}/{modification_request.api_slug}"
            try:
                file_service.save_version(
                    user_id=modification_request.user_id,
                    api_slug=modification_request.api_slug,
                    code=code,
                    prompt=modification_request.prompt,
                    endpoint_url=endpoint_url,
                    commit_message=f"Modification: {modification_request.prompt[:50]}..."
                )
            except Exception as e:
                logger.error(f"Failed to save version history: {e}")
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Updating documentation...",
                    "is_ai": True,
                    "message_type": "documentation"
                }
            }) + "\n\n"

            # Modify the documentation of the existing API 
            if settings.GENERATE_DOCS_SERVICE == "OPENAI_SERVICE":
                doc_service = openai_service
            else:
                doc_service = claude_service

            # Check if there is existing documentation; if not, create from scratch, else modify
            existing_doc = await file_service.load_api_documentation(
                user_id=modification_request.user_id,
                api_slug=modification_request.api_slug
            ) if hasattr(file_service, "load_api_documentation") else None
            
            # Get API name from metadata if available
            api_metadata = file_service.get_api_metadata(
                user_id=modification_request.user_id,
                api_slug=modification_request.api_slug
            )
            api_name = api_metadata.api_name if api_metadata else None

            if not existing_doc or not existing_doc.get("documentation"):
                documentation, openapi_spec, curl_example = await doc_service.generate_documentation(
                    code=code,
                    prompt=modification_request.prompt,
                    user_id=modification_request.user_id,
                    api_key_id=api_key_id,
                    api_slug=modification_request.api_slug,
                    api_name=api_name
                )
            else:
                # Get existing documentation content
                existing_doc_content = existing_doc.get("documentation", "")
                if existing_doc.get("openapi_spec"):
                    existing_doc_content += f"\n\n## OpenAPI Specification\n```yaml\n{existing_doc.get('openapi_spec')}\n```"
                if existing_doc.get("curl_example"):
                    existing_doc_content += f"\n\n## Curl Example\n{existing_doc.get('curl_example')}"
                
                documentation, openapi_spec, curl_example = await doc_service.modify_api_documentation(
                    code=code,
                    prompt=modification_request.prompt,
                    user_id=modification_request.user_id,
                    api_key_id=api_key_id,
                    api_slug=modification_request.api_slug,
                    existing_documentation=existing_doc_content
                )

            # Build endpoint URL
            endpoint_url = f"{settings.API_PREFIX}/{modification_request.user_id}/{modification_request.api_slug}"
            
            # Update curl example with actual endpoint
            if "bucketapi" in curl_example:
                curl_example = curl_example.replace("bucketapi", endpoint_url)
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Updating API metadata...",
                    "is_ai": True,
                    "message_type": "metadata_update"
                }
            }) + "\n\n"
            
            # Update API metadata in database with new documentation
            try:
                existing_api = mongodb.saved_apis.find_one({
                    "user_id": modification_request.user_id,
                    "api_slug": modification_request.api_slug
                })
                
                if existing_api:
                    # Update existing metadata with new documentation
                    mongodb.saved_apis.update_one(
                        {"user_id": modification_request.user_id, "api_slug": modification_request.api_slug},
                        {"$set": {
                            "documentation": documentation,
                            "curl_example": curl_example,
                            "openapi_spec": json.dumps(openapi_spec) if openapi_spec else existing_api.get("openapi_spec"),
                            "prompt": modification_request.prompt,
                            "endpoint_url": endpoint_url
                        }}
                    )
                    logger.info(f"Updated API metadata in database for {modification_request.api_slug}")
                else:
                    logger.warning(f"API metadata not found in database for {modification_request.api_slug}, skipping metadata update")
            except Exception as e:
                logger.warning(f"Failed to update API metadata in database: {e}")
                # Continue without database update if service is unavailable
            
            yield "data: " + json.dumps({
                "type": "chat_message",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": "Re-analyzing code for pricing...",
                    "is_ai": True,
                    "message_type": "pricing_analysis"
                }
            }) + "\n\n"
            
            # Re-analyze the modified code to detect execution model and calculate pricing
            try:
                # Get the generation model used
                generation_model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-latest')
                
                # Analyze the modified code to detect LLM usage and calculate pricing
                metadata = await api_pricing_service.analyze_and_price_api_code(
                    api_slug=modification_request.api_slug,
                    user_id=modification_request.user_id,
                    api_code=code,
                    original_prompt=modification_request.prompt,
                    generation_model_used=generation_model
                )
                
                logger.info(f"API {modification_request.api_slug} re-analysis complete: execution_model={metadata.execution_model_used or metadata.ai_model_used}, generation_model={generation_model}")
                
            except Exception as e:
                logger.warning(f"Failed to re-analyze API code after modification: {e}")
                # Continue without pricing analysis if service is unavailable
            
            # Send final success message with results
            yield "data: " + json.dumps({
                "type": "modification_complete",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "success": True,
                    "message": "Your API has been modified successfully!",
                    "endpoint_url": endpoint_url,
                    "documentation": documentation,
                    "curl_example": curl_example,
                    "api_slug": modification_request.api_slug,
                    "user_id": modification_request.user_id,
                    "modified_at": datetime.now().isoformat(),
                    "debug_info": {
                        "issues_found": issues_found,
                        "fixes_applied": fixes_applied,
                        "code_quality": "high" if not issues_found else "improved",
                        "chat_analysis": analysis_result
                    }
                }
            }) + "\n\n"
            
        except HTTPException as e:
            yield "data: " + json.dumps({
                "type": "error",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": f"{e.detail}",
                    "error_type": "HTTPException",
                    "status_code": e.status_code
                }
            }) + "\n\n"
        except Exception as e:
            logger.error(f"Unexpected error in modify_api: {str(e)}", exc_info=True)
            yield "data: " + json.dumps({
                "type": "error",
                "timestamp": datetime.now().isoformat(),
                "data": {
                    "message": f"Failed to modify API: {str(e)}",
                    "error_type": type(e).__name__
                }
            }) + "\n\n"
    
    return StreamingResponse(
        modify_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "*",
        }
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

# ===================================
# CUSTOM DOMAIN ENDPOINTS
# NOTE: These routes MUST come before /api/{user_id} to avoid route conflicts
# ===================================

@app.post("/api/domains", response_model=CreateDomainResponse)
async def create_domain(
    request: CreateDomainRequest,
    current_user: User = Depends(require_active_user)
):
    """
    Register a custom domain for an API.
    The domain must be verified via DNS TXT record before it becomes active.
    """
    try:
        logger.info(f"User {current_user.id} creating domain {request.domain} for API {request.api_slug}")
        
        result = await domain_service.create_domain(
            user_id=current_user.id,
            request=request
        )
        
        if not result.success:
            raise HTTPException(status_code=400, detail=result.message)
        
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating domain: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to create domain: {str(e)}")


@app.get("/api/domains", response_model=ListDomainsResponse)
async def list_domains(
    api_slug: Optional[str] = None,
    current_user: User = Depends(require_active_user)
):
    """
    List all custom domains for the authenticated user.
    Optionally filter by API slug.
    """
    try:
        return await domain_service.list_domains(
            user_id=current_user.id,
            api_slug=api_slug
        )
    except Exception as e:
        logger.error(f"Error listing domains: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to list domains: {str(e)}")


@app.get("/api/domains/{domain_id}", response_model=DomainStatusResponse)
async def get_domain(
    domain_id: str,
    current_user: User = Depends(require_active_user)
):
    """Get details for a specific domain."""
    try:
        domain = await domain_service.get_domain(domain_id, current_user.id)
        
        if not domain:
            raise HTTPException(status_code=404, detail="Domain not found")
        
        return DomainStatusResponse(
            success=True,
            domain=domain,
            ssl_status=domain.ssl_certificate_status,
            message=f"Domain status: {domain.status.value}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting domain: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get domain: {str(e)}")


@app.post("/api/domains/{domain_id}/verify", response_model=VerifyDomainResponse)
async def verify_domain(
    domain_id: str,
    current_user: User = Depends(require_active_user)
):
    """
    Verify domain ownership via DNS TXT record or HTTP file.
    Must be called after DNS/HTTP setup is complete.
    """
    try:
        logger.info(f"User {current_user.id} verifying domain {domain_id}")
        
        result = await domain_verification_service.verify_domain(
            domain_id=domain_id,
            user_id=current_user.id
        )
        
        return result
        
    except Exception as e:
        logger.error(f"Error verifying domain: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to verify domain: {str(e)}")


@app.delete("/api/domains/{domain_id}", response_model=DeleteDomainResponse)
async def delete_domain(
    domain_id: str,
    current_user: User = Depends(require_active_user)
):
    """Delete a custom domain."""
    try:
        logger.info(f"User {current_user.id} deleting domain {domain_id}")
        
        return await domain_service.delete_domain(
            domain_id=domain_id,
            user_id=current_user.id
        )
        
    except Exception as e:
        logger.error(f"Error deleting domain: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to delete domain: {str(e)}")


@app.get("/api/domains/{domain_id}/status", response_model=DomainStatusResponse)
async def get_domain_status(
    domain_id: str,
    current_user: User = Depends(require_active_user)
):
    """Get verification and SSL status for a domain."""
    try:
        domain = await domain_service.get_domain(domain_id, current_user.id)
        
        if not domain:
            raise HTTPException(status_code=404, detail="Domain not found")
        
        # Check SSL status if domain is active
        ssl_status = domain.ssl_certificate_status
        if domain.status == DomainStatus.ACTIVE:
            ssl_info = await caddy_service.check_ssl_status(domain.domain)
            if ssl_info and ssl_info.get("issued"):
                ssl_status = SSLCertificateStatus.ISSUED
        
        return DomainStatusResponse(
            success=True,
            domain=domain,
            ssl_status=ssl_status,
            message=f"Domain is {domain.status.value}"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting domain status: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get domain status: {str(e)}")


# ===================================
# CADDY INTEGRATION ENDPOINT
# ===================================

@app.get("/api/caddy/check-domain")
async def check_domain_for_caddy(domain: str):
    """
    Called by Caddy before issuing SSL certificate via on-demand TLS.
    Returns 200 if domain is verified and allowed, 403 otherwise.
    
    This endpoint MUST respond quickly (Caddy has a timeout).
    """
    try:
        is_allowed = await domain_service.check_domain_for_caddy(domain)
        
        if is_allowed:
            logger.info(f"Caddy check: Domain {domain} is allowed for SSL")
            return Response(status_code=200)
        
        logger.warning(f"Caddy check: Domain {domain} is NOT allowed for SSL")
        return Response(status_code=403)
        
    except Exception as e:
        logger.error(f"Error checking domain for Caddy: {str(e)}")
        return Response(status_code=403)


@app.get("/api/caddy/health")
async def caddy_health():
    """Check Caddy connectivity status."""
    try:
        is_healthy = await caddy_service.health_check()
        
        return {
            "success": is_healthy,
            "message": "Caddy is healthy" if is_healthy else "Caddy is not reachable",
            "status": "healthy" if is_healthy else "unhealthy"
        }
        
    except Exception as e:
        logger.error(f"Caddy health check failed: {str(e)}")
        return {
            "success": False,
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy"
        }


@app.get("/api/domains/health")
async def domains_health():
    """Check domain service health."""
    try:
        # Count domains by status
        total_domains = mongodb.custom_domains.count_documents({})
        active_domains = mongodb.custom_domains.count_documents({"status": DomainStatus.ACTIVE.value})
        pending_domains = mongodb.custom_domains.count_documents({"status": DomainStatus.PENDING.value})
        
        return {
            "success": True,
            "total_domains": total_domains,
            "active_domains": active_domains,
            "pending_domains": pending_domains,
            "status": "healthy"
        }
        
    except Exception as e:
        logger.error(f"Domain health check failed: {str(e)}")
        return {
            "success": False,
            "message": f"Health check failed: {str(e)}",
            "status": "unhealthy"
        }

# ===================================
# USER API ENDPOINTS
# ===================================

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
        
        # Convert to JSON-serializable format
        import json
        from bson import ObjectId
        
        def json_serializer(obj):
            """JSON serializer for objects not serializable by default json code"""
            if isinstance(obj, datetime):
                return obj.isoformat()
            if isinstance(obj, ObjectId):
                return str(obj)
            if hasattr(obj, 'model_dump'):
                return obj.model_dump()
            if hasattr(obj, 'dict'):
                return obj.dict()
            raise TypeError(f"Type {type(obj)} not serializable")
        
        # Recursively serialize the dict
        def serialize_dict(d):
            if isinstance(d, dict):
                return {k: serialize_dict(v) for k, v in d.items()}
            elif isinstance(d, list):
                return [serialize_dict(item) for item in d]
            elif isinstance(d, datetime):
                return d.isoformat()
            elif hasattr(d, 'model_dump'):
                return serialize_dict(d.model_dump())
            elif hasattr(d, 'dict'):
                return serialize_dict(d.dict())
            else:
                try:
                    json_serializer(d)
                    return d
                except (TypeError, AttributeError):
                    return str(d)
        
        serialized = serialize_dict(api_details)
        
        # Verify it's JSON serializable before returning
        try:
            json.dumps(serialized)
        except TypeError as e:
            logger.error(f"JSON serialization failed: {e}")
            logger.error(f"Problematic data: {serialized}")
            raise HTTPException(
                status_code=500,
                detail=f"Failed to serialize API details: {str(e)}"
            )
        
        return serialized
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting API details for {user_id}/{api_slug}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to get API details: {str(e)}"
        )

@app.post("/api/{user_id}/{api_slug}/test-database-connection")
async def test_api_database_connection(user_id: str, api_slug: str):
    """
    Test the database connection for a specific API.
    """
    try:
        api_details = file_service.get_api_details(user_id, api_slug)
        
        # Check if API has database configuration
        if not api_details.get("database_config"):
            return {
                "success": False,
                "message": "This API does not have a database connection configured",
                "has_database": False
            }
        
        # Get database config
        db_config_dict = api_details["database_config"]
        
        # Check if database is enabled
        if not db_config_dict.get("enabled"):
            return {
                "success": False,
                "message": "Database connection is disabled for this API",
                "has_database": True,
                "enabled": False
            }
        
        # Create DatabaseConfig object
        db_config = DatabaseConfig(**db_config_dict)
        
        # Test the connection
        success, message, connection_time = await database_connection_service.test_connection(db_config)
        
        return {
            "success": success,
            "message": message,
            "connection_time_ms": connection_time,
            "has_database": True,
            "enabled": True,
            "db_type": db_config.db_type.value if db_config.db_type else None,
            "host": db_config.host,
            "port": db_config.port,
            "database_name": db_config.database_name
        }
    except Exception as e:
        logger.error(f"Error testing database connection for {user_id}/{api_slug}: {str(e)}", exc_info=True)
        return {
            "success": False,
            "message": f"Failed to test connection: {str(e)}",
            "has_database": True,
            "enabled": True
        }

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

@app.post("/generate-documentation", response_model=GenerateDocumentationResponse)
async def generate_documentation(
    doc_request: GenerateDocumentationRequest,
    user_and_key: Tuple[Optional[User], Optional[str]] = Depends(get_current_user_and_api_key_hybrid)
):
    """
    Generate documentation for an existing API.
    This endpoint regenerates documentation for an API by loading its code and metadata.
    """
    try:
        current_user, api_key_id = user_and_key
        
        # Verify user has access to this API
        if current_user and current_user.id != doc_request.user_id:
            raise HTTPException(
                status_code=403,
                detail="Access denied: You can only generate documentation for your own APIs"
            )
        
        # Check if API exists
        if not file_service.api_exists(doc_request.user_id, doc_request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {doc_request.user_id}/{doc_request.api_slug}"
            )
        
        # Get API metadata to retrieve prompt and other info
        api_metadata = file_service.get_api_metadata(doc_request.user_id, doc_request.api_slug)
        if not api_metadata:
            raise HTTPException(
                status_code=404,
                detail=f"API metadata not found: {doc_request.user_id}/{doc_request.api_slug}"
            )
        
        # Load API code
        code = file_service.load_api_code(doc_request.user_id, doc_request.api_slug)
        
        # Generate documentation
        documentation, openapi_spec, curl_example = await openai_service.generate_documentation(
            code=code,
            prompt=api_metadata.prompt,
            user_id=doc_request.user_id,
            api_key_id=api_key_id,
            api_slug=doc_request.api_slug,
            api_name=api_metadata.api_name
        )
        
        # Build endpoint URL
        endpoint_url = f"{settings.API_PREFIX}/{doc_request.user_id}/{doc_request.api_slug}"
        
        # Update curl example with actual endpoint
        if "your-endpoint-url" in curl_example:
            curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
        
        # Update API documentation in database
        try:
            # Update existing metadata with new documentation
            mongodb.saved_apis.update_one(
                {"user_id": doc_request.user_id, "api_slug": doc_request.api_slug},
                {"$set": {
                    "documentation": documentation,
                    "curl_example": curl_example,
                    "openapi_spec": json.dumps(openapi_spec) if openapi_spec else api_metadata.openapi_spec,
                    "endpoint_url": endpoint_url
                }}
            )
            logger.info(f"API documentation updated in database for {doc_request.api_slug}")
        except Exception as e:
            logger.warning(f"Failed to update API documentation in database: {e}")
            # Continue even if database update fails
        
        return GenerateDocumentationResponse(
            success=True,
            message=f"Documentation generated successfully for {doc_request.api_slug}",
            api_slug=doc_request.api_slug,
            documentation=documentation
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to generate documentation for {doc_request.api_slug}: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate documentation: {str(e)}"
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
                is_test_execution=True  # This is a test execution
            )
            
            execution_time = time.time() - start_time
            
            # Format response data - handle binary data specially
            if isinstance(result, bytes):
                # Binary data (like images) - base64 encode for JSON serialization
                response_data = {
                    "result_type": "binary",
                    "content_type": "application/octet-stream",
                    "size_bytes": len(result),
                    "data_base64": base64.b64encode(result).decode('ascii'),
                    "message": "Binary data returned successfully"
                }
                status_code = 200
            elif isinstance(result, dict):
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
            
            # Automatically attempt to fix the code using the new auto-debug loop system
            logger.info(f"API execution failed, starting auto-debug loop...")
            try:
                # Use the new protected smart debug loop system with retry
                debug_session = await code_debugger.protected_smart_debug_with_retry(
                    user_id=request.user_id,
                    api_slug=request.api_slug,
                    test_request=request.dict(),
                    max_iterations=3,  # Allow up to 3 debug iterations
                    confidence_threshold=0.7,  # Require 70% confidence for success
                    user_api_key_id=None  # No API key tracking for test endpoint
                )
                
                debugged = True
                
                # Check if the debug loop was successful
                if debug_session.get("overall_success", False):
                    logger.info(f"Auto-debug loop successful! Iterations: {len(debug_session.get('iterations', []))}")
                    
                    # Get the final successful result from the debug session
                    best_result = debug_session.get("best_result", {})
                    final_test_result = best_result.get("test_result", {})
                    
                    if final_test_result.get("success", False):
                        # Update response to success
                        error_response.success = True
                        error_response.response_data = final_test_result.get("response_data")
                        error_response.error = None
                        error_response.status_code = 200
                        error_response.execution_time = debug_session.get("total_execution_time", execution_time)
                        error_response.debugged = True
                        
                        logger.info("API execution successful after auto-debug loop!")
                    
                    # Add comprehensive debug information
                    error_response.validation = {
                        "is_valid": True,
                        "confidence": debug_session.get("best_confidence", 0.0),
                        "validation_message": f"Auto-debug successful in {len(debug_session.get('iterations', []))} iterations",
                        "issues_found": [],
                        "auto_fix_applied": True,
                        "debug_session": {
                            "session_id": debug_session.get("session_id"),
                            "final_status": debug_session.get("final_status"),
                            "iterations": len(debug_session.get("iterations", [])),
                            "code_changes_made": debug_session.get("code_changes_made", 0),
                            "total_execution_time": debug_session.get("total_execution_time", 0),
                            "validation_improvements": debug_session.get("validation_improvements", [])
                        },
                        "debug_completed_at": datetime.now().isoformat(),
                        "validator": "smart_debug_loop"
                    }
                    
                else:
                    # Debug loop didn't achieve success, but may have made improvements
                    logger.warning(f"Auto-debug loop completed without full success. Status: {debug_session.get('final_status')}")
                    
                    best_confidence = debug_session.get("best_confidence", 0.0)
                    iterations_count = len(debug_session.get("iterations", []))
                    
                    # Add debug information to the error response
                    error_response.validation = {
                        "is_valid": False,
                        "confidence": best_confidence,
                        "validation_message": f"Auto-debug attempted {iterations_count} iterations, best confidence: {best_confidence:.2f}",
                        "issues_found": [],
                        "auto_fix_applied": debug_session.get("code_changes_made", 0) > 0,
                        "debug_session": {
                            "session_id": debug_session.get("session_id"),
                            "final_status": debug_session.get("final_status"),
                            "iterations": iterations_count,
                            "code_changes_made": debug_session.get("code_changes_made", 0),
                            "total_execution_time": debug_session.get("total_execution_time", 0),
                            "best_confidence": best_confidence,
                            "reason": debug_session.get("final_status", "unknown")
                        },
                        "debug_completed_at": datetime.now().isoformat(),
                        "validator": "smart_debug_loop"
                    }
                    
                    # If we have a reasonably good result, update the response
                    if best_confidence >= 0.5 and debug_session.get("best_result"):
                        best_result = debug_session["best_result"]
                        final_test_result = best_result.get("test_result", {})
                        
                        if final_test_result.get("success", False):
                            error_response.success = True
                            error_response.response_data = final_test_result.get("response_data")
                            error_response.error = None
                            error_response.status_code = 200
                            error_response.validation["is_valid"] = True
                            error_response.validation["validation_message"] += " (Acceptable result achieved)"
                            
                            logger.info(f"Using best result from debug loop (confidence: {best_confidence:.2f})")
                    
            except Exception as debug_error:
                logger.error(f"Auto-debug loop failed: {str(debug_error)}")
                error_response.validation = {
                    "is_valid": False,
                    "confidence": 0.0,
                    "validation_message": f"Auto-debug loop failed: {str(debug_error)}",
                    "issues_found": [],
                    "auto_fix_applied": False,
                    "debug_error": str(debug_error),
                    "debug_completed_at": datetime.now().isoformat(),
                    "validator": "smart_debug_loop"
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
            # First, try to get existing API metadata
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
            logger.info(f"Cost estimation: {cost_estimation}")

        except HTTPException as http_e:
            if http_e.status_code == 404:
                # API metadata not found - this is the first test, analyze the code
                logger.info(f"First test for API {request.api_slug} - analyzing code for pricing")
                try:
                    # Load the API code for analysis
                    api_code = file_service.load_api_code(request.user_id, request.api_slug)
                    
                    # Analyze the code to detect LLM usage and calculate pricing
                    # Try to get the generation model from the API metadata if available
                    generation_model = None
                    try:
                        # For now, we'll use the default generation model from config
                        generation_model = getattr(settings, 'CLAUDE_MODEL', 'claude-3-5-haiku-latest')
                    except:
                        generation_model = 'claude-3-5-haiku-latest'  # Default fallback
                    
                    metadata = await api_pricing_service.analyze_and_price_api_code(
                        api_slug=request.api_slug,
                        user_id=request.user_id,
                        api_code=api_code,
                        original_prompt="",  # We don't have the original prompt in test context
                        generation_model_used=generation_model
                    )
                    
                    # Now get the cost estimation
                    api_cost = await api_pricing_service.get_api_execution_cost(
                        api_slug=request.api_slug,
                        user_id=request.user_id
                    )
                    
                    cost_estimation = {
                        "cost_per_call_cents": api_cost.cost_per_call_cents,
                        "internal_tokens_per_call": api_cost.internal_tokens_per_call,
                        "ai_model_used": api_cost.ai_model_used,
                        "complexity_multiplier": api_cost.complexity_multiplier,
                        "estimated_tokens_used": api_cost.estimated_tokens_used,
                        "first_time_analysis": True,  # Flag to indicate this was analyzed during testing
                        "analysis_confidence": getattr(metadata, 'analysis_details', {}).get('confidence_score', 0.0)
                    }
                    
                    logger.info(f"Code analysis complete for {request.api_slug}: "
                               f"model={api_cost.ai_model_used}, cost={api_cost.cost_per_call_cents}$, "
                               f"tokens={api_cost.internal_tokens_per_call}")
                    
                except Exception as analysis_error:
                    logger.error(f"Failed to analyze API code during first test: {str(analysis_error)}")
                    # Fall back to default estimation
                    cost_estimation = {
                        "cost_per_call_cents": 2,  # Default 2 cents
                        "internal_tokens_per_call": 20,  # Default 20 internal tokens
                        "ai_model_used": "estimated",
                        "complexity_multiplier": 1.5,
                        "estimated_tokens_used": 1000,
                        "analysis_error": str(analysis_error)
                    }
            else:
                raise
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
                "x-ai-model-used": cost_estimation["ai_model_used"],
                "x-first-time-analysis": str(cost_estimation.get("first_time_analysis", False)).lower()
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
                            try:
                                await file_service.save_api_code(f"{request.user_id}_{backup_slug}", current_code)
                            except Exception as save_err:
                                logger.warning(f"Failed to save backup code to disk (continuing): {save_err}")
                            
                            # Save fixed code
                            try:
                                await file_service.save_api_code(
                                    f"{request.user_id}_{request.api_slug}",
                                    debug_result["fixed_code"]
                                )
                            except Exception as save_err:
                                logger.warning(f"Failed to save fixed code to disk (continuing with DB persistence): {save_err}")

                            # Persist fixed code in DB so future executions work even without disk persistence.
                            try:
                                mongodb.saved_apis.update_one(
                                    {"user_id": request.user_id, "api_slug": request.api_slug},
                                    {"$set": {"code": debug_result["fixed_code"]}}
                                )
                            except Exception as db_err:
                                logger.warning(f"Failed to persist fixed API code to database: {db_err}")
                            
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


@app.post("/test-database-connection", response_model=TestDatabaseConnectionResponse)
async def test_database_connection(request: TestDatabaseConnectionRequest):
    """
    Test a database connection with the provided credentials.
    Supports PostgreSQL and MongoDB databases.
    """
    logger.info(f"=== TEST-DATABASE-CONNECTION ENDPOINT CALLED ===")
    logger.info(f"Testing {request.db_type} connection to {request.host}:{request.port}/{request.database_name}")
    
    try:
        # Create a DatabaseConfig from the request
        config = DatabaseConfig(
            enabled=True,
            db_type=request.db_type,
            host=request.host,
            port=request.port,
            database_name=request.database_name,
            username=request.username,
            password=request.password
        )
        
        # Test the connection
        success, message, connection_time_ms = await database_connection_service.test_connection(config)
        
        logger.info(f"Database connection test result: success={success}, message={message}")
        
        return TestDatabaseConnectionResponse(
            success=success,
            message=message,
            db_type=request.db_type,
            connection_time_ms=connection_time_ms
        )
        
    except Exception as e:
        logger.error(f"Database connection test error: {str(e)}", exc_info=True)
        return TestDatabaseConnectionResponse(
            success=False,
            message=f"Connection test failed: {str(e)}",
            db_type=request.db_type,
            connection_time_ms=None
        )

@app.post("/debug-api")
async def debug_api_with_loop(request: TestRequest):
    """
    Manually trigger the auto-debug loop system for an API.
    This endpoint allows users to explicitly debug their APIs with multiple iterations.
    """
    logger.info(f"=== DEBUG-API ENDPOINT CALLED ===")
    logger.info(f"Starting manual debug loop for API {request.api_slug} (user: {request.user_id})")
    
    start_time = time.time()
    debug_id = str(uuid.uuid4())
    
    try:
        # Check if API exists
        if not file_service.api_exists(request.user_id, request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {request.user_id}/{request.api_slug}"
            )
        
        # Use the protected smart debug loop system with configurable parameters
        debug_session = await code_debugger.protected_smart_debug_with_retry(
            user_id=request.user_id,
            api_slug=request.api_slug,
            test_request=request.dict(),
            max_iterations=5,  # Allow more iterations for manual debugging
            confidence_threshold=0.8,  # Higher threshold for manual debugging
            user_api_key_id=None  # No API key tracking for debug endpoint
        )
        
        total_time = time.time() - start_time
        
        # Create comprehensive response
        debug_response = {
            "success": debug_session.get("overall_success", False),
            "debug_id": debug_id,
            "session_id": debug_session.get("session_id"),
            "api_slug": request.api_slug,
            "user_id": request.user_id,
            "total_execution_time": total_time,
            "debug_session": debug_session,
            "summary": {
                "iterations_completed": len(debug_session.get("iterations", [])),
                "code_changes_made": debug_session.get("code_changes_made", 0),
                "final_confidence": debug_session.get("best_confidence", 0.0),
                "final_status": debug_session.get("final_status"),
                "validation_improvements": debug_session.get("validation_improvements", [])
            },
            "timestamp": datetime.now().isoformat()
        }
        
        # Add final result if available
        if debug_session.get("best_result"):
            best_result = debug_session["best_result"]
            debug_response["final_test_result"] = {
                "success": best_result.get("test_result", {}).get("success", False),
                "response_data": best_result.get("test_result", {}).get("response_data"),
                "validation": best_result.get("validation", {}),
                "achieved_in_iteration": best_result.get("iteration", 0)
            }
        
        logger.info(f"Manual debug loop completed: {debug_response['success']} "
                   f"(iterations: {debug_response['summary']['iterations_completed']}, "
                   f"confidence: {debug_response['summary']['final_confidence']:.2f})")
        
        return debug_response
        
    except HTTPException:
        raise
    except Exception as e:
        total_time = time.time() - start_time
        logger.error(f"Manual debug loop failed: {str(e)}", exc_info=True)
        
        return {
            "success": False,
            "debug_id": debug_id,
            "api_slug": request.api_slug,
            "user_id": request.user_id,
            "total_execution_time": total_time,
            "error": str(e),
            "error_type": type(e).__name__,
            "timestamp": datetime.now().isoformat(),
            "summary": {
                "iterations_completed": 0,
                "code_changes_made": 0,
                "final_confidence": 0.0,
                "final_status": "error"
            }
        }

@app.get("/debug-service/status")
async def get_debug_service_status():
    """
    Get the current status of the debug service including circuit breaker and rate limits.
    """
    try:
        status = code_debugger.get_debug_service_status()
        return {
            "success": True,
            "status": status,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        logger.error(f"Failed to get debug service status: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

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

@app.get("/api-generation-limits", response_model=APIGenerationLimitsResponse)
async def get_api_generation_limits(
    request: Request,
    api_key_id: Optional[str] = None,
    current_user: User = Depends(require_auth_hybrid)
):
    """Get API generation limits and current usage for the current user."""
    try:
        limits = await api_generation_usage_service.check_generation_limits(
            user_id=current_user.id,
            api_key_id=api_key_id,
            tokens_to_use=2000  # Estimated tokens for API generation
        )
        return limits
    except Exception as e:
        logger.error(f"Failed to get API generation limits: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get generation limits: {str(e)}")

@app.get("/api/{user_id}/{api_slug}/usage-stats")
async def get_api_usage_stats(
    user_id: str,
    api_slug: str,
    days: int = 30,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Get comprehensive usage statistics for a specific API."""
    try:
        # Verify user has access to this API
        if current_user.id != user_id:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # Check if API exists
        if not file_service.api_exists(user_id, api_slug):
            raise HTTPException(status_code=404, detail="API not found")
        
        # Get usage statistics from the aggregator
        from app.services.api_usage_aggregator import APIUsageAggregator
        usage_aggregator = APIUsageAggregator()
        
        usage_stats = await usage_aggregator.get_api_usage_stats(
            api_slug=api_slug,
            user_id=user_id,
            days_back=days
        )
        
        # Get execution statistics as well
        execution_stats = await api_execution_usage_service.get_execution_stats(
            user_id=user_id,
            days=days
        )
        
        # Filter execution stats for this specific API
        api_execution_data = None
        if hasattr(execution_stats, 'by_api') and api_slug in execution_stats.by_api:
            api_execution_data = execution_stats.by_api[api_slug]
        
        # Combine the data
        response_data = {
            "api_slug": api_slug,
            "user_id": user_id,
            "days_analyzed": days,
            "has_usage_data": usage_stats is not None,
            "usage_stats": usage_stats.__dict__ if usage_stats else None,
            "execution_data": api_execution_data,
            "recent_executions": execution_stats.recent_executions if hasattr(execution_stats, 'recent_executions') else []
        }
        
        return response_data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get API usage stats for {api_slug}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get usage statistics: {str(e)}")

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

@app.get("/estimate-api-cost/{api_slug}", response_model=EstimateAPIUsageCostResponse)
async def get_api_usage_cost_estimate(
    api_slug: str,
    expected_calls_per_month: int = 1000,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Get API usage cost using real usage data when available, fallback to initial estimates."""
    try:
        estimate = await api_pricing_service.get_api_usage_cost_with_real_data(
            api_slug=api_slug,
            user_id=current_user.id,
            expected_calls_per_month=expected_calls_per_month
        )
        return estimate
    except Exception as e:
        logger.error(f"Failed to get API usage cost: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get API usage cost: {str(e)}")

@app.get("/api-cost/{api_slug}")
async def get_api_execution_cost(
    api_slug: str,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Get API execution cost, using real usage data when available."""
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

@app.post("/api-cost/{api_slug}/update-with-real-usage")
async def update_api_pricing_with_real_usage(
    api_slug: str,
    current_user: User = Depends(require_auth_or_api_key)
):
    """Update API pricing with real usage statistics from executed calls."""
    try:
        from app.services.api_usage_aggregator import api_usage_aggregator
        
        # Get real usage statistics
        usage_stats = await api_usage_aggregator.get_api_usage_stats(
            api_slug=api_slug,
            user_id=current_user.id
        )
        
        if not usage_stats:
            return {
                "success": False,
                "message": "No usage data found for this API",
                "executions": 0
            }
        
        if usage_stats.successful_executions < 3:
            return {
                "success": False,
                "message": f"Need at least 3 successful executions for reliable pricing (have {usage_stats.successful_executions})",
                "executions": usage_stats.successful_executions,
                "usage_stats": {
                    "total_executions": usage_stats.total_executions,
                    "successful_executions": usage_stats.successful_executions,
                    "avg_tokens": usage_stats.avg_total_tokens,
                    "avg_cost_cents": usage_stats.avg_cost_per_call_cents
                }
            }
        
        # Update pricing with real usage
        updated = await api_usage_aggregator.update_api_pricing_with_real_usage(
            api_slug=api_slug,
            user_id=current_user.id
        )
        
        if updated:
            # Get updated cost information
            cost = await api_pricing_service.get_api_execution_cost(
                api_slug=api_slug,
                user_id=current_user.id
            )
            
            return {
                "success": True,
                "message": "API pricing updated with real usage data",
                "executions": usage_stats.successful_executions,
                "updated_pricing": {
                    "cost_per_call_cents": cost.cost_per_call_cents,
                    "internal_tokens_per_call": cost.internal_tokens_per_call,
                    "ai_model_used": cost.ai_model_used,
                    "estimated_tokens_used": cost.estimated_tokens_used
                },
                "usage_stats": {
                    "total_executions": usage_stats.total_executions,
                    "successful_executions": usage_stats.successful_executions,
                    "avg_tokens": usage_stats.avg_total_tokens,
                    "avg_cost_cents": usage_stats.avg_cost_per_call_cents,
                    "models_used": usage_stats.models_used,
                    "primary_model": usage_stats.primary_model_used
                }
            }
        else:
            return {
                "success": False,
                "message": "Failed to update API pricing",
                "executions": usage_stats.successful_executions
            }
            
    except Exception as e:
        logger.error(f"Failed to update API pricing with real usage: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update API pricing: {str(e)}")

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
        user = await get_current_user(request)
        if not user:
            return {"success": False, "is_admin": False, "message": "Authentication required"}
        
        is_admin = is_admin_user(user.email)
        admin_emails_str = os.getenv("ADMIN_EMAILS", "admin@localhost,admin@yourdomain.com")
        admin_emails = [e.strip() for e in admin_emails_str.split(',')]
        
        return {
            "success": True,
            "is_admin": is_admin,
            "user": {
                "email": user.email,
                "id": user.id
            },
            "admin_emails_configured": admin_emails,
            "email_contains_admin": 'admin' in user.email.lower(),
            "setup_instructions": {
                "method1": f"Set ADMIN_EMAILS environment variable to include: {user.email}",
                "method2": "Use an email address that contains 'admin' (case-insensitive)",
                "current_env": admin_emails_str
            }
        }
    except Exception as e:
        logger.error(f"Error checking admin auth: {str(e)}")
        return {"success": False, "is_admin": False, "message": f"Error: {str(e)}"}

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


# Settings endpoints

@app.get("/admin/settings")
async def get_all_settings(
    request: Request,
    category: Optional[str] = None,
    admin_user: User = Depends(require_admin_auth)
):
    """Get all system settings (admin only)."""
    try:
        from .services.settings_service import settings_service
        
        if category:
            settings_list = settings_service.get_settings_by_category(category)
        else:
            settings_list = settings_service.get_all_settings(include_sensitive=False)
        
        categories = settings_service.get_categories()
        
        return {
            "success": True,
            "settings": settings_list,
            "categories": categories
        }
    except Exception as e:
        logger.error(f"Failed to get settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get settings: {str(e)}")

@app.get("/admin/settings/{key}")
async def get_setting(
    request: Request,
    key: str,
    admin_user: User = Depends(require_admin_auth)
):
    """Get a specific setting by key (admin only)."""
    try:
        from .services.settings_service import settings_service
        
        setting = settings_service.get_setting(key)
        if not setting:
            raise HTTPException(status_code=404, detail=f"Setting not found: {key}")
        
        return {
            "success": True,
            "setting": setting
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get setting {key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get setting: {str(e)}")

@app.put("/admin/settings/{key}")
async def update_setting(
    request: Request,
    key: str,
    update_data: dict = Body(...),
    admin_user: User = Depends(require_admin_auth)
):
    """Update a specific setting (admin only)."""
    try:
        from .services.settings_service import settings_service
        
        value = update_data.get("value")
        if value is None:
            raise HTTPException(status_code=400, detail="Value is required")
        
        result = settings_service.update_setting(key, value, admin_user.id)
        
        if not result["success"]:
            raise HTTPException(status_code=400, detail=result["message"])
        
        return {
            "success": True,
            "message": result["message"],
            "setting": result.get("setting"),
            "requires_restart": result.get("requires_restart", True)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update setting {key}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update setting: {str(e)}")

@app.post("/admin/settings/bulk-update")
async def bulk_update_settings(
    request: Request,
    updates: dict = Body(...),
    admin_user: User = Depends(require_admin_auth)
):
    """Update multiple settings at once (admin only)."""
    try:
        from .services.settings_service import settings_service
        
        settings_to_update = updates.get("settings", [])
        if not settings_to_update:
            raise HTTPException(status_code=400, detail="No settings provided")
        
        results = []
        any_requires_restart = False
        
        for setting_update in settings_to_update:
            key = setting_update.get("key")
            value = setting_update.get("value")
            
            if not key or value is None:
                results.append({
                    "key": key,
                    "success": False,
                    "message": "Key and value are required"
                })
                continue
            
            result = settings_service.update_setting(key, value, admin_user.id)
            results.append({
                "key": key,
                "success": result["success"],
                "message": result["message"]
            })
            
            if result.get("requires_restart"):
                any_requires_restart = True
        
        success_count = sum(1 for r in results if r["success"])
        
        return {
            "success": True,
            "message": f"Updated {success_count} of {len(settings_to_update)} settings",
            "results": results,
            "requires_restart": any_requires_restart
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to bulk update settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to bulk update settings: {str(e)}")

@app.post("/admin/settings/reset")
async def reset_settings_to_defaults(
    request: Request,
    admin_user: User = Depends(require_admin_auth)
):
    """Reset all settings to their default values (admin only)."""
    try:
        from .services.settings_service import settings_service
        
        result = settings_service.reset_to_defaults(admin_user.id)
        
        return {
            "success": result["success"],
            "message": result["message"],
            "requires_restart": result.get("requires_restart", True)
        }
    except Exception as e:
        logger.error(f"Failed to reset settings: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to reset settings: {str(e)}")

@app.get("/admin/settings/categories")
async def get_setting_categories(
    request: Request,
    admin_user: User = Depends(require_admin_auth)
):
    """Get all setting categories (admin only)."""
    try:
        from .services.settings_service import settings_service
        
        categories = settings_service.get_categories()
        
        return {
            "success": True,
            "categories": categories
        }
    except Exception as e:
        logger.error(f"Failed to get categories: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get categories: {str(e)}")

# ===================================
# SUBSCRIPTION ENDPOINTS
# ===================================


@app.get("/subscription", response_class=HTMLResponse)
async def subscription_page(request: Request):
    """Redirect to pricing section on landing page."""
    return RedirectResponse(url="/landing#pricing", status_code=302)

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
        
        # Get current tier details from USER document (source of truth for limits)
        # This ensures consistency with limit checks in api_generation_usage_service
        user = mongodb.users.find_one({"_id": current_user.id})
        tier_name = user.get("subscription_tier", "free") if user else "free"
        current_tier = subscription_service.SUBSCRIPTION_TIERS.get(tier_name)
        
        if not current_tier:
            # Fallback to free tier if tier not found
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
        # Free tier doesn't need checkout, use change-tier endpoint instead
        if request.tier == "free":
            raise HTTPException(
                status_code=400,
                detail="Free tier does not require checkout. Use /subscription/change-tier endpoint instead."
            )
        
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
    except HTTPException:
        raise
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

@app.post("/subscription/cancel")
async def cancel_subscription_endpoint(
    current_user: User = Depends(require_active_user)
):
    """Cancel user's subscription."""
    try:
        result = await subscription_service.cancel_subscription(current_user.id)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to cancel subscription: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel subscription: {str(e)}")

@app.get("/subscription/customer-portal")
async def get_customer_portal(
    current_user: User = Depends(require_active_user)
):
    """Get LemonSqueezy customer portal URL for payment method updates."""
    try:
        # Get the subscription to extract both URLs
        subscription = await subscription_service.get_user_subscription(current_user.id)
        if not subscription:
            raise HTTPException(status_code=404, detail="No active subscription found")
        
        import os
        api_key = os.getenv("LEMONSQUEEZY_API_KEY")
        if not api_key:
            raise HTTPException(status_code=500, detail="LemonSqueezy API key not configured")
        
        # Get both URLs from LemonSqueezy
        import httpx
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"https://api.lemonsqueezy.com/v1/subscriptions/{subscription.lemonsqueezy_subscription_id}",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/vnd.api+json"
                }
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=500, detail="Failed to get portal URLs")
            
            data = response.json()
            urls = data.get("data", {}).get("attributes", {}).get("urls", {})
            
            update_payment_url = urls.get("update_payment_method")
            customer_portal_url = urls.get("customer_portal")
            
            return {
                "success": True,
                "update_payment_url": update_payment_url,
                "customer_portal_url": customer_portal_url,
                "portal_url": update_payment_url or customer_portal_url,  # Backward compatibility
                "urls": urls
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get customer portal URL: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get customer portal URL: {str(e)}")

@app.get("/subscription/invoices")
async def get_invoices_endpoint(
    current_user: User = Depends(require_active_user),
    limit: int = 10
):
    """Get user's invoices from LemonSqueezy."""
    try:
        invoices = await subscription_service.get_invoices(current_user.id, limit)
        return {
            "success": True,
            "invoices": invoices,
            "count": len(invoices)
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get invoices: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to get invoices: {str(e)}")

@app.post("/subscription/change-tier")
async def change_subscription_tier_endpoint(
    new_tier: str = Body(..., embed=True),
    current_user: User = Depends(require_active_user)
):
    """Change user's subscription tier (upgrade/downgrade)."""
    try:
        result = await subscription_service.change_subscription_tier(current_user.id, new_tier)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to change subscription tier: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to change subscription tier: {str(e)}")

@app.get("/subscription/debug")
async def debug_subscription(
    current_user: User = Depends(require_active_user)
):
    """Debug endpoint to check subscription status across all sources."""
    try:
        # Get user from database
        user_doc = mongodb.users.find_one({"_id": current_user.id})
        
        # Get subscription from subscriptions collection
        subscription = await subscription_service.get_user_subscription(current_user.id)
        
        # Get all subscriptions for this user
        all_subs = list(mongodb.subscriptions.find({"user_id": current_user.id}).sort("created_at", -1))
        
        # Get generation limits
        generation_limits = await api_generation_usage_service.check_generation_limits(
            user_id=current_user.id,
            api_key_id=None,
            tokens_to_use=0
        )
        
        return {
            "success": True,
            "user_email": user_doc.get("email"),
            "user_tier_from_db": user_doc.get("subscription_tier"),
            "user_status_from_db": user_doc.get("subscription_status"),
            "user_allocation_from_db": user_doc.get("monthly_token_allocation"),
            "lemonsqueezy_customer_id": user_doc.get("lemonsqueezy_customer_id"),
            "lemonsqueezy_subscription_id": user_doc.get("lemonsqueezy_subscription_id"),
            "active_subscription": {
                "tier": subscription.tier if subscription else None,
                "status": subscription.status if subscription else None,
                "lemonsqueezy_id": subscription.lemonsqueezy_subscription_id if subscription else None,
            } if subscription else None,
            "all_subscriptions_count": len(all_subs),
            "all_subscriptions": [
                {
                    "tier": s.get("tier"),
                    "status": s.get("status"),
                    "created_at": s.get("created_at").isoformat() if s.get("created_at") else None,
                    "lemonsqueezy_subscription_id": s.get("lemonsqueezy_subscription_id")
                } for s in all_subs[:5]  # Show last 5
            ],
            "generation_limits": {
                "monthly_limit": generation_limits.monthly_generation_limit,
                "used": generation_limits.monthly_generations_used,
                "remaining": generation_limits.monthly_generations_remaining,
                "tier": generation_limits.subscription_tier,
                "is_over_limit": generation_limits.is_over_limit,
                "reason": generation_limits.limit_exceeded_reason
            }
        }
    except Exception as e:
        logger.error(f"Failed to debug subscription: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to debug subscription: {str(e)}")

@app.post("/subscription/sync")
async def sync_subscription(
    current_user: User = Depends(require_active_user)
):
    """Manually sync subscription from subscriptions collection to user document."""
    try:
        # Get active subscription
        subscription = await subscription_service.get_user_subscription(current_user.id)
        
        if not subscription:
            return {
                "success": False,
                "message": "No active subscription found",
                "action": "User remains on current tier"
            }
        
        # Get tier info
        tier_info = subscription_service.SUBSCRIPTION_TIERS.get(subscription.tier)
        if not tier_info:
            raise HTTPException(status_code=500, detail=f"Invalid tier: {subscription.tier}")
        
        # Update user document with subscription data
        mongodb.users.update_one(
            {"_id": current_user.id},
            {
                "$set": {
                    "subscription_tier": subscription.tier,
                    "subscription_status": subscription.status,
                    "monthly_token_allocation": tier_info.monthly_tokens,
                    "lemonsqueezy_customer_id": subscription.lemonsqueezy_customer_id,
                    "lemonsqueezy_subscription_id": subscription.lemonsqueezy_subscription_id
                }
            }
        )
        
        # Allocate tokens if needed
        await api_pricing_service.allocate_separated_monthly_tokens(
            user_id=current_user.id,
            generation_tokens=tier_info.monthly_generation_tokens,
            execution_tokens=tier_info.monthly_execution_tokens,
            source="manual_sync"
        )
        
        logger.info(f"✅ Manually synced subscription for user {current_user.id} to tier {subscription.tier}")
        
        return {
            "success": True,
            "message": f"Successfully synced subscription to {tier_info.display_name} tier",
            "tier": subscription.tier,
            "status": subscription.status,
            "monthly_api_generations": tier_info.monthly_api_generations,
            "monthly_generation_tokens": tier_info.monthly_generation_tokens,
            "monthly_execution_tokens": tier_info.monthly_execution_tokens
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync subscription: {str(e)}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to sync subscription: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 


# Report endpoints

@app.get("/admin/reports")
async def list_all_reports(
    request: Request,
    status: Optional[str] = None,
    category: Optional[str] = None,
    severity: Optional[str] = None,
    admin_user: User = Depends(require_admin_auth)
):
    """List all reports in the system (admin only)."""
    try:
        # Build MongoDB query
        query = {}
        if status:
            query["status"] = status
        if category:
            query["category"] = category
        if severity:
            query["severity"] = severity
        
        # Get all reports with filtering
        reports_cursor = mongodb.reports.find(query).sort("created_at", -1)
        reports_list = list(reports_cursor)
        
        # Convert to Report models
        reports = []
        for report_doc in reports_list:
            reports.append(Report(
                report_id=report_doc["report_id"],
                api_user_id=report_doc["api_user_id"],
                api_slug=report_doc["api_slug"],
                endpoint_url=report_doc.get("endpoint_url"),
                reporter_user_id=report_doc["reporter_user_id"],
                reporter_email=report_doc["reporter_email"],
                category=report_doc["category"],
                severity=report_doc["severity"],
                description=report_doc["description"],
                status=report_doc["status"],
                created_at=report_doc["created_at"],
                updated_at=report_doc["updated_at"]
            ))
        
        return {
            "success": True,
            "reports": reports,
            "total": len(reports)
        }
    except Exception as e:
        logger.error(f"Failed to list all reports: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list reports: {str(e)}")

@app.put("/admin/reports/{report_id}/status")
async def update_report_status(
    request: Request,
    report_id: str,
    status_data: dict = Body(...),
    admin_user: User = Depends(require_admin_auth)
):
    """Update report status (admin only)."""
    try:
        new_status = status_data.get("status")
        if not new_status:
            raise HTTPException(status_code=400, detail="Status is required")
        
        valid_statuses = ["pending", "reviewed", "resolved", "dismissed"]
        if new_status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )
        
        result = mongodb.reports.update_one(
            {"report_id": report_id},
            {
                "$set": {
                    "status": new_status,
                    "updated_at": datetime.utcnow()
                }
            }
        )
        
        if result.matched_count == 0:
            raise HTTPException(status_code=404, detail="Report not found")
        
        logger.info(f"Admin {admin_user.email} updated report {report_id} status to {new_status}")
        
        return {
            "success": True,
            "message": f"Report status updated to {new_status}"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update report status: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update report status: {str(e)}")

@app.delete("/admin/reports/{report_id}")
async def delete_report(
    request: Request,
    report_id: str,
    admin_user: User = Depends(require_admin_auth)
):
    """Delete a report (admin only)."""
    try:
        result = mongodb.reports.delete_one({"report_id": report_id})
        
        if result.deleted_count == 0:
            raise HTTPException(status_code=404, detail="Report not found")
        
        logger.info(f"Admin {admin_user.email} deleted report {report_id}")
        
        return {
            "success": True,
            "message": "Report deleted successfully"
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete report: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to delete report: {str(e)}")

# ===================================
# PUBLIC REPORT ENDPOINTS
# ===================================

@app.post("/api/reports", response_model=CreateReportResponse)
async def create_report(
    report_request: CreateReportRequest,
    request: Request,
    current_user: User = Depends(require_active_user)
):
    """
    Create a new report for an API.
    Requires authentication - only logged-in users can report APIs.
    """
    try:
        logger.info(f"User {current_user.id} reporting API {report_request.api_user_id}/{report_request.api_slug}")
        
        # Validate category
        valid_categories = ["bug", "inappropriate", "security", "documentation", "performance", "other"]
        if report_request.category not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )
        
        # Validate severity
        valid_severities = ["low", "medium", "high"]
        if report_request.severity not in valid_severities:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid severity. Must be one of: {', '.join(valid_severities)}"
            )
        
        # Check if API exists
        if not file_service.api_exists(report_request.api_user_id, report_request.api_slug):
            raise HTTPException(
                status_code=404,
                detail=f"API not found: {report_request.api_user_id}/{report_request.api_slug}"
            )
        
        # Generate unique report ID
        import uuid
        report_id = str(uuid.uuid4())
        
        # Create report document
        report_doc = {
            "report_id": report_id,
            "api_user_id": report_request.api_user_id,
            "api_slug": report_request.api_slug,
            "endpoint_url": report_request.endpoint_url,
            "reporter_user_id": current_user.id,
            "reporter_email": current_user.email,
            "category": report_request.category,
            "severity": report_request.severity,
            "description": report_request.description,
            "status": "pending",
            "created_at": datetime.utcnow(),
            "updated_at": datetime.utcnow()
        }
        
        # Save to database
        mongodb.reports.insert_one(report_doc)
        
        logger.info(f"Report {report_id} created successfully for API {report_request.api_user_id}/{report_request.api_slug}")
        
        return CreateReportResponse(
            success=True,
            message="Report submitted successfully. Thank you for helping us maintain quality!",
            report_id=report_id
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error creating report: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create report: {str(e)}"
        )

@app.get("/api/reports", response_model=ListReportsResponse)
async def list_reports(
    request: Request,
    current_user: User = Depends(require_active_user),
    status: Optional[str] = None,
    category: Optional[str] = None,
    limit: int = 50
):
    """
    List reports. 
    Regular users can only see reports they've submitted.
    Admin users can see all reports (future enhancement).
    """
    try:
        # Build query - regular users only see their own reports
        query = {"reporter_user_id": current_user.id}
        
        if status:
            query["status"] = status
        if category:
            query["category"] = category
        
        # Fetch reports from database
        reports_cursor = mongodb.reports.find(query).sort("created_at", -1).limit(limit)
        reports_list = list(reports_cursor)
        
        # Convert to Report models
        reports = []
        for report_doc in reports_list:
            reports.append(Report(
                report_id=report_doc["report_id"],
                api_user_id=report_doc["api_user_id"],
                api_slug=report_doc["api_slug"],
                endpoint_url=report_doc.get("endpoint_url"),
                reporter_user_id=report_doc["reporter_user_id"],
                reporter_email=report_doc["reporter_email"],
                category=report_doc["category"],
                severity=report_doc["severity"],
                description=report_doc["description"],
                status=report_doc["status"],
                created_at=report_doc["created_at"],
                updated_at=report_doc["updated_at"]
            ))
        
        return ListReportsResponse(
            success=True,
            reports=reports,
            total=len(reports)
        )
        
    except Exception as e:
        logger.error(f"Error listing reports: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to list reports: {str(e)}"
        )