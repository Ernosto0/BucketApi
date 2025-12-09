"""
Interactive Migration Script: Add Database Configuration to Existing APIs

This script provides an interactive way to add database configuration
to APIs that were created before the database_config feature.

Usage:
    python tests/migrate_database_config_interactive.py
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.mongodb import mongodb, init_database
from app.services.database_connection_service import database_connection_service
from app.models import DatabaseConfig, DatabaseType
import asyncio

def list_user_apis(user_id: str):
    """List all APIs for a user"""
    apis = list(mongodb.saved_apis.find({"user_id": user_id}))
    return apis

async def interactive_migrate():
    """Interactive migration process"""
    print("=" * 60)
    print("Database Configuration Migration Tool")
    print("=" * 60)
    print()
    
    # Initialize database
    init_database()
    
    # Get user ID
    user_id = input("Enter your User ID: ").strip()
    if not user_id:
        print("❌ User ID is required")
        return
    
    # List user's APIs
    apis = list_user_apis(user_id)
    if not apis:
        print(f"❌ No APIs found for user: {user_id}")
        return
    
    print(f"\n✅ Found {len(apis)} API(s):")
    for i, api in enumerate(apis, 1):
        has_db = "✓" if api.get('database_config') else "✗"
        print(f"  {i}. {api['api_slug']} - {api.get('api_name', 'N/A')} [DB: {has_db}]")
    
    # Select API
    print()
    api_choice = input(f"Select API number (1-{len(apis)}) or enter API slug: ").strip()
    
    selected_api = None
    if api_choice.isdigit() and 1 <= int(api_choice) <= len(apis):
        selected_api = apis[int(api_choice) - 1]
    else:
        # Try to find by slug
        for api in apis:
            if api['api_slug'] == api_choice:
                selected_api = api
                break
    
    if not selected_api:
        print("❌ Invalid selection")
        return
    
    api_slug = selected_api['api_slug']
    print(f"\n📦 Selected API: {api_slug} - {selected_api.get('api_name', 'N/A')}")
    
    # Check if already has database config
    if selected_api.get('database_config'):
        print("⚠️  This API already has database configuration")
        update = input("Do you want to update it? (yes/no): ").strip().lower()
        if update not in ['yes', 'y']:
            print("❌ Migration cancelled")
            return
    
    # Get database type
    print("\n📊 Database Type:")
    print("  1. PostgreSQL")
    print("  2. MongoDB")
    db_type_choice = input("Select database type (1-2): ").strip()
    
    if db_type_choice == '1':
        db_type = 'postgresql'
        default_port = 5432
    elif db_type_choice == '2':
        db_type = 'mongodb'
        default_port = 27017
    else:
        print("❌ Invalid database type")
        return
    
    # Ask for connection method
    print("\n🔗 Connection Method:")
    print("  1. Individual parameters (host, port, etc.)")
    print("  2. Connection string")
    method = input("Select method (1-2): ").strip()
    
    connection_string = None
    host = None
    port = None
    database_name = None
    username = None
    password = None
    
    if method == '1':
        # Individual parameters
        host = input(f"\nDatabase Host [localhost]: ").strip() or "localhost"
        port_input = input(f"Database Port [{default_port}]: ").strip()
        port = int(port_input) if port_input else default_port
        database_name = input("Database Name: ").strip()
        username = input("Database Username: ").strip()
        password = input("Database Password: ").strip()
        
        if not all([database_name, username]):
            print("❌ Database name and username are required")
            return
    
    elif method == '2':
        # Connection string
        connection_string = input("\nConnection String: ").strip()
        if not connection_string:
            print("❌ Connection string is required")
            return
    else:
        print("❌ Invalid method")
        return
    
    # Create database config
    db_config_dict = {
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
    db_config_dict = {k: v for k, v in db_config_dict.items() if v is not None}
    
    # Test connection
    print("\n🔍 Testing database connection...")
    try:
        db_config = DatabaseConfig(**db_config_dict)
        success, message, conn_time = await database_connection_service.test_connection(db_config)
        
        if success:
            print(f"✅ Connection successful! ({conn_time:.2f}ms)")
            print(f"   {message}")
        else:
            print(f"❌ Connection failed: {message}")
            proceed = input("\nDo you want to save the configuration anyway? (yes/no): ").strip().lower()
            if proceed not in ['yes', 'y']:
                print("❌ Migration cancelled")
                return
    except Exception as e:
        print(f"❌ Error testing connection: {e}")
        proceed = input("\nDo you want to save the configuration anyway? (yes/no): ").strip().lower()
        if proceed not in ['yes', 'y']:
            print("❌ Migration cancelled")
            return
    
    # Save to database
    print("\n💾 Saving configuration...")
    result = mongodb.saved_apis.update_one(
        {
            "user_id": user_id,
            "api_slug": api_slug
        },
        {
            "$set": {
                "database_config": db_config_dict
            }
        }
    )
    
    if result.modified_count > 0:
        print(f"\n✅ Successfully added database configuration to {api_slug}!")
        print(f"   Database Type: {db_type.upper()}")
        if host:
            print(f"   Host: {host}:{port}")
            print(f"   Database: {database_name}")
        else:
            print(f"   Connection String: {connection_string[:50]}...")
        print("\n🎉 You can now view the database details in the API details page!")
    else:
        print(f"\n❌ Failed to update API (no changes made)")

def main():
    try:
        asyncio.run(interactive_migrate())
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()




