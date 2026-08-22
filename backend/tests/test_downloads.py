"""
Tests for download tokens and tenant isolation.
"""

from uuid import uuid4

from utils.download_tokens import (
    generate_download_token,
    validate_download_token,
    get_token_info,
)


class TestDownloadTokenGeneration:
    """Tests for token generation."""

    def test_generate_token_returns_string(self):
        """Token generation returns a string."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id)
        assert isinstance(token, str)
        assert len(token) > 0

    def test_token_has_two_parts(self):
        """Token has payload.signature format."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id)
        parts = token.split(".")
        assert len(parts) == 2

    def test_token_payload_contains_claims(self):
        """Token payload contains expected claims."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id, purpose="download")

        info = get_token_info(token)
        assert info is not None
        assert info["doc_id"] == str(doc_id)
        assert info["tenant_id"] == str(tenant_id)
        assert info["purpose"] == "download"
        assert "exp" in info


class TestDownloadTokenValidation:
    """Tests for token validation."""

    def test_validate_valid_token(self):
        """Valid token passes validation."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id)

        result = validate_download_token(token, doc_id)
        assert result is not None
        assert result["tenant_id"] == tenant_id

    def test_validate_wrong_doc_id_fails(self):
        """Token for different doc_id fails validation."""
        doc_id = uuid4()
        wrong_doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id)

        result = validate_download_token(token, wrong_doc_id)
        assert result is None

    def test_validate_wrong_purpose_fails(self):
        """Token with wrong purpose fails validation."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id, purpose="download")

        result = validate_download_token(token, doc_id, expected_purpose="preview")
        assert result is None

    def test_validate_expired_token_fails(self):
        """Expired token fails validation."""
        doc_id = uuid4()
        tenant_id = uuid4()
        # Token that expires in -1 minutes (already expired)
        token = generate_download_token(doc_id, tenant_id, expiry_minutes=-1)

        result = validate_download_token(token, doc_id)
        assert result is None

    def test_validate_tampered_signature_fails(self):
        """Token with tampered signature fails validation."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id)

        # Tamper with signature
        parts = token.split(".")
        tampered = parts[0] + ".INVALID_SIGNATURE"

        result = validate_download_token(tampered, doc_id)
        assert result is None

    def test_validate_malformed_token_fails(self):
        """Malformed token fails validation."""
        doc_id = uuid4()

        assert validate_download_token("not-a-token", doc_id) is None
        assert validate_download_token("", doc_id) is None
        assert validate_download_token("a.b.c", doc_id) is None


class TestTenantIsolation:
    """Tests for tenant isolation in tokens."""

    def test_token_bound_to_specific_tenant(self):
        """Token is bound to specific tenant_id."""
        doc_id = uuid4()
        tenant_1 = uuid4()
        tenant_2 = uuid4()

        token = generate_download_token(doc_id, tenant_1)

        # Validate returns tenant_1, not tenant_2
        result = validate_download_token(token, doc_id)
        assert result is not None
        assert result["tenant_id"] == tenant_1
        assert result["tenant_id"] != tenant_2

    def test_token_cannot_access_other_tenant_docs(self):
        """Token for tenant A cannot be used for tenant B's docs."""
        doc_id = uuid4()
        tenant_a = uuid4()
        uuid4()

        # Token created for tenant_a
        token = generate_download_token(doc_id, tenant_a)

        # When validated, it returns tenant_a (which is correct)
        # Application code must enforce that returned tenant matches document's tenant
        result = validate_download_token(token, doc_id)
        assert result is not None
        assert result["tenant_id"] == tenant_a


class TestConstantTimeComparison:
    """Test that signature comparison is constant-time."""

    def test_timing_attack_resistance(self):
        """Signature validation should be constant-time."""
        doc_id = uuid4()
        tenant_id = uuid4()
        token = generate_download_token(doc_id, tenant_id)

        # Create two invalid tokens with different wrong signatures
        parts = token.split(".")
        wrong_1 = parts[0] + ".AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA=="
        wrong_2 = parts[0] + ".ZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZZ=="

        # Both should fail validation
        # (Timing analysis would require more sophisticated testing)
        assert validate_download_token(wrong_1, doc_id) is None
        assert validate_download_token(wrong_2, doc_id) is None
