import secrets
import hashlib
import uuid
import logging
from datetime import datetime, timedelta
from typing import Optional, List
from ..models import APIKey, CreateAPIKeyRequest, CreateAPIKeyResponse
from .mongodb import mongodb
from fastapi import HTTPException

logger = logging.getLogger(__name__)


class APIKeyService:
    def __init__(self):
        self.key_prefix = "ak_"
        self.key_length = 32  # Total length of the generated key part
        logger.info("APIKeyService initialized")
        
    def _generate_api_key(self) -> str:
        """Generate a secure API key."""
        # Generate random bytes and encode as hex
        random_part = secrets.token_hex(self.key_length)
        return f"{self.key_prefix}{random_part}"
    
    def _hash_api_key(self, api_key: str) -> str:
        """Hash an API key for secure storage."""
        # Use SHA-256 with salt
        salt = secrets.token_hex(16)
        key_hash = hashlib.sha256((api_key + salt).encode()).hexdigest()
        return f"{salt}${key_hash}"
    
    def _verify_api_key(self, api_key: str, stored_hash: str) -> bool:
        """Verify an API key against its stored hash."""
        try:
            salt, stored_key_hash = stored_hash.split('$', 1)
            key_hash = hashlib.sha256((api_key + salt).encode()).hexdigest()
            return key_hash == stored_key_hash
        except:
            return False
    
    def _get_key_prefix(self, api_key: str) -> str:
        """Get the display prefix of an API key."""
        return api_key
    
    def create_api_key(self, user_id: str, request: CreateAPIKeyRequest) -> CreateAPIKeyResponse:
        """Create a new API key for a user."""
        logger.info(f"🔑 create_api_key called for user {user_id} with key name '{request.key_name}'")
        try:
            # Check if user already has a key with this name
            existing = mongodb.api_keys.find_one({
                "user_id": user_id,
                "key_name": request.key_name,
                "is_active": True
            })
            if existing:
                return CreateAPIKeyResponse(
                    success=False,
                    message="API key with this name already exists"
                )
            
            # Generate new API key
            api_key = self._generate_api_key()
            key_hash = self._hash_api_key(api_key)
            key_prefix = self._get_key_prefix(api_key)
            
            # Calculate expiration if specified
            expires_at = None
            if request.expires_in_days:
                expires_at = datetime.utcnow() + timedelta(days=request.expires_in_days)
            
            # Create database record
            key_id = str(uuid.uuid4())
            db_key = {
                "_id": key_id,
                "user_id": user_id,
                "key_name": request.key_name,
                "key_hash": key_hash,
                "full_key": key_prefix,
                "is_active": True,
                "created_at": datetime.utcnow(),
                "last_used": None,
                "usage_count": 0,
                "expires_at": expires_at
            }
            
            mongodb.api_keys.insert_one(db_key)
            
            # Convert to API model
            key_info = APIKey(
                id=db_key["_id"],
                user_id=db_key["user_id"],
                key_name=db_key["key_name"],
                full_key=db_key["full_key"],
                is_active=db_key["is_active"],
                created_at=db_key["created_at"],
                last_used=db_key["last_used"],
                usage_count=db_key["usage_count"],
                expires_at=db_key["expires_at"]
            )
            
            logger.info(f"✅ API key created successfully for user {user_id}, key ID: {key_id}")
            return CreateAPIKeyResponse(
                success=True,
                message="API key created successfully",
                api_key=api_key,  # Return full key only once
                key_info=key_info
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to create API key for user {user_id}: {str(e)}")
            return CreateAPIKeyResponse(
                success=False,
                message=f"Failed to create API key: {str(e)}"
            )
    
    def get_user_api_keys(self, user_id: str) -> List[APIKey]:
        """Get all API keys for a user."""
        db_keys = mongodb.api_keys.find(
            {"user_id": user_id}
        ).sort("created_at", -1)
        
        return [
            APIKey(
                id=db_key["_id"],
                user_id=db_key["user_id"],
                key_name=db_key["key_name"],
                full_key=db_key["full_key"],
                is_active=db_key["is_active"],
                created_at=db_key["created_at"],
                last_used=db_key.get("last_used"),
                usage_count=db_key.get("usage_count", 0),
                expires_at=db_key.get("expires_at")
            )
            for db_key in db_keys
        ]
    
    def validate_api_key(self, api_key: str) -> Optional[APIKey]:
        """Validate an API key and return user info if valid."""
        # Get all active keys and check against each one
        query = {
            "is_active": True,
            "$or": [
                {"expires_at": None},
                {"expires_at": {"$gt": datetime.utcnow()}}
            ]
        }
        
        db_keys = mongodb.api_keys.find(query)
        
        for db_key in db_keys:
            if self._verify_api_key(api_key, db_key["key_hash"]):
                # Update last used and usage count
                mongodb.api_keys.update_one(
                    {"_id": db_key["_id"]},
                    {
                        "$set": {"last_used": datetime.utcnow()},
                        "$inc": {"usage_count": 1}
                    }
                )
                
                return APIKey(
                    id=db_key["_id"],
                    user_id=db_key["user_id"],
                    key_name=db_key["key_name"],
                    full_key=db_key["full_key"],
                    is_active=db_key["is_active"],
                    created_at=db_key["created_at"],
                    last_used=datetime.utcnow(),
                    usage_count=db_key.get("usage_count", 0) + 1,
                    expires_at=db_key.get("expires_at")
                )
        
        return None

    def update_api_key(self, user_id: str, key_id: str, key_name: Optional[str] = None, is_active: Optional[bool] = None) -> bool:
        """Update an API key."""
        logger.info(f"🔑 update_api_key called for user {user_id} with key ID {key_id}")
        try:
            db_key = mongodb.api_keys.find_one({
                "_id": key_id,
                "user_id": user_id
            })
            
            if not db_key:
                return False
            
            update_data = {}
            
            if key_name is not None:
                # Check if another active key with this name exists
                existing = mongodb.api_keys.find_one({
                    "user_id": user_id,
                    "key_name": key_name,
                    "is_active": True,
                    "_id": {"$ne": key_id}
                })
                if existing:
                    return False
                
                update_data["key_name"] = key_name
            
            if is_active is not None:
                update_data["is_active"] = is_active
            
            if update_data:
                mongodb.api_keys.update_one(
                    {"_id": key_id},
                    {"$set": update_data}
                )
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to update API key: {str(e)}")
            return False
    
    def delete_api_key(self, user_id: str, key_id: str) -> bool:
        """Delete an API key."""
        try:
            db_key = mongodb.api_keys.find_one({
                "_id": key_id,
                "user_id": user_id
            })
            
            if not db_key:
                return False
            
            mongodb.api_keys.delete_one({"_id": key_id})
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to delete API key: {str(e)}")
            return False
        
    def update_api_key_usage(self, api_key: str) -> bool:
        """Update the usage count for an API key."""
        try:
            result = mongodb.api_keys.update_one(
                {"key_hash": api_key},
                {"$inc": {"usage_count": 1}}
            )
            return result.modified_count > 0
        except Exception as e:
            logger.error(f"❌ Failed to update API key usage: {str(e)}")
            return False

# Global instance
api_key_service = APIKeyService()