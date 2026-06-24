"""
spotify_handler.py
==================
Spotify Web API wrapper for the Granite Ghost device.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any

import requests

from config import (
    SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET,
    SPOTIFY_TOKEN_STORE, SPOTIFY_DEVICE_NAME,
)

SPOTIFY_API  = "https://api.spotify.com/v1"
SPOTIFY_AUTH = "https://accounts.spotify.com/api/token"


# ─── Errors ──────────────────────────────────────────────────────────────────

class SpotifyError(Exception):
    pass

class NoActiveDeviceError(SpotifyError):
    pass

class PremiumRequiredError(SpotifyError):
    pass


# ─── Token management ────────────────────────────────────────────────────────

@dataclass
class Tokens:
    access_token:  str
    refresh_token: str
    expires_at:    float

    @property
    def expired(self) -> bool:
        return time.time() >= (self.expires_at - 60)

    def to_dict(self) -> dict[str, Any]:
        return {
            "access_token":  self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at":    self.expires_at,
        }


def _load_tokens() -> Tokens:
    if not SPOTIFY_TOKEN_STORE.exists():
        raise SpotifyError(
            f"No tokens at {SPOTIFY_TOKEN_STORE}. Run onboard.py first."
        )
    with open(SPOTIFY_TOKEN_STORE) as f:
        data = json.load(f)
    return Tokens(**data)


def _save_tokens(tokens: Tokens) -> None:
    SPOTIFY_TOKEN_STORE.parent.mkdir(parents=True, exist_ok=True)
    with open(SPOTIFY_TOKEN_STORE, "w") as f:
        json.dump(tokens.to_dict(), f)
    os.chmod(SPOTIFY_TOKEN_STORE, 0o600)


def _refresh(tokens: Tokens) -> Tokens:
    r = requests.post(
        SPOTIFY_AUTH,
        data={"grant_type": "refresh_token", "refresh_token": tokens.refresh_token},
        auth=(SPOTIFY_CLIENT_ID, SPOTIFY_CLIENT_SECRET),
        timeout=10,
    )
    if r.status_code != 200:
        raise SpotifyError(f"Token refresh failed: {r.status_code} {r.text}")
    body = r.json()
    return Tokens(
        access_token=body["access_token"],
        refresh_token=body.get("refresh_token", tokens.refresh_token),
        expires_at=time.time() + body["expires_in"],
    )


# ─── Main handler ─────────────────────────────────────────────────────────────

class SpotifyHandler:
    def __init__(self):
        self._tokens = _load_tokens()

    def _ensure_fresh(self) -> None:
        if self._tokens.expired:
            self._tokens = _refresh(self._tokens)
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
            self._tokens = _refresh(self._tokens)
            _save_tokens(self._tokens)
            headers["Authorization"] = f"Bearer {self._tokens.access_token}"
            r = requests.request(
                method, f"{SPOTIFY_API}{path}",
                headers=headers, timeout=10, **kwargs,
            )
        if r.status_code == 403:
            raise PremiumRequiredError("Playback control requires Spotify Premium.")
        if r.status_code == 404 and "device" in r.text.lower():
            raise NoActiveDeviceError(
                f"'{SPOTIFY_DEVICE_NAME}' is not visible to Spotify. Is raspotify running?"
            )
        if not r.ok:
            raise SpotifyError(f"{method} {path} -> {r.status_code} {r.text}")
        return r.json() if r.content else {}

    def find_device_id(self) -> str:
        data = self._request("GET", "/me/player/devices")
        for d in data.get("devices", []):
            if d["name"] == SPOTIFY_DEVICE_NAME:
                return d["id"]
        raise NoActiveDeviceError(
            f"No device named '{SPOTIFY_DEVICE_NAME}'. "
            f"Available: {[d['name'] for d in data.get('devices', [])]}"
        )

    def search(self, query: str, kind: str = "track", limit: int = 1) -> dict:
        data = self._request("GET", "/search", params={"q": query, "type": kind, "limit": limit})
        items = data.get(f"{kind}s", {}).get("items", [])
        if not items:
            return {"found": False, "query": query}
        top = items[0]
        if kind == "track":
            return {
                "found": True, "uri": top["uri"], "name": top["name"],
                "artist": ", ".join(a["name"] for a in top["artists"]),
                "album": top["album"]["name"], "duration_ms": top["duration_ms"],
            }
        if kind == "artist":
            return {"found": True, "uri": top["uri"], "name": top["name"]}
        if kind == "playlist":
            return {
                "found": True, "uri": top["uri"], "name": top["name"],
                "owner": top["owner"]["display_name"],
            }
        return {"found": True, "uri": top["uri"]}

    def play(self, uri: str | None = None, uris: list | None = None) -> dict:
        device_id = self.find_device_id()
        body: dict = {"device_id": device_id}
        if uris:
            body["uris"] = uris
        elif uri:
            if uri.startswith("spotify:track:"):
                body["uris"] = [uri]
            else:
                body["context_uri"] = uri
        self._request("PUT", "/me/player/play", json=body)
        return {"status": "playing"}

    def pause(self) -> dict:
        self._request("PUT", "/me/player/pause")
        return {"status": "paused"}

    def next_track(self) -> dict:
        self._request("POST", "/me/player/next")
        return {"status": "skipped"}

    def previous_track(self) -> dict:
        self._request("POST", "/me/player/previous")
        return {"status": "back"}

    def now_playing(self) -> dict:
        data = self._request("GET", "/me/player/currently-playing")
        if not data or not data.get("item"):
            return {"playing": False}
        item = data["item"]
        return {
            "playing": data.get("is_playing", False),
            "uri":     item["uri"],
            "name":    item["name"],
            "artist":  ", ".join(a["name"] for a in item["artists"]),
            "album":   item["album"]["name"],
            "progress_ms": data.get("progress_ms", 0),
            "duration_ms": item["duration_ms"],
        }

    def set_volume(self, percent: int) -> dict:
        percent = max(0, min(100, percent))
        self._request("PUT", "/me/player/volume", params={"volume_percent": percent})
        return {"status": "volume_set", "volume": percent}

    def get_saved_tracks(self, limit: int = 20) -> list:
        data = self._request("GET", "/me/tracks", params={"limit": min(limit, 50)})
        return [
            {"uri": i["track"]["uri"], "name": i["track"]["name"],
             "artist": ", ".join(a["name"] for a in i["track"]["artists"])}
            for i in data.get("items", []) if i.get("track")
        ]

    def save_track(self, track_id: str) -> dict:
        self._request("PUT", "/me/tracks", json={"ids": [track_id]})
        return {"status": "saved"}

    def get_playlists(self, limit: int = 20) -> list:
        data = self._request("GET", "/me/playlists", params={"limit": min(limit, 50)})
        return [{"uri": p["uri"], "name": p["name"]} for p in data.get("items", [])]

    def play_playlist_by_name(self, name: str) -> dict:
        hit = self.search(name, kind="playlist")
        if not hit["found"]:
            return {"found": False, "voice_response": f"I couldn't find a playlist called {name}."}
        self.play(hit["uri"])
        return {**hit, "voice_response": f"Playing the {hit['name']} playlist."}

    def get_recently_played(self, limit: int = 10) -> list:
        data = self._request("GET", "/me/player/recently-played", params={"limit": min(limit, 50)})
        return [
            {"uri": i["track"]["uri"], "name": i["track"]["name"],
             "artist": ", ".join(a["name"] for a in i["track"]["artists"])}
            for i in data.get("items", [])
        ]

    def play_similar(self, query: str) -> dict:
        hit = self.search(query, kind="track")
        if not hit["found"]:
            return {"found": False, "voice_response": f"I couldn't find {query}."}
        track_id  = hit["uri"].split(":")[-1]
        artist_id = self._request("GET", f"/tracks/{track_id}")["artists"][0]["id"]
        rec = self._request("GET", "/recommendations",
                            params={"seed_tracks": track_id, "seed_artists": artist_id, "limit": 20})
        uris = [t["uri"] for t in rec.get("tracks", [])]
        if not uris:
            return {"found": False, "voice_response": "I couldn't find similar tracks."}
        self.play(uris=uris)
        return {"status": "playing", "voice_response": f"Playing music similar to {hit['name']}."}

    def get_queue(self) -> dict:
        data = self._request("GET", "/me/player/queue")
        upcoming = [
            {"uri": t["uri"], "name": t["name"],
             "artist": ", ".join(a["name"] for a in t["artists"])}
            for t in data.get("queue", [])
        ]
        return {"upcoming": upcoming}

    def add_to_queue(self, uri: str) -> dict:
        self._request("POST", "/me/player/queue", params={"uri": uri})
        return {"status": "queued"}

    def set_repeat(self, state: str = "track") -> dict:
        self._request("PUT", "/me/player/repeat", params={"state": state})
        return {"status": "repeat_set", "repeat": state}

    def set_shuffle(self, on: bool = True) -> dict:
        self._request("PUT", "/me/player/shuffle", params={"state": str(on).lower()})
        return {"status": "shuffle_set", "shuffle": on}

    def seek(self, position_ms: int = 0) -> dict:
        self._request("PUT", "/me/player/seek", params={"position_ms": max(0, position_ms)})
        return {"status": "seeked", "position_ms": position_ms}

    def handle_intent(self, intent: str, query: str = "") -> dict:
        try:
            if intent == "play":
                if not query:
                    result = self.play()
                    return {**result, "voice_response": "Resuming."}
                hit = self.search(query, kind="track")
                if not hit["found"]:
                    return {"found": False, "voice_response": f"I couldn't find {query} on Spotify."}
                self.play(hit["uri"])
                return {**hit, "voice_response": f"Playing {hit['name']} by {hit['artist']}."}

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
                return {"status": "volume_set", "volume": pct, "voice_response": f"Volume set to {pct} percent."}

            if intent == "now_playing":
                np = self.now_playing()
                if not np["playing"]:
                    return {**np, "voice_response": "Nothing is playing."}
                return {**np, "voice_response": f"This is {np['name']} by {np['artist']}."}

            if intent == "favourites":
                tracks = self.get_saved_tracks(limit=30)
                if not tracks:
                    return {"found": False, "voice_response": "You don't have any saved songs yet."}
                self.play(uris=[t["uri"] for t in tracks])
                return {"status": "playing", "track_count": len(tracks), "voice_response": "Playing your favourites."}

            if intent == "save":
                np = self.now_playing()
                if not np.get("playing"):
                    return {"voice_response": "Nothing is playing to save."}
                self.save_track(np["uri"].split(":")[-1])
                return {"status": "saved", "voice_response": f"Saved {np['name']} to your library."}

            if intent == "playlist":
                if not query:
                    playlists = self.get_playlists(limit=10)
                    if not playlists:
                        return {"voice_response": "You don't have any playlists."}
                    names = ", ".join(p["name"] for p in playlists[:5])
                    return {"playlists": playlists, "voice_response": f"Your playlists include: {names}."}
                return self.play_playlist_by_name(query)

            if intent == "recent":
                recent = self.get_recently_played(limit=10)
                if not recent:
                    return {"voice_response": "No recent listening history."}
                if query:
                    self.play(uri=recent[0]["uri"])
                    return {**recent[0], "status": "playing",
                            "voice_response": f"Playing {recent[0]['name']} by {recent[0]['artist']}."}
                names = ", ".join(t["name"] for t in recent[:5])
                return {"recent": recent, "voice_response": f"Recently you listened to: {names}."}

            if intent == "similar":
                return self.play_similar(query)

            if intent == "queue":
                if not query:
                    q = self.get_queue()
                    if not q["upcoming"]:
                        return {"voice_response": "The queue is empty."}
                    names = ", ".join(t["name"] for t in q["upcoming"][:5])
                    return {**q, "voice_response": f"Coming up: {names}."}
                hit = self.search(query, kind="track")
                if not hit["found"]:
                    return {"found": False, "voice_response": f"I couldn't find {query}."}
                self.add_to_queue(hit["uri"])
                return {**hit, "voice_response": f"Added {hit['name']} by {hit['artist']} to the queue."}

            if intent == "repeat":
                state = query if query in ("track", "context", "off") else "track"
                self.set_repeat(state)
                label = "off" if state == "off" else f"on ({state})"
                return {"status": "repeat_set", "voice_response": f"Repeat is {label}."}

            if intent == "shuffle":
                on = query.lower() not in ("off", "false", "0") if query else True
                self.set_shuffle(on)
                return {"status": "shuffle_set", "voice_response": f"Shuffle {'on' if on else 'off'}."}

            if intent == "restart":
                self.seek(0)
                return {"status": "restarted", "voice_response": "Starting over."}

            return {"error": "unknown_intent", "voice_response": "I'm not sure what you'd like me to play."}

        except PremiumRequiredError:
            return {"error": "premium_required",
                    "voice_response": "Spotify needs a Premium account for me to play music. Could a family member help set that up?"}
        except NoActiveDeviceError:
            return {"error": "no_device",
                    "voice_response": "I can't reach the speaker right now. Let me try again in a moment."}
        except SpotifyError as e:
            return {"error": "spotify_error", "detail": str(e), "voice_response": "Something went wrong with Spotify."}


if __name__ == "__main__":
    import sys
    h      = SpotifyHandler()
    intent = sys.argv[1] if len(sys.argv) > 1 else "now_playing"
    query  = " ".join(sys.argv[2:])
    print(json.dumps(h.handle_intent(intent, query), indent=2))
