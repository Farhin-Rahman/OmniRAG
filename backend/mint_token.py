"""Mint a Firebase ID token for local API testing.

The frontend's Google sign-in can be flaky on localhost (browsers
restricting third-party cookies breaks Firebase's popup flow). This
bypasses the frontend entirely: the Admin SDK issues a custom token for
an existing user, which is exchanged for a real ID token carrying that
user's custom claims (e.g. the TrustAndSafetyAdmin role). Paste the
output into Swagger's "Authorize" box as:  Bearer <token>

    ../.venv/Scripts/python.exe mint_token.py [email]

Default email is sadiafarhin063@gmail.com. Token is valid ~1 hour.
"""

import sys

import firebase_admin
import httpx
from firebase_admin import auth, credentials

# Public Firebase Web API key (identifies the project; not a secret —
# it's shipped in the frontend bundle). From frontend/src/auth/firebase.ts.
WEB_API_KEY = "AIzaSyB70KbsQXxAF0Sh9ZMWZCWeNy2MbAUKdIA"
SERVICE_ACCOUNT_PATH = "gcp-service-account.json"


def main() -> None:
    email = sys.argv[1] if len(sys.argv) > 1 else "sadiafarhin063@gmail.com"

    firebase_admin.initialize_app(credentials.Certificate(SERVICE_ACCOUNT_PATH))
    user = auth.get_user_by_email(email)
    custom_token = auth.create_custom_token(user.uid).decode()

    resp = httpx.post(
        "https://identitytoolkit.googleapis.com/v1/accounts:signInWithCustomToken",
        params={"key": WEB_API_KEY},
        json={"token": custom_token, "returnSecureToken": True},
        timeout=15,
    )
    resp.raise_for_status()
    id_token = resp.json()["idToken"]

    roles = (user.custom_claims or {}).get("roles")
    print(f"\nUser:  {user.email}   roles: {roles}   verified: {user.email_verified}")
    print("\nID token (valid ~1 hour) — Swagger Authorize -> paste:  Bearer <token>\n")
    print(id_token)


if __name__ == "__main__":
    main()
