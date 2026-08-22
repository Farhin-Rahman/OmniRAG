"""
ACL and RBAC Tests for Step 2.

Tests run without Docker using SQLite in-memory and mocked dependencies.

Test categories:
1. Tenant isolation - users can only access their tenant's data
2. ACL behavior - documents with no ACL are public within tenant, with ACL are restricted
3. RBAC - admin can manage, viewer cannot delete
4. Query non-leak - restricted docs don't appear in query results
"""

import os
import sys
from pathlib import Path
from uuid import UUID, uuid4

import pytest

# Setup path
backend_dir = Path(__file__).parent.parent
sys.path.insert(0, str(backend_dir))

# Set test environment
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("POSTGRES_URL", "sqlite:///:memory:")
os.environ.setdefault("DOWNLOAD_URL_SECRET", "test-secret-key")
os.environ.setdefault("JWT_SECRET_KEY", "test-jwt-secret")


# =============================================================================
# Fixtures
# =============================================================================


class FakeUser:
    """Fake user for testing."""

    def __init__(
        self,
        user_id: UUID = None,
        email: str = "test@example.com",
        role: str = "member",
        tenant_id: UUID = None,
    ):
        self.user_id = user_id or uuid4()
        self.email = email
        self.role = role
        self.tenant_id = tenant_id or uuid4()
        self.full_name = "Test User"
        self.is_active = 1


class FakeDocument:
    """Fake document for ACL testing."""

    def __init__(
        self,
        doc_id: UUID = None,
        tenant_id: UUID = None,
        doc_name: str = "test.pdf",
    ):
        self.doc_id = doc_id or uuid4()
        self.tenant_id = tenant_id or uuid4()
        self.doc_name = doc_name


@pytest.fixture
def tenant_a_id():
    return uuid4()


@pytest.fixture
def tenant_b_id():
    return uuid4()


@pytest.fixture
def user_a(tenant_a_id):
    return FakeUser(tenant_id=tenant_a_id, email="user_a@tenant-a.com", role="member")


@pytest.fixture
def user_b(tenant_b_id):
    return FakeUser(tenant_id=tenant_b_id, email="user_b@tenant-b.com", role="member")


@pytest.fixture
def admin_a(tenant_a_id):
    return FakeUser(tenant_id=tenant_a_id, email="admin@tenant-a.com", role="admin")


@pytest.fixture
def viewer_a(tenant_a_id):
    return FakeUser(tenant_id=tenant_a_id, email="viewer@tenant-a.com", role="viewer")


@pytest.fixture
def doc_tenant_a(tenant_a_id):
    return FakeDocument(tenant_id=tenant_a_id, doc_name="tenant_a_doc.pdf")


@pytest.fixture
def doc_tenant_b(tenant_b_id):
    return FakeDocument(tenant_id=tenant_b_id, doc_name="tenant_b_doc.pdf")


# =============================================================================
# Test: Tenant Isolation
# =============================================================================


class TestTenantIsolation:
    """Test that users cannot access documents from other tenants."""

    def test_user_can_access_own_tenant_doc(self, user_a, doc_tenant_a):
        """User should access documents in their own tenant."""
        from services.authorization import authorize

        # User A accessing Tenant A doc = allowed
        result = authorize(
            user=user_a,
            action="read",
            resource=doc_tenant_a,
            db=None,  # No DB = falls back to tenant-only check
            tenant_id=user_a.tenant_id,
        )
        assert result is True

    def test_user_cannot_access_other_tenant_doc(
        self, user_a, doc_tenant_b, tenant_b_id
    ):
        """User should NOT access documents in other tenant."""
        from services.authorization import authorize

        # User A trying to access Tenant B doc = denied
        result = authorize(
            user=user_a,
            action="read",
            resource=doc_tenant_b,
            db=None,
            tenant_id=user_a.tenant_id,  # User A's tenant doesn't match doc_tenant_b
        )
        assert result is False

    def test_tenant_mismatch_returns_false(self, user_a, doc_tenant_a, tenant_b_id):
        """Even if doc is accessible, tenant mismatch should deny."""
        from services.authorization import authorize

        # Create doc that pretends to be in a different tenant
        fake_doc = FakeDocument(tenant_id=tenant_b_id)

        result = authorize(
            user=user_a,
            action="read",
            resource=fake_doc,
            db=None,
            tenant_id=user_a.tenant_id,  # User A's tenant
        )
        assert result is False


# =============================================================================
# Test: Request Context
# =============================================================================


