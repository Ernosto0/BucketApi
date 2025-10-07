from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text, Integer, Float, Index
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from datetime import datetime
from typing import AsyncGenerator
import os
from ..config import settings

# Database URL
DATABASE_URL = "sqlite+aiosqlite:///./api_generator.db"
SYNC_DATABASE_URL = "sqlite:///./api_generator.db"

# Create async engine
async_engine = create_async_engine(
    DATABASE_URL,
    echo=False,  # Set to True for SQL logging in development
    future=True
)

# Create sync engine for initial setup
sync_engine = create_engine(SYNC_DATABASE_URL, echo=False)

# Session makers
AsyncSessionLocal = async_sessionmaker(
    async_engine, 
    class_=AsyncSession, 
    expire_on_commit=False
)

SessionLocal = sessionmaker(
    autocommit=False, 
    autoflush=False, 
    bind=sync_engine
)

# Base class for models
Base = declarative_base()

# Database Models
class UserDB(Base):
    __tablename__ = "users"

    id = Column(String, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    password_hash = Column(String, nullable=True)  # Nullable for OAuth users
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)
    
    # OAuth fields
    oauth_provider = Column(String, nullable=True)  # 'google', 'github', etc.
    oauth_id = Column(String, nullable=True, index=True)  # User ID from OAuth provider
    profile_picture = Column(String, nullable=True)  # Profile picture URL
    full_name = Column(String, nullable=True)  # Full name from OAuth
    
    # Subscription fields
    subscription_tier = Column(String, default="free", nullable=False)  # free, starter, professional, enterprise
    subscription_status = Column(String, default="active", nullable=False)  # active, cancelled, past_due, unpaid
    lemonsqueezy_customer_id = Column(String, nullable=True)  # LemonSqueezy customer ID
    lemonsqueezy_subscription_id = Column(String, nullable=True)  # LemonSqueezy subscription ID
    subscription_started_at = Column(DateTime, nullable=True)
    subscription_expires_at = Column(DateTime, nullable=True)
    monthly_token_allocation = Column(Integer, default=10000, nullable=False)  # Based on subscription tier

class UserSessionDB(Base):
    __tablename__ = "user_sessions"

    session_id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_accessed = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(String, nullable=True)
    user_agent = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)

class SavedAPIDB(Base):
    __tablename__ = "saved_apis"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    api_slug = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    api_name = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    endpoint_url = Column(String, nullable=False)
    documentation = Column(Text, nullable=False)
    curl_example = Column(Text, nullable=False)
    openapi_spec = Column(Text, nullable=True)  # Store as JSON string
    sample_input = Column(Text, nullable=True)
    expected_output = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    saved_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    is_saved = Column(Boolean, default=True, nullable=False)

class APIKeyDB(Base):
    __tablename__ = "api_keys"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    key_name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False)  # Store hashed version of the key
    full_key = Column(String, nullable=False)  # Store first 8 chars for display
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_used = Column(DateTime, nullable=True)
    usage_count = Column(Integer, default=0, nullable=False)
    expires_at = Column(DateTime, nullable=True)  # Optional expiration

class LLMUsageDB(Base):
    __tablename__ = "llm_usage"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    api_key_id = Column(String, index=True, nullable=True)  # Which API key was used
    service_type = Column(String, nullable=False)  # 'claude', 'openai', etc.
    operation_type = Column(String, nullable=False)  # 'code_generation', 'code_modification', 'documentation', 'analysis'
    model_name = Column(String, nullable=False)  # e.g., 'claude-3-sonnet', 'gpt-4'
    
    # Token usage
    input_tokens = Column(Integer, default=0, nullable=False)
    output_tokens = Column(Integer, default=0, nullable=False)
    total_tokens = Column(Integer, default=0, nullable=False)
    
    # Cost tracking (in USD cents to avoid float precision issues)
    estimated_cost_cents = Column(Integer, default=0, nullable=False)
    
    # Request metadata
    prompt_length = Column(Integer, default=0, nullable=False)
    response_length = Column(Integer, default=0, nullable=False)
    request_duration_ms = Column(Integer, default=0, nullable=False)
    
    # Context and debugging
    operation_context = Column(Text, nullable=True)  # JSON string with additional context
    api_slug = Column(String, nullable=True)  # Related API if applicable
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    completed_at = Column(DateTime, nullable=True)
    
    # Status
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)

