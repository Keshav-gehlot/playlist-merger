import os
import secrets
from pathlib import Path
from typing import Any

import spotipy
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from spotipy.oauth2 import SpotifyOAuth
from starlette.middleware.base import BaseHTTPMiddleware


class SessionIDMiddleware(BaseHTTPMiddleware):
    """Attach a random session ID cookie used to map server-side tokens in memory."""

    def __init__(self, app: FastAPI, cookie_name: str = "sp_session") -> None:
        super().__init__(app)
        self.cookie_name = cookie_name

    async def dispatch(self, request: Request, call_next):
        session_id = request.cookies.get(self.cookie_name)
        if not session_id:
            session_id = secrets.token_urlsafe(24)
            request.state.new_session_id = session_id
        request.state.session_id = session_id

        response = await call_next(request)
        if hasattr(request.state, "new_session_id"):
            response.set_cookie(
                self.cookie_name,
                request.state.new_session_id,
                httponly=True,
                secure=False,
                samesite="lax",
                max_age=60 * 60 * 24,
            )
        return response


app = FastAPI(title="Spotify Playlist Merger")
app.add_middleware(SessionIDMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"

CLIENT_ID = os.getenv("SPOTIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SPOTIFY_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("SPOTIFY_REDIRECT_URI", "http://localhost:8000/callback")
SCOPES = "playlist-read-private playlist-read-collaborative playlist-modify-private playlist-modify-public"

# Server-side token store keyed by secure HTTP-only session ID cookie.
TOKEN_STORE: dict[str, dict[str, Any]] = {}


class MergeRequest(BaseModel):
    playlist_ids: list[str] = Field(default_factory=list)
    new_playlist_name: str = Field(default="Merged Playlist")


def get_oauth() -> SpotifyOAuth:
    if not CLIENT_ID or not CLIENT_SECRET:
        raise HTTPException(
            status_code=500,
            detail="Spotify credentials are missing. Set SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET.",
        )

    return SpotifyOAuth(
        client_id=CLIENT_ID,
        client_secret=CLIENT_SECRET,
        redirect_uri=REDIRECT_URI,
        scope=SCOPES,
        open_browser=False,
    )


def get_spotify_client(request: Request) -> spotipy.Spotify:
    token_info = TOKEN_STORE.get(request.state.session_id)
    if not token_info or not token_info.get("access_token"):
        raise HTTPException(status_code=401, detail="Not authenticated with Spotify")
    return spotipy.Spotify(auth=token_info["access_token"])


@app.get("/")
def serve_index() -> FileResponse:
    return FileResponse(FRONTEND_DIR / "index.html")


app.mount("/frontend", StaticFiles(directory=FRONTEND_DIR), name="frontend")


@app.get("/login")
def login() -> RedirectResponse:
    oauth = get_oauth()
    auth_url = oauth.get_authorize_url()
    return RedirectResponse(auth_url)


@app.get("/callback")
def callback(request: Request, code: str | None = None, error: str | None = None):
    if error:
        raise HTTPException(status_code=400, detail=f"Spotify auth failed: {error}")
    if not code:
        raise HTTPException(status_code=400, detail="Missing OAuth authorization code")

    oauth = get_oauth()
    token_info = oauth.get_access_token(code=code, as_dict=True)
    TOKEN_STORE[request.state.session_id] = token_info
    return RedirectResponse(url="/")


@app.get("/playlists")
def playlists(request: Request) -> JSONResponse:
    sp = get_spotify_client(request)

    playlists_data: list[dict[str, Any]] = []
    offset = 0
    limit = 50

    while True:
        page = sp.current_user_playlists(limit=limit, offset=offset)
        items = page.get("items", [])
        for playlist in items:
            playlists_data.append(
                {
                    "id": playlist["id"],
                    "name": playlist["name"],
                    "tracks_total": playlist["tracks"]["total"],
                    "owner": playlist["owner"]["display_name"] or "Unknown",
                }
            )
        if not page.get("next"):
            break
        offset += limit

    return JSONResponse({"playlists": playlists_data})


@app.post("/merge")
def merge_playlists(payload: MergeRequest, request: Request) -> JSONResponse:
    if not payload.playlist_ids:
        raise HTTPException(status_code=400, detail="At least one playlist ID is required")

    sp = get_spotify_client(request)
    me = sp.current_user()
    user_id = me["id"]

    unique_uris: set[str] = set()

    for playlist_id in payload.playlist_ids:
        offset = 0
        while True:
            page = sp.playlist_items(
                playlist_id,
                fields="items(track(uri)),next",
                additional_types=["track"],
                limit=100,
                offset=offset,
            )
            for item in page.get("items", []):
                track = item.get("track")
                if track and track.get("uri"):
                    unique_uris.add(track["uri"])

            if not page.get("next"):
                break
            offset += 100

    if not unique_uris:
        raise HTTPException(status_code=400, detail="No tracks found in selected playlists")

    merged = sp.user_playlist_create(
        user=user_id,
        name=payload.new_playlist_name.strip() or "Merged Playlist",
        public=False,
        description="Merged automatically with Spotify Playlist Merger",
    )

    uris_list = list(unique_uris)
    for index in range(0, len(uris_list), 100):
        batch = uris_list[index : index + 100]
        sp.playlist_add_items(merged["id"], batch)

    return JSONResponse(
        {
            "message": "Playlists merged successfully",
            "new_playlist_id": merged["id"],
            "tracks_added": len(uris_list),
        }
    )


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse({"status": "ok"})
