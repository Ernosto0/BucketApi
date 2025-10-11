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

from ..models_auth import User, UserSession
from ..config import settings
from .mongodb import mongodb

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
    
    
    def authenticate_user(self, email: str, password: str) -> Optional[User]:
        """Authenticate user with email and password"""
        # Get user by email
        db_user = mongodb.users.find_one({"email": email})
        
        if not db_user:
            logger.warning(f"❌ Authentication failed - user not found: {email}")
            return None
        
        if not db_user.get("is_active", True):
            logger.warning(f"❌ Authentication failed - account disabled: {email}")
            return None
        
        # Verify password
        if not self.verify_password(password, db_user["password_hash"]):
            logger.warning(f"❌ Authentication failed - invalid password: {email}")
            return None
        
        # Update last login
        mongodb.users.update_one(
            {"_id": db_user["_id"]},
            {"$set": {"last_login": datetime.utcnow()}}
        )
        
        logger.info(f"✅ User authenticated: {email}")
        
        return User(
            id=db_user["_id"],
            email=db_user["email"],
            is_active=db_user.get("is_active", True),
            created_at=db_user["created_at"],
            last_login=datetime.utcnow(),
            oauth_provider=db_user.get("oauth_provider"),
            oauth_id=db_user.get("oauth_id"),
            profile_picture=db_user.get("profile_picture"),
            full_name=db_user.get("full_name"),
            subscription_tier=db_user.get("subscription_tier", "free"),
            subscription_status=db_user.get("subscription_status", "active"),
            monthly_token_allocation=db_user.get("monthly_token_allocation", 10000)
        )
    
    def get_user_by_id(self, user_id: str) -> Optional[User]:
        """Get user by ID"""
        db_user = mongodb.users.find_one({"_id": user_id})
        
        if not db_user:
            return None
        
        return User(
            id=db_user["_id"],
            email=db_user["email"],
            is_active=db_user.get("is_active", True),
            created_at=db_user["created_at"],
            last_login=db_user.get("last_login"),
            oauth_provider=db_user.get("oauth_provider"),
            oauth_id=db_user.get("oauth_id"),
            profile_picture=db_user.get("profile_picture"),
            full_name=db_user.get("full_name"),
            subscription_tier=db_user.get("subscription_tier", "free"),
            subscription_status=db_user.get("subscription_status", "active"),
            monthly_token_allocation=db_user.get("monthly_token_allocation", 10000)
        )
    
    def get_user_by_email(self, email: str) -> Optional[User]:
        """Get user by email"""
        db_user = mongodb.users.find_one({"email": email})
        
        if not db_user:
            return None
        
        return User(
            id=db_user["_id"],
            email=db_user["email"],
            is_active=db_user.get("is_active", True),
            created_at=db_user["created_at"],
            last_login=db_user.get("last_login"),
            oauth_provider=db_user.get("oauth_provider"),
            oauth_id=db_user.get("oauth_id"),
            profile_picture=db_user.get("profile_picture"),
            full_name=db_user.get("full_name"),
            subscription_tier=db_user.get("subscription_tier", "free"),
            subscription_status=db_user.get("subscription_status", "active"),
            monthly_token_allocation=db_user.get("monthly_token_allocation", 10000)
        )
    
    def get_or_create_oauth_user(
        self, 
        email: str, 
        oauth_provider: str, 
        oauth_id: str,
        full_name: Optional[str] = None,
        profile_picture: Optional[str] = None
    ) -> User:
        """Get or create a user from OAuth login"""
        # Try to find existing user by OAuth ID
        db_user = mongodb.users.find_one({
            "oauth_provider": oauth_provider,
            "oauth_id": oauth_id
        })
        
        # If not found, try by email
        if not db_user:
            db_user = mongodb.users.find_one({"email": email})
        
        if db_user:
            # Update OAuth info if user exists
            update_data = {
                "oauth_provider": oauth_provider,
                "oauth_id": oauth_id,
                "last_login": datetime.utcnow()
            }
            if full_name:
                update_data["full_name"] = full_name
            if profile_picture:
                update_data["profile_picture"] = profile_picture
            
            mongodb.users.update_one(
                {"_id": db_user["_id"]},
                {"$set": update_data}
            )
            
            # Refresh user data
            db_user = mongodb.users.find_one({"_id": db_user["_id"]})
            
            logger.info(f"✅ OAuth user logged in: {email}")
        else:
            # Create new OAuth user
            user_id = self.create_user_id()
            db_user = {
                "_id": user_id,
                "email": email,
                "password_hash": None,  # OAuth users don't have passwords
                "is_active": True,
                "created_at": datetime.utcnow(),
                "last_login": datetime.utcnow(),
                "oauth_provider": oauth_provider,
                "oauth_id": oauth_id,
                "full_name": full_name,
                "profile_picture": profile_picture,
                "subscription_tier": "free",
                "subscription_status": "active",
                "monthly_token_allocation": 10000
            }
            
            mongodb.users.insert_one(db_user)
            
            logger.info(f"✅ New OAuth user created: {email} ({oauth_provider})")
        
        return User(
            id=db_user["_id"],
            email=db_user["email"],
            is_active=db_user.get("is_active", True),
            created_at=db_user["created_at"],
            last_login=db_user.get("last_login"),
            oauth_provider=db_user.get("oauth_provider"),
            oauth_id=db_user.get("oauth_id"),
            profile_picture=db_user.get("profile_picture"),
            full_name=db_user.get("full_name"),
            subscription_tier=db_user.get("subscription_tier", "free"),
            subscription_status=db_user.get("subscription_status", "active"),
            monthly_token_allocation=db_user.get("monthly_token_allocation", 10000)
        )
    
    # Session Management
    def create_session(self, user_id: str, request: Request, remember_me: bool = False) -> str:
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
        self._cleanup_user_sessions(user_id)
        
        session_data = {
            "_id": session_id,
            "user_id": user_id,
            "created_at": datetime.utcnow(),
            "last_accessed": datetime.utcnow(),
            "expires_at": expires_at,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "is_active": True
        }
        
        # Store session
        mongodb.user_sessions.insert_one(session_data)
        
        logger.info(f"✅ Session created for user {user_id}: {session_id}")
        return session_id
    
    def validate_session(self, session_id: str) -> Optional[User]:
        """Validate a session and return the user"""
        if not session_id:
            return None
        
        # Get session data
        session_data = mongodb.user_sessions.find_one({"_id": session_id})
        if not session_data:
            return None
        
        # Check if session is expired or inactive
        if not session_data.get("is_active", True) or datetime.utcnow() > session_data["expires_at"]:
            mongodb.user_sessions.delete_one({"_id": session_id})
            return None
        
        # Update last accessed time
        mongodb.user_sessions.update_one(
            {"_id": session_id},
            {"$set": {"last_accessed": datetime.utcnow()}}
        )
        
        # Get and return user
        user = self.get_user_by_id(session_data["user_id"])
        return user
    
    def destroy_session(self, session_id: str) -> bool:
        """Destroy a user session"""
        if not session_id:
            return False
        
        mongodb.user_sessions.delete_one({"_id": session_id})
        logger.info(f"✅ Session destroyed: {session_id}")
        return True
    
    def destroy_all_user_sessions(self, user_id: str) -> int:
        """Destroy all sessions for a user"""
        result = mongodb.user_sessions.delete_many({"user_id": user_id})
        count = result.deleted_count
        logger.info(f"✅ Destroyed {count} sessions for user {user_id}")
        return count
    
    def _cleanup_user_sessions(self, user_id: str):
        """Clean up old sessions for a user, keeping only the most recent ones"""
        # Get all sessions for user, ordered by creation time (newest first)
        sessions = list(mongodb.user_sessions.find(
            {"user_id": user_id}
        ).sort("created_at", -1))
        
        # If we have more than max allowed, delete the oldest ones
        if len(sessions) >= self.max_sessions_per_user:
            sessions_to_delete = sessions[self.max_sessions_per_user-1:]
            session_ids = [s["_id"] for s in sessions_to_delete]
            mongodb.user_sessions.delete_many({"_id": {"$in": session_ids}})
            logger.info(f"🧹 Cleaned up {len(sessions_to_delete)} old sessions for user {user_id}")
    
    def cleanup_expired_sessions(self):
        """Clean up all expired sessions (should be run periodically)"""
        result = mongodb.user_sessions.delete_many({
            "expires_at": {"$lt": datetime.utcnow()}
        })
        count = result.deleted_count
        
        if count > 0:
            logger.info(f"🧹 Cleaned up {count} expired sessions")
        
        return count

# Global auth service instance
auth_service = AuthService()