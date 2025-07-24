from fastapi import FastAPI, HTTPException, UploadFile, File, Form, Depends, status
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
from typing import Optional
import logging
from .models import (
    User, UserCreate, UserLogin, UserProfile, Token, TokenData,
    APIGenerationRequest, APIGenerationResponse, APIModificationRequest, APIModificationResponse,
    APIExecutionRequest, APIExecutionResponse, SaveAPIRequest, SaveAPIResponse, ListAPIsResponse,
    ChatAnalysisRequest, ChatAnalysisResponse, HealthResponse, ChatMessage,
    RegisterResponse, LoginResponse, TestRequest, TestResponse
)
from .services.claude_service import claude_service
from .services.code_debugger import code_debugger
from .services.security_service import security_service
from .services.file_service import file_service
from .services.auth_service import auth_service
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
    if not credentials:
        return None
    
    try:
        token_data = auth_service.verify_token(credentials.credentials)
        # The token contains email in the 'sub' field (stored as username for compatibility)
        user = await auth_service.get_user_by_email(token_data.username)
        return user
    except HTTPException:
        return None

async def require_auth(current_user: User = Depends(get_current_user)) -> User:
    """Require authentication for protected endpoints."""
    if not current_user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
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
        
        return RegisterResponse(
            success=True,
            message="User registered successfully!",
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
async def generate_api(request: APIGenerationRequest):
    """
    Generate a new API based on user prompt.
    Optionally analyzes the prompt first, then generates if buildable.
    """
    logger.info(f"Generating API for user {request.user_id} with prompt: {request.prompt[:100]}...")
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
            expected_output=request.expected_output
        )
        logger.info("Code generation completed successfully")
        logger.debug(f"Generated code preview: {raw_code[:300]}...")
        
        # Debug and fix the generated code
        logger.info("Analyzing and fixing generated code...")
        code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
            raw_code, request.prompt
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
        file_service.save_api_code(api_slug, code)
        
        # Generate documentation
        documentation, curl_example = await claude_service.generate_documentation(
            code=code, 
            prompt=request.prompt
        )
        
        # Build endpoint URL
        endpoint_url = f"{settings.API_PREFIX}/{request.user_id}/{clean_slug}"
        
        # Update curl example with actual endpoint
        if "your-endpoint-url" in curl_example:
            curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
        
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
async def modify_api(request: APIModificationRequest):
    """
    Modify an existing API based on user prompt.
    """
    logger.info(f"Modifying API {request.api_slug} for user {request.user_id} with prompt: {request.prompt[:100]}...")
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
            existing_code=existing_code
        )
        logger.info("Code generation completed successfully")
        logger.debug(f"Generated code preview: {raw_code[:300]}...")
        
        # Debug and fix the generated code
        logger.info("Analyzing and fixing generated code...")
        code, issues_found, fixes_applied = await code_debugger.analyze_and_fix_code(
            raw_code, request.prompt
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
        file_service.save_api_code(full_slug, code)
        
        # Generate documentation
        documentation, curl_example = await claude_service.generate_documentation(
            code=code, 
            prompt=request.prompt
        )
        
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
    file: Optional[UploadFile] = File(None),
    input_data: Optional[str] = Form(None)
):
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
        
        if file:
            # Read uploaded file
            file_bytes = await file.read()
            
            # Validate file size
            if len(file_bytes) > settings.MAX_FILE_SIZE:
                raise HTTPException(
                    status_code=413,
                    detail=f"File too large. Maximum size: {settings.MAX_FILE_SIZE} bytes"
                )
        
        if input_data:
            try:
                import json
                parsed_input_data = json.loads(input_data)
            except json.JSONDecodeError:
                raise HTTPException(
                    status_code=400,
                    detail="Invalid JSON in input_data"
                )
        
        # Execute the API
        result = file_service.load_and_execute_api(
            user_id=user_id,
            api_slug=api_slug,
            file_bytes=file_bytes,
            input_data=parsed_input_data
        )
        
        execution_time = time.time() - start_time
        
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
        logger.error(f"API execution error: {str(e)}", exc_info=True)
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
            result = file_service.load_and_execute_api(
                user_id=request.user_id,
                api_slug=request.api_slug,
                file_bytes=file_bytes,
                input_data=parsed_input_data
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
                validation=None
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
                    test_response=error_response.dict()
                )
                
                # If code was fixed, save it automatically with backup
                if debug_result.get("fixed_code"):
                    logger.info(f"Code fixes found for execution error: {debug_result.get('fixes_applied', [])}")
                    
                    # Create backup of current code
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    backup_slug = f"{request.api_slug}_backup_{timestamp}"
                    
                    # Save backup
                    file_service.save_api_code(f"{request.user_id}_{backup_slug}", current_code)
                    
                    # Save fixed code
                    file_service.save_api_code(f"{request.user_id}_{request.api_slug}", debug_result["fixed_code"])
                    
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
            validation=None
        )
        
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
                            test_response=test_response.dict()
                        )
                        
                        # If code was fixed, save it automatically with backup
                        if debug_result.get("fixed_code"):
                            logger.info(f"Code fixes found: {debug_result.get('fixes_applied', [])}")
                            
                            # Create backup of current code
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            backup_slug = f"{request.api_slug}_backup_{timestamp}"
                            
                            # Save backup
                            file_service.save_api_code(f"{request.user_id}_{backup_slug}", current_code)
                            
                            # Save fixed code
                            file_service.save_api_code(f"{request.user_id}_{request.api_slug}", debug_result["fixed_code"])
                            
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




if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 