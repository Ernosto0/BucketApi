"""
Script to regenerate documentation for a specific API.
This script deletes the current documentation and creates a new one.
ONLY FOR TESTING PURPOSES
Usage:
    python regenerate_documentation.py api-1763579496673
"""
import sys
import asyncio
import json
import os
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from app.services.mongodb import init_database, mongodb
from app.services.file_service import file_service
from app.services.openai_service import openai_service
from app.config import settings

async def regenerate_documentation(api_slug: str):
    """
    Regenerate documentation for a specific API.
    
    Args:
        api_slug: The API slug (e.g., 'api-1763579496673')
    """
    print(f"🔍 Looking for API with slug: {api_slug}")
    
    # Find the API in the database
    db_api = mongodb.saved_apis.find_one({"api_slug": api_slug})
    
    if not db_api:
        print(f"❌ API not found with slug: {api_slug}")
        print("💡 Searching in all APIs...")
        # List all APIs to help debug
        all_apis = list(mongodb.saved_apis.find({}, {"api_slug": 1, "user_id": 1, "api_name": 1}))
        if all_apis:
            print(f"Found {len(all_apis)} APIs in database:")
            for api in all_apis[:10]:  # Show first 10
                print(f"  - {api.get('api_slug')} (user: {api.get('user_id')}, name: {api.get('api_name')})")
        return False
    
    user_id = db_api["user_id"]
    api_name = db_api.get("api_name", f"API {api_slug}")
    prompt = db_api.get("prompt", "")
    
    print(f"✅ Found API:")
    print(f"   User ID: {user_id}")
    print(f"   API Name: {api_name}")
    print(f"   Prompt: {prompt[:100]}..." if len(prompt) > 100 else f"   Prompt: {prompt}")
    
    # Check if API code exists
    try:
        code = file_service.load_api_code(user_id, api_slug)
        print(f"✅ API code loaded ({len(code)} characters)")
    except Exception as e:
        print(f"❌ Failed to load API code: {e}")
        return False
    
    # Delete current documentation (clear documentation fields)
    print(f"\n🗑️  Clearing current documentation...")
    try:
        mongodb.saved_apis.update_one(
            {"user_id": user_id, "api_slug": api_slug},
            {"$set": {
                "documentation": "",
                "curl_example": "",
                "openapi_spec": None
            }}
        )
        print("✅ Current documentation cleared")
    except Exception as e:
        print(f"⚠️  Warning: Failed to clear documentation: {e}")
        # Continue anyway
    
    # Generate new documentation
    print(f"\n📚 Generating new documentation...")
    try:
        documentation, openapi_spec, curl_example = await openai_service.generate_documentation(
            code=code,
            prompt=prompt,
            user_id=user_id,
            api_key_id=None,  # No API key for script execution
            api_slug=api_slug,
            api_name=api_name
        )
        
        print(f"✅ Documentation generated successfully")
        print(f"   Documentation length: {len(documentation)} characters")
        print(f"   OpenAPI spec: {'Generated' if openapi_spec else 'Not generated'}")
        print(f"   Curl example: {'Generated' if curl_example else 'Not generated'}")
        
        # Build endpoint URL
        endpoint_url = f"{settings.API_PREFIX}/{user_id}/{api_slug}"
        
        # Update curl example with actual endpoint
        if "your-endpoint-url" in curl_example:
            curl_example = curl_example.replace("your-endpoint-url", endpoint_url)
        
        # Save new documentation to database
        print(f"\n💾 Saving new documentation to database...")
        mongodb.saved_apis.update_one(
            {"user_id": user_id, "api_slug": api_slug},
            {"$set": {
                "documentation": documentation,
                "curl_example": curl_example,
                "openapi_spec": json.dumps(openapi_spec) if openapi_spec else None,
                "endpoint_url": endpoint_url
            }}
        )
        
        print("✅ Documentation saved successfully!")
        print(f"\n📋 Summary:")
        print(f"   API Slug: {api_slug}")
        print(f"   User ID: {user_id}")
        print(f"   Endpoint URL: {endpoint_url}")
        print(f"   Documentation preview: {documentation[:200]}...")
        
        return True
        
    except Exception as e:
        print(f"❌ Failed to generate documentation: {e}")
        import traceback
        traceback.print_exc()
        return False

async def main():
    """Main function"""
    if len(sys.argv) < 2:
        print("Usage: python regenerate_documentation.py <api_slug>")
        print("Example: python regenerate_documentation.py api-1763579496673")
        sys.exit(1)
    
    api_slug = sys.argv[1]
    
    print("=" * 60)
    print("Documentation Regeneration Script")
    print("=" * 60)
    
    # Initialize database connection
    print("\n🔌 Connecting to MongoDB...")
    try:
        init_database()
        print("✅ Connected to MongoDB")
    except Exception as e:
        print(f"❌ Failed to connect to MongoDB: {e}")
        sys.exit(1)
    
    try:
        # Regenerate documentation
        success = await regenerate_documentation(api_slug)
        
        if success:
            print("\n" + "=" * 60)
            print("✅ Documentation regeneration completed successfully!")
            print("=" * 60)
            sys.exit(0)
        else:
            print("\n" + "=" * 60)
            print("❌ Documentation regeneration failed!")
            print("=" * 60)
            sys.exit(1)
            
    finally:
        # Close database connection
        mongodb.close()

if __name__ == "__main__":
    asyncio.run(main())

