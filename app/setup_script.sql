-- Listening Lens setup script. Runs automatically at install/upgrade.
-- Not yet run against a real account; see the TODO block below before trusting
-- the data-load step specifically. Everything else here follows the documented
-- pattern from Snowflake's own Native App tutorial and Streamlit-in-app guide.

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

-- TODO, needs verifying against a real account: this is the one piece of this
-- script I don't have a confirmed pattern for. Two candidate approaches, from
-- two different Snowflake doc pages that didn't fully agree with each other:
--
-- (a) Reference the package's own bundled stage directly, something like:
--       COPY INTO core.listening_history
--       FROM @listening_lens_pkg.app_src.stage/data/listening_history.csv
--       FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"');
--     (app_src.stage is the default stage location per snowflake.yml; adjust
--     if that default doesn't match what `snow app run` actually creates.)
--
-- (b) Snowflake's documented "share data content" pattern instead treats
--     bundled data as a table created directly in a shared content schema
--     (populated by the provider before the version is created), exposed to
--     the app via a secure view, rather than a CSV loaded at setup time. See:
--     https://docs.snowflake.com/en/developer-guide/native-apps/preparing-data-content
--
-- Try (a) first, since it requires no change to the CSV pipeline already
-- built. Fall back to (b) if the stage reference doesn't resolve inside the
-- setup script's execution context.
--
-- COPY INTO core.listening_history
-- FROM @listening_lens_pkg.app_src.stage/data/listening_history.csv
-- FILE_FORMAT = (TYPE = CSV SKIP_HEADER = 1 FIELD_OPTIONALLY_ENCLOSED_BY = '"');

GRANT SELECT ON TABLE core.listening_history TO APPLICATION ROLE app_public;

-- Streamlit page. Syntax confirmed against Snowflake's own "Add a Streamlit
-- app" doc: https://docs.snowflake.com/en/developer-guide/native-apps/adding-streamlit
CREATE OR REPLACE STREAMLIT core.listening_lens_streamlit
    FROM '/streamlit'
    MAIN_FILE = '/listening_lens.py';

GRANT USAGE ON STREAMLIT core.listening_lens_streamlit TO APPLICATION ROLE app_public;
