"""
Quick Script to add Internal Tokens (No confirmation required)
Usage: python add_tokens_quick.py [amount]
Example: python add_tokens_quick.py 50000
"""
import os
import sys
import uuid
from datetime import datetime, timedelta
from pymongo import MongoClient
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
USER_EMAIL = "ernosto20.03@gmail.com"
TOKEN_TYPE = "api_execution"  # Type: 'api_execution' or 'api_generation'
SOURCE = "manual_allocation"  # Source: 'purchase', 'monthly_allocation', 'bonus', 'manual_allocation'

# Get amount from command line or use default
TOKEN_AMOUNT = int(sys.argv[1]) if len(sys.argv) > 1 else 50000

def add_tokens():
    """Add tokens without confirmation"""
    mongodb_url = os.getenv("MONGODB_URL")
    mongodb_db_name = os.getenv("MONGODB_DB_NAME")
    
    if not mongodb_url or not mongodb_db_name:
        print("❌ Error: MongoDB environment variables not configured")
        return False
    
    try:
        # Connect
        client = MongoClient(mongodb_url)
        db = client[mongodb_db_name]
        client.admin.command('ping')
        
        # Find user
        user = db.users.find_one({"email": USER_EMAIL})
        if not user:
            print(f"❌ User not found: {USER_EMAIL}")
            return False
        
        user_id = user["_id"]
        
        # Check current balance
        current_tokens = list(db.internal_tokens.find({"user_id": user_id, "is_used": False}))
        current_balance = sum(token["amount"] for token in current_tokens)
        
        # Create token allocation
        token_id = str(uuid.uuid4())
        now = datetime.utcnow()
        next_month = now.replace(day=1) + timedelta(days=32)
        expires_at = next_month.replace(day=1) - timedelta(days=1)
        
        new_token = {
            "_id": token_id,
            "user_id": user_id,
            "api_key_id": None,
            "token_type": TOKEN_TYPE,
            "amount": TOKEN_AMOUNT,
            "source": SOURCE,
            "expires_at": expires_at,
            "created_at": now,
            "is_used": False,
            "used_at": None
        }
        
        db.internal_tokens.insert_one(new_token)
        
        # Get new balance
        new_tokens = list(db.internal_tokens.find({"user_id": user_id, "is_used": False}))
        new_balance = sum(token["amount"] for token in new_tokens)
        
        print(f"✅ Added {TOKEN_AMOUNT:,} tokens")
        print(f"   Before: {current_balance:,} → After: {new_balance:,}")
        print(f"   Expires: {expires_at.strftime('%Y-%m-%d')}")
        
        client.close()
        return True
        
    except Exception as e:
        print(f"❌ Error: {str(e)}")
        return False

if __name__ == "__main__":
    print(f"💰 Adding {TOKEN_AMOUNT:,} tokens to {USER_EMAIL}...")
    success = add_tokens()
    sys.exit(0 if success else 1)
