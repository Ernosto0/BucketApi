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


def clear_oauth_session(request: Request):
    """Clear OAuth session state (works with both Redis and regular sessions)"""
    if settings.USE_REDIS_SESSIONS:
        # Redis-backed session
        if hasattr(request.state, 'session') and request.state.session:
            request.state.session.clear()
    else:
        # Regular SessionMiddleware
        if hasattr(request, 'session'):
            request.session.clear()

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
        clear_oauth_session(request)

        redirect_response = await google.authorize_redirect(request, redirect_uri)

        # Safe debug: log cookie attributes (not values) so we can verify the session cookie
        # is being set in a way that browsers will store/send on the callback.
        set_cookie = redirect_response.headers.get("set-cookie", "")
        if set_cookie:
            try:
                parts = [p.strip() for p in set_cookie.split(";")]
                cookie_name = parts[0].split("=", 1)[0] if parts else "unknown"
                attrs = []
                for p in parts[1:]:
                    lower = p.lower()
                    if lower.startswith("samesite=") or lower.startswith("domain=") or lower.startswith("path=") or lower.startswith("max-age="):
                        attrs.append(p)
                    elif lower in ("secure", "httponly"):
                        attrs.append(p)
                logger.info(f"OAuth login set cookie: {cookie_name}; " + "; ".join(attrs))
            except Exception:
                logger.info("OAuth login set cookie (unable to parse attributes)")
        else:
            logger.warning("OAuth login response had no Set-Cookie header")

        return redirect_response
        
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
            # High-signal diagnostics: the most common cause is the session cookie not being sent.
            cookie_header_present = bool(request.headers.get("cookie"))
            has_session_cookie = "session" in request.cookies
            logger.error(
                "OAuth callback diagnostics: cookie_header=%s, session_cookie=%s, cookies=%s, "
                "x-forwarded-proto=%s, x-forwarded-host=%s, host=%s",
                cookie_header_present,
                has_session_cookie,
                list(request.cookies.keys()),
                request.headers.get("x-forwarded-proto"),
                request.headers.get("x-forwarded-host"),
                request.headers.get("host"),
            )
            logger.error(f"Token authorization failed: {token_error}")
            # Clear session state and try again
            clear_oauth_session(request)
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
        existing_user = auth_service.get_user_by_email(email)
        is_new_user = existing_user is None
        
        # Get or create user
        user = auth_service.get_or_create_oauth_user(
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
        session_id = auth_service.create_session(
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
        clear_oauth_session(request)
        
        logger.info(f"✅ Google OAuth login successful: {email}")
        return redirect_response
        
    except Exception as e:
        logger.error(f"Google OAuth callback error: {e}", exc_info=True)
        # Clear session state on error
        clear_oauth_session(request)
        return RedirectResponse(url="/login?error=oauth_failed")


@router.get("/github/login")
async def github_login(request: Request):
    """Initiate GitHub OAuth login"""
    if not settings.ENABLE_GITHUB_AUTH:
        raise HTTPException(
            status_code=503,
            detail="GitHub authentication is currently disabled"
        )
    
    if not oauth_service.validate_github_credentials():
        raise HTTPException(
            status_code=500,
            detail="GitHub OAuth is not configured properly"
        )
    
    try:
        # Get the OAuth client
        github = oauth_service.oauth.github
        
        # Generate authorization URL
        redirect_uri = settings.GITHUB_REDIRECT_URI
        
        # Clear any existing session state to prevent conflicts
        clear_oauth_session(request)
        
        return await github.authorize_redirect(request, redirect_uri)
        
    except Exception as e:
        logger.error(f"Error initiating GitHub login: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to initiate GitHub login"
        )

@router.get("/github/callback")
async def github_callback(request: Request, response: Response):
    """Handle GitHub OAuth callback"""
    if not settings.ENABLE_GITHUB_AUTH:
        return RedirectResponse(url="/login?error=oauth_disabled")
    
    try:
        # Get the OAuth client
        github = oauth_service.oauth.github
        
        # Check for error in callback
        error = request.query_params.get('error')
        if error:
            logger.error(f"OAuth error from GitHub: {error}")
            return RedirectResponse(url="/login?error=oauth_failed")
        
        # Get the access token with better error handling
        try:
            token = await github.authorize_access_token(request)
        except Exception as token_error:
            logger.error(f"Token authorization failed: {token_error}")
            # Clear session state and try again
            clear_oauth_session(request)
            return RedirectResponse(url="/login?error=oauth_failed")
        
        # Get user info from GitHub
        user_info = await oauth_service.get_github_user_info(token)
        
        if not user_info:
            logger.error("Failed to get user info from GitHub")
            return RedirectResponse(url="/login?error=oauth_failed")
        
        # Extract user information
        email = user_info.get('email')
        github_id = str(user_info.get('id'))  # GitHub user ID
        full_name = user_info.get('name') or user_info.get('login')  # Use login as fallback
        profile_picture = user_info.get('avatar_url')
        
        if not email or not github_id:
            logger.error("Missing required user information from GitHub")
            return RedirectResponse(url="/login?error=missing_info")
        
        # Check if this is a new user
        existing_user = auth_service.get_user_by_email(email)
        is_new_user = existing_user is None
        
        # Get or create user
        user = auth_service.get_or_create_oauth_user(
            email=email,
            oauth_provider='github',
            oauth_id=github_id,
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
                logger.info(f"✅ Allocated 1000 starter tokens to new GitHub user: {email}")
            except Exception as e:
                logger.warning(f"Failed to allocate starter tokens: {e}")
        
        # Create session
        session_id = auth_service.create_session(
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
        clear_oauth_session(request)
        
        logger.info(f"✅ GitHub OAuth login successful: {email}")
        return redirect_response
        
    except Exception as e:
        logger.error(f"GitHub OAuth callback error: {e}", exc_info=True)
        # Clear session state on error
        if hasattr(request, 'session'):
            request.session.clear()
        return RedirectResponse(url="/login?error=oauth_failed")


