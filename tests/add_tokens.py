"""
Script to add Internal Tokens to a user's account
Usage: python add_tokens.py
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
TOKEN_AMOUNT = 100000  # Number of tokens to add (adjust as needed)
TOKEN_TYPE = "api_execution"  # Type: 'api_execution' or 'api_generation'
SOURCE = "manual_allocation"  # Source: 'purchase', 'monthly_allocation', 'bonus', 'manual_allocation'

def add_tokens_to_user():
    """Add internal tokens to the specified user account"""
    
    # Get MongoDB connection details from environment
    mongodb_url = os.getenv("MONGODB_URL")
    mongodb_db_name = os.getenv("MONGODB_DB_NAME")
    
    if not mongodb_url or not mongodb_db_name:
        print("❌ Error: MONGODB_URL or MONGODB_DB_NAME not found in environment variables")
        print("   Please ensure your .env file is properly configured")
        return False
    
    try:
        # Connect to MongoDB
        print(f"🔌 Connecting to MongoDB...")
        client = MongoClient(mongodb_url)
        db = client[mongodb_db_name]
        
        # Test connection
        client.admin.command('ping')
        print(f"✅ Connected to MongoDB database: {mongodb_db_name}")
        
        # Find user by email
        print(f"\n🔍 Looking for user: {USER_EMAIL}")
        user = db.users.find_one({"email": USER_EMAIL})
        
        if not user:
            print(f"❌ Error: User with email '{USER_EMAIL}' not found")
            return False
        
        user_id = user["_id"]
        print(f"✅ Found user: {user.get('name', 'Unknown')} (ID: {user_id})")
        print(f"   Subscription tier: {user.get('subscription_tier', 'free')}")
        
        # Check current token balance
        print(f"\n📊 Checking current token balance...")
        current_tokens = list(db.internal_tokens.find({
            "user_id": user_id,
            "is_used": False
        }))
        
        current_balance = sum(token["amount"] for token in current_tokens)
        print(f"   Current balance: {current_balance:,} tokens")
        
        # Create new token allocation
        print(f"\n💰 Adding {TOKEN_AMOUNT:,} tokens...")
        
        token_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        # Set expiration to end of next month
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
        
        # Insert token allocation
        db.internal_tokens.insert_one(new_token)
        
        # Verify the new balance
        new_tokens = list(db.internal_tokens.find({
            "user_id": user_id,
            "is_used": False
        }))
        
        new_balance = sum(token["amount"] for token in new_tokens)
        
        print(f"✅ Successfully added {TOKEN_AMOUNT:,} tokens!")
        print(f"\n📈 Token Balance Summary:")
        print(f"   Previous balance: {current_balance:,} tokens")
        print(f"   Added:           {TOKEN_AMOUNT:,} tokens")
        print(f"   New balance:     {new_balance:,} tokens")
        print(f"   Token type:      {TOKEN_TYPE}")
        print(f"   Source:          {SOURCE}")
        print(f"   Expires:         {expires_at.strftime('%Y-%m-%d')}")
        
        # Close connection
        client.close()
        print(f"\n✅ Script completed successfully!")
        return True
        
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("  Internal Token Addition Script")
    print("=" * 60)
    print(f"\nUser:   {USER_EMAIL}")
    print(f"Amount: {TOKEN_AMOUNT:,} tokens")
    print(f"Type:   {TOKEN_TYPE}")
    print(f"Source: {SOURCE}")
    print("\n" + "=" * 60)
    
    # Confirm before proceeding
    response = input("\nDo you want to proceed? (yes/no): ").strip().lower()
    
    if response in ['yes', 'y']:
        print("\n🚀 Starting token addition...")
        success = add_tokens_to_user()
        sys.exit(0 if success else 1)
    else:
        print("\n❌ Operation cancelled by user")
        sys.exit(1)
