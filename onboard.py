"""
onboard.py
==========
ONE-TIME Spotify OAuth flow for Granite Ghost.

Run this once during device setup. It opens a browser, lets the user log in
to Spotify, captures the authorization code, exchanges it for tokens, and
saves them to disk.

After this runs successfully, spotify_handler.py can refresh the token
silently forever (until the user revokes access).

Usage:
    python onboard.py
"""

import http.server
import json
import secrets
import socketserver
import time
import urllib.parse
import webbrowser

import requests

from config import (
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI, SPOTIFY_TOKEN_STORE,
)

SCOPES = " ".join([
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
    "user-library-read",
    "user-library-modify",
    "user-read-recently-played",
    "streaming",
])

state     = secrets.token_urlsafe(16)
auth_code = None


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

    def log_message(self, *_):
        pass


def main():
    auth_url = "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode({
        "client_id":     SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri":  SPOTIFY_REDIRECT_URI,
        "scope":         SCOPES,
        "state":         state,
    })
    print(f"Opening browser to: {auth_url}")
    webbrowser.open(auth_url)

    with socketserver.TCPServer(("127.0.0.1", 8765), CallbackHandler) as httpd:
        while auth_code is None:
            httpd.handle_request()

    r = requests.post(
        "https://accounts.spotify.com/api/token",
        data={
            "grant_type":   "authorization_code",
            "code":         auth_code,
            "redirect_uri": SPOTIFY_REDIRECT_URI,
        },
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    r.raise_for_status()
    body = r.json()

    tokens = {
        "access_token":  body["access_token"],
        "refresh_token": body["refresh_token"],
        "expires_at":    time.time() + body["expires_in"],
    }

    SPOTIFY_TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    SPOTIFY_TOKEN_STORE.write_text(json.dumps(tokens))
    SPOTIFY_TOKEN_STORE.chmod(0o600)
    print(f"Tokens saved to {SPOTIFY_TOKEN_STORE}. You're done.")


if __name__ == "__main__":
    main()
