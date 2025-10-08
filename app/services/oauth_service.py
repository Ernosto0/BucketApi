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
        },
        # Add state parameter configuration
        authorize_params={
            'access_type': 'offline',
            'prompt': 'consent'
        }
    )
    logger.info("✅ Google OAuth configured successfully")
else:
    logger.warning("⚠️ Google OAuth not configured - missing credentials")

# Configure GitHub OAuth
if settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET:
    oauth.register(
        name='github',
        client_id=settings.GITHUB_CLIENT_ID,
        client_secret=settings.GITHUB_CLIENT_SECRET,
        access_token_url='https://github.com/login/oauth/access_token',
        authorize_url='https://github.com/login/oauth/authorize',
        api_base_url='https://api.github.com/',
        client_kwargs={
            'scope': 'user:email'
        }
    )
    logger.info("✅ GitHub OAuth configured successfully")
else:
    logger.warning("⚠️ GitHub OAuth not configured - missing credentials")


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
    
    async def get_github_user_info(self, token: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Get user information from GitHub using the access token
        
        Args:
            token: OAuth token dictionary
            
        Returns:
            User information dictionary or None if failed
        """
        try:
            # Get user info from GitHub API
            async with httpx.AsyncClient() as client:
                # Get user profile
                user_response = await client.get(
                    'https://api.github.com/user',
                    headers={'Authorization': f'token {token["access_token"]}'}
                )
                
                if user_response.status_code != 200:
                    logger.error(f"❌ Failed to get GitHub user info: {user_response.status_code}")
                    return None
                
                user_info = user_response.json()
                
                # Get user email (GitHub requires separate API call for email)
                email_response = await client.get(
                    'https://api.github.com/user/emails',
                    headers={'Authorization': f'token {token["access_token"]}'}
                )
                
                if email_response.status_code == 200:
                    emails = email_response.json()
                    # Find primary email
                    primary_email = next((email['email'] for email in emails if email['primary']), None)
                    if primary_email:
                        user_info['email'] = primary_email
                
                logger.info(f"✅ Retrieved GitHub user info for: {user_info.get('email')}")
                return user_info
                    
        except Exception as e:
            logger.error(f"❌ Error getting GitHub user info: {e}")
            return None
    
    def validate_google_credentials(self) -> bool:
        """Check if Google OAuth is properly configured"""
        return bool(settings.GOOGLE_CLIENT_ID and settings.GOOGLE_CLIENT_SECRET)
    
    def validate_github_credentials(self) -> bool:
        """Check if GitHub OAuth is properly configured"""
        return bool(settings.GITHUB_CLIENT_ID and settings.GITHUB_CLIENT_SECRET)


# Create singleton instance
oauth_service = OAuthService()


