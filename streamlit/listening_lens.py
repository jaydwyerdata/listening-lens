"""
Listening Lens: Streamlit-in-Snowflake app.

Two tabs, per docs/requirements.md FR-3 and FR-4 (both revised 2026-09-12 to
drop genre dependence, since Spotify's genre data came back empty on a real
pull, see OQ-3):

- Trends: top artists by a real date window, an hour-of-day view across all
  loaded plays, and the longest run of consecutive days with a play.
- Discover: a short Cortex-generated taste summary, built only from aggregated
  stats computed here, never from raw per-track rows (FR-4's privacy rule).

Confirmed live 2026-09-12 against a real Streamlit-in-Snowflake session: both
tabs render real data and the Cortex call succeeds. See docs/build-log.md for
the two account-level issues that surfaced along the way (a missing
application-level Cortex grant, and Snowflake's trial-account restriction on
AI functions), neither of which needed a code change here.

Revised 2026-09-13, after loading the Extended Streaming History (FR-7)
appeared to change nothing: every query here was still reading only the
original recently_played/top_artists_* rows from the Web API pull, since
that's all that existed when this file was first written. Top artists, hour
of day, and the longest streak all now read real played_at timestamps from
whichever sources have them (recently_played and extended_history), and the
time-window selector filters by actual date instead of relying on Spotify's
own opaque top-items ranking windows. See docs/build-log.md, 2026-09-13
entry, for the full diagnosis.

Also added 2026-09-13: FR-6, the reference/bind path. load_history() now
checks whether a consumer has bound listening_history_ref (via
SYSTEM$GET_ALL_REFERENCES) and reads that table instead of the bundled
sample when they have, with a caption showing which one is active. The
Trends tab also gained a drill-through under Top artists: picking an artist
shows the real underlying play rows for the selected window, live-queried
from whichever table is actually loaded.

Revised 2026-10-07, two display bugs caught reviewing the app before
recording: st.bar_chart sorts its x axis alphabetically, so Top artists read
A to Z despite a caption saying "most-played first" (now an Altair chart
sorted by play count); and hour of day and the streak were computed on raw
UTC timestamps, which put an all-night listening gap in the middle of the
afternoon (both now use DISPLAY_TIMEZONE). Window cutoffs stay in UTC, since
they compare instants, not local clock times.
"""

import datetime

import json
import re

import altair as alt
import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

# Confirmed available in this account's region, 2026-09-12.
CORTEX_MODEL = "llama3.1-8b"

# Sources that carry a real played_at timestamp, i.e. actual play events, not
# a ranking. top_tracks_*/top_artists_* rows have no played_at and are not
# used here; see docs/build-log.md, 2026-09-13 entry, for why relying on
# these instead of real play events was the actual bug that made the
# Extended Streaming History load (FR-7) look like it had done nothing.
PLAY_EVENT_SOURCES = ["recently_played", "extended_history"]

# Window lengths in days, applied against real played_at timestamps.
# Redefined 2026-09-13: originally these named Spotify's own opaque
# top-items ranking windows (top_artists_short_term etc.); now that real
# play-event timestamps exist at meaningful scale (post FR-7), computing an
# actual date-based window ourselves is both more transparent and no longer
# blind to the extended history. None means no cutoff, all real plays.
WINDOW_DAYS = {"short_term": 28, "medium_term": 182, "long_term": None}

# Spotify's export timestamps (`ts`) are UTC. Hour-of-day and day boundaries
# only mean something in the listener's own local time, so those views
# convert to this zone first. A config value, not a hard-coded assumption
# baked into the queries; change it here for a listener elsewhere.
DISPLAY_TIMEZONE = "Australia/Brisbane"
# Fallback if the runtime has no tz database: Brisbane observes no daylight
# saving, so a fixed UTC+10 offset is exact for this zone specifically.
DISPLAY_TIMEZONE_FALLBACK = datetime.timezone(datetime.timedelta(hours=10))

session = get_active_session()

st.set_page_config(page_title="Listening Lens", layout="wide")
st.title("Listening Lens")

trends_tab, discover_tab = st.tabs(["Trends", "Discover"])


