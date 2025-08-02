import os
from typing import Set
from dotenv import load_dotenv

load_dotenv()

class Settings:

    # Some Settings
    ENABLE_TEST_VALIDATION_DEBUGGING: bool = "true"

    # OpenAI Configuration
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    
    
    # Claude Configuration
    CLAUDE_API_KEY: str = os.getenv("CLAUDE_API_KEY", "")
    CLAUDE_MODEL: str = "claude-opus-4-20250514"
    
    GENERATE_DOCS_SERVICE: str = "OPENAI_SERVICE"

    # Application Configuration
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")
    MAX_FILE_SIZE: int = 10 * 1024 * 1024  # 10MB
    
    # Authentication Configuration
    SECRET_KEY: str = os.getenv("SECRET_KEY", "your-secret-key-change-this-in-production-please-make-it-very-long-and-random")
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
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