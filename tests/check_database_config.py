"""
Check if database configuration exists for an API
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.mongodb import mongodb, init_database
import json

def check_api_config(user_id: str, api_slug: str):
    """Check the database configuration for an API"""
    
    # Initialize database connection
    init_database()
    
    # Find the API
    api = mongodb.saved_apis.find_one({
        "user_id": user_id,
        "api_slug": api_slug
    })
    
    if not api:
        print(f"❌ API not found: {user_id}/{api_slug}")
        return
    
    print(f"✅ Found API: {api.get('api_name', api_slug)}")
    print(f"\nAPI Fields:")
    for key in api.keys():
        if key != '_id':
            print(f"  - {key}")
    
    print(f"\n{'='*60}")
    
    if 'database_config' in api:
        print("✅ database_config field EXISTS")
        db_config = api['database_config']
        print(f"\nDatabase Configuration:")
        print(json.dumps(db_config, indent=2, default=str))
    else:
        print("❌ database_config field DOES NOT EXIST")
        print("\nYou need to run the migration script to add it.")
    
    print(f"{'='*60}\n")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python check_database_config.py USER_ID API_SLUG")
        print("\nExample: python check_database_config.py user123 getusersapi")
        sys.exit(1)
    
    user_id = sys.argv[1]
    api_slug = sys.argv[2]
    
    check_api_config(user_id, api_slug)




