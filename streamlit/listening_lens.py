"""
Listening Lens: Streamlit-in-Snowflake app.

Two tabs, per docs/requirements.md FR-3 and FR-4 (both revised 2026-09-12 to
drop genre dependence, since Spotify's genre data came back empty on a real
pull, see OQ-3):

- Trends: top artists by ranking window, an hour-of-day view of recent plays,
  and the longest run of consecutive days with a play.
- Discover: a short Cortex-generated taste summary, built only from aggregated
  stats computed here, never from raw per-track rows (FR-4's privacy rule).

Confirmed live 2026-09-12 against a real Streamlit-in-Snowflake session: both
tabs render real data and the Cortex call succeeds. See docs/build-log.md for
the two account-level issues that surfaced along the way (a missing
application-level Cortex grant, and Snowflake's trial-account restriction on
AI functions), neither of which needed a code change here.
"""

import pandas as pd
import streamlit as st
from snowflake.snowpark.context import get_active_session

# Confirmed available in this account's region, 2026-09-12.
CORTEX_MODEL = "llama3.1-8b"

session = get_active_session()

st.set_page_config(page_title="Listening Lens", layout="wide")
st.title("Listening Lens")

trends_tab, discover_tab = st.tabs(["Trends", "Discover"])


@st.cache_data(ttl=600)
def load_history() -> pd.DataFrame:
    return session.table("core.listening_history").to_pandas()


history = load_history()

with trends_tab:
    window = st.selectbox(
        "Time window",
        options=["short_term", "medium_term", "long_term"],
        index=1,
        format_func=lambda w: {
            "short_term": "Last ~4 weeks",
            "medium_term": "Last ~6 months",
            "long_term": "All time (Spotify's estimate)",
        }[w],
    )

    top_artists = (
        history[history["SOURCE"] == f"top_artists_{window}"]
        .sort_values("RANK")
        .head(10)[["RANK", "ARTIST_NAME"]]
    )

    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Top artists")
        if top_artists.empty:
            st.info("No top-artists data loaded for this window yet.")
        else:
            st.bar_chart(top_artists.set_index("ARTIST_NAME")["RANK"].sort_values())
            st.caption("Lower bar = higher rank (1 is your most-listened artist).")

    with col2:
        st.subheader("Listening by hour of day")
        recent = history[history["SOURCE"] == "recently_played"].copy()
        if recent.empty:
            st.info("No recently-played data loaded yet.")
        else:
            recent["PLAYED_AT"] = pd.to_datetime(recent["PLAYED_AT"])
            recent["hour"] = recent["PLAYED_AT"].dt.hour
            by_hour = recent.groupby("hour").size().reindex(range(24), fill_value=0)
            st.bar_chart(by_hour)
            st.caption(
                "Based on your last ~50 plays only, so this is a snapshot, not a "
                "full pattern. Gets more meaningful if the Extended Streaming "
                "History export (docs/requirements.md FR-7) is ever folded in."
            )

    st.subheader("Longest streak")
    if recent.empty:
        st.info("No recently-played data loaded yet.")
    else:
        play_dates = sorted(set(recent["PLAYED_AT"].dt.date))
        longest = current = 1 if play_dates else 0
        for i in range(1, len(play_dates)):
            if (play_dates[i] - play_dates[i - 1]).days == 1:
                current += 1
                longest = max(longest, current)
            else:
                current = 1
        st.metric("Consecutive days with a play (recent window)", longest)

with discover_tab:
    st.subheader("Your taste, summarized")

    top5 = (
        history[history["SOURCE"] == "top_artists_medium_term"]
        .sort_values("RANK")
        .head(5)["ARTIST_NAME"]
        .tolist()
    )

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
