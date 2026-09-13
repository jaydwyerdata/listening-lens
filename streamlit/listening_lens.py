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
"""

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

session = get_active_session()

st.set_page_config(page_title="Listening Lens", layout="wide")
st.title("Listening Lens")

trends_tab, discover_tab = st.tabs(["Trends", "Discover"])


@st.cache_data(ttl=600)
def load_history() -> pd.DataFrame:
    return session.table("core.listening_history").to_pandas()


def top_artists_by_window(real_plays: pd.DataFrame, days) -> pd.Series:
    """Real play counts per artist within the last `days` (None = all time),
    descending. Replaces relying on Spotify's own top_artists_* ranking rows,
    which never reflected the Extended Streaming History import at all."""
    if days is not None:
        cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=days)
        real_plays = real_plays[real_plays["PLAYED_AT"] >= cutoff]
    return real_plays.groupby("ARTIST_NAME").size().sort_values(ascending=False)


history = load_history()

real_plays = history[history["SOURCE"].isin(PLAY_EVENT_SOURCES)].copy()
if not real_plays.empty:
    real_plays["PLAYED_AT"] = pd.to_datetime(real_plays["PLAYED_AT"], utc=True)

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

    top_artists = top_artists_by_window(real_plays, WINDOW_DAYS[window]).head(10)

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Top artists")
        if top_artists.empty:
            st.info("No plays loaded for this window yet.")
        else:
            st.bar_chart(top_artists)
            st.caption("Real play counts for the selected window, most-played first.")

    with col2:
        st.subheader("Listening by hour of day")
        if real_plays.empty:
            st.info("No play-event data loaded yet.")
        else:
            by_hour = (
                real_plays.groupby(real_plays["PLAYED_AT"].dt.hour)
                .size()
                .reindex(range(24), fill_value=0)
            )
            st.bar_chart(by_hour)
            st.caption(f"Based on {len(real_plays):,} real plays, all time.")

    st.subheader("Longest streak")
    if real_plays.empty:
        st.info("No play-event data loaded yet.")
    else:
        play_dates = sorted(set(real_plays["PLAYED_AT"].dt.date))
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
                st.write(rec_part.strip())
            else:
                st.write(summary_text)

            with st.expander("What was actually sent to Cortex"):
                st.code(prompt)
