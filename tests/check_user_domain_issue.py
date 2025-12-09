
from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

mongodb_url = os.getenv("MONGODB_URL")
db_name = os.getenv("MONGODB_DB_NAME")

if not mongodb_url or not db_name:
    print("Error: MONGODB_URL or MONGODB_DB_NAME not set in .env")
    exit(1)

try:
    client = MongoClient(mongodb_url)
    db = client[db_name]
    
    domain_name = "loopfeedback.dev"
    domain_doc = db.custom_domains.find_one({"domain": domain_name})

    print(f"Checking domain: {domain_name}")
    if domain_doc:
        print(f"Found domain doc: {domain_doc}")
        user_id = domain_doc.get("user_id")
        status = domain_doc.get("status")
        print(f"User ID: {user_id}")
        print(f"Status: {status}")
        
        if status != "active":
            print("WARNING: Domain is not active!")
        
        api_slug = "api-1764859641148"
        api_doc = db.saved_apis.find_one({"user_id": user_id, "api_slug": api_slug})
        if api_doc:
            print(f"API {api_slug} found for user.")
        else:
            print(f"API {api_slug} NOT found for user.")
            
            # List APIs for this user
            apis = list(db.saved_apis.find({"user_id": user_id}))
            print(f"Available APIs for user {user_id}:")
            for api in apis:
                print(f" - {api.get('api_slug')}")
                
    else:
        print("Domain not found in database.")
        
        # List all custom domains to check if it exists under a different name/user
        all_domains = list(db.custom_domains.find())
        if all_domains:
            print("\nExisting custom domains:")
            for d in all_domains:
                print(f" - {d.get('domain')} (Status: {d.get('status')})")
        else:
            print("No custom domains found in database.")
            
except Exception as e:
    print(f"Error: {e}")
