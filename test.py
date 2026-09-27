# test_nova_sonic_apis.py
import json
import os

import boto3

# Get credentials from profile
session = boto3.Session(profile_name=os.getenv("AWS_PROFILE"))
credentials = session.get_credentials()

# Set up environment variables
os.environ["AWS_ACCESS_KEY_ID"] = credentials.access_key
os.environ["AWS_SECRET_ACCESS_KEY"] = credentials.secret_key
os.environ["AWS_SESSION_TOKEN"] = credentials.token

# Create a bedrock-runtime client
client = session.client("bedrock-runtime", region_name="us-east-1")

# List all available API operations for the client
print("Available API operations:")
for operation_name in dir(client):
    if not operation_name.startswith("_") and callable(getattr(client, operation_name)):
        print(f"- {operation_name}")

# Try with streaming API
try:
    print("\nTrying with streaming API...")
    response = client.invoke_model_with_response_stream(
        modelId="amazon.nova-sonic-v1:0",
        contentType="application/json",
        accept="application/json",
        body=json.dumps({"prompt": "Hello, Nova Sonic!", "max_tokens": 100}),
    )
    print(f"Response: {response}")
except Exception as e:
    print(f"Error with streaming API: {e}")

# Try with bidirectional streaming if available
try:
    print("\nTrying with bidirectional streaming API...")
    if hasattr(client, "invoke_model_with_bidirectional_stream"):
        response = client.invoke_model_with_bidirectional_stream(
            modelId="amazon.nova-sonic-v1:0",
            contentType="application/json",
            accept="application/json",
        )
        print(f"Response: {response}")
    else:
        print("Bidirectional streaming API not available")
except Exception as e:
    print(f"Error with bidirectional streaming API: {e}")
