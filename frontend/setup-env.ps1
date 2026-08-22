# OmniRAG Frontend Environment Setup Script (PowerShell)
# Creates .env file with proper configuration

Write-Host "🚀 Setting up OmniRAG Frontend Environment..." -ForegroundColor Green

$envContent = @"
# OmniRAG Frontend Configuration

# Backend API URL (adjust based on your deployment)
VITE_API_BASE_URL=http://localhost:8081

# Application Settings
VITE_APP_MOTTO=Talk With Your Doc
VITE_APP_NAME=OmniRAG

# Environment
VITE_NODE_ENV=development
"@

# Create .env file
Set-Content -Path ".env" -Value $envContent

Write-Host "✅ Created .env file" -ForegroundColor Green
Write-Host ""
Write-Host "📝 Default configuration:" -ForegroundColor Cyan
Write-Host "   API URL: http://localhost:8081"
Write-Host "   App Name: OmniRAG"
Write-Host ""
Write-Host "💡 Edit .env file to customize settings" -ForegroundColor Yellow
Write-Host "🎉 Setup complete!" -ForegroundColor Green