class APIExecutionUsageDB(Base):
    __tablename__ = "api_execution_usage"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    api_key_id = Column(String, index=True, nullable=True)  # Which API key was used
    api_slug = Column(String, index=True, nullable=False)  # Which API was executed
    
    # Execution metrics
    execution_time_ms = Column(Integer, default=0, nullable=False)
    input_data_size = Column(Integer, default=0, nullable=False)  # Size of input data in bytes
    output_data_size = Column(Integer, default=0, nullable=False)  # Size of output data in bytes
    
    # Status
    success = Column(Boolean, default=True, nullable=False)
    error_message = Column(Text, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class APIMetadataDB(Base):
    __tablename__ = "api_metadata"

    id = Column(String, primary_key=True, index=True)
    api_slug = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    ai_model_used = Column(String, nullable=False)  # e.g., 'gpt-3.5-turbo', 'claude-3-sonnet'
    estimated_tokens_per_call = Column(Integer, default=0, nullable=False)
    estimated_cost_per_call_cents = Column(Integer, default=0, nullable=False)
    base_complexity = Column(String, default='medium', nullable=False)  # 'simple', 'medium', 'complex'
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_updated = Column(DateTime, default=datetime.utcnow, nullable=False)

class InternalTokenDB(Base):
    __tablename__ = "internal_tokens"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    api_key_id = Column(String, index=True, nullable=True)
    token_type = Column(String, default='api_execution', nullable=False)
    amount = Column(Integer, nullable=False)
    source = Column(String, nullable=False)  # 'purchase', 'monthly_allocation', 'bonus'
    expires_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    used_at = Column(DateTime, nullable=True)
    is_used = Column(Boolean, default=False, nullable=False)

class APIExecutionTokenUsageDB(Base):
    __tablename__ = "api_execution_token_usage"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    api_key_id = Column(String, index=True, nullable=True)
    api_slug = Column(String, index=True, nullable=False)
    internal_tokens_used = Column(Integer, nullable=False)
    cost_cents = Column(Integer, nullable=False)
    execution_successful = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class APIProcessDB(Base):
    __tablename__ = "api_processes"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    api_slug = Column(String, index=True, nullable=False)
    port = Column(Integer, unique=True, nullable=False)
    process_id = Column(Integer, nullable=True)  # OS process ID
    is_running = Column(Boolean, default=True)
    last_accessed = Column(DateTime, default=datetime.utcnow)
    created_at = Column(DateTime, default=datetime.utcnow)
    memory_usage = Column(Integer, nullable=True)  # in MB
    cpu_usage = Column(Float, nullable=True)  # percentage

# Logging Models
class SystemLogDB(Base):
    __tablename__ = "system_logs"
    
    # Primary fields
    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    level = Column(String, nullable=False, index=True)  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    category = Column(String, nullable=False, index=True)  # HTTP_REQUEST, LLM_CALL, etc.
    
    # User context
    user_id = Column(String, index=True, nullable=True)
    api_key_id = Column(String, index=True, nullable=True)
    session_id = Column(String, index=True, nullable=True)
    
    # Request context
    request_id = Column(String, index=True, nullable=True)
    endpoint = Column(String, nullable=True)
    method = Column(String, nullable=True)
    status_code = Column(Integer, nullable=True)
    
    # Message and details
    message = Column(Text, nullable=False)
    details = Column(Text, nullable=True)  # JSON string with additional data
    
    # Performance metrics
    duration_ms = Column(Integer, nullable=True)
    memory_usage_mb = Column(Float, nullable=True)
    
    # Error information
    error_type = Column(String, nullable=True)
    error_traceback = Column(Text, nullable=True)
    
    # Additional metadata
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    # Indexes for better performance
    __table_args__ = (
        Index('idx_logs_timestamp_category', 'timestamp', 'category'),
        Index('idx_logs_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_logs_level_timestamp', 'level', 'timestamp'),
        Index('idx_logs_request_id', 'request_id'),
    )

class HTTPRequestLogDB(Base):
    __tablename__ = "http_request_logs"
    
    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    request_id = Column(String, index=True, nullable=False)
    
    # Request details
    method = Column(String, nullable=False)
    endpoint = Column(String, nullable=False, index=True)
    full_url = Column(String, nullable=True)
    
    # Request data
    headers = Column(Text, nullable=True)  # JSON
    query_params = Column(Text, nullable=True)  # JSON
    body = Column(Text, nullable=True)  # JSON or text
    body_size = Column(Integer, nullable=True)
    
    # Response details
    status_code = Column(Integer, nullable=True, index=True)
    response_headers = Column(Text, nullable=True)  # JSON
    response_body = Column(Text, nullable=True)
    response_size = Column(Integer, nullable=True)
    
    # Performance
    duration_ms = Column(Integer, nullable=True)
    
    # User context
    user_id = Column(String, index=True, nullable=True)
    api_key_id = Column(String, index=True, nullable=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    
    # Success/Error
    success = Column(Boolean, nullable=True)
    error_message = Column(Text, nullable=True)

class LLMCallLogDB(Base):
    __tablename__ = "llm_call_logs"
    
    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    request_id = Column(String, index=True, nullable=True)
    
    # LLM service details
    service_type = Column(String, nullable=False, index=True)  # 'openai', 'claude'
    model_name = Column(String, nullable=False, index=True)
    operation_type = Column(String, nullable=False, index=True)  # 'code_generation', 'documentation', etc.
    
    # Request details
    system_prompt = Column(Text, nullable=True)
    user_prompt = Column(Text, nullable=True)
    prompt_length = Column(Integer, nullable=True)
    
    # Response details
    response_content = Column(Text, nullable=True)
    response_length = Column(Integer, nullable=True)
    
    # Token usage
    input_tokens = Column(Integer, nullable=True)
    output_tokens = Column(Integer, nullable=True)
    total_tokens = Column(Integer, nullable=True)
    
    # Cost and performance
    estimated_cost_cents = Column(Integer, nullable=True)
    duration_ms = Column(Integer, nullable=True)
    
    # User context
    user_id = Column(String, index=True, nullable=True)
    api_key_id = Column(String, index=True, nullable=True)
    api_slug = Column(String, index=True, nullable=True)
    
    # Success/Error
    success = Column(Boolean, nullable=False, default=True)
    error_message = Column(Text, nullable=True)
    
    # Additional context
    operation_context = Column(Text, nullable=True)  # JSON

class ChatMessageLogDB(Base):
    __tablename__ = "chat_message_logs"
    
    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # User context
    user_id = Column(String, index=True, nullable=False)
    session_id = Column(String, index=True, nullable=True)
    
    # Message details
    message_type = Column(String, nullable=False)  # 'user_message', 'ai_response', 'system_message'
    content = Column(Text, nullable=False)
    content_length = Column(Integer, nullable=True)
    
    # AI response details (if applicable)
    ai_model_used = Column(String, nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    confidence_score = Column(Float, nullable=True)
    
    # Conversation context
    conversation_id = Column(String, index=True, nullable=True)
    parent_message_id = Column(String, nullable=True)
    
    # Additional metadata
    message_metadata = Column(Text, nullable=True)  # JSON

class ErrorLogDB(Base):
    __tablename__ = "error_logs"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Error details
    error_type = Column(String, nullable=False)
    error_message = Column(Text, nullable=False)
    user_id = Column(String, index=True, nullable=True)
    request_id = Column(String, index=True, nullable=True)
    api_slug = Column(String, nullable=True)

    # Additional metadata
    model_name = Column(String, nullable=True)
    details = Column(Text, nullable=True)  # JSON string for additional details
    success = Column(Boolean, nullable=False, default=False)

class RetryLogDB(Base):
    __tablename__ = "retry_logs"

    id = Column(String, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    
    # Retry context
    request_id = Column(String, index=True, nullable=False)
    original_error_type = Column(String, nullable=False)
    original_error_message = Column(Text, nullable=False)
    
    # Retry attempt details
    attempt_number = Column(Integer, nullable=False)  # 1, 2, 3, etc.
    max_attempts = Column(Integer, nullable=False)    # Total retry attempts configured
    retry_delay_seconds = Column(Float, nullable=True)  # Delay before this retry
    
    # Context
    user_id = Column(String, index=True, nullable=True)
    api_key_id = Column(String, index=True, nullable=True)
    api_slug = Column(String, index=True, nullable=True)
    
    # Service details
    service_type = Column(String, nullable=False, index=True)  # 'claude', 'openai'
    model_name = Column(String, nullable=True)
    operation_type = Column(String, nullable=False, index=True)  # 'code_generation', etc.
    
    # Additional details
    details = Column(Text, nullable=True)  # JSON with additional retry context
    
    # Indexes for better performance
    __table_args__ = (
        Index('idx_retry_logs_request_id', 'request_id'),
        Index('idx_retry_logs_user_timestamp', 'user_id', 'timestamp'),
        Index('idx_retry_logs_service_operation', 'service_type', 'operation_type'),
    )
    
# Database dependency
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Dependency to get database session."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()

def get_sync_db() -> Session:
    """Get synchronous database session."""
    db = SessionLocal()
    try:
        return db
    finally:
        db.close()

def create_tables():
    """Create all database tables."""
    Base.metadata.create_all(bind=sync_engine)

def drop_tables():
    """Drop all database tables."""
    Base.metadata.drop_all(bind=sync_engine)

async def init_database():
    """Initialize the database with tables."""
    # Create tables if they don't exist
    create_tables()

# Subscription management tables
class SubscriptionDB(Base):
    __tablename__ = "subscriptions"
    
    id = Column(String, primary_key=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    lemonsqueezy_subscription_id = Column(String, unique=True, nullable=False)
    lemonsqueezy_customer_id = Column(String, nullable=False)
    lemonsqueezy_product_id = Column(String, nullable=False)
    lemonsqueezy_variant_id = Column(String, nullable=False)
    
    tier = Column(String, nullable=False)  # free, starter, professional, enterprise
    status = Column(String, nullable=False)  # active, cancelled, past_due, unpaid, paused
    
    current_period_start = Column(DateTime, nullable=True)
    current_period_end = Column(DateTime, nullable=True)
    trial_start = Column(DateTime, nullable=True)
    trial_end = Column(DateTime, nullable=True)
    
    monthly_token_allocation = Column(Integer, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)

class SubscriptionEventDB(Base):
    __tablename__ = "subscription_events"
    
    id = Column(String, primary_key=True, index=True)
    subscription_id = Column(String, index=True, nullable=False)
    user_id = Column(String, index=True, nullable=False)
    
    event_type = Column(String, nullable=False)  # subscription_created, subscription_updated, payment_success, etc.
    lemonsqueezy_event_id = Column(String, unique=True, nullable=False)
    
    event_data = Column(Text, nullable=True)  # JSON data from LemonSqueezy
    processed = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

# Database service class
class DatabaseService:
    def __init__(self):
        self.async_engine = async_engine
        self.sync_engine = sync_engine

    async def get_session(self) -> AsyncSession:
        """Get an async database session."""
        return AsyncSessionLocal()

    def get_sync_session(self) -> Session:
        """Get a sync database session."""
        return SessionLocal()

    async def health_check(self) -> bool:
        """Check if database is accessible."""
        try:
            async with AsyncSessionLocal() as session:
                await session.execute("SELECT 1")
                return True
        except Exception:
            return False

# Global instance
database_service = DatabaseService() 