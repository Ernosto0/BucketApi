"""
Quick script to check domains in the database
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.mongodb import mongodb
from pprint import pprint

def check_domains():
    """Check all domains in the database"""
    print("\n=== Checking Custom Domains ===\n")
    
    # Get all domains
    domains = list(mongodb.custom_domains.find())
    
    if not domains:
        print("❌ No domains found in database")
        return
    
    print(f"✅ Found {len(domains)} domain(s)\n")
    
    for i, domain in enumerate(domains, 1):
        print(f"Domain #{i}:")
        print(f"  ID: {domain.get('_id')}")
        print(f"  Domain: {domain.get('domain')}")
        print(f"  User ID: {domain.get('user_id')}")
        print(f"  API Slug: {domain.get('api_slug')}")
        print(f"  Status: {domain.get('status')}")
        print(f"  Created: {domain.get('created_at')}")
        print(f"  Verified: {domain.get('verified_at')}")
        print()

if __name__ == "__main__":
    check_domains()

