from datetime import datetime, timedelta
from typing import Optional
from jose import JWTError, jwt
import hashlib
import secrets
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import Session
import uuid
from ..models import User, UserCreate, TokenData
from ..config import settings
from .database import UserDB, AsyncSessionLocal, SessionLocal

class AuthService:
    def __init__(self):
        # JWT settings
        self.secret_key = settings.SECRET_KEY if hasattr(settings, 'SECRET_KEY') else "your-secret-key-change-this"
        self.algorithm = "HS256"
        self.access_token_expire_minutes = 30

    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """Verify a plaintext password against its hash."""
        # Split the stored hash to get salt and hash
        try:
            salt, stored_hash = hashed_password.split('$', 1)
            # Hash the plain password with the same salt
            password_hash = hashlib.pbkdf2_hmac('sha256', plain_password.encode(), salt.encode(), 100000)
            return password_hash.hex() == stored_hash
        except:
            return False

    def get_password_hash(self, password: str) -> str:
        """Hash a password for storing."""
        # Generate a random salt
        salt = secrets.token_hex(16)
        # Hash the password with the salt
        password_hash = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 100000)
        # Return salt$hash format
        return f"{salt}${password_hash.hex()}"

    def create_access_token(self, data: dict, expires_delta: Optional[timedelta] = None):
        """Create a JWT access token."""
        to_encode = data.copy()
        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=self.access_token_expire_minutes)
        
        to_encode.update({"exp": expire})
        encoded_jwt = jwt.encode(to_encode, self.secret_key, algorithm=self.algorithm)
        return encoded_jwt

    def verify_token(self, token: str) -> TokenData:
        """Verify and decode a JWT token."""
        credentials_exception = HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
        
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            username: str = payload.get("sub")
            if username is None:
                raise credentials_exception
            token_data = TokenData(username=username)
        except JWTError:
            raise credentials_exception
        
        return token_data

    def create_user_id(self) -> str:
        """Generate a unique user ID."""
        return str(uuid.uuid4())

    def validate_user_data(self, user_data: UserCreate) -> None:
        """Validate user registration data."""
        if len(user_data.password) < 6:
            raise HTTPException(
                status_code=400,
                detail="Password must be at least 6 characters long"
            )

    def create_user(self, user_data: UserCreate) -> User:
        """Create a new user object (without saving to database)."""
        self.validate_user_data(user_data)
        
        user = User(
            id=self.create_user_id(),
            email=user_data.email,
            is_active=True,
            created_at=datetime.now(),
            last_login=None
        )
        
        return user

    # Database operations
    async def save_user(self, user_data: UserCreate, hashed_password: str) -> User:
        """Save a new user to the database."""
        async with AsyncSessionLocal() as session:
            # Check if email already exists
            existing_email = await session.execute(
                select(UserDB).where(UserDB.email == user_data.email)
            )
            if existing_email.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail="Email already exists"
                )
            
            # Create user object
            user = self.create_user(user_data)
            
            # Create database user
            db_user = UserDB(
                id=user.id,
                email=user.email,
                password_hash=hashed_password,
                is_active=user.is_active,
                created_at=user.created_at,
                last_login=user.last_login
            )
            
            session.add(db_user)
            await session.commit()
            await session.refresh(db_user)
            
            return user

    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email from database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.email == email)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                return None
            
            return User(
                id=db_user.id,
                email=db_user.email,
                is_active=db_user.is_active,
                created_at=db_user.created_at,
                last_login=db_user.last_login
            )

    async def get_user_password_hash(self, email: str) -> Optional[str]:
        """Get user's password hash from database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB.password_hash).where(UserDB.email == email)
            )
            password_hash = result.scalar_one_or_none()
            return password_hash

    async def update_user_last_login(self, email: str) -> None:
        """Update user's last login timestamp in database."""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.email == email)
            )
            db_user = result.scalar_one_or_none()
            
            if db_user:
                db_user.last_login = datetime.utcnow()
                await session.commit()

    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate a user with email and password."""
        user = await self.get_user_by_email(email)
        
        if not user:
            return None
        
        # Get password hash and verify
        password_hash = await self.get_user_password_hash(user.email)
        if not password_hash:
            return None
        
        if not self.verify_password(password, password_hash):
            return None
        
        # Update last login
        await self.update_user_last_login(user.email)
        
        # Return updated user with last login
        return await self.get_user_by_email(user.email)

# Global instance
auth_service = AuthService() 