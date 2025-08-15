import time
import uuid
import json
import logging
from typing import Callable, Optional, Dict, Any
from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
from ..services.logging_service import logging_service, LogLevel, LogCategory
import asyncio

logger = logging.getLogger(__name__)

class LoggingMiddleware(BaseHTTPMiddleware):
    """Middleware to automatically log all HTTP requests and responses"""
    
    def __init__(
        self,
        app: ASGIApp,
        log_request_body: bool = True,
        log_response_body: bool = True,
        max_body_size: int = 10000,  # Maximum body size to log
        exclude_paths: Optional[list] = None
    ):
        super().__init__(app)
        self.log_request_body = log_request_body
        self.log_response_body = log_response_body
        self.max_body_size = max_body_size
        self.exclude_paths = exclude_paths or ['/health', '/docs', '/redoc', '/openapi.json', '/static']
        
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Process request and response logging"""
        
        # Generate unique request ID
        request_id = str(uuid.uuid4())
        start_time = time.time()
        
        # Add request ID to request state for use in other parts of the application
        request.state.request_id = request_id
        
        # Check if path should be excluded from logging
        if any(request.url.path.startswith(excluded) for excluded in self.exclude_paths):
            return await call_next(request)
        
        # Extract user context
        user_id = None
        api_key_id = None
        session_id = None
        
        try:
            # Try to extract user info from request state if available
            if hasattr(request.state, 'user') and request.state.user:
                user_id = request.state.user.id
            
            # Extract session ID from cookies if available
            session_id = request.cookies.get('session_id')
            
            # Extract API key info if available
            auth_header = request.headers.get('authorization', '')
            if auth_header.startswith('Bearer '):
                # This will be resolved later in the request processing
                pass
                
        except Exception as e:
            logger.debug(f"Could not extract user context: {e}")
        
        # Capture request details
        request_data = await self._capture_request_data(request)
        
        # Process request
        response = None
        error_occurred = False
        error_message = None
        
        try:
            response = await call_next(request)
        except Exception as e:
            error_occurred = True
            error_message = str(e)
            logger.error(f"Request {request_id} failed: {error_message}")
            
            # Create error response
            response = JSONResponse(
                status_code=500,
                content={"error": "Internal server error", "request_id": request_id}
            )
        
        # Calculate duration
        duration_ms = int((time.time() - start_time) * 1000)
        
        # Capture response details
        response_data = await self._capture_response_data(response)
        
        # Extract final user context (might be available after authentication)
        try:
            if hasattr(request.state, 'user') and request.state.user:
                user_id = request.state.user.id
            if hasattr(request.state, 'api_key_id'):
                api_key_id = request.state.api_key_id
        except Exception:
            pass
        
        # Log the request - use fire-and-forget with proper error handling
        try:
            # Create a background task that doesn't block the response
            # but properly handles database sessions
            import asyncio
            loop = asyncio.get_event_loop()
            loop.create_task(self._safe_log_request_async(
                request_id=request_id,
                request_data=request_data,
                response_data=response_data,
                duration_ms=duration_ms,
                user_id=user_id,
                api_key_id=api_key_id,
                session_id=session_id,
                error_occurred=error_occurred,
                error_message=error_message
            ))
        except Exception as log_error:
            logger.error(f"Failed to create logging task for request {request_id}: {log_error}")
        
        # Add request ID to response headers for debugging
        response.headers["X-Request-ID"] = request_id
        
        return response
    
    async def _capture_request_data(self, request: Request) -> Dict[str, Any]:
        """Capture request data for logging"""
        
        try:
            # Basic request info
            data = {
                "method": request.method,
                "url": str(request.url),
                "path": request.url.path,
                "query_params": dict(request.query_params),
                "headers": dict(request.headers),
                "client_ip": self._get_client_ip(request),
                "user_agent": request.headers.get("user-agent")
            }
            
            # Capture request body if enabled
            if self.log_request_body and request.method in ["POST", "PUT", "PATCH"]:
                try:
                    body = await request.body()
                    if body:
                        # Try to parse as JSON, fallback to string
                        try:
                            body_str = body.decode('utf-8')
                            if len(body_str) <= self.max_body_size:
                                try:
                                    data["body"] = json.loads(body_str)
                                except json.JSONDecodeError:
                                    data["body"] = body_str
                            else:
                                data["body"] = {
                                    "truncated": True,
                                    "size": len(body_str),
                                    "preview": body_str[:self.max_body_size]
                                }
                        except UnicodeDecodeError:
                            data["body"] = {
                                "binary": True,
                                "size": len(body)
                            }
                        
                        data["body_size"] = len(body)
                except Exception as e:
                    logger.debug(f"Could not capture request body: {e}")
                    data["body_error"] = str(e)
            
            return data
            
        except Exception as e:
            logger.error(f"Failed to capture request data: {e}")
            return {"error": f"Failed to capture request data: {e}"}
    
    async def _capture_response_data(self, response: Response) -> Dict[str, Any]:
        """Capture response data for logging"""
        
        try:
            data = {
                "status_code": response.status_code,
                "headers": dict(response.headers)
            }
            
            # Capture response body if enabled and it's a JSON response
            if self.log_response_body and hasattr(response, 'body'):
                try:
                    if isinstance(response, JSONResponse):
                        # For JSONResponse, we can get the content directly
                        if hasattr(response, '_content') and response._content:
                            content_str = response._content.decode('utf-8')
                            if len(content_str) <= self.max_body_size:
                                try:
                                    data["body"] = json.loads(content_str)
                                except json.JSONDecodeError:
                                    data["body"] = content_str
                            else:
                                data["body"] = {
                                    "truncated": True,
                                    "size": len(content_str),
                                    "preview": content_str[:self.max_body_size]
                                }
                            
                            data["body_size"] = len(content_str)
                except Exception as e:
                    logger.debug(f"Could not capture response body: {e}")
                    data["body_error"] = str(e)
            
            return data
            
        except Exception as e:
            logger.error(f"Failed to capture response data: {e}")
            return {"error": f"Failed to capture response data: {e}"}
    
    async def _safe_log_request_async(
        self,
        request_id: str,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
        duration_ms: int,
        user_id: Optional[str],
        api_key_id: Optional[str],
        session_id: Optional[str],
        error_occurred: bool,
        error_message: Optional[str]
    ):
        """Safely log request data asynchronously with proper error handling"""
        
        try:
            # Sanitize sensitive data
            safe_headers = self._sanitize_headers(request_data.get("headers", {}))
            safe_response_headers = self._sanitize_headers(response_data.get("headers", {}))
            
            # Log HTTP request with timeout and error handling
            try:
                import asyncio
                await asyncio.wait_for(
                    logging_service.log_http_request(
                        request_id=request_id,
                        method=request_data.get("method"),
                        endpoint=request_data.get("path"),
                        full_url=request_data.get("url"),
                        headers=safe_headers,
                        query_params=request_data.get("query_params"),
                        body=request_data.get("body"),
                        body_size=request_data.get("body_size"),
                        status_code=response_data.get("status_code"),
                        response_headers=safe_response_headers,
                        response_body=response_data.get("body"),
                        response_size=response_data.get("body_size"),
                        duration_ms=duration_ms,
                        user_id=user_id,
                        api_key_id=api_key_id,
                        ip_address=request_data.get("client_ip"),
                        user_agent=request_data.get("user_agent"),
                        success=not error_occurred,
                        error_message=error_message
                    ),
                    timeout=5.0  # 5 second timeout for logging
                )
            except asyncio.TimeoutError:
                logger.warning(f"HTTP request logging timed out for request {request_id}")
            except Exception as e:
                logger.error(f"HTTP request logging failed for request {request_id}: {e}")
            
            # Log system event with timeout and error handling
            try:
                log_level = LogLevel.ERROR if error_occurred else LogLevel.INFO
                message = f"{request_data.get('method')} {request_data.get('path')} - {response_data.get('status_code')} ({duration_ms}ms)"
                
                await asyncio.wait_for(
                    logging_service.log_system_event(
                        level=log_level,
                        category=LogCategory.HTTP_REQUEST,
                        message=message,
                        details={
                            "endpoint": request_data.get("path"),
                            "method": request_data.get("method"),
                            "status_code": response_data.get("status_code"),
                            "duration_ms": duration_ms,
                            "user_agent": request_data.get("user_agent"),
                            "query_params": request_data.get("query_params")
                        },
                        user_id=user_id,
                        api_key_id=api_key_id,
                        session_id=session_id,
                        request_id=request_id,
                        endpoint=request_data.get("path"),
                        method=request_data.get("method"),
                        status_code=response_data.get("status_code"),
                        duration_ms=duration_ms,
                        ip_address=request_data.get("client_ip"),
                        user_agent=request_data.get("user_agent"),
                        error_type="HTTPException" if error_occurred else None,
                        error_traceback=error_message if error_occurred else None
                    ),
                    timeout=5.0  # 5 second timeout for logging
                )
            except asyncio.TimeoutError:
                logger.warning(f"System event logging timed out for request {request_id}")
            except Exception as e:
                logger.error(f"System event logging failed for request {request_id}: {e}")
            
        except Exception as e:
            logger.error(f"Failed to log request {request_id}: {e}")

    async def _log_request_async(
        self,
        request_id: str,
        request_data: Dict[str, Any],
        response_data: Dict[str, Any],
        duration_ms: int,
        user_id: Optional[str],
        api_key_id: Optional[str],
        session_id: Optional[str],
        error_occurred: bool,
        error_message: Optional[str]
    ):
        """Log request data asynchronously (deprecated - use _safe_log_request_async)"""
        await self._safe_log_request_async(
            request_id, request_data, response_data, duration_ms,
            user_id, api_key_id, session_id, error_occurred, error_message
        )
    
    def _get_client_ip(self, request: Request) -> Optional[str]:
        """Extract client IP address from request"""
        
        # Check for forwarded headers first (for reverse proxies)
        forwarded_for = request.headers.get("x-forwarded-for")
        if forwarded_for:
            return forwarded_for.split(',')[0].strip()
        
        real_ip = request.headers.get("x-real-ip")
        if real_ip:
            return real_ip
        
        # Fallback to client info
        if request.client:
            return request.client.host
        
        return None
    
    def _sanitize_headers(self, headers: Dict[str, str]) -> Dict[str, str]:
        """Remove sensitive information from headers"""
        
        sensitive_keys = {
            'authorization', 'cookie', 'x-api-key', 'api-key', 
            'token', 'x-auth-token', 'authentication'
        }
        
        return {
            k: '***REDACTED***' if k.lower() in sensitive_keys else v
            for k, v in headers.items()
        }


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware to add request context for logging"""
    
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        """Add request context"""
        
        # Generate request ID if not already present
        if not hasattr(request.state, 'request_id'):
            request.state.request_id = str(uuid.uuid4())
        
        # Add start time for performance tracking
        request.state.start_time = time.time()
        
        return await call_next(request)
