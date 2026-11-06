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

Decision: add a payment method to the trial account rather than work around this in code, there's no code-level workaround for an account-tier policy gate. Checked first, from Snowflake's own docs, that this is low-risk: adding a payment method converts the trial to a paid account without ending the trial period, so existing free trial credits (400 USD on this account, essentially untouched) get drawn down first, and charges only start once those credits are exhausted or the 30-day trial period ends, whichever comes first. The one caveat worth documenting: trial/paid accounts can't be self-cancelled through the web interface, closing one to guarantee zero further charges requires contacting Snowflake Support directly, it isn't a self-service toggle.

## 2026-09-12: Discover tab confirmed working end to end

Payment method added to the trial account. Reloaded the Discover tab and clicked "Generate summary" again: real Cortex output, no errors, a multi-sentence taste summary referencing actual top artists from the loaded data (Dan Gibson's Solitudes, Alex Warren, Gyptian), with a genre-thread observation and a suggested-artist recommendation, matching FR-4's acceptance criteria.

This closes both remaining open items from the previous entry in one test: the trial-account restriction was the only real blocker (payment method resolved it, as expected from Snowflake's docs), and `llama3.1-8b` is confirmed available in this account's region, no model swap needed.

Both tabs of the core demo (FR-1 through FR-5) are now confirmed working live against a real Snowflake account with real personal data. Remaining work is Phase 2 scope: the consumer reference/bind path (FR-6), not yet built, and the demo recording.

## 2026-09-12: Discover tab, strengthened the recommendations

The original prompt only asked Cortex to "suggest one direction to explore next," which produced a single throwaway artist mention buried at the end of the paragraph, thin for a tab literally called Discover. Reworked the prompt to explicitly ask for a separate `Recommendations:` section, three to four specific artist or song picks, each with a one-line reason, biased toward lesser-known or adjacent choices rather than the obvious mainstream pick for each genre.

Still aggregation-only per FR-4: the model only ever sees the same five top-artist names as before, nothing new is exposed. Streamlit side now splits the response on `Recommendations:` into two sections (the taste summary, then a "You might also like" subheader), with a fallback to showing the raw response unsplit if the model doesn't follow the requested format exactly, since silently dropping content on a formatting assumption would be worse than an unsplit block of text.

Confirmed live after redeploying with the new `listening_lens_pat` connection profile: the model followed the requested format exactly, a four-sentence taste summary followed by a distinct "You might also like" section naming four specific artists (Kaidon, Yung Gud, The Black Seeds, L'indécis), each with a one-line reason tied back to the top-artist input. Both tabs of the core demo are now fully working end to end, including this refinement.

## 2026-09-12: Upgrading from trial to paid account triggered a mandatory MFA requirement

Adding a payment method (to unblock Cortex, see above) converted the account from trial to paid, which brought Snowflake's own MFA enforcement policy into effect. This broke the existing `listening_lens2` connection profile's login flow for interactive CLI use, since it now stops on an MFA prompt each time rather than completing headlessly.

Considered key-pair authentication first (the more established route), but switched to a Programmatic Access Token (PAT) instead, generated via Snowsight after setting up the account's required network policy. PATs are simpler to provision for a single local dev machine and don't need an RSA key pair generated and registered against the user.

Two real mistakes made getting this working, both worth recording since they cost real debugging time:

1. **Wrong mechanism assumed.** First attempt configured the new connection profile with `authenticator = "PROGRAMMATIC_ACCESS_TOKEN"` and a `token_file_path` field, based on a secondary source, not Snowflake's own documentation. This produced `Password is empty` on `snow connection test`, since neither field is real: Snowflake's own PAT documentation confirms a PAT is used as a drop-in replacement for the password itself, with the Python connector (which the `snow` CLI wraps) taking it via the plain `password` parameter, no special authenticator value or token-file mechanism involved. Lesson: verify CLI/connector-specific auth mechanisms against Snowflake's own docs directly, a plausible-sounding secondary source turned out to be wrong here.
2. **TOML backslash escaping.** A separate, unrelated mistake while the wrong mechanism above was still in place: the `token_file_path` value was a double-quoted TOML string containing a literal Windows path (`"C:\Users\...`, standards:allow). TOML basic (double-quoted) strings treat backslash as an escape character, and `\U` is TOML's syntax for an 8-digit Unicode escape, so `\Users` was parsed as a broken Unicode escape, producing `Configuration file seems to be corrupted. Invalid unicode value`. Moot once the `token_file_path` field was removed entirely, but the general lesson holds for any future Windows path written into TOML: use forward slashes, or a single-quoted TOML literal string, never an unescaped backslash inside double quotes.

Final working configuration: a new `listening_lens_pat` connection profile with `account`, `user`, and `password` (the PAT value) set directly, no special authenticator. `snow connection test -c listening_lens_pat` confirmed working. `snow app run` and related commands now use `-c listening_lens_pat` instead of `-c listening_lens2` going forward, avoiding the MFA prompt entirely for CLI use.

One more wrinkle surfaced running `snow app run` with `--role listening_lens_role` against the new profile: `Role 'LISTENING_LENS_ROLE' specified in the connect string is not granted to this user`, despite the role genuinely being granted. Root cause, confirmed against Snowflake's own PAT documentation: a PAT is permanently bound to whichever role is active when it's generated (`ACCOUNTADMIN` in this case, matching the earlier `snow connection test` output), and `--role` can't override that at connection time regardless of what the user actually has granted elsewhere. Tokens can't be rescoped after creation, generating a new one scoped to `listening_lens_role` is the only way to change it.

Bypassed rather than regenerating a token: ran `GRANT ROLE listening_lens_role TO ROLE ACCOUNTADMIN`, so `ACCOUNTADMIN` (the PAT's bound role) now inherits everything `listening_lens_role` had. Works, but worth being honest about the tradeoff: this is a real, permanent deviation from `bootstrap_account.sql`'s original design, which was a dedicated, narrower role for running the CLI rather than doing everything as `ACCOUNTADMIN`. Fine for a solo demo account with no other consumers; the "do it properly" fix, if it ever matters, is a second PAT scoped to `listening_lens_role` directly instead of widening `ACCOUNTADMIN`.

## 2026-09-13: Extended Streaming History arrived, pulled FR-7 forward

The export requested from Spotify's privacy settings on 2026-09-11 arrived today, a `my_spotify_data.zip` containing 13 `Streaming_History_Audio_*.json` files (2018 through 2026) and 4 `Streaming_History_Video_*.json` files. FR-7 (Extended Streaming History ingestion) was scoped as Phase 2/future specifically because this export could take up to 30 days, longer than a days-not-weeks build. It arrived before the demo was recorded, so that constraint no longer applied, decided to pull it forward and build the ingestion now rather than record with the thinner API-sourced sample.

Inspected the export before writing any code, rather than assuming its shape matched the API-sourced data:

- 131,935 raw audio rows total, no genre field anywhere (consistent with the existing gap, not a new one), but each row carries `conn_country` and `ip_addr`, real network-location data per play that the API-sourced rows never had. Decision: never read either field into the parser's output, keeping the same "track and artist names only" privacy boundary already documented in `docs/solution-design.md` section 7.
- 103 rows had no `master_metadata_track_name`/`master_metadata_album_artist_name`: podcast plays that Spotify's export mixes into the audio history file. Dropped, this app is about music.
- The video history files (443 rows total) were left unread entirely: different content type, out of scope for what the Trends and Discover tabs analyse.
- The real surprise: 89,466 of the remaining 131,832 rows, 67.9%, had `ms_played` under 30 seconds. Spotify doesn't publish an official "what counts as a play" threshold, and the API-sourced data never surfaced this question at all (`recently_played` only returns tracks that already finished or were actively playing, `top_tracks`/`top_artists` are rankings with no per-play duration). Decided on a 30-second cutoff, the commonly cited industry figure, and to drop rows under it entirely rather than keep them with a flag, so the existing Trends tab queries (top artists, streaks) don't need to change to account for a mix of real and near-zero listens.

Built `scripts/parse_extended_history.py`: pure standard library (json, csv, pathlib, zipfile), no network calls, accepts either the unzipped export folder or the `.zip` directly. Writes to the same `data/listening_history.csv` path and column order `pull_spotify_data.py` already produces (`played_at, track_name, artist_name, genre_tags, source, rank`, with `source = "extended_history"` and `rank` always null since these are play events, not rankings), so `manifest.yml` and `setup_script.sql` need zero changes. Running it overwrites whatever `data/listening_history.csv` currently holds; it doesn't merge with a prior `pull_spotify_data.py` run.

Ran it against the real export: 42,366 rows written, spanning 2018-06-04 to 2026-09-11. Top artists shift meaningfully once the 30-second filter is applied (Dan Gibson's Solitudes jumps from 6th to 2nd by play count, for example), confirming the threshold decision actually matters and wasn't just a cosmetic filter.

Not yet done: rebuilding the app against this CSV (`snow app run`) and re-verifying the Trends and Discover tabs at 42,366 rows instead of the ~330-row sample they were last confirmed against. Flagging this specifically since a 100x-plus jump in row count is exactly the kind of change that can surface a query that only worked by accident at small scale (an unindexed scan, an implicit row-count assumption in a chart call). Next step, not yet started.

## 2026-09-13: extended history loaded, but two real bugs made it look like nothing changed

Ran `snow app run` against the new `data/listening_history.csv` (42,366 rows). Trends tab loaded without error, but the "Longest streak" metric still read 4, identical to before, despite 8 years of real listening history now being loaded. That's not a plausible coincidence for a genuine 100x-plus jump in data, so treated it as a bug rather than an unlikely-but-possible result.

Checked the table directly in Snowsight: `SELECT COUNT(*) FROM listening_lens_app.core.listening_history` returned 42,696, not 42,366. The difference, exactly 330, is the original bundled sample's row count. Root cause: `setup_script.sql`'s `COPY INTO` had no `TRUNCATE` before it, and `CREATE TABLE IF NOT EXISTS` means the table survives every upgrade. Every `snow app run` since the original install had been appending to the table, not replacing it. Fix: added `TRUNCATE TABLE core.listening_history;` immediately before the `COPY INTO`.

That alone wouldn't have explained the unchanged streak, though, since even the old 330 rows sitting alongside the new 42,366 should have shifted a streak calculated over all of it. Read `streamlit/listening_lens.py` directly rather than guessing further: every query in the Trends and Discover tabs filtered to specific `source` values that predate FR-7 entirely. The longest-streak and hour-of-day logic filtered to `source = 'recently_played'` only (the ~50-row Web API sample); top artists and the Discover tab's input filtered to `source = 'top_artists_medium_term'` (Spotify's own pre-computed ranking). Neither code path had ever been touched when `extended_history` rows were added, so all 42,366 new rows were being loaded into the table and then completely ignored by every chart in the app.

Fix, in `streamlit/listening_lens.py`: introduced `PLAY_EVENT_SOURCES = ["recently_played", "extended_history"]`, the set of sources that carry a real `played_at` timestamp, and rewrote top artists, hour-of-day, the streak, and the Discover tab's top-5 input to all read from that combined set instead of a single hardcoded source. This also meant reworking what the "time window" selector means: it used to select one of Spotify's own opaque `top_artists_{window}` ranking rows; now that real play-event timestamps exist at meaningful scale, it filters by actual elapsed days (28 / 182 / all-time) computed from `played_at` directly, which is both more transparent and no longer blind to whatever source the play events came from.

Broader lesson for the build log: FR-7's acceptance criteria only checked that the parser produced correct output and that the table received it. Neither checked that the *application code consuming the table* actually used the new rows. A schema-level change (new `source` value) is invisible to any query that hardcodes a different `source` value, and that gap doesn't show up as an error, it shows up as a suspiciously unchanged number. Worth remembering for FR-6 (the reference/bind path) too, whenever that gets built: loading data correctly and using it correctly are two separate things to verify.

Re-ran `snow app run` with both fixes in place. Confirmed live: row count exactly 42,366 (no more duplication), longest streak now 87 days, Discover tab's Cortex call still succeeds at this scale. FR-7 and the FR-3/FR-4 re-verification are now closed out.

One more real-data observation worth recording, not a bug: the top artists panel now surfaces Dan Gibson's Solitudes (ambient/relaxation music) prominently, real background listening (used to settle the kids), not a mistaken pick. Raw play count doesn't distinguish a deliberately chosen track from one left running continuously as background audio, both count the same way once a play clears the 30-second threshold. Not something FR-3 requires accounting for, and no fix planned, just noted here since it's the kind of nuance worth being able to explain if it comes up.

## 2026-09-13: FR-6 reference/bind path built and confirmed, plus an artist drill-through

With the extended history loaded and the app looking noticeably more like a real product, decided the remaining time was better spent finishing FR-6 (the reference/bind path, deferred since the original ADR) than polishing the UI around a read-only dataset. Built both FR-6 and a UI drill-through in the same pass.

**FR-6 build.** Added a `references` block to `app/manifest.yml` (`listening_history_ref`, `TABLE`, `SELECT`, single-valued, `register_callback: core.register_single_reference`), and the callback procedure itself in `setup_script.sql`, confirmed against Snowflake's own docs (`developer-guide/native-apps/requesting-refs`) rather than guessed: `ADD`/`REMOVE` go through `SYSTEM$SET_REFERENCE`/`SYSTEM$REMOVE_REFERENCE`, `CLEAR` through `SYSTEM$REMOVE_ALL_REFERENCES`. Built `scripts/test_fr6_reference_bind.sql`, a throwaway 5-row table (two distinct artists, a short streak) specifically so a bind is obvious at a glance against the 42,366-row bundled data.

**Bug 1: `GRANT MONITOR` mistaken for `GRANT USAGE`.** First bind attempt failed: `Database 'MY_OWN_DATA' does not exist or not authorized`, despite having granted `MONITOR ON DATABASE`, `USAGE ON SCHEMA`, and `SELECT ON ALL TABLES IN SCHEMA` to `listening_lens_role`. Root cause: `MONITOR` only permits metadata visibility (`SHOW`/`DESCRIBE`), not traversal; it is not a substitute for `USAGE`, which was never actually granted on the database itself. Fix: `GRANT USAGE ON DATABASE my_own_data TO ROLE listening_lens_role;`.

**Bug 2: querying a bound reference by literal name, a code mistake, not a grant gap.** The same error persisted after the grant fix, this time from inside the Streamlit app itself, traced via the error's line number to `load_history()`. Different root cause entirely: the Streamlit app runs as the application object (`listening_lens_app`), a separate principal from `listening_lens_role`, and the first version of this code queried the bound table with `SELECT * FROM IDENTIFIER('db.schema.table')`, which needs general database/schema `USAGE` that a reference never grants to the application, only the specific table-level privilege `SYSTEM$REFERENCE` captured. Confirmed against Snowflake's own documented mechanism: the fix is `SELECT * FROM reference('listening_history_ref', alias)`, a table function built specifically to read through a reference's narrower grant, no separate database/schema `USAGE` needed. Rewrote `get_bound_reference_table()` into `get_bound_reference_alias()` (resolves just the alias via `SYSTEM$GET_ALL_REFERENCES`) and `load_history()` to query through `reference()` instead.

**Confirmed live, both directions.** Binding the 5-row test table: caption switched to "your own bound table", top artists showed only the two test artists, streak was short as expected, drill-through matched. Running the commented `CLEAR` statement to unbind: fell back cleanly to the full 42,366-row bundled data, correct top artists (Dan Gibson's Solitudes, Alex Warren, Vex King), correct hour-of-day distribution, drill-through showing real timestamps and the `extended_history` source.

**Same day, unplanned: artist drill-through.** Reviewing the app while testing FR-6 made an existing gap obvious: no filtering or drill-through anywhere, just static charts. Added a drill-through under Top artists: a dropdown of the current window's top artists, selecting one shows up to 200 real underlying play rows (timestamp, track, source), live-queried from whichever table is actually loaded, not a static illustration. Caught one bug via self-review before showing Jay, not user-reported: the first version filtered the drill-through against all-time plays while its caption claimed "in this window". Fixed by refactoring both the windowed top-artists computation and the drill-through to share one `filter_by_window()` helper, so they can no longer disagree.

Broader lesson, consistent with the one from the FR-7 entry above: both bugs here were "looks right, isn't" failures, not startup-time errors. A missing `TRUNCATE`, a hardcoded source filter, an over-broad grant assumption, and a literal-identifier query all installed and ran without complaint; every one of them needed an actual number or an actual error message to catch, not a code review alone.

## 2026-10-07: pre-recording review, one data-quality fix and two display bugs

Reviewing the live app before recording surfaced three problems, all "looks right, isn't" again, none of them errors.

**Household listening in the history.** A children's bedtime album played nightly on the same Spotify account (Dan Gibson's Solitudes, 1,089 plays, plus the same tracks under a second credit, plain "Dan Gibson", 403 plays) ranked second all time and sat at the top of the 6-month window that feeds the Discover tab's Cortex prompt, so it skewed the taste summary as well as the charts. Same class of problem as the 30-second threshold: the export is faithful to what played, not to what the account holder actually listens to. Fix: `parse_extended_history.py` gained a repeatable `--exclude-artist` flag (exact name match, so both credits are listed; nothing excluded by default). The export zip isn't kept in the repo, so the identical rule was applied once to the existing `data/listening_history.csv`: 42,366 rows to 40,874, 1,492 dropped. To reproduce from a fresh export: `python scripts/parse_extended_history.py <export.zip> --exclude-artist "Dan Gibson's Solitudes" --exclude-artist "Dan Gibson"`.

**Top artists sorted A to Z.** `st.bar_chart` sorts a categorical x axis alphabetically, so the chart read Alkaline, Busy Signal, Dan Gibson's Solitudes... directly above a caption saying "most-played first". The Series was sorted correctly; the chart discarded that order. Replaced with an Altair bar chart sorted by play count (`sort="-y"`).

**Hour of day in UTC.** Spotify's `ts` is UTC, and the hour-of-day chart grouped on it raw, which showed zero listening from 13:00 to 19:00 and a peak at 21:00: overnight and early morning in Brisbane, shifted ten hours. The streak had the same flaw at the day boundary. Both now use a `DISPLAY_TIMEZONE` setting (Australia/Brisbane, with a fixed UTC+10 fallback since Brisbane has no daylight saving); the drill-through shows local times too. Window cutoffs stay in UTC, since they compare instants rather than clock times.

**After redeploy** (predicted by a dry run of the app's own logic against the new CSV; all confirmed live the same day): 40,874 plays; all-time top artist Taylor Swift (1,155); 6-month top five Kes, Hezron, Alex Warren, Duane Stephenson, Vex King; hour-of-day peaks at 07:00 and 16:00 to 18:00 with the quiet hours overnight; longest streak 70 days (down from 87, from both the exclusion and local-time day boundaries).

**Same day, Discover tab polish.** The "You might also like" recommendations rendered as one run-on paragraph, because Streamlit's markdown merges single line breaks. Now split per line and rendered as a list, stripping only genuine list markers the model adds (`-`, `*`, `1.`, `2)`), so an artist name that starts with a digit is left intact. Confirmed live after redeploy.

**Same day, two FR-6 bugs found recording the bind/unbind clip.**

- *Stale data source after unbind.* After `CLEAR` and a page reload, the app kept showing the bound 5-row table ("Showing cache...") before switching back. `load_history()` resolved the binding inside a `@st.cache_data` function with no arguments, so a bind or unbind didn't change the cache key and the previous source was served until the 10-minute TTL or an eviction. Fix: the binding alias is resolved on every run and passed in as the cached function's argument, so each data source caches separately and a bind or unbind always takes effect on the next run. The FR-6 confirmation on 13 Sep passed because nothing had been cached under the other state yet.
- *Drill-through crash on a tiny result.* With the bound test table, the drill-through table intermittently failed with "Minified React error #185" (maximum update depth exceeded), then rendered fine on a later run at a different window size. Read as a resize loop in Streamlit's table component when auto height and container width interact on a very small table; not reproduced deterministically, so the fix is defensive: an explicit height and natural width.

Also: `scripts/test_fr6_reference_bind.sql` now inserts with `SYSDATE()` (UTC) instead of `CURRENT_TIMESTAMP()`, which returned the account's US Pacific session time and put the test rows at about 02:42 Brisbane time after the app's local-time conversion.

## Open as of this entry

- FR-6 (the reference/bind path) and the Trends tab drill-through are both built and confirmed live, bind and unbind. Everything through FR-7 and FR-6 is now confirmed working live. Remaining: recording the demo.

## 2026-10-07: Demo recorded, nothing open

The demo was recorded and linked from the README: [youtu.be/dOxFxmPNGrs](https://youtu.be/dOxFxmPNGrs). The item left open above is closed; no further build work is planned for this scope.
