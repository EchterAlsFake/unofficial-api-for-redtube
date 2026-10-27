# Changelog

## 1.4.4 — 2026-10-27

- Accept bare video and playlist IDs and normalize profile routes to the paths the site supports.
- Return real thumbnail URLs instead of lazy-loading placeholders or raw srcset strings.
- Handle German, French, Spanish and Italian statistics and playlist counts more reliably.
- Load optional uploader and performer fields lazily and remove duplicate performer entries.
- Accept the supported user-playlist JSON shapes and resolve playlists without requiring a loaded display name.
- Export Amateur and User and support async client context management.
- Use the published `eaf-base-api>=4.2.5` dependency.

