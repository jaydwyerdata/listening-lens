# Listening Lens

Repo-specific context for Claude Code. General rules come from the user-level CLAUDE.md on this machine; this file only adds what is unique to this project. It may be published, so it must stand alone and follow every public-repo rule (no employer detail, no career framing, no private repo references).

## Purpose

A Snowflake Native App that turns a personal Spotify listening history into a Streamlit dashboard, with a short AI-generated taste summary from Snowflake Cortex.

## Layout

- `app/` : manifest, setup script, and the in-app README shown to a consumer on install
- `streamlit/` : the Streamlit-in-Snowflake app code (Trends and Discover tabs)
- `scripts/` : one-time account bootstrap, Cortex grant, and Spotify data pull/parse scripts
- `docs/` : README-linked design docs (`adr/`, requirements, solution design, build log)
- `demo-assets/` : gitignored demo prep

## Project specifics

- Listening history is the author's own real Spotify data, not a synthetic or fictional dataset. It is pulled via the Spotify Web API or parsed from a Spotify Extended Streaming History export; see `docs/requirements.md` for why it is not committed to the repo.
- Installing and upgrading the app requires the `snow` CLI (Native App deployment has no Snowsight-only path). This is a stated exception to the usual no-CLI rule, decided for Native App repos generally; see `docs/adr/0001-architecture.md`.
- Requires a Snowflake Enterprise-edition trial account in a region with direct Cortex model support.

## Status

See `docs/build-log.md` and the README Status section.