class TestRequestContext:
    """Test the RequestContext dataclass."""

    def test_request_context_properties(self, admin_a, tenant_a_id):
        """RequestContext should expose user, tenant_id, and role correctly."""
        from services.request_context import RequestContext

        ctx = RequestContext(
            user=admin_a,
            tenant_id=tenant_a_id,
            role="admin",
        )

        assert ctx.user_id == admin_a.user_id
        assert ctx.tenant_id == tenant_a_id
        assert ctx.role == "admin"
        assert ctx.is_admin is True
        assert ctx.can_manage() is True
        assert ctx.can_write() is True

    def test_viewer_cannot_write(self, viewer_a, tenant_a_id):
        """Viewer role should not have write access."""
        from services.request_context import RequestContext

        ctx = RequestContext(
            user=viewer_a,
            tenant_id=tenant_a_id,
            role="viewer",
        )

        assert ctx.is_viewer is True
        assert ctx.is_admin is False
        assert ctx.can_manage() is False
        assert ctx.can_write() is False

    def test_member_can_write_not_manage(self, user_a, tenant_a_id):
        """Member role can write but cannot manage."""
        from services.request_context import RequestContext

        ctx = RequestContext(
            user=user_a,
            tenant_id=tenant_a_id,
            role="member",
        )

        assert ctx.is_admin is False
        assert ctx.can_manage() is False
        assert ctx.can_write() is True


# =============================================================================
# Test: ACL Service Functions
# =============================================================================


class TestACLService:
    """Test ACL service functions."""

    def test_build_qdrant_acl_filter_includes_tenant(self, user_a):
        """Qdrant filter should include tenant_id."""
        from services.acl_service import build_qdrant_acl_filter

        user_groups = [uuid4(), uuid4()]

        filter_dict = build_qdrant_acl_filter(
            user_id=user_a.user_id,
            tenant_id=user_a.tenant_id,
            user_group_ids=user_groups,
        )

        # Check tenant filter is present
        assert "must" in filter_dict
        tenant_condition = filter_dict["must"][0]
        assert tenant_condition["key"] == "tenant_id"
        assert tenant_condition["match"]["value"] == str(user_a.tenant_id)

    def test_build_qdrant_acl_filter_includes_acl_conditions(self, user_a):
        """Qdrant filter should include ACL conditions."""
        from services.acl_service import build_qdrant_acl_filter

        user_groups = [uuid4()]

        filter_dict = build_qdrant_acl_filter(
            user_id=user_a.user_id,
            tenant_id=user_a.tenant_id,
            user_group_ids=user_groups,
        )

        # Check we have "should" conditions for ACL
        assert "should" in filter_dict
        conditions = filter_dict["should"]

        # Should have conditions for: public docs, user access, group access
        assert len(conditions) >= 2  # At least public + user
        if user_groups:
            assert len(conditions) == 3  # public + user + group


# =============================================================================
# Test: RBAC Enforcement
# =============================================================================


class TestRBAC:
    """Test role-based access control."""

    def test_require_admin_passes_for_admin(self, admin_a, tenant_a_id):
        """require_admin should pass for admin role."""
        from services.request_context import RequestContext

        ctx = RequestContext(user=admin_a, tenant_id=tenant_a_id, role="admin")

        # Should not raise
        assert ctx.is_admin is True

    def test_require_admin_fails_for_member(self, user_a, tenant_a_id):
        """require_admin should fail for member role."""
        from services.request_context import RequestContext

        ctx = RequestContext(user=user_a, tenant_id=tenant_a_id, role="member")

        assert ctx.is_admin is False
        assert ctx.can_manage() is False

    def test_require_write_passes_for_member(self, user_a, tenant_a_id):
        """require_write_access should pass for member role."""
        from services.request_context import RequestContext

        ctx = RequestContext(user=user_a, tenant_id=tenant_a_id, role="member")

        assert ctx.can_write() is True

    def test_require_write_fails_for_viewer(self, viewer_a, tenant_a_id):
        """require_write_access should fail for viewer role."""
        from services.request_context import RequestContext

        ctx = RequestContext(user=viewer_a, tenant_id=tenant_a_id, role="viewer")

        assert ctx.can_write() is False


# =============================================================================
# Test: JWT Claims
# =============================================================================


class TestJWTClaims:
    """Test that JWT contains tenant_id claim."""

    def test_access_token_contains_tid(self):
        """Access token should contain 'tid' claim."""
        from utils.auth import create_access_token, verify_token

        user_id = uuid4()
        tenant_id = uuid4()

        token, _ = create_access_token(
            user_id=user_id,
            email="test@example.com",
            role="member",
            tenant_id=tenant_id,
        )

        payload = verify_token(token, expected_type="access")

        assert payload is not None
        assert "tid" in payload
        assert payload["tid"] == str(tenant_id)
        assert payload["role"] == "member"
        assert payload["sub"] == str(user_id)

    def test_token_pair_contains_tid(self):
        """Token pair should include tid in access token."""
        from utils.auth import create_token_pair, verify_token

        user_id = uuid4()
        tenant_id = uuid4()

        tokens = create_token_pair(
            user_id=user_id,
            email="test@example.com",
            role="admin",
            tenant_id=tenant_id,
        )

        payload = verify_token(tokens["access_token"], expected_type="access")

        assert payload["tid"] == str(tenant_id)
        assert payload["role"] == "admin"
