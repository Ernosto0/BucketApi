"""
OAuth Authentication Service
Handles Google OAuth authentication flow
"""
import logging
from typing import Optional, Dict, Any
from authlib.integrations.starlette_client import OAuth
from starlette.config import Config as StarletteConfig
from fastapi import HTTPException
import httpx

from ..config import settings

logger = logging.getLogger(__name__)

# Initialize OAuth
oauth = OAuth()

# Configure Google OAuth
if settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET:
    oauth.register(
        name='google',
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        server_metadata_url='https://accounts.google.com/.well-known/openid-configuration',
        client_kwargs={
            'scope': 'openid email profile',
            'prompt': 'select_account'  # Always show account selection
        }
    )
    logger.info("✅ Google OAuth configured successfully")
else:
    logger.warning("⚠️ Google OAuth not configured - missing credentials")


class OAuthService:
    """Service for handling OAuth authentication"""
    
    def __init__(self):
        self.oauth = oauth
    
    async def get_google_user_info(self, token: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get user information from Google using the access token
        
        Args:
            token: OAuth token dictionary
            
        Returns:
            User information dictionary or None if failed
        """
        try:
            # Use the userinfo endpoint to get user details
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    'https://www.googleapis.com/oauth2/v3/userinfo',
                    headers={'Authorization': f'Bearer {token["access_token"]}'}
                )
                
                if response.status_code == 200:
                    user_info = response.json()
                    logger.info(f"✅ Retrieved Google user info for: {user_info.get('email')}")
                    return user_info
                else:
                    logger.error(f"❌ Failed to get Google user info: {response.status_code}")
                    return None
                    
        except Exception as e:
            logger.error(f"❌ Error getting Google user info: {e}")
            return None
    
    def validate_google_credentials(self) -> bool:
        """Check if Google OAuth is properly configured"""
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)


# Create singleton instance
oauth_service = OAuthService()

