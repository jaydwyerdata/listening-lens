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

## 2026-09-12: Discover tab confirmed working end to end

Payment method added to the trial account. Reloaded the Discover tab and clicked "Generate summary" again: real Cortex output, no errors, a multi-sentence taste summary referencing actual top artists from the loaded data (Dan Gibson's Solitudes, Alex Warren, Gyptian), with a genre-thread observation and a suggested-artist recommendation, matching FR-4's acceptance criteria.

This closes both remaining open items from the previous entry in one test: the trial-account restriction was the only real blocker (payment method resolved it, as expected from Snowflake's docs), and `llama3.1-8b` is confirmed available in this account's region, no model swap needed.

Both tabs of the core demo (FR-1 through FR-5) are now confirmed working live against a real Snowflake account with real personal data. Remaining work is Phase 2 scope: the consumer reference/bind path (FR-6), not yet built, and the demo recording.

## 2026-09-12: Discover tab, strengthened the recommendations

The original prompt only asked Cortex to "suggest one direction to explore next," which produced a single throwaway artist mention buried at the end of the paragraph, thin for a tab literally called Discover. Reworked the prompt to explicitly ask for a separate `Recommendations:` section, three to four specific artist or song picks, each with a one-line reason, biased toward lesser-known or adjacent choices rather than the obvious mainstream pick for each genre.

Still aggregation-only per FR-4: the model only ever sees the same five top-artist names as before, nothing new is exposed. Streamlit side now splits the response on `Recommendations:` into two sections (the taste summary, then a "You might also like" subheader), with a fallback to showing the raw response unsplit if the model doesn't follow the requested format exactly, since silently dropping content on a formatting assumption would be worse than an unsplit block of text. Not yet re-tested live against the account, that's the next step after redeploying.

## 2026-09-12: Upgrading from trial to paid account triggered a mandatory MFA requirement

Adding a payment method (to unblock Cortex, see above) converted the account from trial to paid, which brought Snowflake's own MFA enforcement policy into effect. This broke the existing `listening_lens2` connection profile's login flow for interactive CLI use, since it now stops on an MFA prompt each time rather than completing headlessly.

Considered key-pair authentication first (the more established route), but switched to a Programmatic Access Token (PAT) instead, generated via Snowsight after setting up the account's required network policy. PATs are simpler to provision for a single local dev machine and don't need an RSA key pair generated and registered against the user.

Two real mistakes made getting this working, both worth recording since they cost real debugging time:

1. **Wrong mechanism assumed.** First attempt configured the new connection profile with `authenticator = "PROGRAMMATIC_ACCESS_TOKEN"` and a `token_file_path` field, based on a secondary source, not Snowflake's own documentation. This produced `Password is empty` on `snow connection test`, since neither field is real: Snowflake's own PAT documentation confirms a PAT is used as a drop-in replacement for the password itself, with the Python connector (which the `snow` CLI wraps) taking it via the plain `password` parameter, no special authenticator value or token-file mechanism involved. Lesson: verify CLI/connector-specific auth mechanisms against Snowflake's own docs directly, a plausible-sounding secondary source turned out to be wrong here.
2. **TOML backslash escaping.** A separate, unrelated mistake while the wrong mechanism above was still in place: the `token_file_path` value was a double-quoted TOML string containing a literal Windows path (`"C:\Users\...`). TOML basic (double-quoted) strings treat backslash as an escape character, and `\U` is TOML's syntax for an 8-digit Unicode escape, so `\Users` was parsed as a broken Unicode escape, producing `Configuration file seems to be corrupted. Invalid unicode value`. Moot once the `token_file_path` field was removed entirely, but the general lesson holds for any future Windows path written into TOML: use forward slashes, or a single-quoted TOML literal string, never an unescaped backslash inside double quotes.

Final working configuration: a new `listening_lens_pat` connection profile with `account`, `user`, and `password` (the PAT value) set directly, no special authenticator. `snow connection test -c listening_lens_pat` confirmed working. `snow app run` and related commands now use `-c listening_lens_pat` instead of `-c listening_lens2` going forward, avoiding the MFA prompt entirely for CLI use.

One more wrinkle surfaced running `snow app run` with `--role listening_lens_role` against the new profile: `Role 'LISTENING_LENS_ROLE' specified in the connect string is not granted to this user`, despite the role genuinely being granted. Root cause, confirmed against Snowflake's own PAT documentation: a PAT is permanently bound to whichever role is active when it's generated (`ACCOUNTADMIN` in this case, matching the earlier `snow connection test` output), and `--role` can't override that at connection time regardless of what the user actually has granted elsewhere. Tokens can't be rescoped after creation, generating a new one scoped to `listening_lens_role` is the only way to change it.

Bypassed rather than regenerating a token: ran `GRANT ROLE listening_lens_role TO ROLE ACCOUNTADMIN`, so `ACCOUNTADMIN` (the PAT's bound role) now inherits everything `listening_lens_role` had. Works, but worth being honest about the tradeoff: this is a real, permanent deviation from `bootstrap_account.sql`'s original design, which was a dedicated, narrower role for running the CLI rather than doing everything as `ACCOUNTADMIN`. Fine for a solo demo account with no other consumers; the "do it properly" fix, if it ever matters, is a second PAT scoped to `listening_lens_role` directly instead of widening `ACCOUNTADMIN`.

## Open as of this entry

- None for the core (Phase 1) demo. Phase 2 (FR-6, the reference/bind path) has not been started.
