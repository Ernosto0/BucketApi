"""
Database Connection Service

Service for testing and managing database connections for generated APIs.
Supports PostgreSQL and MongoDB connections.
"""

import base64
import logging
import time
from typing import Tuple, Optional, Dict, Any
from ..models import DatabaseConfig, DatabaseType

logger = logging.getLogger(__name__)


class DatabaseConnectionService:
    """Service for handling database connection operations"""
    
    def __init__(self):
        logger.info("DatabaseConnectionService initialized")
        self._schema_cache = {}  # Cache for database schemas
    
    async def test_connection(self, config: DatabaseConfig) -> Tuple[bool, str, Optional[float]]:
        """
        Test a database connection based on the configuration.
        
        Args:
            config: DatabaseConfig with connection details
            
        Returns:
            Tuple of (success, message, connection_time_ms)
        """
        if config.db_type == DatabaseType.POSTGRESQL:
            return await self.test_postgres_connection(config)
        elif config.db_type == DatabaseType.MONGODB:
            return await self.test_mongodb_connection(config)
        else:
            return False, f"Unsupported database type: {config.db_type}", None
    
    async def test_postgres_connection(self, config: DatabaseConfig) -> Tuple[bool, str, Optional[float]]:
        """
        Test a PostgreSQL database connection.
        
        Args:
            config: DatabaseConfig with PostgreSQL connection details
            
        Returns:
            Tuple of (success, message, connection_time_ms)
        """
        try:
            import asyncpg
        except ImportError:
            logger.error("asyncpg not installed")
            return False, "PostgreSQL driver (asyncpg) is not installed. Please install it with: pip install asyncpg", None
        
        start_time = time.time()
        
        try:
            # Build connection string if not provided
            if config.connection_string:
                dsn = config.connection_string
            else:
                # Decode password if it's base64 encoded
                password = self._decode_if_base64(config.password) if config.password else ""
                dsn = f"postgresql://{config.username}:{password}@{config.host}:{config.port}/{config.database_name}"
            
            logger.info(f"Testing PostgreSQL connection to {config.host}:{config.port}/{config.database_name}")
            
            # Attempt connection with timeout
            conn = await asyncpg.connect(dsn, timeout=10)
            
            # Test the connection with a simple query
            version = await conn.fetchval("SELECT version()")
            await conn.close()
            
            connection_time_ms = (time.time() - start_time) * 1000
            
            logger.info(f"PostgreSQL connection successful in {connection_time_ms:.2f}ms")
            return True, f"Connection successful! PostgreSQL version: {version[:50]}...", connection_time_ms
            
        except asyncpg.InvalidCatalogNameError:
            return False, f"Database '{config.database_name}' does not exist", None
        except asyncpg.InvalidPasswordError:
            return False, "Invalid username or password", None
        except asyncpg.ConnectionDoesNotExistError:
            return False, f"Could not connect to {config.host}:{config.port}. Server may be down or unreachable", None
        except OSError as e:
            return False, f"Network error: Could not reach {config.host}:{config.port}. Error: {str(e)}", None
        except Exception as e:
            logger.error(f"PostgreSQL connection error: {str(e)}", exc_info=True)
            return False, f"Connection failed: {str(e)}", None
    
    async def test_mongodb_connection(self, config: DatabaseConfig) -> Tuple[bool, str, Optional[float]]:
        """
        Test a MongoDB database connection.
        
        Args:
            config: DatabaseConfig with MongoDB connection details
            
        Returns:
            Tuple of (success, message, connection_time_ms)
        """
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
        except ImportError:
            logger.error("motor not installed")
            return False, "MongoDB driver (motor) is not installed. Please install it with: pip install motor", None
        
        start_time = time.time()
        
        try:
            # Build connection string if not provided
            if config.connection_string:
                uri = config.connection_string
            else:
                # Decode password if it's base64 encoded
                password = self._decode_if_base64(config.password) if config.password else ""
                # URL encode the password for special characters
                from urllib.parse import quote_plus
                encoded_password = quote_plus(password)
                uri = f"mongodb://{config.username}:{encoded_password}@{config.host}:{config.port}/{config.database_name}"
            
            logger.info(f"Testing MongoDB connection to {config.host}:{config.port}/{config.database_name}")
            
            # Create client with timeout
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
            
            # Test the connection by pinging the server
            await client.admin.command('ping')
            
            # Get server info
            server_info = await client.server_info()
            version = server_info.get('version', 'unknown')
            
            # Close the client
            client.close()
            
            connection_time_ms = (time.time() - start_time) * 1000
            
            logger.info(f"MongoDB connection successful in {connection_time_ms:.2f}ms")
            return True, f"Connection successful! MongoDB version: {version}", connection_time_ms
            
        except Exception as e:
            error_msg = str(e)
            logger.error(f"MongoDB connection error: {error_msg}", exc_info=True)
            
            # Parse common MongoDB errors for user-friendly messages
            if "Authentication failed" in error_msg:
                return False, "Invalid username or password", None
            elif "timed out" in error_msg.lower():
                return False, f"Connection timed out. Could not reach {config.host}:{config.port}", None
            elif "ServerSelectionTimeoutError" in error_msg:
                return False, f"Could not connect to {config.host}:{config.port}. Server may be down or unreachable", None
            else:
                return False, f"Connection failed: {error_msg}", None
    
    def encode_credentials(self, config: DatabaseConfig) -> DatabaseConfig:
        """
        Encode sensitive credentials in the config using base64.
        
        Args:
            config: DatabaseConfig with plain text credentials
            
        Returns:
            DatabaseConfig with base64 encoded password
        """
        if config.password:
            encoded_password = base64.b64encode(config.password.encode()).decode()
            return DatabaseConfig(
                enabled=config.enabled,
                db_type=config.db_type,
                host=config.host,
                port=config.port,
                database_name=config.database_name,
                username=config.username,
                password=encoded_password,
                connection_string=config.connection_string
            )
        return config
    
    def decode_credentials(self, config: DatabaseConfig) -> DatabaseConfig:
        """
        Decode base64 encoded credentials in the config.
        
        Args:
            config: DatabaseConfig with base64 encoded password
            
        Returns:
            DatabaseConfig with plain text password
        """
        if config.password:
            try:
                decoded_password = base64.b64decode(config.password.encode()).decode()
                return DatabaseConfig(
                    enabled=config.enabled,
                    db_type=config.db_type,
                    host=config.host,
                    port=config.port,
                    database_name=config.database_name,
                    username=config.username,
                    password=decoded_password,
                    connection_string=config.connection_string
                )
            except Exception:
                # If decoding fails, assume it's already plain text
                return config
        return config
    
    def _decode_if_base64(self, value: str) -> str:
        """
        Attempt to decode a value if it's base64 encoded.
        Returns the original value if decoding fails.
        """
        if not value:
            return value
        try:
            decoded = base64.b64decode(value.encode()).decode()
            return decoded
        except Exception:
            return value
    
    def build_connection_string(self, config: DatabaseConfig) -> str:
        """
        Build a connection string from the configuration.
        
        Args:
            config: DatabaseConfig with connection details
            
        Returns:
            Connection string suitable for the database type
        """
        if config.connection_string:
            return config.connection_string
        
        password = self._decode_if_base64(config.password) if config.password else ""
        
        if config.db_type == DatabaseType.POSTGRESQL:
            return f"postgresql://{config.username}:{password}@{config.host}:{config.port}/{config.database_name}"
        elif config.db_type == DatabaseType.MONGODB:
            from urllib.parse import quote_plus
            encoded_password = quote_plus(password)
            return f"mongodb://{config.username}:{encoded_password}@{config.host}:{config.port}/{config.database_name}"
        else:
            raise ValueError(f"Unsupported database type: {config.db_type}")
    
    async def get_database_schema(self, config: DatabaseConfig, table_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Get the schema information from the database.
        
        Args:
            config: DatabaseConfig with connection details
            table_name: Optional specific table to get schema for
            
        Returns:
            Dictionary containing schema information
        """
        cache_key = f"{config.db_type}_{config.host}_{config.database_name}_{table_name or 'all'}"
        
        # Check cache first
        if cache_key in self._schema_cache:
            logger.info(f"Returning cached schema for {cache_key}")
            return self._schema_cache[cache_key]
        
        if config.db_type == DatabaseType.POSTGRESQL:
            schema = await self._get_postgres_schema(config, table_name)
        elif config.db_type == DatabaseType.MONGODB:
            schema = await self._get_mongodb_schema(config, table_name)
        else:
            return {"error": f"Unsupported database type: {config.db_type}"}
        
        # Cache the result
        self._schema_cache[cache_key] = schema
        return schema
    
    async def _get_postgres_schema(self, config: DatabaseConfig, table_name: Optional[str] = None) -> Dict[str, Any]:
        """Get PostgreSQL database schema information."""
        try:
            import asyncpg
        except ImportError:
            return {"error": "asyncpg not installed"}
        
        conn = None
        try:
            # Build connection string
            if config.connection_string:
                dsn = config.connection_string
            else:
                password = self._decode_if_base64(config.password) if config.password else ""
                dsn = f"postgresql://{config.username}:{password}@{config.host}:{config.port}/{config.database_name}"
            
            conn = await asyncpg.connect(dsn, timeout=10)
            
            schema_info = {
                "database_type": "postgresql",
                "database_name": config.database_name,
                "tables": {}
            }
            
            # Query for tables
            if table_name:
                # Get specific table
                tables_query = """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_type = 'BASE TABLE'
                    AND table_name = $1
                """
                tables = await conn.fetch(tables_query, table_name)
            else:
                # Get all tables
                tables_query = """
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'public' 
                    AND table_type = 'BASE TABLE'
                    ORDER BY table_name
                """
                tables = await conn.fetch(tables_query)
            
            # Get columns for each table
            for table_row in tables:
                tbl_name = table_row['table_name']
                
                columns_query = """
                    SELECT 
                        column_name,
                        data_type,
                        is_nullable,
                        column_default,
                        character_maximum_length
                    FROM information_schema.columns
                    WHERE table_schema = 'public'
                    AND table_name = $1
                    ORDER BY ordinal_position
                """
                columns = await conn.fetch(columns_query, tbl_name)
                
                # Get primary keys
                pk_query = """
                    SELECT a.attname
                    FROM pg_index i
                    JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                    WHERE i.indrelid = $1::regclass
                    AND i.indisprimary
                """
                pks = await conn.fetch(pk_query, tbl_name)
                pk_columns = [pk['attname'] for pk in pks]
                
                schema_info["tables"][tbl_name] = {
                    "columns": [
                        {
                            "name": col['column_name'],
                            "type": col['data_type'],
                            "nullable": col['is_nullable'] == 'YES',
                            "default": col['column_default'],
                            "max_length": col['character_maximum_length'],
                            "is_primary_key": col['column_name'] in pk_columns
                        }
                        for col in columns
                    ],
                    "primary_keys": pk_columns
                }
            
            await conn.close()
            
            logger.info(f"Retrieved PostgreSQL schema: {len(schema_info['tables'])} tables")
            return schema_info
            
        except Exception as e:
            logger.error(f"Failed to get PostgreSQL schema: {str(e)}")
            if conn:
                await conn.close()
            return {"error": str(e)}
    
    async def _get_mongodb_schema(self, config: DatabaseConfig, collection_name: Optional[str] = None) -> Dict[str, Any]:
        """Get MongoDB database schema information by sampling documents."""
        try:
            from motor.motor_asyncio import AsyncIOMotorClient
        except ImportError:
            return {"error": "motor not installed"}
        
        client = None
        try:
            # Build connection string
            if config.connection_string:
                uri = config.connection_string
            else:
                password = self._decode_if_base64(config.password) if config.password else ""
                from urllib.parse import quote_plus
                encoded_password = quote_plus(password)
                uri = f"mongodb://{config.username}:{encoded_password}@{config.host}:{config.port}/{config.database_name}"
            
            client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=10000)
            db = client[config.database_name]
            
            schema_info = {
                "database_type": "mongodb",
                "database_name": config.database_name,
                "collections": {}
            }
            
            # Get collections
            if collection_name:
                collections = [collection_name]
            else:
                collections = await db.list_collection_names()
            
            # Sample documents from each collection to infer schema
            for coll_name in collections:
                collection = db[coll_name]
                
                # Sample a few documents to infer fields
                sample_docs = await collection.find().limit(5).to_list(5)
                
                if sample_docs:
                    # Collect all unique fields from samples
                    all_fields = set()
                    field_types = {}
                    
                    for doc in sample_docs:
                        for key, value in doc.items():
                            all_fields.add(key)
                            if key not in field_types:
                                field_types[key] = type(value).__name__
                    
                    schema_info["collections"][coll_name] = {
                        "fields": [
                            {
                                "name": field,
                                "type": field_types.get(field, "unknown"),
                                "is_id": field == "_id"
                            }
                            for field in sorted(all_fields)
                        ],
                        "sample_count": len(sample_docs)
                    }
                else:
                    schema_info["collections"][coll_name] = {
                        "fields": [],
                        "sample_count": 0,
                        "note": "Collection is empty"
                    }
            
            client.close()
            
            logger.info(f"Retrieved MongoDB schema: {len(schema_info['collections'])} collections")
            return schema_info
            
        except Exception as e:
            logger.error(f"Failed to get MongoDB schema: {str(e)}")
            if client:
                client.close()
            return {"error": str(e)}


# Singleton instance
database_connection_service = DatabaseConnectionService()
