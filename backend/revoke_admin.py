"""
One-off admin script: revoke a Firebase user's TrustAndSafetyAdmin role by
clearing their custom claims, looked up by email. Standalone — not part of
the running app, run manually. Companion to set_admin.py.

Usage:
    python revoke_admin.py <email>

Clearing the claim takes effect on the user's *next* ID token refresh
(e.g., after signing out/in, or up to ~1 hour for silent refresh) — same
as granting it.
"""

import sys

import firebase_admin
from firebase_admin import auth, credentials

SERVICE_ACCOUNT_PATH = "gcp-service-account.json"


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python revoke_admin.py <email>", file=sys.stderr)
        raise SystemExit(1)
    target_email = sys.argv[1]

    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)

    try:
        user = auth.get_user_by_email(target_email)
    except auth.UserNotFoundError:
        print(f"No Firebase user found for {target_email}.", file=sys.stderr)
        raise SystemExit(1)

    auth.set_custom_user_claims(user.uid, {"roles": []})
    print(f"Revoked 'TrustAndSafetyAdmin' role from {target_email} (uid: {user.uid})")


if __name__ == "__main__":
    main()
