from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Text, Integer
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