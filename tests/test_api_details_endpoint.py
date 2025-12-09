"""
Test what the API details endpoint returns
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.file_service import file_service
import json

def test_api_details(user_id: str, api_slug: str):
    """Test what get_api_details returns"""
    
    print(f"Testing API details for: {user_id}/{api_slug}")
    print("="*60)
    
    try:
        details = file_service.get_api_details(user_id, api_slug)
        
        print(f"\n✅ API details retrieved successfully")
        print(f"\nFields in response:")
        for key in details.keys():
            print(f"  - {key}: {type(details[key]).__name__}")
        
        print(f"\n{'='*60}")
        
        if 'database_config' in details:
            print("✅ database_config field is in the response")
            db_config = details['database_config']
            print(f"\nDatabase Config Type: {type(db_config)}")
            print(f"\nDatabase Configuration:")
            print(json.dumps(db_config, indent=2, default=str))
            
            # Check if it's enabled
            if isinstance(db_config, dict):
                if db_config.get('enabled'):
                    print("\n✅ Database is ENABLED")
                else:
                    print("\n⚠️  Database is DISABLED")
        else:
            print("❌ database_config field is NOT in the response")
        
        print(f"{'='*60}\n")
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python test_api_details_endpoint.py USER_ID API_SLUG")
        print("\nExample: python test_api_details_endpoint.py user123 getusersapi")
        sys.exit(1)
    
    user_id = sys.argv[1]
    api_slug = sys.argv[2]
    
    test_api_details(user_id, api_slug)




