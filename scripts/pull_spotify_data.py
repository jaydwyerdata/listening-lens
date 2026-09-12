"""
One-time pull of Spotify listening data for Listening Lens.

Pulls three things from the Spotify Web API, using your own account (Authorization
Code flow, not Client Credentials, since these scopes are user-specific):

- Recently played tracks (last ~50 plays): real play events, each with a timestamp.
- Top tracks, across short/medium/long_term windows: a ranking, not play events.
- Top artists, across the same three windows: also a ranking.

All three are flattened into one CSV, data/listening_history.csv. Schema notes that
came out of actually building this against the live API, not from the design doc
alone:

1. `played_at` and `track_name` are nullable. Only recently-played rows are real
   play events with a timestamp; top-tracks/top-artists rows are rankings and get
   a `rank` (1-50) instead. Top-artists rows have no specific track, so
   `track_name` is null there.
2. `genre_tags` is populated ONLY for top-artists rows, by design, not as a data
   gap to fix later. Spotify's "Get Several Artists" batch endpoint (the only way
   to look up genres for an artist you only know from a track, since track objects
   embed a simplified artist with no genre data) was removed from Development Mode
   as part of Spotify's February 2026 platform changes; confirmed by a live 403 on
   this exact call while building this script, and again in the endpoint list of
   Spotify's own migration guide. Top-artists rows are unaffected because
   `current_user_top_artists` returns full artist objects with genres inline, no
   separate lookup needed, so they're the only source of genre data here.

Separately, note Spotify now requires the app owner's account to have an active
Premium subscription for any Development Mode app (also part of the February 2026
changes). Not something this script can detect or work around; if the Spotify
Developer Dashboard flags your app for this, that's Spotify's account-level gate,
not a bug here.

Requires a Spotify Developer app (Web API scope) and a filled-in .env (see
.env.example). First run opens a browser tab to approve access; spotipy runs a
small local server on your redirect URI to catch the response automatically, then
caches the resulting token next to this script so later runs don't need
re-approval.
"""

import csv
import os
import pathlib

from dotenv import load_dotenv
import spotipy
from spotipy.oauth2 import SpotifyOAuth

SCOPE = "user-read-recently-played user-top-read"
TOP_TIME_RANGES = ["short_term", "medium_term", "long_term"]

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR.parent / "data" / "listening_history.csv"
CACHE_PATH = SCRIPT_DIR / ".cache-listening-lens"

FIELDNAMES = ["played_at", "track_name", "artist_name", "genre_tags", "source", "rank"]


def get_client():
    load_dotenv()
    auth_manager = SpotifyOAuth(
        client_id=os.environ["SPOTIFY_CLIENT_ID"],
        client_secret=os.environ["SPOTIFY_CLIENT_SECRET"],
        redirect_uri=os.environ["SPOTIFY_REDIRECT_URI"],
        scope=SCOPE,
        cache_path=str(CACHE_PATH),
    )
    return spotipy.Spotify(auth_manager=auth_manager)


def pull_recently_played(sp):
    rows = []
    for item in sp.current_user_recently_played(limit=50)["items"]:
        track = item["track"]
        artist = track["artists"][0]
        rows.append(
            {
                "played_at": item["played_at"],
                "track_name": track["name"],
                "artist_name": artist["name"],
                "genre_tags": "",  # not available: see module docstring, point 2
                "source": "recently_played",
                "rank": None,
            }
        )
    return rows


def pull_top_tracks(sp):
    rows = []
    for time_range in TOP_TIME_RANGES:
        items = sp.current_user_top_tracks(time_range=time_range, limit=50)["items"]
        for rank, track in enumerate(items, start=1):
            artist = track["artists"][0]
            rows.append(
                {
                    "played_at": None,
                    "track_name": track["name"],
                    "artist_name": artist["name"],
                    "genre_tags": "",  # not available: see module docstring, point 2
                    "source": f"top_tracks_{time_range}",
                    "rank": rank,
                }
            )
    return rows


def pull_top_artists(sp):
    """The only source of genre data in this dataset: current_user_top_artists
    returns full artist objects with genres inline, so no separate lookup is
    needed (or, since Spotify's February 2026 changes, possible)."""
    rows = []
    for time_range in TOP_TIME_RANGES:
        items = sp.current_user_top_artists(time_range=time_range, limit=50)["items"]
        for rank, artist in enumerate(items, start=1):
            genres = artist.get("genres") or []
            rows.append(
                {
                    "played_at": None,
                    "track_name": None,
                    "artist_name": artist["name"],
                    "genre_tags": "|".join(genres),
                    "source": f"top_artists_{time_range}",
                    "rank": rank,
                }
            )
    return rows


def main():
    sp = get_client()

    recently_played_rows = pull_recently_played(sp)
    top_track_rows = pull_top_tracks(sp)
    top_artist_rows = pull_top_artists(sp)

    all_rows = recently_played_rows + top_track_rows + top_artist_rows

    top_artist_rows_with_genres = sum(1 for r in top_artist_rows if r["genre_tags"])

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(all_rows)

    print(f"Wrote {len(all_rows)} rows to {OUTPUT_PATH}")
    print(f"  recently_played: {len(recently_played_rows)}")
    print(f"  top_tracks (3 windows): {len(top_track_rows)}")
    print(f"  top_artists (3 windows): {len(top_artist_rows)}")
    print(
        f"  top_artists rows with at least one genre tag: "
        f"{top_artist_rows_with_genres} of {len(top_artist_rows)}"
    )


if __name__ == "__main__":
    main()
