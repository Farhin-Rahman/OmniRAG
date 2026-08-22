#!/bin/bash

# OmniRAG Frontend Environment Setup Script
# Creates .env file with proper configuration

echo "🚀 Setting up OmniRAG Frontend Environment..."

# Create .env file
cat > .env << 'EOF'
# OmniRAG Frontend Configuration

# Backend API URL (adjust based on your deployment)
VITE_API_BASE_URL=http://localhost:8081

# Application Settings
VITE_APP_MOTTO=Talk With Your Doc
VITE_APP_NAME=OmniRAG

# Environment
VITE_NODE_ENV=development
EOF

echo "✅ Created .env file"
echo ""
echo "📝 Default configuration:"
echo "   API URL: http://localhost:8081"
echo "   App Name: OmniRAG"
echo ""
echo "💡 Edit .env file to customize settings"
echo "🎉 Setup complete!"

