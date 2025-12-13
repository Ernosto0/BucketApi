import os
import time
from typing import Set, List, Optional
from dotenv import load_dotenv

load_dotenv()

class Settings:
    """
    Application settings with support for dynamic configuration.
    Settings can be overridden from the database via the settings service.
    """
    
    _settings_cache: Optional[dict] = None
    _cache_timestamp: Optional[float] = None
    _cache_ttl: int = 60  # Cache settings for 60 seconds
    
    def _get_db_setting(self, key: str, default):
        """
        Get a setting from the database with caching.
        Falls back to default if database is unavailable or setting not found.
        """
        try:
            # Check if cache is valid
            current_time = time.time()
            if (self._settings_cache is not None and 
                self._cache_timestamp is not None and 
                current_time - self._cache_timestamp < self._cache_ttl):
                return self._settings_cache.get(key, default)
            
            # Try to load from database
            try:
                from .services.mongodb import mongodb
                if mongodb and hasattr(mongodb, 'system_settings'):
                    setting_doc = mongodb.system_settings.find_one({"key": key})
                    if setting_doc:
                        # Update cache
                        if self._settings_cache is None:
                            self._settings_cache = {}
                        self._settings_cache[key] = setting_doc.get("value", default)
                        self._cache_timestamp = current_time
                        return setting_doc.get("value", default)
            except Exception:
                # Database not available yet (during startup), use default
                pass
                
            return default
        except Exception:
            # Any error, return default
            return default
    
    def clear_cache(self):
        """Clear the settings cache to force reload from database."""
        self._settings_cache = None
        self._cache_timestamp = None

    # MongoDB Configuration 
    MONGODB_URL: str = os.getenv("MONGODB_URL")
    MONGODB_DB_NAME: str = os.getenv("MONGODB_DB_NAME")
    
    # Redis Configuration (for session storage in multi-worker environment)
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://localhost:6379/0")
    USE_REDIS_SESSIONS: bool = os.getenv("USE_REDIS_SESSIONS", "false").lower() == "true"

    # OpenAI Configuration for api generation
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")
    
    @property
    def OPENAI_MODEL(self) -> str:
        return self._get_db_setting("OPENAI_MODEL", os.getenv("OPENAI_MODEL", "gpt-4-turbo"))
    
    @property
    def MAX_TOKENS_OPENAI(self) -> int:
        return self._get_db_setting("MAX_TOKENS_OPENAI", 10000)
    
    @property
    def TEMPERATURE_OPENAI(self) -> float:
        return self._get_db_setting("TEMPERATURE_OPENAI", 0.3)
    
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
    
    @property
    def CLAUDE_MODEL(self) -> str:
        return self._get_db_setting("CLAUDE_MODEL", "claude-3-5-haiku-latest")
    
    @property
    def MAX_TOKENS_CLAUDE(self) -> int:
        return self._get_db_setting("MAX_TOKENS_CLAUDE", 10000)
    
    @property
    def TEMPERATURE_CLAUDE(self) -> float:
        return self._get_db_setting("TEMPERATURE_CLAUDE", 0.3)
    
    TOP_P_CLAUDE: float = 1.0
    FREQUENCY_PENALTY_CLAUDE: float = 0.0
    PRESENCE_PENALTY_CLAUDE: float = 0.0
    MAX_COMPLETIONS_CLAUDE: int = 1
    STOP_CLAUDE: List[str] = []
    STOP_SEQUENCE_CLAUDE: List[str] = []
    STOP_TOKEN_CLAUDE: List[str] = []
    STOP_TOKEN_IDS_CLAUDE: List[int] = []
    
    @property
    def GENERATE_DOCS_SERVICE(self) -> str:
        return self._get_db_setting("GENERATE_DOCS_SERVICE", "OPENAI_SERVICE")

    @property
    def RETRY_MAX_ATTEMPTS(self) -> int:
        return self._get_db_setting("RETRY_MAX_ATTEMPTS", 3)
    
    @property
    def RETRY_MAX_DELAY_SECONDS(self) -> int:
        return self._get_db_setting("RETRY_MAX_DELAY_SECONDS", 10)
    
    @property
    def RETRY_MIN_DELAY_SECONDS(self) -> int:
        return self._get_db_setting("RETRY_MIN_DELAY_SECONDS", 2)

    # Application Configuration
    @property
    def ENVIRONMENT(self) -> str:
        return self._get_db_setting("ENVIRONMENT", os.getenv("ENVIRONMENT", "development"))
    
    @property
    def MAX_FILE_SIZE(self) -> int:
        return self._get_db_setting("MAX_FILE_SIZE", 10 * 1024 * 1024)
    
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
                "https://bucketapi.com",
                "https://app.bucketapi.com", 
                "https://api.bucketapi.com"
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
    
    @property
    def ACCESS_TOKEN_EXPIRE_MINUTES(self) -> int:
        return self._get_db_setting("ACCESS_TOKEN_EXPIRE_MINUTES", 4320)
    
    # OAuth Configuration
    GOOGLE_CLIENT_ID: str = os.getenv("GOOGLE_CLIENT_ID", "")
    GOOGLE_CLIENT_SECRET: str = os.getenv("GOOGLE_CLIENT_SECRET", "")
    OAUTH_REDIRECT_URI: str = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8001/auth/google/callback")
    
    # GitHub OAuth Configuration
    GITHUB_CLIENT_ID: str = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET: str = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_REDIRECT_URI: str = os.getenv("GITHUB_REDIRECT_URI", "http://localhost:8001/auth/github/callback")
    
    # Feature Flags
    @property
    def ENABLE_CUSTOM_AUTH(self) -> bool:
        return self._get_db_setting("ENABLE_CUSTOM_AUTH", os.getenv("ENABLE_CUSTOM_AUTH", "false").lower() == "true")
    
    @property
    def ENABLE_GOOGLE_AUTH(self) -> bool:
        return self._get_db_setting("ENABLE_GOOGLE_AUTH", os.getenv("ENABLE_GOOGLE_AUTH", "true").lower() == "true")
    
    @property
    def ENABLE_GITHUB_AUTH(self) -> bool:
        return self._get_db_setting("ENABLE_GITHUB_AUTH", os.getenv("ENABLE_GITHUB_AUTH", "true").lower() == "true")
    
    @property
    def ENABLE_TEST_VALIDATION_DEBUGGING(self) -> bool:
        return self._get_db_setting("ENABLE_TEST_VALIDATION_DEBUGGING", True)
    
    # Security Configuration
    @property
    def SECURITY_SERVICE_ENABLED(self) -> bool:
        return self._get_db_setting("SECURITY_SERVICE_ENABLED", os.getenv("SECURITY_SERVICE_ENABLED", "true").lower() == "true")
    FORBIDDEN_KEYWORDS: Set[str] = {
        "subprocess", "eval", "exec", "requests", "urllib", 
        "socket", "import", "__import__", "open", "file", "input",
        "raw_input", "compile", "globals", "locals", "vars", "dir",
        "getattr", "setattr", "delattr", "hasattr", "shutil",
        "tempfile", "pickle", "marshal", "builtins", "__builtins__"
    }
    
    # File Storage
    GENERATED_APIS_DIR: str = "generated_apis"
    
    # API Configuration
    API_PREFIX: str = "/api"
    DOCS_URL: str = "/docs"
    REDOC_URL: str = "/redoc"

    # Add port configuration
    @property
    def PORT(self) -> int:
        return self._get_db_setting("PORT", int(os.getenv('PORT', 8001)))
    
    @property
    def HOST(self) -> str:
        return self._get_db_setting("HOST", os.getenv('HOST', '127.0.0.1'))

settings = Settings()  