#!/bin/bash
set -e
PROJECT_ID="mytt147app004"
KEY_ID="gemini-api-key"
SERVICE_NAME="generativelanguage.googleapis.com"
ENV_FILE=".env"
echo "----------------------------------------------------"
echo "Step 1: Creating project '$PROJECT_ID'..."
echo "----------------------------------------------------"
if gcloud projects describe "$PROJECT_ID" >/dev/null 2>&1; then
    echo "Project '$PROJECT_ID' already exists."
else
    gcloud projects create "$PROJECT_ID" --name="Gemini API Project" --set-as-default
fi
echo ""
echo "----------------------------------------------------"
echo "Step 2: Setting '$PROJECT_ID' as the active project..."
echo "----------------------------------------------------"
gcloud config set project "$PROJECT_ID"
echo ""
echo "----------------------------------------------------"
echo "Step 3: Enabling the Generative Language API..."
echo "----------------------------------------------------"
echo "Note: This may require a billing account to be linked to the project."
gcloud services enable "$SERVICE_NAME"
echo ""
echo "----------------------------------------------------"
echo "Step 4: Creating a restricted API Key for Gemini..."
echo "----------------------------------------------------"
if gcloud services api-keys describe "$KEY_ID" --location=global >/dev/null 2>&1; then
    echo "API Key '$KEY_ID' already exists. Using existing key metadata."
else
    gcloud services api-keys create \
        --key-id="$KEY_ID" \
        --display-name="Gemini API Key" \
        --api-target="service=$SERVICE_NAME" \
        --location=global
fi
echo ""
echo "----------------------------------------------------"
echo "Step 5: Retrieving the API Key string..."
echo "----------------------------------------------------"
MAX_RETRIES=5
RETRY_COUNT=0
API_KEY=""
while [ $RETRY_COUNT -lt $MAX_RETRIES ]; do
    API_KEY=$(gcloud services api-keys get-key-string "$KEY_ID" --location=global --format="value(keyString)" 2>/dev/null || echo "")
    if [ -n "$API_KEY" ]; then
        break
    fi
    echo "Waiting for API Key to be ready... (Attempt $((RETRY_COUNT+1))/$MAX_RETRIES)"
    sleep 3
    RETRY_COUNT=$((RETRY_COUNT+1))
done
if [ -n "$API_KEY" ]; then
    echo "GEMINI_API_KEY=$API_KEY" > "$ENV_FILE"
    echo "===================================================="
    echo " SUCCESS: Project set up and API Key generated!"
    echo "===================================================="
    echo "Project ID: $PROJECT_ID"
    echo "API Key:    $API_KEY"
    echo "Saved to:   $(pwd)/$ENV_FILE"
    echo "===================================================="
    echo "You can now use this key in your Gemini applications."
else
    echo "ERROR: Failed to retrieve the API Key string after creation."
    echo "Please ensure your account has the necessary permissions (e.g., Owner or Editor)."
    exit 1
fi
