#!/bin/bash

# Agora DRE Crawler Deployment Script

echo "🚀 Starting Agora DRE Crawler Deployment"

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "❌ Docker is not installed. Please install Docker first."
    exit 1
fi

# Build the Docker image
echo "📦 Building Docker image..."
docker build -t agora-dre-crawler .

if [ $? -ne 0 ]; then
    echo "❌ Docker build failed"
    exit 1
fi

echo "✅ Docker image built successfully"

# Create .env file if it doesn't exist
if [ ! -f .env ]; then
    echo "⚠️  .env file not found. Please create it with your Supabase credentials:"
    echo "SUPABASE_URL=\"your-supabase-url\""
    echo "SUPABASE_SERVICE_ROLE_KEY=\"your-service-role-key\""
    echo "CRAWLER_START_YEAR=\"1976\""
    echo "CRAWLER_END_YEAR=\"2024\""
    exit 1
fi

# Run the crawler
echo "🏃 Running the crawler..."
docker run --env-file .env --rm agora-dre-crawler

echo "✅ Crawler execution completed"