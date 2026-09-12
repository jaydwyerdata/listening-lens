-- Listening Lens: grant Cortex access to the installed application.
-- Run once after every `snow app run` that creates a new application object
-- (not needed for upgrades of an existing one, the grant persists across those).
--
-- Confirmed live 2026-09-12: without this, the Discover tab's Cortex COMPLETE
-- call fails with "Unknown user-defined function SNOWFLAKE.CORTEX.COMPLETE."
-- The app/manifest.yml `snowflake_database: roles: - CORTEX_USER` block only
-- declares that the app wants this role, it does not grant it. An application
-- cannot grant itself a role that lives in Snowflake's own SNOWFLAKE database,
-- so this has to happen as a separate consumer-side step, run by a role with
-- MANAGE GRANTS (ACCOUNTADMIN works).
--
-- This is distinct from bootstrap_account.sql's
--   GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE listening_lens_role;
-- which grants the role to the human role that runs `snow app run`, not to
-- the resulting application object. Both are needed: one lets the role
-- install/manage the app, this one lets the installed app call Cortex.

GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO APPLICATION listening_lens_app;
