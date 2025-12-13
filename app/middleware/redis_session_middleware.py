"""
Redis-backed session middleware for multi-worker OAuth support
"""
import json
import logging
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.datastructures import MutableHeaders
from itsdangerous import URLSafeTimedSerializer, BadSignature
import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class RedisSessionMiddleware(BaseHTTPMiddleware):
    """
    Session middleware that stores session data in Redis.
    This allows session sharing across multiple worker processes.
    """
    
    def __init__(self, app, redis_url: str, secret_key: str, max_age: int = 1800, session_cookie: str = "session", domain: str = None, https_only: bool = False):
        super().__init__(app)
        self.redis_url = redis_url
        self.secret_key = secret_key
        self.max_age = max_age
        self.session_cookie = session_cookie
        self.domain = domain
        self.https_only = https_only
        self.serializer = URLSafeTimedSerializer(secret_key)
        self.redis_client: Optional[aioredis.Redis] = None
        
    async def _get_redis(self) -> aioredis.Redis:
        """Get or create Redis connection"""
        if self.redis_client is None:
            try:
                self.redis_client = await aioredis.from_url(
                    self.redis_url,
                    encoding="utf-8",
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_keepalive=True
                )
                # Test connection
                await self.redis_client.ping()
                logger.info("✅ Connected to Redis for session storage")
            except Exception as e:
                logger.error(f"❌ Failed to connect to Redis: {e}")
                raise
        return self.redis_client
    
    async def dispatch(self, request: Request, call_next):
        """Process request and manage session"""
        session_id = None
        session_data = {}
        
        # Try to load existing session
        session_cookie = request.cookies.get(self.session_cookie)
        if session_cookie:
            try:
                # Verify and decode session ID
                session_id = self.serializer.loads(
                    session_cookie,
                    max_age=self.max_age
                )
                
                # Load session data from Redis
                redis = await self._get_redis()
                session_json = await redis.get(f"session:{session_id}")
                if session_json:
                    session_data = json.loads(session_json)
                    logger.debug(f"Loaded session {session_id[:8]}... from Redis")
                else:
                    logger.warning(f"Session {session_id[:8]}... not found in Redis")
                    session_id = None
                    
            except BadSignature:
                logger.warning("Invalid session signature")
                session_id = None
            except Exception as e:
                logger.error(f"Error loading session: {e}")
                session_id = None
        
        # Attach session to request
        request.state.session = session_data
        request.state.session_id = session_id
        
        # Process request
        response = await call_next(request)
        
        # Save session if modified
        if hasattr(request.state, 'session') and request.state.session:
            try:
                redis = await self._get_redis()
                
                # Generate new session ID if needed
                if not session_id:
                    import uuid
                    session_id = str(uuid.uuid4())
                
                # Save session data to Redis
                session_json = json.dumps(request.state.session)
                await redis.setex(
                    f"session:{session_id}",
                    self.max_age,
                    session_json
                )
                
                # Set session cookie
                signed_session_id = self.serializer.dumps(session_id)
                
                # Check if we're behind a reverse proxy (X-Forwarded-Proto header)
                forwarded_proto = request.headers.get("X-Forwarded-Proto", "")
                is_https = forwarded_proto == "https" or request.url.scheme == "https"
                
                # For OAuth, we need 'none' samesite when behind reverse proxy
                # to allow the callback to send the cookie
                cookie_params = {
                    "key": self.session_cookie,
                    "value": signed_session_id,
                    "max_age": self.max_age,
                    "httponly": True,
                    "secure": self.https_only if self.https_only is not None else is_https,
                    "samesite": "none" if is_https else "lax",  # 'none' requires secure=True
                    "path": "/"
                }
                
                # Add domain if specified
                if self.domain:
                    cookie_params["domain"] = self.domain
                
                response.set_cookie(**cookie_params)
                logger.debug(f"Saved session {session_id[:8]}... to Redis (secure={cookie_params['secure']}, samesite={cookie_params['samesite']})")
                
            except Exception as e:
                logger.error(f"Error saving session: {e}")
        
        # Clear session if explicitly cleared
        elif hasattr(request.state, 'session') and not request.state.session and session_id:
            try:
                redis = await self._get_redis()
                await redis.delete(f"session:{session_id}")
                response.delete_cookie(self.session_cookie)
                logger.debug(f"Cleared session {session_id[:8]}...")
            except Exception as e:
                logger.error(f"Error clearing session: {e}")
        
        return response
    
    async def close(self):
        """Close Redis connection"""
        if self.redis_client:
            await self.redis_client.close()
            logger.info("Closed Redis connection")


class RedisSessionInterface:
    """
    Session interface that mimics Starlette's SessionMiddleware API
    but uses Redis for storage
    """
    
    def __init__(self, request: Request):
        self.request = request
        self._data = getattr(request.state, 'session', {})
    
    def __getitem__(self, key):
        return self._data[key]
    
    def __setitem__(self, key, value):
        self._data[key] = value
        self.request.state.session = self._data
    
    def __delitem__(self, key):
        del self._data[key]
        self.request.state.session = self._data
    
    def __contains__(self, key):
        return key in self._data
    
    def get(self, key, default=None):
        return self._data.get(key, default)
    
    def pop(self, key, default=None):
        value = self._data.pop(key, default)
        self.request.state.session = self._data
        return value
    
    def clear(self):
        self._data.clear()
        self.request.state.session = {}
    
    def setdefault(self, key, default=None):
        if key not in self._data:
            self._data[key] = default
            self.request.state.session = self._data
        return self._data[key]
    
    def update(self, other):
        self._data.update(other)
        self.request.state.session = self._data
    
    def keys(self):
        return self._data.keys()
    
    def values(self):
        return self._data.values()
    
    def items(self):
        return self._data.items()


def get_session(request: Request) -> RedisSessionInterface:
    """Get session interface for request"""
    return RedisSessionInterface(request)

