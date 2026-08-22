# ============================================================================
# OMNIRAG EVALUATION DEMO - PowerShell Script
# ============================================================================
# This script runs the complete evaluation pipeline for demo purposes.
#
# Prerequisites:
#   1. Docker Desktop running
#   2. Backend services started: docker compose up -d
#   3. Documents ingested via /ingest/batch
#   4. Python venv with mlflow installed
#
# Usage:
#   .\eval\tools\run_demo.ps1
# ============================================================================

param(
    [string]$Dataset = "eval/datasets/demo.jsonl",
    [string]$Experiment = "omnirag_demo",
    [switch]$SkipHealthCheck,
    [switch]$OpenMLflow
)

$ErrorActionPreference = "Stop"

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  OMNIRAG RAG EVALUATION PIPELINE" -ForegroundColor Cyan
Write-Host "============================================" -ForegroundColor Cyan
Write-Host ""

# Set environment variables
$env:EVAL_BACKEND_URL = "http://localhost:8081"
$env:MLFLOW_TRACKING_URI = "file:./mlruns"
$env:EVAL_ENABLE_LLM_EVAL = "false"

Write-Host "[1/5] Environment Variables Set:" -ForegroundColor Yellow
Write-Host "  EVAL_BACKEND_URL = $env:EVAL_BACKEND_URL"
Write-Host "  MLFLOW_TRACKING_URI = $env:MLFLOW_TRACKING_URI"
Write-Host "  EVAL_ENABLE_LLM_EVAL = $env:EVAL_ENABLE_LLM_EVAL"
Write-Host "  EVAL_ACCESS_TOKEN = (set via environment)" -ForegroundColor DarkGray
Write-Host ""

# Require access token for authenticated API calls
if (-not $env:EVAL_ACCESS_TOKEN) {
    Write-Host "✗ EVAL_ACCESS_TOKEN is not set." -ForegroundColor Red
    Write-Host "  Set a JWT access token from /api/auth/signin before running this demo." -ForegroundColor Yellow
    exit 1
}

# Health check
if (-not $SkipHealthCheck) {
    Write-Host "[2/5] Checking backend health..." -ForegroundColor Yellow
    try {
        $health = Invoke-RestMethod -Uri "$env:EVAL_BACKEND_URL/healthz" -Method GET -TimeoutSec 10
        if ($health.status -eq "ok") {
            Write-Host "  ✓ Backend is healthy" -ForegroundColor Green
        } else {
            Write-Host "  ✗ Backend returned unexpected status: $($health.status)" -ForegroundColor Red
            exit 1
        }
    } catch {
        Write-Host "  ✗ Backend health check failed: $_" -ForegroundColor Red
        Write-Host "  Make sure backend is running: docker compose up -d" -ForegroundColor Yellow
        exit 1
    }
} else {
    Write-Host "[2/5] Skipping health check" -ForegroundColor Yellow
}
Write-Host ""

# Verify dataset exists
Write-Host "[3/5] Verifying dataset..." -ForegroundColor Yellow
if (Test-Path $Dataset) {
    $lineCount = (Get-Content $Dataset | Measure-Object -Line).Lines
    Write-Host "  ✓ Found dataset: $Dataset ($lineCount test cases)" -ForegroundColor Green
} else {
    Write-Host "  ✗ Dataset not found: $Dataset" -ForegroundColor Red
    Write-Host "  Run: python eval/tools/make_demo_dataset.py" -ForegroundColor Yellow
    exit 1
}
Write-Host ""

# Run evaluation
Write-Host "[4/5] Running evaluation..." -ForegroundColor Yellow
Write-Host "  Command: python -m eval.cli --dataset $Dataset --experiment $Experiment --no-llm-eval"
Write-Host ""

python -m eval.cli --dataset $Dataset --experiment $Experiment --no-llm-eval

if ($LASTEXITCODE -ne 0) {
    Write-Host ""
    Write-Host "  ✗ Evaluation failed with exit code $LASTEXITCODE" -ForegroundColor Red
    exit $LASTEXITCODE
}
Write-Host ""

# Open MLflow UI
Write-Host "[5/5] Opening MLflow UI..." -ForegroundColor Yellow
Write-Host "  URL: http://localhost:5000"
Write-Host ""

if ($OpenMLflow) {
    Start-Process "http://localhost:5000"
    mlflow ui --backend-store-uri file:./mlruns --port 5000
} else {
    Write-Host "  To view results, run:" -ForegroundColor Cyan
    Write-Host "    mlflow ui --backend-store-uri file:./mlruns --port 5000" -ForegroundColor White
    Write-Host "  Then open: http://localhost:5000" -ForegroundColor White
}

Write-Host ""
Write-Host "============================================" -ForegroundColor Cyan
Write-Host "  EVALUATION COMPLETE" -ForegroundColor Green
Write-Host "============================================" -ForegroundColor Cyan
