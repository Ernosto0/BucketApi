"""
Migration Script: Add Database Configuration to Existing APIs

This script helps add database configuration to APIs that were created 
before the database_config feature was added.

Usage:
    python tests/migrate_database_config.py --user_id YOUR_USER_ID --api_slug YOUR_API_SLUG --db_type postgresql --host localhost --port 5432 --database mydb --username myuser --password mypass
    
Or use connection string:
    python tests/migrate_database_config.py --user_id YOUR_USER_ID --api_slug YOUR_API_SLUG --connection_string "postgresql://user:pass@localhost:5432/mydb"
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
from app.services.mongodb import mongodb, init_database
from app.models import DatabaseConfig, DatabaseType

def migrate_api_database_config(
    user_id: str,
    api_slug: str,
    db_type: str,
    host: str = None,
    port: int = None,
    database_name: str = None,
    username: str = None,
    password: str = None,
    connection_string: str = None
):
    """Add database configuration to an existing API"""
    
    # Initialize database connection
    init_database()
    
    # Find the API
    api = mongodb.saved_apis.find_one({
        "user_id": user_id,
        "api_slug": api_slug
    })
    
    if not api:
        print(f"❌ API not found: {user_id}/{api_slug}")
        return False
    
    print(f"✅ Found API: {api.get('api_name', api_slug)}")
    
    # Check if it already has database_config
    if api.get('database_config'):
        print(f"⚠️  This API already has database configuration")
        response = input("Do you want to update it? (yes/no): ")
        if response.lower() not in ['yes', 'y']:
            print("❌ Migration cancelled")
            return False
    
    # Create database config
    db_config = {
        "enabled": True,
        "db_type": db_type,
        "host": host,
        "port": port,
        "database_name": database_name,
        "username": username,
        "password": password,
        "connection_string": connection_string
    }
    
    # Remove None values
    db_config = {k: v for k, v in db_config.items() if v is not None}
    
    # Update the API
    result = mongodb.saved_apis.update_one(
        {
            "user_id": user_id,
            "api_slug": api_slug
        },
        {
            "$set": {
                "database_config": db_config
            }
        }
    )
    
    if result.modified_count > 0:
        print(f"✅ Successfully added database configuration to {api_slug}")
        print(f"   Database Type: {db_type}")
        if host:
            print(f"   Host: {host}:{port}")
            print(f"   Database: {database_name}")
        else:
            print(f"   Connection String: {connection_string[:50]}...")
        return True
    else:
        print(f"❌ Failed to update API")
        return False

def main():
    parser = argparse.ArgumentParser(description='Add database configuration to existing APIs')
    parser.add_argument('--user_id', required=True, help='User ID who owns the API')
    parser.add_argument('--api_slug', required=True, help='API slug')
    parser.add_argument('--db_type', required=True, choices=['postgresql', 'mongodb'], help='Database type')
    
    # Individual connection parameters
    parser.add_argument('--host', help='Database host')
    parser.add_argument('--port', type=int, help='Database port')
    parser.add_argument('--database', dest='database_name', help='Database name')
    parser.add_argument('--username', help='Database username')
    parser.add_argument('--password', help='Database password')
    
    # Or connection string
    parser.add_argument('--connection_string', help='Full database connection string')
    
    args = parser.parse_args()
    
    # Validate that we have either connection_string or individual params
    if not args.connection_string:
        if not all([args.host, args.port, args.database_name, args.username]):
            parser.error("Either --connection_string or all of (--host, --port, --database, --username) must be provided")
    
    success = migrate_api_database_config(
        user_id=args.user_id,
        api_slug=args.api_slug,
        db_type=args.db_type,
        host=args.host,
        port=args.port,
        database_name=args.database_name,
        username=args.username,
        password=args.password,
        connection_string=args.connection_string
    )
    
    if success:
        print("\n✅ Migration completed successfully!")
        print("You can now view the database configuration in the API details page.")
    else:
        print("\n❌ Migration failed")
        sys.exit(1)

if __name__ == "__main__":
    main()




