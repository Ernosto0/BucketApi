"""
MongoDB Database Service
Handles all MongoDB connections and collection access
"""
from pymongo import MongoClient, ASCENDING, DESCENDING, IndexModel
from pymongo.database import Database
from pymongo.collection import Collection
from typing import Optional
import logging
from ..config import settings

logger = logging.getLogger(__name__)

class MongoDB:
    """MongoDB connection and collection manager"""
    
    def __init__(self):
        self.client: Optional[MongoClient] = None
        self.db: Optional[Database] = None
        self._collections = {}
        
    def connect(self):
        """Establish connection to MongoDB"""
        try:
            # Check if MongoDB URL is configured
            if not settings.MONGODB_URL:
                error_msg = "MONGODB_URL environment variable is not set. Please configure it in your .env file or environment variables."
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            if not settings.MONGODB_DB_NAME:
                error_msg = "MONGODB_DB_NAME environment variable is not set. Please configure it in your .env file or environment variables."
                logger.error(f"❌ {error_msg}")
                raise ValueError(error_msg)
            
            self.client = MongoClient(
                settings.MONGODB_URL,
                # Connection Pool Settings
                maxPoolSize=20,  # Reduced from 50 to prevent connection exhaustion
                minPoolSize=5,   # Reduced from 10 for better resource management
                maxIdleTimeMS=30000,  # Reduced from 45000 for faster cleanup
                
                # Timeout Settings - More generous for network issues
                serverSelectionTimeoutMS=30000,  # Increased from 5000 to 30 seconds
                connectTimeoutMS=30000,         # 30 seconds for initial connection
                socketTimeoutMS=30000,          # 30 seconds for socket operations
                
                # Retry Settings
                retryWrites=True,               # Enable retry for write operations
                retryReads=True,                # Enable retry for read operations
                
                # Heartbeat Settings
                heartbeatFrequencyMS=10000,     # Check connection every 10 seconds
                
                # Connection Management
                maxConnecting=5,               # Limit concurrent connection attempts
                waitQueueTimeoutMS=30000,      # Wait up to 30 seconds for available connection
                
                # Compression (reduces network load)
                compressors=['zstd', 'zlib'],   # Enable compression
                
                # Additional reliability settings
                directConnection=False,        # Use replica set discovery
                appName="AI-API-Generator"     # Identify this app in MongoDB logs
            )
            
            # Test connection
            self.client.admin.command('ping')
            
            self.db = self.client[settings.MONGODB_DB_NAME]
            logger.info(f"✅ Connected to MongoDB database: {settings.MONGODB_DB_NAME}")
            
            # Initialize collections
            self._init_collections()
            
            # Create indexes
            self._create_indexes()
            
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to MongoDB: {str(e)}")
            # Safely log connection URL (handle None case)
            if settings.MONGODB_URL:
                # Log partial URL for debugging (hide credentials)
                url_display = settings.MONGODB_URL[:50] + "..." if len(settings.MONGODB_URL) > 50 else settings.MONGODB_URL
                # Mask credentials in URL
                if "@" in url_display:
                    parts = url_display.split("@")
                    if len(parts) == 2:
                        url_display = "mongodb://***:***@" + parts[1]
                logger.error(f"Connection URL: {url_display}")
            else:
                logger.error("Connection URL: Not configured (MONGODB_URL is None)")
            raise
    
    def _init_collections(self):
        """Initialize all collection references"""
        # Core collections
        self._collections['users'] = self.db['users']
        self._collections['user_sessions'] = self.db['user_sessions']
        self._collections['saved_apis'] = self.db['saved_apis']
        self._collections['api_keys'] = self.db['api_keys']
        
        # Usage tracking collections
        self._collections['llm_usage'] = self.db['llm_usage']
        self._collections['api_execution_usage'] = self.db['api_execution_usage']
        self._collections['api_generation_usage'] = self.db['api_generation_usage']
        
        # API metadata and pricing
        self._collections['api_metadata'] = self.db['api_metadata']
        self._collections['internal_tokens'] = self.db['internal_tokens']
        self._collections['api_execution_token_usage'] = self.db['api_execution_token_usage']
        
        # Process management
        self._collections['api_processes'] = self.db['api_processes']
        
        # Logging collections
        self._collections['system_logs'] = self.db['system_logs']
        self._collections['http_request_logs'] = self.db['http_request_logs']
        self._collections['llm_call_logs'] = self.db['llm_call_logs']
        self._collections['chat_message_logs'] = self.db['chat_message_logs']
        self._collections['error_logs'] = self.db['error_logs']
        self._collections['retry_logs'] = self.db['retry_logs']
        
        # Subscription collections
        self._collections['subscriptions'] = self.db['subscriptions']
        self._collections['subscription_events'] = self.db['subscription_events']
        
        # Report collections
        self._collections['reports'] = self.db['reports']
        
        # Settings management collection
        self._collections['system_settings'] = self.db['system_settings']
        
        # Custom domains collection
        self._collections['custom_domains'] = self.db['custom_domains']
        
        logger.info(f"✅ Initialized {len(self._collections)} collections")
    
    def _create_indexes(self):
        """Create indexes for all collections"""
        try:
            # Users indexes
            self.users.create_index([("email", ASCENDING)], unique=True)
            self.users.create_index([("oauth_id", ASCENDING)])
            self.users.create_index([("created_at", DESCENDING)])
            
            # User sessions indexes
            self.user_sessions.create_index([("user_id", ASCENDING)])
            self.user_sessions.create_index([("expires_at", ASCENDING)])
            self.user_sessions.create_index([("created_at", DESCENDING)])
            
            # Saved APIs indexes
            self.saved_apis.create_index([("api_slug", ASCENDING), ("user_id", ASCENDING)])
            self.saved_apis.create_index([("user_id", ASCENDING)])
            self.saved_apis.create_index([("created_at", DESCENDING)])
            
            # API Keys indexes
            self.api_keys.create_index([("user_id", ASCENDING)])
            self.api_keys.create_index([("key_hash", ASCENDING)], unique=True)
            self.api_keys.create_index([("created_at", DESCENDING)])
            
            # LLM Usage indexes
            self.llm_usage.create_index([("user_id", ASCENDING)])
            self.llm_usage.create_index([("api_key_id", ASCENDING)])
            self.llm_usage.create_index([("created_at", DESCENDING)])
            self.llm_usage.create_index([("service_type", ASCENDING)])
            
            # API Execution Usage indexes
            self.api_execution_usage.create_index([("user_id", ASCENDING)])
            self.api_execution_usage.create_index([("api_slug", ASCENDING)])
            self.api_execution_usage.create_index([("created_at", DESCENDING)])
            
            # API Generation Usage indexes
            self.api_generation_usage.create_index([("user_id", ASCENDING)])
            self.api_generation_usage.create_index([("api_key_id", ASCENDING)])
            self.api_generation_usage.create_index([("api_slug", ASCENDING)])
            self.api_generation_usage.create_index([("created_at", DESCENDING)])
            self.api_generation_usage.create_index([("success", ASCENDING)])
            
            # API Metadata indexes
            self.api_metadata.create_index([("api_slug", ASCENDING)])
            self.api_metadata.create_index([("user_id", ASCENDING)])
            
            # Internal Tokens indexes
            self.internal_tokens.create_index([("user_id", ASCENDING)])
            self.internal_tokens.create_index([("is_used", ASCENDING)])
            self.internal_tokens.create_index([("expires_at", ASCENDING)])
            
            # API Execution Token Usage indexes
            self.api_execution_token_usage.create_index([("user_id", ASCENDING)])
            self.api_execution_token_usage.create_index([("api_slug", ASCENDING)])
            self.api_execution_token_usage.create_index([("created_at", DESCENDING)])
            
            # API Processes indexes
            self.api_processes.create_index([("api_slug", ASCENDING)])
            self.api_processes.create_index([("port", ASCENDING)], unique=True)
            
            # System Logs indexes
            self.system_logs.create_index([("timestamp", DESCENDING)])
            self.system_logs.create_index([("level", ASCENDING)])
            self.system_logs.create_index([("category", ASCENDING)])
            self.system_logs.create_index([("user_id", ASCENDING)])
            
            # HTTP Request Logs indexes
            self.http_request_logs.create_index([("timestamp", DESCENDING)])
            self.http_request_logs.create_index([("request_id", ASCENDING)])
            self.http_request_logs.create_index([("endpoint", ASCENDING)])
            
            # LLM Call Logs indexes
            self.llm_call_logs.create_index([("timestamp", DESCENDING)])
            self.llm_call_logs.create_index([("service_type", ASCENDING)])
            self.llm_call_logs.create_index([("user_id", ASCENDING)])
            
            # Chat Message Logs indexes
            self.chat_message_logs.create_index([("timestamp", DESCENDING)])
            self.chat_message_logs.create_index([("user_id", ASCENDING)])
            self.chat_message_logs.create_index([("conversation_id", ASCENDING)])
            
            # Error Logs indexes
            self.error_logs.create_index([("timestamp", DESCENDING)])
            self.error_logs.create_index([("user_id", ASCENDING)])
            
            # Retry Logs indexes
            self.retry_logs.create_index([("timestamp", DESCENDING)])
            self.retry_logs.create_index([("request_id", ASCENDING)])
            self.retry_logs.create_index([("service_type", ASCENDING)])
            
            # Subscriptions indexes
            self.subscriptions.create_index([("user_id", ASCENDING)])
            self.subscriptions.create_index([("lemonsqueezy_subscription_id", ASCENDING)], unique=True)
            self.subscriptions.create_index([("status", ASCENDING)])
            
            # Subscription Events indexes
            self.subscription_events.create_index([("subscription_id", ASCENDING)])
            self.subscription_events.create_index([("user_id", ASCENDING)])
            self.subscription_events.create_index([("lemonsqueezy_event_id", ASCENDING)], unique=True)
            self.subscription_events.create_index([("created_at", DESCENDING)])
            
            # Reports indexes
            self.reports.create_index([("report_id", ASCENDING)], unique=True)
            self.reports.create_index([("api_user_id", ASCENDING)])
            self.reports.create_index([("api_slug", ASCENDING)])
            self.reports.create_index([("reporter_user_id", ASCENDING)])
            self.reports.create_index([("status", ASCENDING)])
            self.reports.create_index([("category", ASCENDING)])
            self.reports.create_index([("severity", ASCENDING)])
            self.reports.create_index([("created_at", DESCENDING)])
            
            # System Settings indexes
            self.system_settings.create_index([("key", ASCENDING)], unique=True)
            self.system_settings.create_index([("category", ASCENDING)])
            self.system_settings.create_index([("last_updated", DESCENDING)])
            
            # Custom Domains indexes
            self.custom_domains.create_index([("domain", ASCENDING)], unique=True)
            self.custom_domains.create_index([("user_id", ASCENDING)])
            self.custom_domains.create_index([("api_slug", ASCENDING)])
            self.custom_domains.create_index([("status", ASCENDING)])
            self.custom_domains.create_index([("verification_token", ASCENDING)])
            self.custom_domains.create_index([("created_at", DESCENDING)])
            
            logger.info("✅ Created all database indexes")
            
        except Exception as e:
            logger.error(f"⚠️ Error creating indexes: {str(e)}")
    
    # Collection properties for easy access
    @property
    def users(self) -> Collection:
        return self._collections['users']
    
    @property
    def user_sessions(self) -> Collection:
        return self._collections['user_sessions']
    
    @property
    def saved_apis(self) -> Collection:
        return self._collections['saved_apis']
    
    @property
    def api_keys(self) -> Collection:
        return self._collections['api_keys']
    
    @property
    def llm_usage(self) -> Collection:
        return self._collections['llm_usage']
    
    @property
    def api_execution_usage(self) -> Collection:
        return self._collections['api_execution_usage']
    
    @property
    def api_generation_usage(self) -> Collection:
        return self._collections['api_generation_usage']
    
    @property
    def api_metadata(self) -> Collection:
        return self._collections['api_metadata']
    
    @property
    def internal_tokens(self) -> Collection:
        return self._collections['internal_tokens']
    
    @property
    def api_execution_token_usage(self) -> Collection:
        return self._collections['api_execution_token_usage']
    
    @property
    def api_processes(self) -> Collection:
        return self._collections['api_processes']
    
    @property
    def system_logs(self) -> Collection:
        return self._collections['system_logs']
    
    @property
    def http_request_logs(self) -> Collection:
        return self._collections['http_request_logs']
    
    @property
    def llm_call_logs(self) -> Collection:
        return self._collections['llm_call_logs']
    
    @property
    def chat_message_logs(self) -> Collection:
        return self._collections['chat_message_logs']
    
    @property
    def error_logs(self) -> Collection:
        return self._collections['error_logs']
    
    @property
    def retry_logs(self) -> Collection:
        return self._collections['retry_logs']
    
    @property
    def subscriptions(self) -> Collection:
        return self._collections['subscriptions']
    
    @property
    def subscription_events(self) -> Collection:
        return self._collections['subscription_events']
    
    @property
    def reports(self) -> Collection:
        return self._collections['reports']
    
    @property
    def system_settings(self) -> Collection:
        return self._collections['system_settings']
    
    @property
    def custom_domains(self) -> Collection:
        return self._collections['custom_domains']
    
    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("✅ MongoDB connection closed")
    
    def health_check(self) -> bool:
        """Check if MongoDB connection is healthy"""
        try:
            if not self.client:
                logger.warning("MongoDB client not initialized")
                return False
                
            # Use a shorter timeout for health checks
            self.client.admin.command('ping', maxTimeMS=5000)
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB health check failed: {str(e)}")
            return False
    
    def reconnect(self) -> bool:
        """Attempt to reconnect to MongoDB"""
        try:
            logger.info("🔄 Attempting to reconnect to MongoDB...")
            self.close()  # Close existing connection
            return self.connect()
        except Exception as e:
            logger.error(f"❌ Failed to reconnect to MongoDB: {str(e)}")
            return False

# Global MongoDB instance
mongodb = MongoDB()

def get_db() -> Database:
    """Get MongoDB database instance"""
    return mongodb.db

def init_database():
    """Initialize MongoDB connection"""
    mongodb.connect()
    logger.info("✅ MongoDB initialized successfully")
