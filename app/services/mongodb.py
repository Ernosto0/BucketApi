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
            self.client = MongoClient(
                settings.MONGODB_URL,
                maxPoolSize=50,
                minPoolSize=10,
                maxIdleTimeMS=45000,
                serverSelectionTimeoutMS=5000
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
    
    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("✅ MongoDB connection closed")
    
    def health_check(self) -> bool:
        """Check if MongoDB connection is healthy"""
        try:
            self.client.admin.command('ping')
            return True
        except Exception as e:
            logger.error(f"❌ MongoDB health check failed: {str(e)}")
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
