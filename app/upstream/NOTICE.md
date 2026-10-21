# Upstream provenance

Source: https://github.com/microhan1/music-tag-filler

Commit: `8996e2daa74c787395ebbf3f9d871b1484f4aafe` (2026-10-15).

Vendored `tags.py`, `match.py`, `net.py`, `search_lyrics.py`, `search_itunes.py`,
`search_mb.py`, `search_acoustid.py`, and `pipeline.py` under the upstream MIT license.
Imports were adapted to this package. AcoustID executable/key discovery uses NAS
configuration rather than desktop bundles. Pipeline preference typing and error
logging no longer depend on desktop modules. Search algorithms remain upstream.
NAS orchestration, stricter auto-selection, image validation/cache, transactional
storage, backup integrity, and read-only protections live outside these files.

NAS tag writing adds an optional text-field mask so unchanged fields/identifiers
are preserved when committing a partial edit. Default upstream callers retain
the full-field behavior.