def get_bound_reference_alias():
    """FR-6, added 2026-09-13: resolves the alias Snowflake assigned to
    whatever a consumer has bound to listening_history_ref, or None if
    nothing is bound. Uses SYSTEM$GET_ALL_REFERENCES, confirmed against
    Snowflake's own docs; returns a JSON array of {alias, database, schema,
    name} when something is bound, an empty array otherwise.

    Corrected 2026-09-13, live testing found the first version of this wrong:
    querying the bound table by its literal fully-qualified name
    (IDENTIFIER('db.schema.table')) fails with a misleading "database does
    not exist" error, because the application has no general USAGE on the
    consumer's database or schema, only the specific privilege captured by
    the reference itself. The correct, privilege-safe way to query through a
    reference is the framework's own reference() table function, which takes
    the reference name and this alias, not a literal object name. See
    docs/build-log.md, 2026-09-13 entry, for the full diagnosis."""
    result = session.sql(
        "SELECT SYSTEM$GET_ALL_REFERENCES('listening_history_ref', True) AS refs"
    ).collect()
    refs = json.loads(result[0]["REFS"])
    return refs[0]["alias"] if refs else None


@st.cache_data(ttl=600)
def load_history():
    """Returns (dataframe, source_label). Reads the bound reference table if
    a consumer has bound one (FR-6), otherwise falls back to the bundled
    sample loaded at install/upgrade."""
    alias = get_bound_reference_alias()
    if alias:
        df = session.sql(
            f"SELECT * FROM reference('listening_history_ref', '{alias}')"
        ).to_pandas()
        return df, "your own bound table"
    return session.table("core.listening_history").to_pandas(), "the bundled sample data"


def filter_by_window(real_plays: pd.DataFrame, days) -> pd.DataFrame:
    """Real plays within the last `days` (None = all time)."""
    if days is None:
        return real_plays
    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
    return real_plays[real_plays["PLAYED_AT"] >= cutoff]


def top_artists_by_window(real_plays: pd.DataFrame, days) -> pd.Series:
    """Real play counts per artist within the last `days` (None = all time),
    descending. Replaces relying on Spotify's own top_artists_* ranking rows,
    which never reflected the Extended Streaming History import at all."""
    return filter_by_window(real_plays, days).groupby("ARTIST_NAME").size().sort_values(ascending=False)


history, data_source_label = load_history()
st.caption(f"Currently showing: {data_source_label}.")

real_plays = history[history["SOURCE"].isin(PLAY_EVENT_SOURCES)].copy()
if not real_plays.empty:
    real_plays["PLAYED_AT"] = pd.to_datetime(real_plays["PLAYED_AT"], utc=True)
    try:
        real_plays["PLAYED_AT_LOCAL"] = real_plays["PLAYED_AT"].dt.tz_convert(DISPLAY_TIMEZONE)
    except Exception:
        real_plays["PLAYED_AT_LOCAL"] = real_plays["PLAYED_AT"].dt.tz_convert(
            DISPLAY_TIMEZONE_FALLBACK
        )

