from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Request
import time
import base64
from datetime import datetime
from typing import Optional
import logging
from .models import (
    APIGenerationRequest, APIGenerationResponse, 
    APIExecutionRequest, APIExecutionResponse, HealthResponse
)
from .services.openai_service import openai_service
from .services.security_service import security_service
from .services.file_service import file_service
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

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    """Serve the main frontend page."""
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse(
        status="healthy",
        timestamp=datetime.now(),
        version="1.0.0"
    )

@app.post("/generate-api", response_model=APIGenerationResponse)
async def generate_api(request: APIGenerationRequest):
    """
    Generate a new API based on user prompt.
    """
    logger.info(f"Generating API for user {request.user_id} with prompt: {request.prompt[:100]}...")
    try:
        # Validate OpenAI API key
        if not settings.OPENAI_API_KEY:
            logger.error("OpenAI API key not configured")
            raise HTTPException(
                status_code=500, 
                detail="OpenAI API key not configured"
            )
        
        # Generate API code using OpenAI
        logger.info("Calling OpenAI service to generate code...")
        code = await openai_service.generate_api_code(
            prompt=request.prompt,
            sample_input=request.sample_input,
            expected_output=request.expected_output
        )
        logger.info("Code generation completed successfully")
        logger.debug(f"Generated code preview: {code[:300]}...")
        
        # Validate code for security
        logger.info("Validating generated code for security...")
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
        documentation, curl_example = await openai_service.generate_documentation(
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
            generated_at=datetime.now()
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error in generate_api: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Failed to generate API: {str(e)}"
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

@app.get("/api/{user_id}")
async def list_user_apis(user_id: str):
    """
    List all APIs for a specific user.
    """
    try:
        apis = file_service.get_user_apis(user_id)
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

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000) 