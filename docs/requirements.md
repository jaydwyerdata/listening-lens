# Listening Lens: Requirements

**Status:** Draft
**Date:** 2026-09-11
**Author:** Jay

## Purpose

This is the requirements baseline for Listening Lens, a Snowflake Native App demo built to close a named skills gap on the "Road to Snowflake SE" plan (hands-on Native Apps Framework experience). It complements [`docs/adr/0001-architecture.md`](adr/0001-architecture.md), which covers the *why* behind the technical decisions. This document defines the *what*: the scope, the functional and non-functional requirements, and what is explicitly out of scope.

## Goals

1. Produce a working, installable Snowflake Native App that demonstrates the application package lifecycle, the setup script contract, application roles, and Streamlit-in-Snowflake, end to end.
2. Demonstrate the Native App references/bind mechanism, the more advanced half of the framework that a bundled-data-only demo would skip.
3. Produce a public repository, documented to a standard a hiring manager or SE interviewer can read and understand without a walkthrough.
4. Produce a short recorded demo suitable for linking from a resume.
5. Do all of the above without depending on anything outside Jay's control (data-export queues, Marketplace review, employer systems).

## Non-Goals

This is a solo portfolio demo, not a product. The following are explicitly out of scope, not oversights:

- **Multi-tenant or concurrent-consumer support.** The app is built, installed, and demoed within one account by one person. No load testing, no concurrency handling.
- **Cost optimization or production monitoring.** No warehouse right-sizing work, no alerting, no observability beyond what's needed to debug the build.
- **Production-grade security hardening.** Privileges requested follow least-privilege practice (see NFR-5), but this is not a security review target and won't get one.
- **Full Extended Streaming History ingestion in v1.** Supporting the official multi-year export format is a Phase 2/future item (FR-7), not required for the core demo.
- **Any employer data, account, or tooling.** Everything runs on a personal trial account, entirely separate from Jay's actual job.

## Personas

Single persona for this demo: **Jay, acting as both provider and consumer of the same application**, in the same account. There is no separate end-user population. Requirements below are written as if a real consumer existed (for realism and to keep the app generalizable), but no multi-user testing is required.

## Functional Requirements

### Phase 1: Core demo (P0, must-have)

**FR-1: Pull Spotify listening data**
The system shall pull the user's recently-played tracks and top artists/tracks from the Spotify Web API and write them to a flattened dataset for Snowflake to load.
- [x] Given a registered Spotify Developer app and a valid OAuth token, when `pull_spotify_data.py` runs, then it writes a CSV with no missing required fields (track, artist, played-at timestamp; genre tags are captured where the API provides them, but are not required, see FR-3). Confirmed 2026-09-12: 330 real rows written.
- [x] The script works against the developer's own account in Spotify's Development Mode, with no app review dependency. Confirmed 2026-09-12.

**FR-2: Load bundled sample data at install**
The Native App's setup script shall load the bundled sample dataset into the application's own schema during installation.
- [x] After `snow app run` completes, the application's core schema contains the listening history table, populated and queryable from the app's own objects. Confirmed live 2026-09-12, after fixing a commented-out `COPY INTO` step, see `docs/build-log.md`.

**FR-3: Trends tab**
The Streamlit "Trends" tab shall show top artists over a selectable time window, a listening-by-hour-of-day heatmap, and the longest listening streak. A genre breakdown is shown only when the loaded dataset actually has genre tags; it is not a required view (revised 2026-09-12: a live pull against Jay's own account returned genre tags for 0 of 130 top-artists rows, so this can't be a dependable feature; see OQ-3).
- [x] Top artists, the heatmap, and the streak view render without error using the loaded dataset. Confirmed live 2026-09-12 with real Spotify data (ten top artists, an hour-of-day distribution, a 4-day streak).
- [ ] Changing the time window updates the displayed results. Not yet exercised in testing, only the default window has been checked.
- [x] If genre tags are present in the loaded data, a genre view is shown; if not, the tab degrades cleanly with no broken or empty chart, and no error. Moot in practice since genre tags are empty (OQ-3), the tab has no genre section at all, which is the clean-degrade outcome this criterion asks for.

**FR-4: Discover tab**
The Streamlit "Discover" tab shall generate a short natural-language taste summary using Cortex `COMPLETE`, built only from aggregated statistics, never raw per-track rows.
- [x] The summary is multiple coherent sentences and references at least one artist or listening-pattern insight visible in the Trends tab (a genre reference is a bonus, not required, per FR-3). Confirmed live 2026-09-12, after adding a payment method to the trial account cleared Snowflake's trial-tier restriction on Cortex AI functions (see `docs/build-log.md`): a real multi-sentence summary referencing actual top artists (Dan Gibson's Solitudes, Alex Warren, Gyptian), with a genre-thread observation and a recommendation.
- [x] The SQL passed to `COMPLETE` contains only aggregated fields; this is checked by reading the query, not just the output. Verified by code inspection and now also against a live successful call, both agree: only the top-5 artist names are sent.

