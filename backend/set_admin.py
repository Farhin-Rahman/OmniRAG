"""
One-off admin script: grant a Firebase user the TrustAndSafetyAdmin role via
custom claims, looked up by email. Standalone — not part of the running
app, run manually.

Usage:
    python set_admin.py <email>

The role lands in the user's ID token as a "roles" custom claim, which
backend/api/deps.py reads to authorize require_roles("TrustAndSafetyAdmin")
routes. Custom claims only take effect on the user's *next* ID token
refresh (e.g., after signing out/in, or up to ~1 hour for silent refresh).

Note: the target user must already exist in Firebase Auth (e.g., have
signed in via loginWithGoogle at least once) before this script can find
them by email.
"""

import sys

import firebase_admin
from firebase_admin import auth, credentials

SERVICE_ACCOUNT_PATH = "gcp-service-account.json"


def main() -> None:
    if len(sys.argv) != 2:
        print("Usage: python set_admin.py <email>", file=sys.stderr)
        raise SystemExit(1)
    target_email = sys.argv[1]

    cred = credentials.Certificate(SERVICE_ACCOUNT_PATH)
    firebase_admin.initialize_app(cred)

    try:
        user = auth.get_user_by_email(target_email)
    except auth.UserNotFoundError:
        print(
            f"No Firebase user found for {target_email}. "
            "Sign in via loginWithGoogle in the app at least once first, then rerun this.",
            file=sys.stderr,
        )
        raise SystemExit(1)

    auth.set_custom_user_claims(user.uid, {"roles": ["TrustAndSafetyAdmin"]})
    print(f"Granted 'TrustAndSafetyAdmin' role to {target_email} (uid: {user.uid})")


if __name__ == "__main__":
    main()
