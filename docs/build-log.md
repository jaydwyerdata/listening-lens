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

## Open as of this entry

- Does the CSV actually load into `core.listening_history`? (Trends tab rendering real data is the proof, not app installation.)
- Does the `snowflake_database` / `CORTEX_USER` manifest block actually let the Discover tab's `COMPLETE` call succeed?
- Is `streamlit/environment.yml`'s `dependencies: []` fix actually sufficient, or does dropping the Streamlit-app's builtin charting need something declared after all?
- Is `llama3.1-8b` (pinned in `streamlit/listening_lens.py`) actually available in this account's region? Not checked yet.
