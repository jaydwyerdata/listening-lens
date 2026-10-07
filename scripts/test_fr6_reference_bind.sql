-- FR-6 test harness: a small, obviously-distinct table to bind to
-- listening_history_ref, so the bind is easy to confirm visually (a handful
-- of rows and a short streak look nothing like the 42,366-row bundled data).
-- Not part of the app itself, just a one-time local test fixture. Run this
-- as ACCOUNTADMIN (or another role with CREATE DATABASE).
--
-- Sequence: run section 1 to create the test table, section 2 to bind it,
-- open the app and confirm the Trends tab now shows this small dataset
-- instead of the bundled sample, then section 3 to unbind and confirm it
-- falls back to the bundled data again. Section 4 is cleanup.

-- 1. Create a standalone table matching the schema documented in
--    docs/solution-design.md section 6 (played_at, track_name, artist_name,
--    genre_tags, source, rank), with a handful of distinctive rows.
CREATE DATABASE IF NOT EXISTS my_own_data;
CREATE SCHEMA IF NOT EXISTS my_own_data.public;

CREATE OR REPLACE TABLE my_own_data.public.sample_listening_history (
    played_at    TIMESTAMP_NTZ,
    track_name   STRING,
    artist_name  STRING,
    genre_tags   STRING,
    source       STRING,
    rank         NUMBER
);

-- SYSDATE() is UTC, matching how the app reads played_at (as UTC, like
-- Spotify's export). CURRENT_TIMESTAMP() returns the account's session time
-- zone, which lands these rows hours off once the app converts to local time.
INSERT INTO my_own_data.public.sample_listening_history
    (played_at, track_name, artist_name, genre_tags, source, rank)
VALUES
    (DATEADD(day, 0, SYSDATE()), 'Reference Test Track One', 'FR-6 Test Artist', '', 'extended_history', NULL),
    (DATEADD(day, -1, SYSDATE()), 'Reference Test Track Two', 'FR-6 Test Artist', '', 'extended_history', NULL),
    (DATEADD(day, -2, SYSDATE()), 'Reference Test Track Three', 'FR-6 Test Artist', '', 'extended_history', NULL),
    (DATEADD(day, -3, SYSDATE()), 'Another Reference Track', 'Second Test Artist', '', 'extended_history', NULL),
    (DATEADD(day, -4, SYSDATE()), 'Another Reference Track Two', 'Second Test Artist', '', 'extended_history', NULL);

-- 2. Bind it. SYSTEM$REFERENCE('TABLE', <fully qualified name>, 'PERSISTENT', <privileges...>)
--    authorizes the app to access this specific table with the privileges
--    listed; the app's register_single_reference procedure then registers it
--    against listening_history_ref via SYSTEM$SET_REFERENCE. Adjust the app
--    name below if it differs from listening_lens_app in your account.
CALL listening_lens_app.core.register_single_reference(
    'listening_history_ref',
    'ADD',
    SYSTEM$REFERENCE('TABLE', 'my_own_data.public.sample_listening_history', 'PERSISTENT', 'SELECT')
);

-- Confirm the bind registered:
-- SELECT SYSTEM$GET_ALL_REFERENCES('listening_history_ref', True);

-- Now reload the Streamlit page. The caption at the top of the Trends tab
-- should read "Currently showing: your own bound table (...)", top artists
-- should show only FR-6 Test Artist / Second Test Artist, and the longest
-- streak should be a short one (this test data is deliberately only 5 rows
-- across 5 consecutive days).

-- 3. Unbind, to fall back to the bundled sample again.
-- CALL listening_lens_app.core.register_single_reference(
--     'listening_history_ref', 'CLEAR', NULL);

-- 4. Cleanup, once you're done testing (optional, this database has no other purpose).
-- DROP DATABASE IF EXISTS my_own_data;
