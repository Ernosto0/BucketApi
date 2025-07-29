from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text, Integer, Float
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
    password_hash = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_login = Column(DateTime, nullable=True)

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