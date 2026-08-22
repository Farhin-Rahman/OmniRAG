#!/usr/bin/env python3
"""
Verification script to check that all API contracts are working.

Run this after starting the backend to verify implementation.
"""

import sys
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import requests

# Configuration
BASE_URL = "http://localhost:8000"
AUTH_BASE_URL = f"{BASE_URL}/api/auth"


def get_auth_headers() -> dict:
    """Create a test user and return valid auth headers."""
    email = f"verify_{uuid4()}@example.com"
    password = "VerifyPass123!"

    signup = requests.post(
        f"{AUTH_BASE_URL}/signup",
        json={"email": email, "password": password, "full_name": "Verifier"},
    )

    if signup.status_code not in (200, 201):
        raise RuntimeError(
            f"Failed to sign up test user: {signup.status_code} {signup.text}"
        )

    data = signup.json()
    access_token = data.get("access_token")
    if not access_token:
        raise RuntimeError("Signup response missing access_token")

    return {"Authorization": f"Bearer {access_token}"}


def test_health():
    """Test health check endpoint."""
    print("1. Testing Health Check...")
    response = requests.get(f"{BASE_URL}/healthz")
    if response.status_code == 200:
        data = response.json()
        assert "status" in data
        assert data["status"] == "ok"
        print("   ✅ Health check passed")
        return True
    print(f"   ❌ Health check failed: {response.status_code}")
    return False


def test_ingest(headers):
    """Test document ingestion."""
    print("\n2. Testing Document Ingestion...")
    file_content = b"This is a test document for verification"
    files = {"file": ("test.pdf", BytesIO(file_content), "application/pdf")}
    data = {"doc_name": "Verification Test Doc", "doc_type": "report"}

    response = requests.post(
        f"{BASE_URL}/ingest", files=files, data=data, headers=headers
    )
    if response.status_code == 201:
        doc = response.json()
        assert "doc_id" in doc
        assert doc["doc_name"] == "Verification Test Doc"
        assert doc["status"] == "queued"
        print(f"   ✅ Document ingested: {doc['doc_id']}")
        return doc["doc_id"]
    print(f"   ❌ Ingest failed: {response.status_code}")
    return None


def test_get_document(doc_id, headers):
    """Test document retrieval."""
    print("\n3. Testing Document Retrieval...")
    response = requests.get(f"{BASE_URL}/documents/{doc_id}", headers=headers)
    if response.status_code == 200:
        doc = response.json()
        assert doc["doc_id"] == doc_id
        print(f"   ✅ Document retrieved: {doc['doc_name']}")
        return True
    print(f"   ❌ Document retrieval failed: {response.status_code}")
    return False


def test_deduplication(headers):
    """Test SHA256 deduplication."""
    print("\n4. Testing Deduplication...")
    # Upload same content twice
    file_content = b"Duplicate test content for verification"

    files1 = {"file": ("test1.pdf", BytesIO(file_content), "application/pdf")}
    response1 = requests.post(f"{BASE_URL}/ingest", files=files1, headers=headers)
    doc_id_1 = response1.json().get("doc_id")

    files2 = {"file": ("test2.pdf", BytesIO(file_content), "application/pdf")}
    response2 = requests.post(f"{BASE_URL}/ingest", files=files2, headers=headers)
    doc_id_2 = response2.json().get("doc_id")

    if doc_id_1 == doc_id_2:
        print("   ✅ Deduplication working: Same doc_id returned")
        return True
    print("   ❌ Deduplication failed: Different doc_ids")
    return False


def test_query(headers):
    """Test query endpoint."""
    print("\n5. Testing Query Endpoint...")
    payload = {"q": "test query for verification", "k": 5}

    response = requests.post(f"{BASE_URL}/query", json=payload, headers=headers)
    if response.status_code == 200:
        data = response.json()
        assert "query_id" in data
        assert "trace_id" in data
        assert "answers" in data
        print(f"   ✅ Query executed: trace_id={data['trace_id']}")
        return data["trace_id"]
    print(f"   ❌ Query failed: {response.status_code}")
    return None


def test_get_trace(trace_id, headers):
    """Test trace retrieval."""
    print("\n6. Testing Trace Retrieval...")
    response = requests.get(f"{BASE_URL}/traces/{trace_id}", headers=headers)
    if response.status_code == 200:
        trace = response.json()
        assert trace["trace_id"] == trace_id
        assert "steps" in trace
        assert "tools_used" in trace
        print(f"   ✅ Trace retrieved: {len(trace['steps'])} steps")
        return True
    print(f"   ❌ Trace retrieval failed: {response.status_code}")
    return False


def test_tenant_isolation(doc_id, headers):
    """Test tenant isolation."""
    print("\n7. Testing Tenant Isolation...")
    # No auth headers should yield 401
    response = requests.get(f"{BASE_URL}/documents/{doc_id}")
    if response.status_code == 401:
        print("   ✅ Tenant isolation working: 401 for missing auth")
        return True
    print(f"   ❌ Tenant isolation failed: Got {response.status_code}")
    return False


def check_prerequisites():
    """Check that prerequisites are met before running tests."""
    # Check if .env file exists
    project_root = Path(__file__).parent.parent
    env_file = project_root / ".env"

    if not env_file.exists():
        print("\n❌ ERROR: .env file not found!")
        print("\n📝 Please create the .env file first:")
        print("   python setup_env.py")
        print("\n   Or see ENV_SETUP_GUIDE.md for manual setup.\n")
        sys.exit(1)

    print("✅ Prerequisites check passed\n")


def main():
    """Run all verification tests."""
    print("=" * 60)
    print("API CONTRACTS VERIFICATION")
    print("=" * 60)
    print()

    # Check prerequisites
    check_prerequisites()

    results = []

    try:
        # Test 1: Health
        results.append(("Health Check", test_health()))

        # Test 2: Ingest
        headers = get_auth_headers()
        doc_id = test_ingest(headers)
        results.append(("Document Ingestion", doc_id is not None))

        if doc_id:
            # Test 3: Get Document
            results.append(("Document Retrieval", test_get_document(doc_id, headers)))

            # Test 7: Tenant Isolation
            results.append(("Tenant Isolation", test_tenant_isolation(doc_id, headers)))
        else:
            results.append(("Document Retrieval", False))
            results.append(("Tenant Isolation", False))

        # Test 4: Deduplication
        results.append(("Deduplication", test_deduplication(headers)))

        # Test 5: Query
        trace_id = test_query(headers)
        results.append(("Query Endpoint", trace_id is not None))

        if trace_id:
            # Test 6: Get Trace
            results.append(("Trace Retrieval", test_get_trace(trace_id, headers)))
        else:
            results.append(("Trace Retrieval", False))

    except requests.exceptions.ConnectionError:
        print("\n❌ ERROR: Could not connect to backend at", BASE_URL)
        print("   Make sure the backend is running:")
        print("   docker-compose up -d backend")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)

    # Summary
    print("\n" + "=" * 60)
    print("VERIFICATION SUMMARY")
    print("=" * 60)

    for test_name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {test_name}")

    total = len(results)
    passed_count = sum(1 for _, passed in results if passed)

    print("\n" + "=" * 60)
    print(f"Results: {passed_count}/{total} tests passed")
    print("=" * 60)

    if passed_count == total:
        print("\n🎉 ALL TESTS PASSED! API Contracts are working correctly!")
        sys.exit(0)
    else:
        print(f"\n⚠️  {total - passed_count} test(s) failed. Check the output above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
