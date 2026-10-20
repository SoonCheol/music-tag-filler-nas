# Repository Guidelines

## Project Structure & Module Organization

- `app/main.py` is the active FastAPI backend: metadata searches, Mutagen tag operations, and background scan jobs.
- `app/static/index.html` is the active frontend, containing HTML, CSS, and JavaScript. Preserve its existing layout unless a UI redesign is explicitly requested.
- `main_1.py`, `main_new.py`, and corresponding HTML variants are separate implementations; do not assume they are active or synchronize them automatically.
- `Dockerfile`, `docker-compose.yml`, and `portainer-stack.yml` define container deployment. Files ending in `_1` are alternate copies.
- Runtime state belongs under `DATA_ROOT` (`jobs.json` and `backups/`); music belongs under `MUSIC_ROOT`. No test directory currently exists.

## Build, Test, and Development Commands

- `python -m pip install -r requirements.txt` installs the pinned Python dependencies.
- For local PowerShell development, set writable scratch paths before starting:
  ```powershell
  $env:MUSIC_ROOT="$PWD/scratch/music"
  $env:DATA_ROOT="$PWD/scratch/data"
  python -m uvicorn app.main:app --reload --port 8000
  ```
  Create the scratch music directory first and use copied audio files. Server imports create data directories.
- `docker compose up -d --build` builds and starts the service. Review NAS volume mappings first: the configured music mount permits writes.
- `docker compose logs -f` follows service logs.

## Coding Style & Naming Conventions

Use four-space indentation and `snake_case` for Python functions and variables. Preserve existing JavaScript `camelCase` names and DOM IDs. Keep API routes under `/api/` and align request fields with Pydantic models. No formatter or linter configuration is included; avoid unrelated formatting changes.

## Testing Guidelines

No automated test framework or coverage threshold is configured. Validate changes with disposable audio copies: scan, cancel/resume, reload job history, and save selected files. Check tag values after saving and verify the existing frontend layout at desktop and narrow widths. If adding automated tests, use `tests/test_<feature>.py` and document the runner. Never test writes against the production library.

## Commit & Pull Request Guidelines

This checkout has no Git metadata, so existing commit conventions cannot be verified. Use short, imperative commit subjects. Pull requests should describe the behavior change, affected active files, validation performed, and relevant issues. Include screenshots for visible UI changes. Distinguish implemented behavior from placeholders: fingerprint lookup and actual backup restoration are currently incomplete.