with trends_tab:
    window = st.selectbox(
        "Time window",
        options=["short_term", "medium_term", "long_term"],
        index=1,
        format_func=lambda w: {
            "short_term": "Last 4 weeks",
            "medium_term": "Last 6 months",
            "long_term": "All time",
        }[w],
    )

    windowed_plays = filter_by_window(real_plays, WINDOW_DAYS[window])
    top_artists = (
        windowed_plays.groupby("ARTIST_NAME").size().sort_values(ascending=False).head(10)
    )

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Top artists")
        if top_artists.empty:
            st.info("No plays loaded for this window yet.")
        else:
            top_artists_df = top_artists.rename_axis("Artist").reset_index(name="Plays")
            st.altair_chart(
                alt.Chart(top_artists_df)
                .mark_bar()
                .encode(
                    x=alt.X("Artist:N", sort="-y", title=None),
                    y=alt.Y("Plays:Q"),
                    tooltip=["Artist", "Plays"],
                ),
                use_container_width=True,
            )
            st.caption("Real play counts for the selected window, most-played first.")

            # Drill-through, added 2026-09-13: shows the real underlying play
            # rows behind a bar in the chart above, live-queried from
            # whichever table is actually loaded (bundled or bound via FR-6),
            # not a static illustration.
            drill_artist = st.selectbox(
                "Drill into an artist's real plays",
                options=top_artists.index.tolist(),
            )
            artist_plays = (
                windowed_plays[windowed_plays["ARTIST_NAME"] == drill_artist]
                .sort_values("PLAYED_AT", ascending=False)[["PLAYED_AT_LOCAL", "TRACK_NAME", "SOURCE"]]
                .rename(columns={"PLAYED_AT_LOCAL": "PLAYED_AT"})
                .head(200)
            )
            st.dataframe(artist_plays, hide_index=True, use_container_width=True)
            st.caption(
                f"{len(artist_plays):,} real plays for {drill_artist} in this window "
                f"(showing up to 200, most recent first)."
            )

    with col2:
        st.subheader("Listening by hour of day")
        if real_plays.empty:
            st.info("No play-event data loaded yet.")
        else:
            by_hour = (
                real_plays.groupby(real_plays["PLAYED_AT_LOCAL"].dt.hour)
                .size()
                .reindex(range(24), fill_value=0)
            )
            st.bar_chart(by_hour)
            st.caption(
                f"Based on {len(real_plays):,} real plays, all time, in {DISPLAY_TIMEZONE} time."
            )

    st.subheader("Longest streak")
    if real_plays.empty:
        st.info("No play-event data loaded yet.")
    else:
        play_dates = sorted(set(real_plays["PLAYED_AT_LOCAL"].dt.date))
        longest = current = 1 if play_dates else 0
        for i in range(1, len(play_dates)):
            if (play_dates[i] - play_dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1
        st.metric("Consecutive days with a play, all time", longest)

with discover_tab:
    st.subheader("Your taste, summarized")

    top5 = top_artists_by_window(real_plays, WINDOW_DAYS["medium_term"]).head(5).index.tolist()

    if not top5:
        st.info("Not enough data loaded yet to generate a summary.")
    else:
        # Aggregated only: five artist names, nothing else. No raw per-track
        # rows or timestamps leave this scope, per FR-4.
        prompt = (
            "In three to four friendly sentences, describe the likely music "
            "taste of someone whose top five most-listened artists recently "
            f"are: {', '.join(top5)}. Mention a possible genre or mood thread "
            "connecting them if one is plausible.\n\n"
            "Then, on a new line starting with exactly 'Recommendations:', "
            "suggest three to four specific artists or songs they likely "
            "haven't heard yet that fit this taste, each on its own line in "
            "the form 'Name - one-sentence reason why it fits'. Favor "
            "lesser-known or adjacent picks over the most obvious mainstream "
            "choice for each artist's genre."
        )

        if st.button("Generate summary"):
            with st.spinner("Asking Cortex..."):
                result = session.sql(
                    "SELECT SNOWFLAKE.CORTEX.COMPLETE(?, ?) AS summary",
                    params=[CORTEX_MODEL, prompt],
                ).collect()
            summary_text = result[0]["SUMMARY"]

            # Split into the taste summary and the recommendations list if the
            # model followed the requested format; fall back to showing the
            # raw response if it didn't, rather than silently dropping content
            # on a format assumption.
            if "Recommendations:" in summary_text:
                taste_part, rec_part = summary_text.split("Recommendations:", 1)
                st.write(taste_part.strip())
                st.subheader("You might also like")
                # One recommendation per line, as the prompt asks. Rendered as a
                # markdown list, since Streamlit's markdown merges single line
                # breaks into one paragraph (added 2026-10-07). Leading bullets
                # or numbering the model adds itself are stripped first, so
                # they don't double up.
                rec_lines = [
                    re.sub(r"^\s*(?:[-*\u2022]|\d+[.)])\s+", "", line).strip()
                    for line in rec_part.strip().splitlines()
                    if line.strip()
                ]
                st.markdown("\n".join(f"- {line}" for line in rec_lines))
            else:
                st.write(summary_text)

            with st.expander("What was actually sent to Cortex"):
                st.code(prompt)
