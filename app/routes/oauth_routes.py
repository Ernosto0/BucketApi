"""
OAuth Authentication Routes
Handles Google OAuth login flow
"""
import logging
from fastapi import APIRouter, Request, HTTPException, Response
from fastapi.responses import RedirectResponse
from starlette.config import Config

from ..services.oauth_service import oauth_service
from ..services.auth_service import auth_service
from ..services.api_pricing_service import api_pricing_service
from ..config import settings

logger = logging.getLogger(__name__)

# Create router
router = APIRouter(prefix="/auth", tags=["oauth"])

@router.get("/google/login")
async def google_login(request: Request):
    """Initiate Google OAuth login"""
    if not settings.ENABLE_GOOGLE_AUTH:
        raise HTTPException(
            status_code=503,
            detail="Google authentication is currently disabled"
        )
    
    if not oauth_service.validate_google_credentials():
        raise HTTPException(
            status_code=500,
            detail="Google OAuth is not configured properly"
        )
    
    try:
        # Get the OAuth client
        google = oauth_service.oauth.google
        
        # Generate authorization URL with explicit state handling
        redirect_uri = settings.OAUTH_REDIRECT_URI
        
        # Clear any existing session state to prevent conflicts
        if hasattr(request, 'session'):
            request.session.clear()
        
        return await google.authorize_redirect(request, redirect_uri)
        
    except Exception as e:
        logger.error(f"Error initiating Google login: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate Google login"
        )

@router.get("/google/callback")
async def google_callback(request: Request, response: Response):
    """Handle Google OAuth callback"""
    if not settings.ENABLE_GOOGLE_AUTH:
        return RedirectResponse(url="/login?error=oauth_disabled")
    
    try:
        # Get the OAuth client
        google = oauth_service.oauth.google
        
        # Check for error in callback
        error = request.query_params.get('error')
        if error:
            logger.error(f"OAuth error from Google: {error}")
            return RedirectResponse(url="/login?error=oauth_failed")
        
        # Get the access token with better error handling
        try:
            token = await google.authorize_access_token(request)
        except Exception as token_error:
            logger.error(f"Token authorization failed: {token_error}")
            # Clear session state and try again
            if hasattr(request, 'session'):
                request.session.clear()
            return RedirectResponse(url="/login?error=oauth_failed")
        
        # Get user info from Google
        user_info = await oauth_service.get_google_user_info(token)
        
        if not user_info:
            logger.error("Failed to get user info from Google")
            return RedirectResponse(url="/login?error=oauth_failed")
        
        # Extract user information
        email = user_info.get('email')
        google_id = user_info.get('sub')  # Google user ID
        full_name = user_info.get('name')
        profile_picture = user_info.get('picture')
        
        if not email or not google_id:
            logger.error("Missing required user information from Google")
            return RedirectResponse(url="/login?error=missing_info")
        
        # Check if this is a new user
        existing_user = await auth_service.get_user_by_email(email)
        is_new_user = existing_user is None
        
        # Get or create user
        user = await auth_service.get_or_create_oauth_user(
            email=email,
            oauth_provider='google',
            oauth_id=google_id,
            full_name=full_name,
            profile_picture=profile_picture
        )
        
        # Allocate starter tokens for new users
        if is_new_user:
            try:
                await api_pricing_service.allocate_monthly_tokens(
                    user_id=user.id,
                    amount=1000,
                    source="new_user_bonus"
                )
                logger.info(f"✅ Allocated 1000 starter tokens to new Google user: {email}")
            except Exception as e:
                logger.warning(f"Failed to allocate starter tokens: {e}")
        
        # Create session
        session_id = await auth_service.create_session(
            user_id=user.id,
            request=request,
            remember_me=True  # Always remember OAuth users
        )
        
        # Set session cookie
        max_age = 30 * 24 * 60 * 60  # 30 days
        
        # Create response and set cookie
        redirect_response = RedirectResponse(url="/dashboard", status_code=302)
        redirect_response.set_cookie(
            key="session_id",
            value=session_id,
            max_age=max_age,
            httponly=True,
            secure=settings.COOKIE_SECURE,
            samesite=settings.COOKIE_SAMESITE
        )
        
        # Clear OAuth session state after successful login
        if hasattr(request, 'session'):
            request.session.clear()
        
        logger.info(f"✅ Google OAuth login successful: {email}")
        return redirect_response
        
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}", exc_info=True)
        # Clear session state on error
        if hasattr(request, 'session'):
            request.session.clear()
        return RedirectResponse(url="/login?error=oauth_failed")


