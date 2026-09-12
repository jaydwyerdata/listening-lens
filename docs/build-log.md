# Build log

Chronological record of what actually happened running this against a real Snowflake account, as opposed to what the design docs predicted. The ADR, requirements, and solution design docs stay focused on decisions and architecture; this is where the "and then it broke, here's why" detail lives.

## 2026-09-12: First successful install

Trial account created (Enterprise edition, a Cortex-supported region), `scripts/bootstrap_account.sql` run successfully: role, warehouse, `CREATE APPLICATION PACKAGE`/`CREATE APPLICATION ON ACCOUNT` privileges, and the `CORTEX_USER` database role all granted without issue.

Three fixes, all confirmed live against the real account except the last:

1. **`snowflake.yml`, the `debug` field.** Defaults to `true` per the CLI's own project-definition docs, but a `manifest_version: 2` app rejects that outright: `Cannot use debug mode on an application when manifest version is 2 or above. Please use session debugging.` Fixed to explicit `debug: false`. Worth knowing: this has to be set explicitly, omitting the field inherits the `true` default and fails the same way.

2. **`app/manifest.yml`, the Cortex access TODO, resolved.** Confirmed against Snowflake's own manifest-reference doc: Cortex access needs a `snowflake_database: roles: - CORTEX_USER` block, a different mechanism entirely from the `privileges` block (that one's for privileges in the consumer's own account, not roles that live in Snowflake's own `SNOWFLAKE` database). Not yet confirmed whether this alone is sufficient for `COMPLETE` calls to succeed, the Discover tab hasn't been reached yet in testing. That's a separate open item, not resolved by this fix.

3. **`streamlit/environment.yml`, two live failures before the fix.** First: `python==3.10` (double `=`) isn't valid Anaconda-channel spec syntax (`Anaconda dependency versions must be characters, numbers of one of [.+!]`). Fixed to single `=`. Second: `python=3.10` alone still failed differently (`Packages not found: python==3.10`), a Native-App-specific resolution failure, not a syntax one, the bundled Streamlit runtime doesn't resolve an explicit Python pin the way a standalone Streamlit object does. Fix: drop the pin entirely (`dependencies: []`), since nothing in this app actually needs a specific Python version. **This fix has not been verified live yet**, that's the immediate next step.

App installed successfully with:

```
snow app run -c listening_lens2 --role listening_lens_role --warehouse listening_lens_wh
```

Important distinction: a successful install confirms the setup script *ran*. It does not confirm `setup_script.sql`'s CSV-load step (the flagged TODO, option (a): `COPY INTO ... FROM @listening_lens_pkg.app_src.stage/data/listening_history.csv`) actually populated the table, or that the Streamlit page opens without error. Both are still open, checked next.

## 2026-09-12: CSV load fixed, Trends tab confirmed with real data

First render of the Trends tab after install showed empty state on all three panels (top artists, hour-of-day, streak). Root cause: `setup_script.sql`'s `COPY INTO` block was still commented out from the original TODO, the table got created on install but nothing ever loaded into it. A successful `snow app run` only proves the setup script executed, not that every statement in it did something.

Fix: uncommented the `COPY INTO core.listening_history FROM @listening_lens_pkg.app_src.stage/data/listening_history.csv ...` statement. Before doing that, checked that `scripts/pull_spotify_data.py`'s CSV column order (`played_at, track_name, artist_name, genre_tags, source, rank`) matches the table's column order exactly, since a positional `COPY INTO` with no explicit column list would otherwise misalign silently rather than error.

Re-ran `snow app run` to trigger the upgrade path against the existing install, which re-executes the setup script. Confirmed live: Trends tab now renders real data, ten top artists, an hour-of-day distribution, and a 4-day longest streak, all matching the actual pulled Spotify history.

`streamlit/environment.yml`'s `dependencies: []` fix is now also confirmed live as a side effect: the Streamlit page rendered and the built-in `st.bar_chart` calls worked with no dependency errors, so nothing extra needs declaring there.

## 2026-09-12: Cortex COMPLETE call, manifest block confirmed insufficient alone

First click of "Generate summary" on the Discover tab failed: `SnowparkSQLException (1304): SQL compilation error: Unknown user-defined function SNOWFLAKE.CORTEX.COMPLETE.` This answers the open question from the previous entry, and the answer is no, the `snowflake_database: roles: - CORTEX_USER` manifest block is not sufficient by itself.

Root cause: that manifest block only declares that the app *wants* the `CORTEX_USER` database role, it does not grant it. The application still needs the role granted to it explicitly, as a separate consumer-side action, after install or upgrade. The app cannot grant itself a role that lives in Snowflake's own `SNOWFLAKE` database, that has to come from outside.

Fix, run once per install (as a role with `MANAGE GRANTS`, `ACCOUNTADMIN` in this case):

```sql
GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO APPLICATION listening_lens_app;
```

This is distinct from `scripts/bootstrap_account.sql`'s `GRANT DATABASE ROLE SNOWFLAKE.CORTEX_USER TO ROLE listening_lens_role`, which grants the role to the human role that *runs* `snow app run`, not to the resulting application object itself. Both grants are needed: one lets the role install/manage the app, the other lets the installed app call Cortex.

## 2026-09-12: Cortex blocked at the account-tier level, not the app level

After the grant fix above, the same button produced a different error: `SnowparkSQLException (1304): 0A000: AI function COMPLETE is not available for trial accounts.` This is not a manifest, grant, or code problem, every layer of the app's own Cortex-access chain (manifest declaration, application-level grant) was correct. The remaining gate is Snowflake's own trial-account policy.

Confirmed against Snowflake's own trial account documentation: a trial account without a payment method on file has restricted access to Cortex AI Functions. Independent reports (a near-identical "quickstart says trial works, trial account throws a hard error" pattern for a different Cortex-adjacent feature, compute pools, on a separate Snowflake quickstart) corroborate that this class of restriction on trial accounts is real and not specific to this app.

Decision: add a payment method to the trial account rather than work around this in code, there's no code-level workaround for an account-tier policy gate. Checked first, from Snowflake's own docs, that this is low-risk: adding a payment method converts the trial to a paid account without ending the trial period, so existing free trial credits (400 USD on this account, essentially untouched) get drawn down first, and charges only start once those credits are exhausted or the 30-day trial period ends, whichever comes first. The one caveat worth documenting: trial/paid accounts can't be self-canceled through the web interface, closing one to guarantee zero further charges requires contacting Snowflake Support directly, it isn't a self-service toggle.

## Open as of this entry

- Payment method not yet added. Once it is: does `COMPLETE` succeed, and is `llama3.1-8b` (pinned in `streamlit/listening_lens.py`) actually available in this account's region? Both confirmed or ruled out by the same next test.
