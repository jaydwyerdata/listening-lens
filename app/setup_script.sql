-- Listening Lens setup script. Runs automatically at install/upgrade.

CREATE APPLICATION ROLE IF NOT EXISTS app_public;

CREATE SCHEMA IF NOT EXISTS core;
GRANT USAGE ON SCHEMA core TO APPLICATION ROLE app_public;

CREATE TABLE IF NOT EXISTS core.listening_history (
    played_at    TIMESTAMP_NTZ,
    track_name   STRING,
    artist_name  STRING,
    genre_tags   STRING,   -- pipe-delimited; see docs/solution-design.md section 6
    source       STRING,
    rank         NUMBER
);

-- Loads the bundled sample CSV at install/upgrade time. Two candidate approaches
-- existed for this (referencing the package's own bundled stage directly, vs.
-- Snowflake's documented "share data content" pattern of a provider-populated
-- table exposed via a secure view). Went with the stage reference below since it
-- needed no change to the existing CSV pipeline; the column list in the CSV
-- (data/listening_history.csv, written by scripts/pull_spotify_data.py) matches
-- this table's column order exactly, confirmed 2026-09-12, so no explicit column
-- mapping is needed here.
--
-- Uncommented 2026-09-12 after confirming the table was created but staying
-- empty on first install, since this block had been left commented out pending
-- a live test.
--
-- TRUNCATE added 2026-09-13, a real bug found while verifying the Extended
-- Streaming History load (FR-7): without it, every upgrade's COPY INTO just
-- appends to whatever the table already had, since CREATE TABLE IF NOT EXISTS
-- means the table survives across upgrades. Confirmed live: after replacing
-- data/listening_history.csv with a 42,366-row extended-history export and
-- re-running `snow app run`, the table held 42,696 rows, the new data plus
-- the original 330-row bundled sample, never cleared. TRUNCATE makes each
-- upgrade a clean reload instead of an accumulation.
TRUNCATE TABLE core.listening_history;

COPY INTO core.listening_history
FROM @listening_lens_pkg.app_src.stage/data/listening_history.csv
FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"');

GRANT SELECT ON TABLE core.listening_history TO APPLICATION ROLE app_public;

-- Streamlit page. Syntax confirmed against Snowflake's own "Add a Streamlit
-- app" doc: https://docs.snowflake.com/en/developer-guide/native-apps/adding-streamlit
CREATE OR REPLACE STREAMLIT core.listening_lens_streamlit
    FROM '/streamlit'
    MAIN_FILE = '/listening_lens.py';

GRANT USAGE ON STREAMLIT core.listening_lens_streamlit TO APPLICATION ROLE app_public;
