import requests

# Test the health check endpoint
url = "http://localhost:8000/api/v1/flow/flow-endpoint"
headers = {"Content-Type": "application/json"}
data = {"action": "ping"}

print("Testing local endpoint...")
try:
    response = requests.post(url, headers=headers, json=data)
    print(f"Status: {response.status_code}")
    print(f"Response: {response.json()}")
    print("✅ Local endpoint works!")
except Exception as e:
    print(f"❌ Error: {e}")
    print("Make sure the server is running first!")

input("Press Enter to exit...")