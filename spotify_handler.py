"""
spotify_handler.py
==================
Spotify Web API wrapper for the Granite Ghost device.

Responsibilities:
  - Authenticate with Spotify (OAuth 2.0 Authorization Code w/ refresh token)
  - Search for tracks / artists / albums / playlists
  - Send playback commands to the Pi (running librespot/raspotify as a
    Spotify Connect target)
  - Return clean, voice-friendly JSON to the rest of the device pipeline

Usage from the voice intent parser:
    handler = SpotifyHandler()
    result = handler.handle_intent("play", "Fly Me to the Moon by Sinatra")
    # -> dict, JSON-serialisable, with a `voice_response` field for TTS
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

SPOTIFY_API = "https://api.spotify.com/v1"
SPOTIFY_AUTH = "https://accounts.spotify.com/api/token"

# Path where the refresh token is stored after one-time onboarding.
# Local-only, in line with the project's privacy decision.
TOKEN_STORE = os.path.expanduser("~/.granite_ghost/spotify_tokens.json")

# Name your raspotify daemon advertises on the network. Must match
# the LIBRESPOT_NAME setting in /etc/raspotify/conf.
DEVICE_NAME = "Granite Ghost"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class SpotifyError(Exception):
    """Anything that goes wrong talking to Spotify."""


class NoActiveDeviceError(SpotifyError):
    """The Pi isn't visible as a Connect device right now."""


class PremiumRequiredError(SpotifyError):
    """User is on Spotify Free - playback control is Premium-only."""


# ---------------------------------------------------------------------------
# Token management
# ---------------------------------------------------------------------------

@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: float  # unix timestamp

    @property
    def expired(self) -> bool:
        # Refresh 60s early to avoid mid-request expiry
        return time.time() >= (self.expires_at - 60)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at,
        }


def _load_tokens() -> Tokens:
    if not os.path.exists(TOKEN_STORE):
        raise SpotifyError(
            f"No tokens at {TOKEN_STORE}. Run onboarding flow first."
        )
    with open(TOKEN_STORE) as f:
        data = json.load(f)
    return Tokens(**data)


def _save_tokens(tokens: Tokens) -> None:
    os.makedirs(os.path.dirname(TOKEN_STORE), exist_ok=True)
    with open(TOKEN_STORE, "w") as f:
        json.dump(tokens.to_dict(), f)
    os.chmod(TOKEN_STORE, 0o600)  # user-only readable


def _refresh(tokens: Tokens, client_id: str, client_secret: str) -> Tokens:
    r = requests.post(
        SPOTIFY_AUTH,
        data={
            "grant_type": "refresh_token",
            "refresh_token": tokens.refresh_token,
        },
        auth=(client_id, client_secret),
        timeout=10,
    )
    if r.status_code != 200:
        raise SpotifyError(f"Token refresh failed: {r.status_code} {r.text}")
    body = r.json()
    return Tokens(
        access_token=body["access_token"],
        # Spotify sometimes omits a new refresh_token; keep the old one
        refresh_token=body.get("refresh_token", tokens.refresh_token),
        expires_at=time.time() + body["expires_in"],
    )


# ---------------------------------------------------------------------------
# Main handler
# ---------------------------------------------------------------------------

