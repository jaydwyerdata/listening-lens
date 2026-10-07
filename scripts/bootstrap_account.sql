-- Listening Lens: one-time account bootstrap.
-- Run this once against any fresh Snowflake trial account before `snow app run`.
-- Idempotent where Snowflake supports it, safe to re-run.
--
-- The role is granted to whoever runs this script (CURRENT_USER()), so no
-- username is hardcoded and it works unchanged on any account. Replaced a
-- hardcoded username on 2026-10-07, before the repo went public; confirmed
-- live the same day.

CREATE ROLE IF NOT EXISTS listening_lens_role;
SET bootstrap_user = CURRENT_USER();
GRANT ROLE listening_lens_role TO USER IDENTIFIER($bootstrap_user);

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
