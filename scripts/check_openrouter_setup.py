
import sys
import os
import requests
import time
from pathlib import Path

# Add backend to python path
backend_path = Path(__file__).parent.parent / "backend"
sys.path.append(str(backend_path))

try:
    from config.settings import settings
except ImportError as e:
    print(f"Error importing settings: {e}")
    # Fallback to direct env var check if import fails
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / ".env")
    class MockSettings:
        llm_timeout = int(os.getenv("LLM_TIMEOUT", "30"))
        openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        # Default model for test
        openrouter_model = "meta-llama/llama-3.3-70b-instruct"
    settings = MockSettings()


def log(msg):
    print(msg)
    with open("check_output.txt", "a", encoding="utf-8") as f:
        f.write(msg + "\n")

def check_openrouter():
    # Clear previous log
    with open("check_output.txt", "w", encoding="utf-8") as f:
        f.write("Starting check...\n")

    log("=== Checking OpenRouter Configuration ===")
    
    # Check 1: Timeout Setting
    log(f"LLM Timeout Setting: {settings.llm_timeout} seconds")
    
    # Check 2: API Key Presence
    api_key = settings.openrouter_api_key
    if not api_key:
        log("❌ OPENROUTER_API_KEY is NOT set in configuration/env!")
        return
    
    masked_key = f"{api_key[:4]}...{api_key[-4:]}" if len(api_key) > 8 else "***"
    log(f"OPENROUTER_API_KEY is present: {masked_key}")
    
    # Check 3: Connectivity
    log("\n=== Testing OpenRouter Connectivity ===")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
    
    # Simple model list or lightweight chat completion
    url = "https://openrouter.ai/api/v1/params"  # A lightweight endpoint to check auth
    # Or just try a very cheap/simple generation
    url = "https://openrouter.ai/api/v1/chat/completions"
    data = {
        "model": settings.openrouter_model or "meta-llama/llama-3.3-70b-instruct",
        "messages": [{"role": "user", "content": "Hi"}],
        "max_tokens": 5
    }
    
    log(f"Sending test request to {url}...")
    start_time = time.time()
    try:
        response = requests.post(url, headers=headers, json=data, timeout=settings.llm_timeout)
        duration = time.time() - start_time
        
        log(f"Request duration: {duration:.2f} seconds")
        log(f"Status Code: {response.status_code}")
        
        if response.status_code == 200:
            log("✅ OpenRouter request SUCCESSFUL")
            log(f"Response: {response.text[:100]}...")
        elif response.status_code == 401:
             log("❌ OpenRouter Authentication FAILED (401). Check your API Key.")
        elif response.status_code == 402:
             log("❌ OpenRouter Quota Exceeded (402). You need to add credits.")
        else:
             log(f"❌ OpenRouter request FAILED with status {response.status_code}")
             log(f"Body: {response.text}")

    except requests.exceptions.Timeout:
        log(f"❌ Request TIMED OUT after {settings.llm_timeout} seconds.")
        log("This confirms the timeout hypothesis.")
    except Exception as e:
        log(f"❌ Request FAILED with error: {e}")


if __name__ == "__main__":
    check_openrouter()
