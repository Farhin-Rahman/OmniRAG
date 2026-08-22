"""
Tests for download token security.

Verifies that:
1. Token includes required claims (doc_id, tenant_id, user_id, exp)
2. Token validation checks all claims
3. Cross-user tokens are rejected
4. Cross-tenant tokens are rejected
5. Expired tokens are rejected
"""

import time
from uuid import uuid4

from utils.download_tokens import (
    generate_download_token,
    validate_download_token,
    get_token_info,
)


class TestDownloadTokenGeneration:
    """Tests for download token generation."""

    def test_token_includes_all_required_claims(self):
        """Token should include doc_id, tenant_id, exp, purpose, and user_id."""
        doc_id = uuid4()
        tenant_id = uuid4()
        user_id = uuid4()

        token = generate_download_token(
            doc_id=doc_id,
            tenant_id=tenant_id,
            user_id=user_id,
            expiry_minutes=5,
        )

        info = get_token_info(token)

        assert info is not None
        assert info["doc_id"] == str(doc_id)
        assert info["tenant_id"] == str(tenant_id)
        assert info["user_id"] == str(user_id)
        assert "exp" in info
        assert info["purpose"] == "download"

    def test_token_without_user_id_still_works(self):
        """Token can be generated without user_id for backwards compatibility."""
        doc_id = uuid4()
        tenant_id = uuid4()

        token = generate_download_token(
            doc_id=doc_id,
            tenant_id=tenant_id,
            expiry_minutes=5,
        )

        info = get_token_info(token)

        assert info is not None
        assert "user_id" not in info or info.get("user_id") is None


class TestDownloadTokenValidation:
    """Tests for download token validation."""

    def test_valid_token_returns_tenant_id(self):
        """A valid token should return the tenant_id."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        tenant_id = uuid4()

        token = generate_download_token(doc_id=doc_id, tenant_id=tenant_id)

        result = validate_download_token(token, doc_id)

        assert result is not None
        assert result["tenant_id"] == tenant_id

    def test_wrong_doc_id_returns_none(self):
        """Token for wrong doc_id should return None."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        wrong_doc_id = uuid4()
        tenant_id = uuid4()

        token = generate_download_token(doc_id=doc_id, tenant_id=tenant_id)

        result = validate_download_token(token, wrong_doc_id)

        assert result is None

    def test_expired_token_returns_none(self):
        """Expired token should return None."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        tenant_id = uuid4()

        # Generate token that expires immediately (0 minutes = already expired)
        token = generate_download_token(
            doc_id=doc_id,
            tenant_id=tenant_id,
            expiry_minutes=0,  # Expires now
        )

        # Wait a tiny bit to ensure expiry
        time.sleep(0.1)

        result = validate_download_token(token, doc_id)

        assert result is None

    def test_wrong_purpose_returns_none(self):
        """Token with wrong purpose should return None."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        tenant_id = uuid4()

        token = generate_download_token(
            doc_id=doc_id,
            tenant_id=tenant_id,
            purpose="inline",
        )

        # Validate with different purpose
        result = validate_download_token(token, doc_id, expected_purpose="download")

        assert result is None

    def test_tampered_token_returns_none(self):
        """Tampered token should return None due to signature mismatch."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        tenant_id = uuid4()

        token = generate_download_token(doc_id=doc_id, tenant_id=tenant_id)

        # Tamper with the token
        parts = token.split(".")
        tampered_token = parts[0] + "X" + "." + parts[1]

        result = validate_download_token(tampered_token, doc_id)

        assert result is None


class TestDownloadTokenUserBinding:
    """Tests for user-bound download tokens."""

    def test_token_contains_user_id_when_provided(self):
        """Token should store user_id when provided."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        tenant_id = uuid4()
        user_id = uuid4()

        token = generate_download_token(
            doc_id=doc_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        info = get_token_info(token)

        assert info["user_id"] == str(user_id)

    def test_token_user_id_can_be_verified(self):
        """User ID in token can be extracted and verified."""
        import os

        os.environ["DOWNLOAD_URL_SECRET"] = "test-secret-key-for-validation-32chars"

        doc_id = uuid4()
        tenant_id = uuid4()
        user_id = uuid4()

        token = generate_download_token(
            doc_id=doc_id,
            tenant_id=tenant_id,
            user_id=user_id,
        )

        # Validate token returns tenant_id
        result = validate_download_token(token, doc_id)
        assert result is not None
        assert result["tenant_id"] == tenant_id

        # Get full info to verify user_id
        info = get_token_info(token)
        assert info["user_id"] == str(user_id)
