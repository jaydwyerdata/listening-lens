"""
One-time parse of Spotify's official "Extended Streaming History" export for
Listening Lens.

This is an alternative to pull_spotify_data.py, not a replacement for it. Both
scripts write the exact same CSV schema to the exact same path
(data/listening_history.csv), so the Native App's setup script and manifest
need zero changes regardless of which one you ran. Use pull_spotify_data.py
if you don't have an export yet (instant, but thin: last ~50 plays plus
ranked top-items). Use this script once Spotify's privacy-settings export has
actually arrived (can take up to 30 days, but gives real multi-year play
history instead of a ranking).

Running this OVERWRITES data/listening_history.csv. It does not merge with a
previous pull_spotify_data.py run.

Schema notes that came out of actually inspecting a real export, not assumed
from Spotify's docs:

1. The export's "Streaming_History_Audio_*.json" files are real play events,
   one row per stream, with a timestamp (`ts`) and a play duration
   (`ms_played`). Unlike the Web API path, there is no ranking here, so every
   row written by this script has `rank = None` and `source =
   "extended_history"`.
2. A small number of rows (103 out of 131,935 in the export this was built
   against) have null track/artist metadata. These are podcast or audiobook
   plays that Spotify's export puts in the audio history file alongside music
   plays; they carry `episode_name` instead of `master_metadata_track_name`.
   Dropped here, since this app is about music listening, not podcasts.
3. The export also includes separate "Streaming_History_Video_*.json" files
   (video content, 443 rows in the export this was built against). Not read
   by this script at all: out of scope for a music listening app, and a
   different content type (podcast video / video podcasts) than what the
   Trends and Discover tabs are built to analyze.
4. Roughly two-thirds of raw audio rows (89,466 of 131,832 rows with real
   track/artist metadata, in the export this was built against) have
   ms_played under 30 seconds: previews, accidental taps, and skips, not
   something a person would call "listening to a song." Spotify's own
   documentation doesn't give a public official threshold for what counts as
   a play, but 30 seconds is the commonly cited industry figure (used
   historically for royalty-counting purposes) and matches the intuitive
   line between "skipped past it" and "played it." Rows under that threshold
   are dropped, not just down-weighted, to keep the existing Trends tab
   queries (top artists, streaks) unchanged: they already assume every row in
   core.listening_history is a countable play or ranking entry, not a mix of
   real and near-zero listens.
5. genre_tags stays empty for every row here, same as recently_played and
   top_tracks rows from the Web API path: the export has no genre field at
   all. This is consistent with, not a new instance of, the genre gap
   documented in docs/requirements.md OQ-3.

Privacy: the export includes conn_country and ip_addr per row (Spotify logs
the network location of each play). Neither is read into the output CSV.
This keeps the same privacy boundary already documented in
docs/solution-design.md section 7: track and artist names only, nothing that
identifies where or on what network a play happened.
"""

import argparse
import csv
import json
import pathlib
import shutil
import tempfile
import zipfile

MIN_MS_PLAYED = 30_000  # 30 seconds; see docstring point 4

SCRIPT_DIR = pathlib.Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR.parent / "data" / "listening_history.csv"

FIELDNAMES = ["played_at", "track_name", "artist_name", "genre_tags", "source", "rank"]


def resolve_export_dir(export_path: pathlib.Path) -> pathlib.Path:
    """Accept either the unzipped export folder or the .zip Spotify emails a
    link to, so there's no manual unzip step to get wrong."""
    if export_path.is_dir():
        return export_path

    if export_path.suffix.lower() == ".zip":
        extract_dir = pathlib.Path(tempfile.mkdtemp(prefix="listening_lens_export_"))
        with zipfile.ZipFile(export_path) as zf:
            zf.extractall(extract_dir)
        # Spotify's export nests everything under one folder inside the zip.
        nested = list(extract_dir.glob("*Extended Streaming History*"))
        return nested[0] if nested else extract_dir

    raise FileNotFoundError(
        f"{export_path} is neither a directory nor a .zip file. Point this at "
        "either the unzipped export folder or the zip Spotify sent a download "
        "link for."
    )


def parse_audio_files(export_dir: pathlib.Path):
    audio_files = sorted(export_dir.glob("Streaming_History_Audio_*.json"))
    if not audio_files:
        raise FileNotFoundError(
            f"No Streaming_History_Audio_*.json files found under {export_dir}. "
            "Point this at the folder that directly contains them (usually "
            "named 'Spotify Extended Streaming History')."
        )

    rows = []
    dropped_no_metadata = 0
    dropped_under_threshold = 0

    for f in audio_files:
        with open(f, encoding="utf-8") as fh:
            entries = json.load(fh)
        for entry in entries:
            track = entry.get("master_metadata_track_name")
            artist = entry.get("master_metadata_album_artist_name")
            if not track or not artist:
                dropped_no_metadata += 1
                continue

            ms_played = entry.get("ms_played") or 0
            if ms_played < MIN_MS_PLAYED:
                dropped_under_threshold += 1
                continue

            rows.append(
                {
                    "played_at": entry.get("ts"),
                    "track_name": track,
                    "artist_name": artist,
                    "genre_tags": "",  # see docstring point 5
                    "source": "extended_history",
                    "rank": None,
                }
            )

    return rows, dropped_no_metadata, dropped_under_threshold, len(audio_files)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "export_path",
        type=pathlib.Path,
        help=(
            "Path to Spotify's Extended Streaming History export: either the "
            "unzipped folder (containing Streaming_History_Audio_*.json) or "
            "the .zip file itself."
        ),
    )
    args = parser.parse_args()

    export_dir = resolve_export_dir(args.export_path)
    rows, dropped_no_metadata, dropped_under_threshold, file_count = parse_audio_files(
        export_dir
    )

    if not rows:
        raise SystemExit(
            "Parsed 0 usable rows after filtering. Check that the export path "
            "actually contains audio history files with real listening data."
        )

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        writer.writerows(rows)

    earliest = min(r["played_at"] for r in rows)
    latest = max(r["played_at"] for r in rows)
    total_raw = len(rows) + dropped_no_metadata + dropped_under_threshold

    print(f"Read {file_count} audio history file(s), {total_raw} raw rows.")
    print(f"Dropped {dropped_no_metadata} rows with no track/artist metadata (podcast plays).")
    print(
        f"Dropped {dropped_under_threshold} rows under the {MIN_MS_PLAYED // 1000}s "
        f"counted-play threshold (skips/previews)."
    )
    print(f"Wrote {len(rows)} counted plays to {OUTPUT_PATH}")
    print(f"  date range: {earliest} to {latest}")
    print(
        "\nThis overwrote data/listening_history.csv. Run `snow app run` again "
        "to rebuild the application package with this data."
    )


if __name__ == "__main__":
    main()
