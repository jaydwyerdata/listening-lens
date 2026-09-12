-- Listening Lens: one-time account bootstrap.
-- Run this once against any fresh Snowflake trial account before `snow app run`.
-- Idempotent where Snowflake supports it, safe to re-run.
--
-- Known deviation from the portability design in the ADR/solution design docs:
-- the GRANT below is hardcoded to a specific username (JayDai88) rather than a
-- placeholder. Decided 2026-09-12 to leave it as-is for now since this is a
-- single-account demo; revisit before the repo goes public or before handing
-- this to anyone redeploying to their own trial account. Swap the literal
-- username for <your_username> (and note the substitution in the README) at
-- that point.

CREATE ROLE IF NOT EXISTS listening_lens_role;
GRANT ROLE listening_lens_role TO USER JayDai88;

CREATE WAREHOUSE IF NOT EXISTS listening_lens_wh
  WAREHOUSE_SIZE = 'XSMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE;
GRANT ALL PRIVILEGES ON WAREHOUSE listening_lens_wh TO ROLE listening_lens_role;

-- Lets this role build and install the Native App locally, no Marketplace listing needed.
GRANT CREATE APPLICATION PACKAGE ON ACCOUNT TO ROLE listening_lens_role;
GRANT CREATE APPLICATION ON ACCOUNT TO ROLE listening_lens_role;

-- Needed for the Discover tab's Cortex COMPLETE calls.
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE listening_lens_role;

-- Switch into the role for everything that follows (snow CLI connection profile
-- should use this role, or this session should stay active before running `snow app run`).
USE ROLE listening_lens_role;
USE WAREHOUSE listening_lens_wh;