class SpotifyHandler:
    def __init__(
        self,
        client_id: str | None = None,
        client_secret: str | None = None,
    ):
        self.client_id = client_id or os.environ.get("SPOTIFY_CLIENT_ID", "eeb838b780824e3787703122897d1b86")
        self.client_secret = client_secret or os.environ.get("SPOTIFY_CLIENT_SECRET", "712607c8364b4f0eac14264d941265b9")
        self._tokens = _load_tokens()

    # -- low-level request --------------------------------------------------

    def _ensure_fresh(self) -> None:
        if self._tokens.expired:
            self._tokens = _refresh(self._tokens, self.client_id, self.client_secret)
            _save_tokens(self._tokens)

    def _request(self, method: str, path: str, **kwargs) -> Any:
        self._ensure_fresh()
        headers = kwargs.pop("headers", {})
        headers["Authorization"] = f"Bearer {self._tokens.access_token}"
        r = requests.request(
            method, f"{SPOTIFY_API}{path}",
            headers=headers, timeout=10, **kwargs,
        )
        if r.status_code == 401:
            # token rejected - force refresh once and retry
            self._tokens = _refresh(self._tokens, self.client_id, self.client_secret)
            _save_tokens(self._tokens)
            headers["Authorization"] = f"Bearer {self._tokens.access_token}"
            r = requests.request(
                method, f"{SPOTIFY_API}{path}",
                headers=headers, timeout=10, **kwargs,
            )
        if r.status_code == 403:
            raise PremiumRequiredError(
                "Playback control requires Spotify Premium."
            )
        if r.status_code == 404 and "device" in r.text.lower():
            raise NoActiveDeviceError(
                f"'{DEVICE_NAME}' is not visible to Spotify. "
                "Is raspotify running?"
            )
        if not r.ok:
            raise SpotifyError(f"{method} {path} -> {r.status_code} {r.text}")
        # Some playback endpoints return 204 No Content
        return r.json() if r.content else {}

    # -- device discovery ---------------------------------------------------

    def find_device_id(self) -> str:
        """Look up the Pi's Connect device id by name."""
        data = self._request("GET", "/me/player/devices")
        for d in data.get("devices", []):
            if d["name"] == DEVICE_NAME:
                return d["id"]
        raise NoActiveDeviceError(
            f"No device named '{DEVICE_NAME}'. "
            f"Available: {[d['name'] for d in data.get('devices', [])]}"
        )

    # -- search -------------------------------------------------------------

    def search(self, query: str, kind: str = "track", limit: int = 1) -> dict:
        """Search Spotify and return a trimmed-down result."""
        data = self._request(
            "GET", "/search",
            params={"q": query, "type": kind, "limit": limit},
        )
        items = data.get(f"{kind}s", {}).get("items", [])
        if not items:
            return {"found": False, "query": query}

        top = items[0]
        if kind == "track":
            return {
                "found": True,
                "uri": top["uri"],
                "name": top["name"],
                "artist": ", ".join(a["name"] for a in top["artists"]),
                "album": top["album"]["name"],
                "duration_ms": top["duration_ms"],
            }
        if kind == "artist":
            return {"found": True, "uri": top["uri"], "name": top["name"]}
        if kind == "playlist":
            return {
                "found": True,
                "uri": top["uri"],
                "name": top["name"],
                "owner": top["owner"]["display_name"],
            }
        return {"found": True, "uri": top["uri"], "name": top.get("name")}

    # -- playback commands --------------------------------------------------

    def play(self, uri: str | None = None, uris: list[str] | None = None) -> dict:
        """Start or resume playback on the Pi.

        Args:
            uri:  A single Spotify URI (track, album, playlist, artist).
            uris: A list of track URIs to play in order.
        """
        device_id = self.find_device_id()
        body: dict[str, Any] = {}
        if uris:
            body["uris"] = uris
        elif uri:
            if uri.startswith("spotify:track:"):
                body["uris"] = [uri]
            else:  # album, playlist, artist
                body["context_uri"] = uri
        self._request(
            "PUT", "/me/player/play",
            params={"device_id": device_id},
            json=body or None,
        )
        return {"status": "playing", "uri": uri, "device": DEVICE_NAME}

    def pause(self) -> dict:
        self._request("PUT", "/me/player/pause")
        return {"status": "paused"}

    def next_track(self) -> dict:
        self._request("POST", "/me/player/next")
        return {"status": "skipped"}

    def previous_track(self) -> dict:
        self._request("POST", "/me/player/previous")
        return {"status": "back"}

    def set_volume(self, percent: int) -> dict:
        percent = max(0, min(100, int(percent)))
        self._request(
            "PUT", "/me/player/volume",
            params={"volume_percent": percent},
        )
        return {"status": "volume_set", "volume": percent}

    def now_playing(self) -> dict:
        data = self._request("GET", "/me/player/currently-playing")
        if not data or not data.get("item"):
            return {"playing": False}
        item = data["item"]
        return {
            "playing": data.get("is_playing", False),
            "name": item["name"],
            "artist": ", ".join(a["name"] for a in item["artists"]),
            "album": item["album"]["name"],
            "progress_ms": data.get("progress_ms"),
            "duration_ms": item["duration_ms"],
            "uri": item["uri"],
        }

    # -- saved tracks (Liked Songs) ----------------------------------------

    def get_saved_tracks(self, limit: int = 20) -> list[dict]:
        """GET /me/tracks — fetch the user's Liked Songs."""
        data = self._request(
            "GET", "/me/tracks", params={"limit": min(limit, 50)},
        )
        return [
            {
                "uri": t["track"]["uri"],
                "name": t["track"]["name"],
                "artist": ", ".join(a["name"] for a in t["track"]["artists"]),
            }
            for t in data.get("items", [])
            if t.get("track")
        ]

    def save_track(self, track_id: str) -> dict:
        """PUT /me/tracks — add a track to the user's Liked Songs."""
        self._request("PUT", "/me/tracks", json={"ids": [track_id]})
        return {"status": "saved", "track_id": track_id}

    # -- user playlists -----------------------------------------------------

    def get_playlists(self, limit: int = 50) -> list[dict]:
        """GET /me/playlists — list the user's playlists."""
        data = self._request(
            "GET", "/me/playlists", params={"limit": min(limit, 50)},
        )
        return [
            {
                "uri": p["uri"],
                "name": p["name"],
                "owner": p["owner"]["display_name"],
                "track_count": p["tracks"]["total"],
            }
            for p in data.get("items", [])
        ]

    def play_playlist_by_name(self, name: str) -> dict:
        """Find a playlist by name (case-insensitive) and play it."""
        playlists = self.get_playlists()
        query = name.lower()
        match = next(
            (p for p in playlists if query in p["name"].lower()), None,
        )
        if not match:
            return {
                "found": False,
                "voice_response": f"I couldn't find a playlist called {name}.",
            }
        self.play(uri=match["uri"])
        return {
            "found": True,
            **match,
            "status": "playing",
            "voice_response": f"Playing {match['name']}.",
        }

    # -- recently played ----------------------------------------------------

    def get_recently_played(self, limit: int = 20) -> list[dict]:
        """GET /me/player/recently-played."""
        data = self._request(
            "GET", "/me/player/recently-played",
            params={"limit": min(limit, 50)},
        )
        return [
            {
                "uri": i["track"]["uri"],
                "name": i["track"]["name"],
                "artist": ", ".join(
                    a["name"] for a in i["track"]["artists"]
                ),
                "played_at": i["played_at"],
            }
            for i in data.get("items", [])
        ]

    # -- artist top tracks --------------------------------------------------

    def get_artist_top_tracks(self, artist_id: str) -> list[dict]:
        """GET /artists/{id}/top-tracks."""
        data = self._request(
            "GET", f"/artists/{artist_id}/top-tracks",
            params={"market": "from_token"},
        )
        return [
            {
                "uri": t["uri"],
                "name": t["name"],
                "artist": ", ".join(a["name"] for a in t["artists"]),
            }
            for t in data.get("tracks", [])
        ]

    # -- recommendations (with fallback) ------------------------------------

    def get_recommendations(
        self,
        seed_tracks: list[str] | None = None,
        seed_artists: list[str] | None = None,
        seed_genres: list[str] | None = None,
        limit: int = 20,
    ) -> list[dict]:
        """GET /recommendations — may fail if endpoint is deprecated for
        this app. Caller should fall back to artist top tracks."""
        params: dict[str, Any] = {"limit": limit}
        if seed_tracks:
            params["seed_tracks"] = ",".join(seed_tracks)
        if seed_artists:
            params["seed_artists"] = ",".join(seed_artists)
        if seed_genres:
            params["seed_genres"] = ",".join(seed_genres)
        data = self._request("GET", "/recommendations", params=params)
        return [
            {
                "uri": t["uri"],
                "name": t["name"],
                "artist": ", ".join(a["name"] for a in t["artists"]),
            }
            for t in data.get("tracks", [])
        ]

    def play_similar(self, query: str = "") -> dict:
        """Play music similar to the current track or a named artist.

        Tries /recommendations first; falls back to artist top tracks
        if the endpoint is unavailable.
        """
        if query:
            # User said "play something like Sinatra"
            hit = self.search(query, kind="artist")
            if not hit["found"]:
                return {
                    "found": False,
                    "voice_response": f"I couldn't find {query}.",
                }
            artist_id = hit["uri"].split(":")[-1]
            artist_name = hit["name"]
        else:
            # Use whatever is currently playing
            np = self.now_playing()
            if not np.get("playing"):
                return {
                    "found": False,
                    "voice_response": "Nothing is playing right now.",
                }
            # Search for the artist of the current track
            hit = self.search(np["artist"], kind="artist")
            if not hit["found"]:
                return {
                    "found": False,
                    "voice_response": "I couldn't find similar music.",
                }
            artist_id = hit["uri"].split(":")[-1]
            artist_name = hit["name"]

        # Try recommendations first, fall back to top tracks
        try:
            tracks = self.get_recommendations(
                seed_artists=[artist_id], limit=20,
            )
        except SpotifyError:
            tracks = []

        if not tracks:
            tracks = self.get_artist_top_tracks(artist_id)

        if not tracks:
            return {
                "found": False,
                "voice_response": f"I couldn't find music like {artist_name}.",
            }

        self.play(uris=[t["uri"] for t in tracks])
        return {
            "found": True,
            "status": "playing",
            "track_count": len(tracks),
            "voice_response": f"Playing music like {artist_name}.",
        }

    # -- queue management ---------------------------------------------------

    def add_to_queue(self, uri: str) -> dict:
        """POST /me/player/queue — add a track without interrupting."""
        self._request(
            "POST", "/me/player/queue", params={"uri": uri},
        )
        return {"status": "queued", "uri": uri}

    def get_queue(self) -> dict:
        """GET /me/player/queue."""
        data = self._request("GET", "/me/player/queue")
        current = data.get("currently_playing")
        upcoming = data.get("queue", [])[:10]
        return {
            "currently_playing": {
                "name": current["name"],
                "artist": ", ".join(a["name"] for a in current["artists"]),
            } if current else None,
            "upcoming": [
                {
                    "name": t["name"],
                    "artist": ", ".join(a["name"] for a in t["artists"]),
                }
                for t in upcoming
            ],
        }

    # -- repeat, shuffle, seek ----------------------------------------------

    def set_repeat(self, state: str = "track") -> dict:
        """PUT /me/player/repeat. state: track | context | off."""
        state = state if state in ("track", "context", "off") else "track"
        self._request(
            "PUT", "/me/player/repeat", params={"state": state},
        )
        return {"status": "repeat_set", "repeat": state}

    def set_shuffle(self, on: bool = True) -> dict:
        """PUT /me/player/shuffle."""
        self._request(
            "PUT", "/me/player/shuffle",
            params={"state": "true" if on else "false"},
        )
        return {"status": "shuffle_set", "shuffle": on}

    def seek(self, position_ms: int = 0) -> dict:
        """PUT /me/player/seek — mostly for 'start over'."""
        self._request(
            "PUT", "/me/player/seek",
            params={"position_ms": max(0, position_ms)},
        )
        return {"status": "seeked", "position_ms": position_ms}

    # -- voice-facing entry point ------------------------------------------

    def handle_intent(self, intent: str, query: str = "") -> dict:
        """
        Top-level entry point for the voice pipeline.
        Always returns a JSON-serialisable dict with a `voice_response`
        field suitable for handing straight to TTS.
        """
        try:
            if intent == "play":
                if not query:
                    result = self.play()
                    return {**result, "voice_response": "Resuming."}
                hit = self.search(query, kind="track")
                if not hit["found"]:
                    return {
                        "found": False,
                        "voice_response": f"I couldn't find {query} on Spotify.",
                    }
                self.play(hit["uri"])
                return {
                    **hit,
                    "voice_response": f"Playing {hit['name']} by {hit['artist']}.",
                }

            if intent == "pause":
                self.pause()
                return {"status": "paused", "voice_response": "Paused."}

            if intent == "next":
                self.next_track()
                return {"status": "skipped", "voice_response": "Skipping."}

            if intent == "previous":
                self.previous_track()
                return {"status": "back", "voice_response": "Going back."}

            if intent == "volume":
                pct = int(query) if query else 50
                self.set_volume(pct)
                return {
                    "status": "volume_set",
                    "volume": pct,
                    "voice_response": f"Volume set to {pct} percent.",
                }

            if intent == "now_playing":
                np = self.now_playing()
                if not np["playing"]:
                    return {**np, "voice_response": "Nothing is playing."}
                return {
                    **np,
                    "voice_response": f"This is {np['name']} by {np['artist']}.",
                }

            # -- new intents ------------------------------------------------

            if intent == "favourites":
                tracks = self.get_saved_tracks(limit=30)
                if not tracks:
                    return {
                        "found": False,
                        "voice_response": "You don't have any saved songs yet.",
                    }
                self.play(uris=[t["uri"] for t in tracks])
                return {
                    "status": "playing",
                    "track_count": len(tracks),
                    "voice_response": "Playing your favourites.",
                }

            if intent == "save":
                np = self.now_playing()
                if not np.get("playing"):
                    return {"voice_response": "Nothing is playing to save."}
                track_id = np["uri"].split(":")[-1]
                self.save_track(track_id)
                return {
                    "status": "saved",
                    "voice_response": f"Saved {np['name']} to your library.",
                }

            if intent == "playlist":
                if not query:
                    playlists = self.get_playlists(limit=10)
                    if not playlists:
                        return {"voice_response": "You don't have any playlists."}
                    names = ", ".join(p["name"] for p in playlists[:5])
                    return {
                        "playlists": playlists,
                        "voice_response": f"Your playlists include: {names}.",
                    }
                return self.play_playlist_by_name(query)

            if intent == "recent":
                recent = self.get_recently_played(limit=10)
                if not recent:
                    return {"voice_response": "No recent listening history."}
                if query:
                    # "play that song from earlier" — play the most recent
                    self.play(uri=recent[0]["uri"])
                    return {
                        **recent[0],
                        "status": "playing",
                        "voice_response": (
                            f"Playing {recent[0]['name']} "
                            f"by {recent[0]['artist']}."
                        ),
                    }
                names = ", ".join(t["name"] for t in recent[:5])
                return {
                    "recent": recent,
                    "voice_response": f"Recently you listened to: {names}.",
                }

            if intent == "similar":
                return self.play_similar(query)

            if intent == "queue":
                if not query:
                    q = self.get_queue()
                    if not q["upcoming"]:
                        return {"voice_response": "The queue is empty."}
                    names = ", ".join(t["name"] for t in q["upcoming"][:5])
                    return {
                        **q,
                        "voice_response": f"Coming up: {names}.",
                    }
                hit = self.search(query, kind="track")
                if not hit["found"]:
                    return {
                        "found": False,
                        "voice_response": f"I couldn't find {query}.",
                    }
                self.add_to_queue(hit["uri"])
                return {
                    **hit,
                    "voice_response": (
                        f"Added {hit['name']} by {hit['artist']} to the queue."
                    ),
                }

            if intent == "repeat":
                state = query if query in ("track", "context", "off") else "track"
                self.set_repeat(state)
                label = "off" if state == "off" else f"on ({state})"
                return {
                    "status": "repeat_set",
                    "voice_response": f"Repeat is {label}.",
                }

            if intent == "shuffle":
                on = query.lower() not in ("off", "false", "0") if query else True
                self.set_shuffle(on)
                return {
                    "status": "shuffle_set",
                    "voice_response": f"Shuffle {'on' if on else 'off'}.",
                }

            if intent == "restart":
                self.seek(0)
                return {
                    "status": "restarted",
                    "voice_response": "Starting over.",
                }

            return {
                "error": "unknown_intent",
                "voice_response": "I'm not sure what you'd like me to play.",
            }

        except PremiumRequiredError:
            return {
                "error": "premium_required",
                "voice_response": (
                    "Spotify needs a Premium account for me to play music. "
                    "Could a family member help set that up?"
                ),
            }
        except NoActiveDeviceError:
            return {
                "error": "no_device",
                "voice_response": (
                    "I can't reach the speaker right now. "
                    "Let me try again in a moment."
                ),
            }
        except SpotifyError as e:
            return {
                "error": "spotify_error",
                "detail": str(e),
                "voice_response": "Something went wrong with Spotify.",
            }


# ---------------------------------------------------------------------------
# CLI for quick testing on the Pi
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    h = SpotifyHandler()
    intent = sys.argv[1] if len(sys.argv) > 1 else "now_playing"
    query = " ".join(sys.argv[2:])
    print(json.dumps(h.handle_intent(intent, query), indent=2))
