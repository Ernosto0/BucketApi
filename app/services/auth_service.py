"""
New Modern Authentication Service for my app. More secure and easy to maintain.
"""

import hashlib
import secrets
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional
from passlib.context import CryptContext
from fastapi import HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from ..models_auth import User, UserCreate, UserSession
from ..config import settings
from .database import UserDB, UserSessionDB, AsyncSessionLocal, SessionLocal

logger = logging.getLogger(__name__)

class AuthService:
    """Modern authentication service with session-based auth"""
    
    def __init__(self):
        # Password hashing with bcrypt (industry standard)
        self.pwd_context = CryptContext(
            schemes=["bcrypt"], 
            deprecated="auto",
            bcrypt__rounds=12,  # Strong hashing (2^12 = 4096 iterations)
            bcrypt__ident="2b"  # Use 2b variant for better compatibility
        )
        
        # Session settings
        self.session_expire_hours = 24  # Default session length
        self.remember_me_expire_days = 30  # "Remember me" length
        self.max_sessions_per_user = 5  # Prevent session accumulation
    
    # Password Security
    def hash_password(self, password: str) -> str:
        """Hash a password securely using a simple hashlib approach"""
        if not isinstance(password, str):
            logger.error(f"Password must be a string, got {type(password)}: {password}")
            raise ValueError("Password must be a string")
        
        if not password:
            raise ValueError("Password cannot be empty")
        
        try:
            # Use a simple, reliable approach with hashlib and secrets
            import hashlib
            import secrets
            
            # Generate a random salt
            salt = secrets.token_hex(32)  # 32 bytes = 64 hex chars
            
            # Create PBKDF2 hash (same as old system for compatibility)
            password_hash = hashlib.pbkdf2_hmac(
                'sha256', 
                password.encode('utf-8'), 
                salt.encode('utf-8'), 
                100000  # 100k iterations
            )
            
            # Return in the same format as old system: salt$hash
            hash_str = f"{salt}${password_hash.hex()}"
            logger.debug(f"Password hashed successfully with PBKDF2")
            return hash_str
            
        except Exception as e:
            logger.error(f"Password hashing failed: {e}")
            raise ValueError(f"Password hashing failed: {e}")
    
    def verify_password(self, plain_password: str, hashed_password: str) -> bool:
        """
        Verify a password against its hash.
        Supports both bcrypt and PBKDF2 formats.
        """
        try:
            # Try bcrypt first (if hash starts with $2b$ or $2a$)
            if hashed_password.startswith('$2b$') or hashed_password.startswith('$2a$'):
                logger.debug("Using bcrypt verification")
                try:
                    # Use passlib for bcrypt verification (more reliable)
                    return self.pwd_context.verify(plain_password, hashed_password)
                except Exception as e:
                    logger.debug(f"Bcrypt verification failed: {e}")
                    return False
            
            # PBKDF2 format: salt$hash (both hex strings)
            if '$' in hashed_password and not hashed_password.startswith('$'):
                logger.debug("Using PBKDF2 verification")
                import hashlib
                
                salt_hex, stored_hash = hashed_password.split('$', 1)
                
                # For new format (salt is hex string)
                if len(salt_hex) == 64:  # New format with hex salt
                    salt_bytes = salt_hex.encode('utf-8')
                else:
                    # Legacy format (salt was hex-encoded bytes)
                    salt_bytes = bytes.fromhex(salt_hex)
                
                # Compute PBKDF2 hash
                password_hash = hashlib.pbkdf2_hmac(
                    'sha256', 
                    plain_password.encode('utf-8'), 
                    salt_bytes, 
                    100000
                )
                computed_hash = password_hash.hex()
                
                logger.debug(f"Computed hash: {computed_hash[:20]}...")
                logger.debug(f"Stored hash: {stored_hash[:20]}...")
                
                return computed_hash == stored_hash
            
            # Unknown format
            logger.warning(f"Unknown password hash format: {hashed_password[:20]}...")
            return False
            
        except Exception as e:
            logger.error(f"Password verification failed: {e}")
            return False
    
    def validate_password_strength(self, password: str) -> tuple[bool, str]:
        """Validate password strength"""
        if len(password) < 8:
            return False, "Password must be at least 8 characters long"
        
        # Check for at least one number, one letter
        has_letter = any(c.isalpha() for c in password)
        has_number = any(c.isdigit() for c in password)
        
        if not has_letter or not has_number:
            return False, "Password must contain at least one letter and one number"
        
        return True, "Password is strong"
    
    # User Management
    def create_user_id(self) -> str:
        """Generate a unique user ID"""
        return str(uuid.uuid4())
    
    def create_session_id(self) -> str:
        """Generate a secure session ID"""
        return secrets.token_urlsafe(32)
    
    async def create_user(self, user_data: UserCreate) -> User:
        """Create a new user account"""
        logger.info(f"Creating user with email: {user_data.email}")
        logger.debug(f"Password type: {type(user_data.password)}, length: {len(user_data.password) if user_data.password else 0}")
        
        # Validate password strength
        is_strong, message = self.validate_password_strength(user_data.password)
        if not is_strong:
            raise HTTPException(status_code=400, detail=message)
        
        async with AsyncSessionLocal() as session:
            # Check if email already exists
            existing_user = await session.execute(
                select(UserDB).where(UserDB.email == user_data.email)
            )
            if existing_user.scalar_one_or_none():
                raise HTTPException(
                    status_code=400,
                    detail="An account with this email already exists"
                )
            
            # Create user
            user_id = self.create_user_id()
            logger.debug(f"Attempting to hash password...")
            password_hash = self.hash_password(user_data.password)
            logger.debug(f"Password hashed successfully, hash length: {len(password_hash)}")
            
            db_user = UserDB(
                id=user_id,
                email=user_data.email,
                password_hash=password_hash,
                is_active=True,
                created_at=datetime.utcnow(),
                last_login=None
            )
            
            session.add(db_user)
            await session.commit()
            await session.refresh(db_user)
            
            logger.info(f"✅ New user created: {user_data.email}")
            
            return User(
                id=db_user.id,
                email=db_user.email,
                is_active=db_user.is_active,
                created_at=db_user.created_at,
                last_login=db_user.last_login,
                oauth_provider=db_user.oauth_provider,
                oauth_id=db_user.oauth_id,
                profile_picture=db_user.profile_picture,
                full_name=db_user.full_name,
                subscription_tier=db_user.subscription_tier,
                subscription_status=db_user.subscription_status,
                monthly_token_allocation=db_user.monthly_token_allocation
            )
    
    async def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate user with email and password"""
        async with AsyncSessionLocal() as session:
            # Get user by email
            result = await session.execute(
                select(UserDB).where(UserDB.email == email)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                logger.warning(f"❌ Authentication failed - user not found: {email}")
                return None
            
            if not db_user.is_active:
                logger.warning(f"❌ Authentication failed - account disabled: {email}")
                return None
            
            # Verify password
            if not self.verify_password(password, db_user.password_hash):
                logger.warning(f"❌ Authentication failed - invalid password: {email}")
                return None
            
            # Update last login
            db_user.last_login = datetime.utcnow()
            await session.commit()
            
            logger.info(f"✅ User authenticated: {email}")
            
            return User(
                id=db_user.id,
                email=db_user.email,
                is_active=db_user.is_active,
                created_at=db_user.created_at,
                last_login=db_user.last_login,
                oauth_provider=db_user.oauth_provider,
                oauth_id=db_user.oauth_id,
                profile_picture=db_user.profile_picture,
                full_name=db_user.full_name,
                subscription_tier=db_user.subscription_tier,
                subscription_status=db_user.subscription_status,
                monthly_token_allocation=db_user.monthly_token_allocation
            )
    
    async def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserDB).where(UserDB.id == user_id)
            )
            db_user = result.scalar_one_or_none()
            
            if not db_user:
                return None
            
            return User(
                id=db_user.id,
                email=db_user.email,
                is_active=db_user.is_active,
                created_at=db_user.created_at,
                last_login=db_user.last_login,
                oauth_provider=db_user.oauth_provider,
                oauth_id=db_user.oauth_id,
                profile_picture=db_user.profile_picture,
                full_name=db_user.full_name,
                subscription_tier=db_user.subscription_tier,
                subscription_status=db_user.subscription_status,
                monthly_token_allocation=db_user.monthly_token_allocation
            )
    
    async def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
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
                last_login=db_user.last_login,
                oauth_provider=db_user.oauth_provider,
                oauth_id=db_user.oauth_id,
                profile_picture=db_user.profile_picture,
                full_name=db_user.full_name,
                subscription_tier=db_user.subscription_tier,
                subscription_status=db_user.subscription_status,
                monthly_token_allocation=db_user.monthly_token_allocation
            )
    
    async def get_or_create_oauth_user(
        self, 
        email: str, 
        oauth_provider: str, 
        oauth_id: str,
        full_name: Optional[str] = None,
        profile_picture: Optional[str] = None
    ) -> User:
        """Get or create a user from OAuth login"""
        async with AsyncSessionLocal() as session:
            # Try to find existing user by OAuth ID
            result = await session.execute(
                select(UserDB).where(
                    UserDB.oauth_provider == oauth_provider,
                    UserDB.oauth_id == oauth_id
                )
            )
            db_user = result.scalar_one_or_none()
            
            # If not found, try by email
            if not db_user:
                result = await session.execute(
                    select(UserDB).where(UserDB.email == email)
                )
                db_user = result.scalar_one_or_none()
            
            if db_user:
                # Update OAuth info if user exists
                db_user.oauth_provider = oauth_provider
                db_user.oauth_id = oauth_id
                db_user.last_login = datetime.utcnow()
                if full_name:
                    db_user.full_name = full_name
                if profile_picture:
                    db_user.profile_picture = profile_picture
                
                await session.commit()
                await session.refresh(db_user)
                
                logger.info(f"✅ OAuth user logged in: {email}")
            else:
                # Create new OAuth user
                user_id = self.create_user_id()
                db_user = UserDB(
                    id=user_id,
                    email=email,
                    password_hash=None,  # OAuth users don't have passwords
                    is_active=True,
                    created_at=datetime.utcnow(),
                    last_login=datetime.utcnow(),
                    oauth_provider=oauth_provider,
                    oauth_id=oauth_id,
                    full_name=full_name,
                    profile_picture=profile_picture
                )
                
                session.add(db_user)
                await session.commit()
                await session.refresh(db_user)
                
                logger.info(f"✅ New OAuth user created: {email} ({oauth_provider})")
            
            return User(
                id=db_user.id,
                email=db_user.email,
                is_active=db_user.is_active,
                created_at=db_user.created_at,
                last_login=db_user.last_login,
                oauth_provider=db_user.oauth_provider,
                oauth_id=db_user.oauth_id,
                profile_picture=db_user.profile_picture,
                full_name=db_user.full_name,
                subscription_tier=db_user.subscription_tier,
                subscription_status=db_user.subscription_status,
                monthly_token_allocation=db_user.monthly_token_allocation
            )
    
    # Session Management
    async def create_session(self, user_id: str, request: Request, remember_me: bool = False) -> str:
        """Create a new user session"""
        session_id = self.create_session_id()
        
        # Determine expiration
        if remember_me:
            expires_at = datetime.utcnow() + timedelta(days=self.remember_me_expire_days)
        else:
            expires_at = datetime.utcnow() + timedelta(hours=self.session_expire_hours)
        
        # Get client info
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")[:500]  # Limit length
        
        # Clean up old sessions for this user (keep only recent ones)
        await self._cleanup_user_sessions(user_id)
        
        session_data = UserSession(
            session_id=session_id,
            user_id=user_id,
            created_at=datetime.utcnow(),
            last_accessed=datetime.utcnow(),
            expires_at=expires_at,
            ip_address=ip_address,
            user_agent=user_agent,
            is_active=True
        )
        
        # Store session (implement session storage)
        await self._store_session(session_data)
        
        logger.info(f"✅ Session created for user {user_id}: {session_id}")
        return session_id
    
    async def validate_session(self, session_id: str) -> Optional[User]:
        """Validate a session and return the user"""
        if not session_id:
            return None
        
        # Get session data
        session_data = await self._get_session(session_id)
        if not session_data:
            return None
        
        # Check if session is expired or inactive
        if not session_data.is_active or datetime.utcnow() > session_data.expires_at:
            await self._delete_session(session_id)
            return None
        
        # Update last accessed time
        await self._update_session_access(session_id)
        
        # Get and return user
        user = await self.get_user_by_id(session_data.user_id)
        return user
    
    async def destroy_session(self, session_id: str) -> bool:
        """Destroy a user session"""
        if not session_id:
            return False
        
        await self._delete_session(session_id)
        logger.info(f"✅ Session destroyed: {session_id}")
        return True
    
    async def destroy_all_user_sessions(self, user_id: str) -> int:
        """Destroy all sessions for a user"""
        count = await self._delete_all_user_sessions(user_id)
        logger.info(f"✅ Destroyed {count} sessions for user {user_id}")
        return count
    
    # Session storage implementation
    async def _store_session(self, session_data: UserSession):
        """Store session data in database"""
        async with AsyncSessionLocal() as session:
            db_session = UserSessionDB(
                session_id=session_data.session_id,
                user_id=session_data.user_id,
                created_at=session_data.created_at,
                last_accessed=session_data.last_accessed,
                expires_at=session_data.expires_at,
                ip_address=session_data.ip_address,
                user_agent=session_data.user_agent,
                is_active=session_data.is_active
            )
            session.add(db_session)
            await session.commit()
    
    async def _get_session(self, session_id: str) -> Optional[UserSession]:
        """Get session data from database"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserSessionDB).where(UserSessionDB.session_id == session_id)
            )
            db_session = result.scalar_one_or_none()
            
            if not db_session:
                return None
            
            return UserSession(
                session_id=db_session.session_id,
                user_id=db_session.user_id,
                created_at=db_session.created_at,
                last_accessed=db_session.last_accessed,
                expires_at=db_session.expires_at,
                ip_address=db_session.ip_address,
                user_agent=db_session.user_agent,
                is_active=db_session.is_active
            )
    
    async def _update_session_access(self, session_id: str):
        """Update session last accessed time"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserSessionDB).where(UserSessionDB.session_id == session_id)
            )
            db_session = result.scalar_one_or_none()
            
            if db_session:
                db_session.last_accessed = datetime.utcnow()
                await session.commit()
    
    async def _delete_session(self, session_id: str):
        """Delete a session"""
        async with AsyncSessionLocal() as session:
            await session.execute(
                delete(UserSessionDB).where(UserSessionDB.session_id == session_id)
            )
            await session.commit()
    
    async def _delete_all_user_sessions(self, user_id: str) -> int:
        """Delete all sessions for a user"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserSessionDB).where(UserSessionDB.user_id == user_id)
            )
            sessions = result.scalars().all()
            count = len(sessions)
            
            await session.execute(
                delete(UserSessionDB).where(UserSessionDB.user_id == user_id)
            )
            await session.commit()
            return count
    
    async def _cleanup_user_sessions(self, user_id: str):
        """Clean up old sessions for a user, keeping only the most recent ones"""
        async with AsyncSessionLocal() as session:
            # Get all sessions for user, ordered by creation time (newest first)
            result = await session.execute(
                select(UserSessionDB)
                .where(UserSessionDB.user_id == user_id)
                .order_by(UserSessionDB.created_at.desc())
            )
            sessions = result.scalars().all()
            
            # If we have more than max allowed, delete the oldest ones
            if len(sessions) >= self.max_sessions_per_user:
                sessions_to_delete = sessions[self.max_sessions_per_user-1:]
                for session_to_delete in sessions_to_delete:
                    await session.delete(session_to_delete)
                await session.commit()
                logger.info(f"🧹 Cleaned up {len(sessions_to_delete)} old sessions for user {user_id}")
    
    async def cleanup_expired_sessions(self):
        """Clean up all expired sessions (should be run periodically)"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(UserSessionDB).where(UserSessionDB.expires_at < datetime.utcnow())
            )
            expired_sessions = result.scalars().all()
            count = len(expired_sessions)
            
            if count > 0:
                await session.execute(
                    delete(UserSessionDB).where(UserSessionDB.expires_at < datetime.utcnow())
                )
                await session.commit()
                logger.info(f"🧹 Cleaned up {count} expired sessions")
            
            return count

# Global auth service instance
auth_service = AuthService()
