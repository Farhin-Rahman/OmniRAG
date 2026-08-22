"""
MLflow UI Smoke Test.

Opens the MLflow UI, verifies it loads, and takes a screenshot.

Usage:
    python eval/tools/ui_smoke_mlflow.py [--url http://127.0.0.1:5000] [--output mlflow_ui_home.png]
"""

import argparse
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("ERROR: playwright not installed. Run: pip install playwright && python -m playwright install chromium")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="MLflow UI smoke test")
    parser.add_argument("--url", default="http://127.0.0.1:5000", help="MLflow UI URL")
    parser.add_argument("--output", default="mlflow_ui_home.png", help="Screenshot output path")
    args = parser.parse_args()
    
    print(f"Opening MLflow UI at {args.url}")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        try:
            page.goto(args.url, wait_until="networkidle", timeout=30000)
            
            # Wait for content to load
            page.wait_for_timeout(2000)
            
            # Verify MLflow is in the page
            content = page.content()
            title = page.title()
            
            if "MLflow" not in content and "MLflow" not in title:
                print(f"ERROR: 'MLflow' not found in page content or title")
                print(f"Title: {title}")
                browser.close()
                return 1
            
            print(f"✓ Page title: {title}")
            print(f"✓ MLflow UI loaded successfully")
            
            # Take screenshot
            page.screenshot(path=args.output, full_page=True)
            print(f"✓ Screenshot saved: {args.output}")
            
            browser.close()
            return 0
            
        except Exception as e:
            print(f"ERROR: {e}")
            browser.close()
            return 1


if __name__ == "__main__":
    sys.exit(main())
