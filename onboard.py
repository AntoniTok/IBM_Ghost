"""
onboard.py
==========
ONE-TIME Spotify OAuth flow for the Granite Ghost.

Run this once during device setup (e.g. by a family member helping out).
It opens a browser, lets the user log in to Spotify, captures the
authorization code, exchanges it for tokens, and saves them to disk.

After this runs successfully, spotify_handler.py can refresh the token
silently forever (until the user revokes access).

Usage:
    export SPOTIFY_CLIENT_ID=...
    export SPOTIFY_CLIENT_SECRET=...
    python onboard.py

Make sure the Redirect URI in your Spotify app dashboard matches
REDIRECT_URI below exactly.
"""

import http.server
import json
import os
import secrets
import socketserver
import time
import urllib.parse
import webbrowser

import requests

CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "eeb838b780824e3787703122897d1b86")
CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "712607c8364b4f0eac14264d941265b9")
REDIRECT_URI = "http://127.0.0.1:8765/callback"
SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-read",
    "user-library-modify",
    "user-read-recently-played",
    "streaming",
])
TOKEN_STORE = os.path.expanduser("~/.granite_ghost/spotify_tokens.json")

state = secrets.token_urlsafe(16)
auth_code: str | None = None


class CallbackHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global auth_code
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if params.get("state", [""])[0] != state:
            self.send_error(400, "State mismatch")
            return
        auth_code = params.get("code", [None])[0]
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(b"<h2>You can close this window now.</h2>")

    def log_message(self, *_):  # quiet
        pass


def main():
    # 1. Send user to Spotify login
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
    })
    print(f"Opening browser to: {auth_url}")
    webbrowser.open(auth_url)

    # 2. Run a tiny local server to catch the redirect
    with socketserver.TCPServer(("127.0.0.1", 8765), CallbackHandler) as httpd:
        while auth_code is None:
            httpd.handle_request()

    # 3. Exchange code for tokens
    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
        },
        auth=(CLIENT_ID, CLIENT_SECRET),
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()

    tokens = {
        "access_token": body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at": time.time() + body["expires_in"],
    }
    os.makedirs(os.path.dirname(TOKEN_STORE), exist_ok=True)
    with open(TOKEN_STORE, "w") as f:
        json.dump(tokens, f)
    os.chmod(TOKEN_STORE, 0o600)
    print(f"Tokens saved to {TOKEN_STORE}. You're done.")


if __name__ == "__main__":
    main()
