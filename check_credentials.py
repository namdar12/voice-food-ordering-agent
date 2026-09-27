import os
import sys
from datetime import datetime

import boto3

print("--- Starting Boto3 Credential Verification ---")

profile_name = os.getenv("AWS_PROFILE")  # optional: an AWS CLI/SSO profile name
region_name = os.getenv(
    "AWS_REGION", "us-east-1"
)  # The region where Bedrock is expected to be accessed

try:
    print(f"Attempting to create boto3 session with profile: {profile_name}")
    session = (
        boto3.Session(profile_name=profile_name)
        if profile_name
        else boto3.Session(
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            aws_session_token=os.getenv("AWS_SESSION_TOKEN"),
            region_name=region_name,
        )
    )

    print("Attempting to get credentials...")
    credentials = session.get_credentials()

    if credentials:
        print("\nCredentials retrieved successfully:")
        print(
            f"  Access Key ID: {credentials.access_key[:4]}...{credentials.access_key[-4:]}"
        )  # Show partial for security
        if credentials.token:
            print(f"  Session Token present (indicates temporary credentials).")
            # The 'token_expiration' attribute might not be directly available on DeferredRefreshableCredentials.
            # Let's try to check 'is_expired()' if that exists.
            if hasattr(credentials, "is_expired"):
                print(
                    f"  Credentials Expired (from is_expired()): {credentials.is_expired()}"
                )
            else:
                print("  Cannot check if credentials are expired via 'is_expired()'.")
        else:
            print(f"  No Session Token found (might be permanent keys or no SSO).")
            if hasattr(credentials, "is_expired"):
                print(
                    f"  Credentials Expired (from is_expired()): {credentials.is_expired()}"
                )

    else:
        print("ERROR: No AWS credentials found for the specified profile.")
        print(
            "Please ensure 'aws sso login --profile YOUR_PROFILE_NAME' was run successfully."
        )
        sys.exit(1)

    # Verify Identity with STS
    print("\nAttempting to verify AWS identity with sts:GetCallerIdentity...")
    # Use the same region for STS for consistency with your Bedrock calls
    sts_client = session.client("sts", region_name=region_name)
    caller_identity = sts_client.get_caller_identity()
    print("  sts:GetCallerIdentity successful:")
    print(f"    Account: {caller_identity['Account']}")
    print(f"    UserId: {caller_identity['UserId']}")
    print(f"    Arn: {caller_identity['Arn']}")

    # Test Bedrock access by listing Foundation Models
    print(f"\nAttempting to list Bedrock Foundation Models in region: {region_name}...")
    # Use the 'bedrock' client (not 'bedrock-runtime') as it's a lighter call
    # for permissions validation that doesn't require model invocation.
    bedrock_client = session.client("bedrock", region_name=region_name)
    try:
        response = bedrock_client.list_foundation_models()
        print(
            f"  SUCCESS: Successfully listed {len(response.get('modelSummaries', []))} Bedrock models."
        )
    except Exception as e:
        print(
            f"ERROR: Failed to list Bedrock models. This might indicate permissions issues or region problems."
        )
        print(f"  Specific Bedrock error: {type(e).__name__}: {e}")
        sys.exit(1)

    print("\n--- Boto3 Credential Verification Complete and Successful ---")

except Exception as e:
    print(f"\nCRITICAL ERROR: An unexpected error occurred during verification:")
    print(f"  Error Type: {type(e).__name__}")
    print(f"  Error Message: {e}")
    sys.exit(1)
