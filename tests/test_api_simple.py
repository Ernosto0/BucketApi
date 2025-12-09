"""
Minimal API test script
"""
import requests
import json

# Your custom domain
url = "https://loopfeedback.dev"

# Request payload
data = {
    "apikey": "ak_2345e4ae252eb2159115a61f6885b521f472d871c86a72b9dc210f7d65307cc2"
}

# Make POST request
response = requests.post(url, json=data)

# Print results
print(f"Status: {response.status_code}")
print(f"Response: {response.json() if response.status_code == 200 else response.text}")




