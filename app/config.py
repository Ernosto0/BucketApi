import os
from typing import Set, List
from dotenv import load_dotenv

load_dotenv()

class Settings:

    # Some Settings
    ENABLE_TEST_VALIDATION_DEBUGGING: bool = "true"

    # MongoDB Configuration 
    MONGODB_URL: str = os.getenv("MONGODB_URL")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME")

    # OpenAI Configuration for api generation
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-5-mini")
    
    MAX_TOKENS_OPENAI: int = 10000
    TEMPERATURE_OPENAI: float = 0.3
    TOP_P_OPENAI: float = 1.0
    FREQUENCY_PENALTY_OPENAI: float = 0.0
    PRESENCE_PENALTY_OPENAI: float = 0.0
    MAX_COMPLETIONS_OPENAI: int = 1
    STOP_OPENAI: List[str] = []
    STOP_SEQUENCE_OPENAI: List[str] = []
    STOP_TOKEN_OPENAI: List[str] = []
    STOP_TOKEN_IDS_OPENAI: List[int] = []
    
    # Claude Configuration for api generation
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
    CLAUDE_MODEL: str = "claude-3-5-haiku-latest"
    
    MAX_TOKENS_CLAUDE: int = 10000
    TEMPERATURE_CLAUDE: float = 0.3
    TOP_P_CLAUDE: float = 1.0
    FREQUENCY_PENALTY_CLAUDE: float = 0.0
    PRESENCE_PENALTY_CLAUDE: float = 0.0
    MAX_COMPLETIONS_CLAUDE: int = 1
    STOP_CLAUDE: List[str] = []
    STOP_SEQUENCE_CLAUDE: List[str] = []
    STOP_TOKEN_CLAUDE: List[str] = []
    STOP_TOKEN_IDS_CLAUDE: List[int] = []
    
    GENERATE_DOCS_SERVICE: str = "OPENAI_SERVICE"

    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_MAX_DELAY_SECONDS: int = 10
    RETRY_MIN_DELAY_SECONDS: int = 2

    # Application Configuration
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # Cookie Security Configuration
    @property
    def COOKIE_SECURE(self) -> bool:
        """Whether to use secure cookies (HTTPS only)"""
        return self.ENVIRONMENT == "production"
    
    @property
    def COOKIE_SAMESITE(self) -> str:
        """SameSite cookie setting based on environment"""
        return "strict" if self.ENVIRONMENT == "production" else "lax"
    
    # Error Handling Configuration
    @property
    def EXPOSE_ERROR_DETAILS(self) -> bool:
        """Whether to expose detailed error information"""
        return self.ENVIRONMENT != "production"
    
    @property
    def INCLUDE_ERROR_IDS(self) -> bool:
        """Whether to include error IDs in responses for debugging"""
        return self.ENVIRONMENT == "development"
    
    # CORS Security Configuration
    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        """Allowed CORS origins based on environment"""
        if self.ENVIRONMENT == "production":
            # 🔒 PRODUCTION: Specify your actual domains
            return [
                "https://yourdomain.com",
                "https://app.yourdomain.com", 
                "https://api.yourdomain.com"
            ]
        else:
            # 🔧 DEVELOPMENT: Local development origins
            return [
                "http://localhost:3000",
                "http://localhost:8001", 
                "http://127.0.0.1:3000",
                "http://127.0.0.1:8001"
            ]
    
    # Authentication Configuration
    SECRET_KEY: str = os.getenv("SECRET_KEY")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 4320  # 3 days
    
    # OAuth Configuration
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    OAUTH_REDIRECT_URI: str = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8001/auth/google/callback")
    
    # GitHub OAuth Configuration
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_REDIRECT_URI: str = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8001/auth/github/callback")
    
    # Feature Flags
    ENABLE_CUSTOM_AUTH: bool = os.getenv("ENABLE_CUSTOM_AUTH", "false").lower() == "true"  # Disabled by default
    ENABLE_GOOGLE_AUTH: bool = os.getenv("ENABLE_GOOGLE_AUTH", "true").lower() == "true"  # Enabled by default
    ENABLE_GITHUB_AUTH: bool = os.getenv("ENABLE_GITHUB_AUTH", "true").lower() == "true"  # Enabled by default
    
    # Security Configuration
    SECURITY_SERVICE_ENABLED: bool = os.getenv("SECURITY_SERVICE_ENABLED", "true").lower() == "true"
    print("security service enabled", SECURITY_SERVICE_ENABLED)
    FORBIDDEN_KEYWORDS: Set[str] = {
        "os", "subprocess", "eval", "exec", "requests", "urllib", 
        "socket", "import", "__import__", "open", "file", "input",
        "raw_input", "compile", "globals", "locals", "vars", "dir",
        "getattr", "setattr", "delattr", "hasattr", "sys", "shutil",
        "tempfile", "pickle", "marshal", "builtins", "__builtins__"
    }
    
    # File Storage
    GENERATED_APIS_DIR: str = "generated_apis"
    
    # API Configuration
    API_PREFIX: str = "/api"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"

    # Add port configuration
    PORT: int = int(os.getenv('PORT', 8001))  # Default to 8001 instead of 8000
    HOST: str = os.getenv('HOST', '127.0.0.1')  # Use localhost instead of 0.0.0.0

settings = Settings()  