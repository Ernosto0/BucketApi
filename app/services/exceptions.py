

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

        return f"{base_str}\n{'\n'.join(extra)}"


class PromptBuildError(LLMBaseError):
    """Raised when there is an error constructing the LLM prompt."""
    pass


class LLMAPIError(LLMBaseError):
    """Raised when the LLM API request fails."""
    pass


class CodeExtractionError(LLMBaseError):
    """Raised when code cannot be extracted from the LLM response."""
    pass


class UsageLoggingError(LLMBaseError):
    """Raised when usage logging fails."""
    pass