**FR-5: Local install, no Marketplace dependency**
The application shall install and run entirely within a single account acting as both provider and consumer.
- [x] `snow app run` and the following Streamlit session complete with no listing, review, or Marketplace-related step involved. Confirmed live 2026-09-12.

### Phase 2: Bring-your-own-data (P1/P2)

**FR-6 (P1): Consumer reference for listening history**
The manifest shall define an optional Native App reference letting a consumer bind their own listening-history table instead of the bundled sample.
- [ ] A consumer can grant the reference to a table matching the expected schema.
- [ ] Once bound, the Trends and Discover tabs reflect the bound table's data instead of the bundled sample.
- [ ] This path is demonstrated on its own (recording or write-up), not relied on for the main demo take, per the ADR's risk decision.

**FR-7 (P2, future): Extended Streaming History ingestion**
Support loading the official Spotify Extended Streaming History export (JSON) directly, enabling full multi-year history instead of the thin API-sourced window.
- [ ] Not required for v1. Documented here so the schema design in FR-1/FR-2 doesn't accidentally make this harder later.

## Non-Functional Requirements

**NFR-1: Data boundary**
Only the account owner's own data is processed. No employer accounts, systems, or data are touched at any point in build, test, or demo.
- [ ] Repo and demo recording contain no references to employer account identifiers, warehouses, or data.

**NFR-2: Portability**
The project must be fully redeployable to a new Snowflake trial account using only what's committed to the repo, excluding local credentials and generated data files.
- [ ] Following the README's "Redeploying to a new trial account" steps on a fresh trial account produces a working install with no undocumented manual steps.

**NFR-3: Documentation standard**
Every component is documented to a standard suitable for public portfolio review.
- [ ] A reader unfamiliar with the project can understand what it does, why it was built this way, and how to run it, using only the repo's docs (README, this document, the ADR, the demo script).

**NFR-4: Usability (qualitative)**
The Streamlit page loads and responds without a noticeable delay for a single-user demo session.
- [ ] No numeric target is set; this is a solo demo with no real user base or SLA. Judged by feel during the demo recording, re-recorded if something visibly lags.

**NFR-5: Least privilege**
Privileges requested by the app (the manifest's `privileges` block) are limited to what each feature actually needs, each carrying a stated description.
- [ ] Every entry in the manifest's `privileges` block maps to a specific feature in this document; nothing is requested "just in case."

## Open Questions

- **OQ-1, resolved 2026-09-12, and reframed:** the original question assumed the risk was credit sufficiency. The real answer, found by actually testing the Discover tab, is different and more fundamental: Snowflake's trial-account policy blocks Cortex AI function calls outright for a trial account with no payment method on file, this is an account-tier gate, not a usage-quota one, confirmed against Snowflake's own trial-account documentation. Fix: added a payment method to convert the trial to a paid account (without ending the trial period or its 400 USD free credit balance, per the same docs). Confirmed live afterward: `COMPLETE` succeeds and `llama3.1-8b` is available in this account's region. See `docs/build-log.md` for the full diagnosis chain.
- **OQ-2 (self, non-blocking):** Will the Extended Streaming History export land before recording? Doesn't block Phase 1 either way.
- **OQ-3, resolved 2026-09-12, revised twice the same day:** first pass assumed Spotify's artist "genres" field was merely inconsistent (broken for many artists since January 2025, per Spotify's own developer community, with no fix or acknowledgment). Building the pull script surfaced something more specific: Spotify's February 2026 platform changes removed the "Get Several Artists" batch endpoint from Development Mode entirely, confirmed by a live 403 while running `pull_spotify_data.py`, so genre data for track-sourced rows (recently-played, top-tracks) isn't obtainable at all, leaving top-artists rows as the only remaining source. Then the actual data closed the question for good: a live pull against Jay's own account returned genre tags for 0 of 130 top-artists rows. Not "partial," not "sparse", empty. Final decision: `genre_tags` stays in the schema (in case Spotify fixes this later, and to document what was tried), but FR-3 no longer requires a genre view at all. The Trends tab is built around what the data actually supports: top artists, the hour-of-day heatmap, and listening streaks.
- **New, discovered 2026-09-12:** Spotify's February 2026 changes also require the Development Mode app owner to hold an active Spotify Premium subscription. Not something the app can check or work around; noted here since it's a real account-level dependency, not a code path.

## Timeline

Open-ended. No external deadline is driving this build; phasing above (Phase 1 vs. Phase 2/future) exists to keep scope honest, not to hit a date.
