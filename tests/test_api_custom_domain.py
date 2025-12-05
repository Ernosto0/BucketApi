"""
Simple test script for API using custom domain
"""
import requests
import json

# Option 1: Using your custom domain (LOCAL TESTING)
# Make sure to add loopfeedback.dev to your hosts file first!
# Windows: C:\Windows\System32\drivers\etc\hosts
# Add this line: 127.0.0.1 loopfeedback.dev
url = "http://loopfeedback.dev"

# Option 2: Using localhost directly (alternative)
# url = "http://localhost:8001/api/3e6c51d4-0915-4e99-9986-4f0d2204e8c4/api-1764859641148"

# Request data
data = {
    "apikey": "ak_2345e4ae252eb2159115a61f6885b521f472d871c86a72b9dc210f7d65307cc2"
}

print(f"Testing API at: {url}")
print(f"Request data: {json.dumps(data, indent=2)}")
print("-" * 50)

try:
    # Make the request
    response = requests.post(url, json=data, timeout=30)
    
    # Handle the response
    print(f"Status Code: {response.status_code}")
    print(f"Response Headers: {dict(response.headers)}")
    print("-" * 50)
    
    if response.status_code == 200:
        try:
            result = response.json()
            print("✅ Success!")
            print("Response:")
            print(json.dumps(result, indent=2))
        except json.JSONDecodeError:
            print("✅ Success! (Non-JSON response)")
            print("Response Text:")
            print(response.text)
    else:
        print(f"❌ Error: {response.status_code}")
        print("Response Text:")
        print(response.text)
        
except requests.exceptions.SSLError as e:
    print(f"❌ SSL Error: {e}")
    print("Note: If SSL certificate is not yet issued, try using http:// instead of https://")
    print("Or wait a few minutes for the SSL certificate to be provisioned.")
    
except requests.exceptions.ConnectionError as e:
    print(f"❌ Connection Error: {e}")
    print("Make sure:")
    print("1. Your domain DNS is pointing to the correct server")
    print("2. Caddy is running and configured")
    print("3. The domain is verified and active")
    
except requests.exceptions.Timeout:
    print("❌ Request timed out")
    
except Exception as e:
    print(f"❌ Unexpected error: {e}")

