
import uuid

class LLMBaseError(Exception):
    """Base exception for all LLM-related errors."""
    

    def __init__(self, message: str, user_id: str, request_id: str, api_slug: str, model_name: str, details: dict = None):
        super().__init__(message)
        self.message = message
        self.user_id = user_id
        self.request_id = request_id
        self.api_slug = api_slug
        self.model_name = model_name
        self.details = details
    def __str__(self):
        base_str = super().__str__()
        extra = []

        if self.request_id:
            extra.append(f"Request ID: {self.request_id}")
        if self.api_slug:
            extra.append(f"API Slug: {self.api_slug}")
        if self.model_name:
            extra.append(f"Model Name: {self.model_name}")
        if self.details:
            extra.append(f"Details: {self.details}")

        if extra:
            joined = "\n".join(extra)
            return f"{base_str}\n{joined}"
        return base_str


class PromptBuildError(LLMBaseError):
    """
    Raised when there is an error constructing the LLM prompt.
    
    Examples:
    - Template variables missing
    - Invalid prompt structure
    - Missing required context for prompt
    """
    pass


class LLMAPIError(LLMBaseError):
    """
    Raised when the LLM API request fails.
    
    Examples:
    - API rate limiting exceeded
    - Network timeout
    - Invalid API credentials
    - API service unavailable
    """
    pass


class CodeExtractionError(LLMBaseError):
    """
    Raised when code cannot be extracted from the LLM response.
    
    Examples:
    - Response format doesn't contain code blocks
    - Code extraction regex fails
    - Response is empty or malformed
    """
    pass


class UsageLoggingError(LLMBaseError):
    """
    Raised when usage logging fails.
    
    Examples:
    - Database write failure
    - Missing usage data fields
    - Aggregation service unavailable
    """
    pass


# Multi-Step Generation Specific Exceptions

class MultiStepGenerationError(LLMBaseError):
    """Base exception for multi-step generation related errors."""
    
    def __init__(self, message: str, user_id: str, session_id: str = None, step_id: str = None, 
                 request_id: str = None, api_slug: str = "multi_step_generation", 
                 model_name: str = "claude", details: dict = None):
        self.session_id = session_id
        self.step_id = step_id
        super().__init__(message, user_id, request_id, api_slug, model_name, details)
    
    def __str__(self):
        base_str = super().__str__()
        extra = []
        
        if self.session_id:
            extra.append(f"Session ID: {self.session_id}")
        if self.step_id:
            extra.append(f"Step ID: {self.step_id}")
            
        if extra:
            joined = "\n".join(extra)
            return f"{base_str}\n{joined}"
        return base_str


class SessionNotFoundError(MultiStepGenerationError):
    """
    Raised when a generation session cannot be found.
    
    Examples:
    - Invalid session_id
    - Session expired and was cleaned up
    - Session never created
    """
    pass


class SessionConfigurationError(MultiStepGenerationError):
    """
    Raised when there's an error in session configuration.
    
    Examples:
    - Invalid generation mode
    - Missing required configuration fields
    - Conflicting configuration parameters
    """
    pass


class PipelineValidationError(MultiStepGenerationError):
    """
    Raised when pipeline validation fails.
    
    Examples:
    - Invalid step sequence
    - Missing required step dependencies
    - Configuration doesn't match pipeline requirements
    """
    pass


class StepExecutionError(MultiStepGenerationError):
    """
    Raised when a generation step fails to execute.
    
    Examples:
    - LLM API call fails during step
    - Step logic encounters an error
    - Required input data is missing for step
    """
    pass


class StepTimeoutError(MultiStepGenerationError):
    """
    Raised when a generation step times out.
    
    Examples:
    - Step execution exceeds maximum allowed time
    - LLM API response is too slow
    - Long-running operation not completed in time
    """
    pass


class TemplateProcessingError(MultiStepGenerationError):
    """
    Raised when prompt template processing fails.
    
    Examples:
    - Template variables not found in context
    - Invalid template syntax
    - Template rendering engine fails
    """
    pass


class SessionCleanupError(MultiStepGenerationError):
    """
    Raised when session cleanup fails.
    
    Examples:
    - Cannot delete session files
    - Cannot update session status in database
    - Resources cannot be released
    """
    pass


class GenerationModeError(MultiStepGenerationError):
    """
    Raised when there's an error with the generation mode.
    
    Examples:
    - Invalid mode specified
    - Mode not supported for current operation
    - Mode-specific configuration missing
    """
    pass


class SecureHTTPException(Exception):
    """
    Secure HTTP exception that prevents information disclosure.
    Logs detailed error information while returning safe user messages.
    """
    
    def __init__(
        self, 
        status_code: int,
        user_message: str,
        internal_error: Exception = None,
        category: str = "general",
        user_id: str = None,
        context: dict = None
    ):
        self.status_code = status_code
        self.user_message = user_message
        self.internal_error = internal_error
        self.category = category
        self.user_id = user_id
        self.context = context or {}
        self.error_id = str(uuid.uuid4())[:8]
        
        # Log the detailed error for debugging using existing logging service
        self._log_error_details()
        
        super().__init__(user_message)
    
    def _log_error_details(self):
        """Log detailed error information for debugging."""
        import logging
        logger = logging.getLogger(__name__)
        
        if self.internal_error:
            logger.error(
                f"SecureHTTPException {self.error_id} [{self.category}]: {str(self.internal_error)}",
                extra={
                    'error_id': self.error_id,
                    'category': self.category,
                    'user_id': self.user_id,
                    'context': self.context,
                    'status_code': self.status_code,
                    'error_type': type(self.internal_error).__name__
                },
                exc_info=True if hasattr(self.internal_error, '__traceback__') else False
            )
    
    def to_http_exception(self):
        """Convert to FastAPI HTTPException with safe message."""
        from fastapi import HTTPException
        from ..config import settings
        
        detail = self.user_message
        if settings.ENVIRONMENT == 'development' and self.error_id:
            detail += f" (Error ID: {self.error_id})"
            
        return HTTPException(status_code=self.status_code, detail=detail)


def create_secure_error(
    status_code: int,
    category: str,
    internal_error: Exception,
    user_message: str = None,
    user_id: str = None,
    context: dict = None
) -> Exception:
    """
    Create a secure error that logs details but returns safe messages.
    
    Args:
        status_code: HTTP status code
        category: Error category for classification
        internal_error: The original exception
        user_message: Safe message for users
        user_id: User ID for context
        context: Additional context for logging
    
    Returns:
        Exception with safe message
    """
    # Default safe messages by category
    safe_messages = {
        'auth': 'Authentication failed',
        'validation': 'Invalid request data',
        'database': 'Internal service error',
        'file': 'File operation failed',
        'api': 'API operation failed',
        'network': 'External service unavailable',
        'permission': 'Access denied',
        'rate_limit': 'Rate limit exceeded'
    }
    
    if not user_message:
        user_message = safe_messages.get(category, 'An error occurred')
    
    return SecureHTTPException(
        status_code=status_code,
        user_message=user_message,
        internal_error=internal_error,
        category=category,
        user_id=user_id,
        context=context
    )


