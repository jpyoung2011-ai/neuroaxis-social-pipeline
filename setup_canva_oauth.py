"""Run this ONCE, locally, in a real browser session.

It performs the Canva OAuth 2.0 + PKCE authorization-code flow: opens your
browser to Canva's consent screen, catches the redirect on a temporary local
server, and exchanges the code for tokens. Prints the refresh token you need
to put in .env (locally) and in your GitHub repo secrets (for CI).

Requires CANVA_CLIENT_ID and CANVA_CLIENT_SECRET to already be set in .env,
and the integration's redirect URL set to http://127.0.0.1:8765/oauth/redirect
in the Canva Developer Portal (see README.md step 2).
"""

import base64
import hashlib
import os
import secrets
import threading
import urllib.parse
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["CANVA_CLIENT_ID"]
CLIENT_SECRET = os.environ["CANVA_CLIENT_SECRET"]
REDIRECT_URI = "http://127.0.0.1:8765/oauth/redirect"
AUTH_URL = "https://www.canva.com/api/oauth/authorize"
TOKEN_URL = "https://api.canva.com/rest/v1/oauth/token"
SCOPES = " ".join(
    [
        "asset:read",
        "asset:write",
        "brandtemplate:content:read",
        "brandtemplate:meta:read",
        "design:content:read",
        "design:content:write",
        "design:meta:read",
        "profile:read",
    ]
)

_auth_code = {}


class _CallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        _auth_code["code"] = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            b"<html><body><h2>Authorized. You can close this tab and return to the terminal.</h2></body></html>"
        )

    def log_message(self, *args):
        pass  # keep the console quiet


def main():
    code_verifier = secrets.token_urlsafe(64)[:128]
    code_challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(code_verifier.encode()).digest())
        .decode()
        .rstrip("=")
    )

    auth_params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": secrets.token_urlsafe(16),
    }
    auth_url = f"{AUTH_URL}?{urllib.parse.urlencode(auth_params)}"

    server = HTTPServer(("127.0.0.1", 8765), _CallbackHandler)
    thread = threading.Thread(target=server.handle_request)  # handles exactly one request
    thread.start()

    print("Opening your browser to authorize this integration with Canva...")
    print(f"If it doesn't open automatically, visit:\n{auth_url}\n")
    webbrowser.open(auth_url)

    thread.join(timeout=180)
    server.server_close()

    code = _auth_code.get("code")
    if not code:
        raise SystemExit("Did not receive an authorization code. Check the redirect URL setting "
                          "in the Canva Developer Portal matches http://127.0.0.1:8765/oauth/redirect")

    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = requests.post(
        TOKEN_URL,
        headers={
            "Authorization": f"Basic {basic}",
            "Content-Type": "application/x-www-form-urlencoded",
        },
        data={
            "grant_type": "authorization_code",
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": REDIRECT_URI,
        },
        timeout=30,
    )
    resp.raise_for_status()
    tokens = resp.json()

    print("\nSuccess! Add this to your .env file and your GitHub repo secrets:\n")
    print(f"CANVA_REFRESH_TOKEN={tokens['refresh_token']}")


if __name__ == "__main__":
    main()
