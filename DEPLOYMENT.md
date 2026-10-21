# NAS deployment

한글 설치·운영·복구의 시작점은 [README.md](README.md)이며,
실제 현 NAS 값은 [docs/CURRENT_NAS.md](docs/CURRENT_NAS.md)에 있다.

Use Windows PowerShell 5.1 or newer. Machine-specific settings belong in
`deploy-nas.local.json`, which is ignored by Git. The existing machine's settings
have been preserved there; no key contents or passwords belong in the file.
The script keeps legacy SCP (`scp -O`) and the existing Docker deployment flow.

On another machine, copy the example and replace every environment placeholder:

```powershell
Copy-Item .\deploy-nas.example.json .\deploy-nas.local.json
```

`NasTarget` is the SSH account/host; `SshKey` is an existing private-key path
(`%USERPROFILE%` is expanded); `RemoteRoot` is the NAS project directory.
`Image`, `Container`, `PortainerStackFile`, and `WebBaseUrl` must match the existing
deployment. The example host is deliberately nonresolving. The script validates
all values before invoking SSH. It never executes configuration as PowerShell.
Use `-ConfigFile <absolute-path>` for an alternative private JSON file; keep it
outside Git or name it `*.local.json`. Do not commit local settings with `git add -f`.

```powershell
# Full deployment: compare, back up, upload, build, recreate v6, verify
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1

# Upload/build only; leave the running container unchanged
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -BuildOnly

# Local checks only; no SSH
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -CheckOnly

# Read-only NAS validation; no upload, build, or recreation
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -PreflightOnly
```

The policy override applies only to that process. Saved execution policies are
unchanged. SSH host keys must already be trusted. `-Redeploy` remains supported
for older invocations; full deployment is now the default.

## Preserve the existing stack

The script reads the confirmed existing definition from
`portainer:/data/compose/STACK_ID/docker-compose.yml` through the authorized Docker
connection. It never modifies Portainer's original definition or requires sudo.
If the stack is recreated in Portainer and its ID changes, update
`PortainerStackFile` in the local JSON or provide a readable NAS
`-RemoteComposeFile` override.

Compose-version differences make configuration hashes unreliable on this NAS.
Semantic validation instead compares volumes/read-only flags, environment,
image defaults, ports, restart policy, and network against the running container.
Unsupported custom service settings or host overrides stop deployment for review.
New image defaults are also checked before recreation.

A private definition snapshot is saved under the project's `deploy-backups/`.
Compose uses the existing project/service name and
`up -d --no-deps --no-build --pull never --force-recreate music-tag-filler-v6`.
Only v6 is recreated. No stack removal, volume deletion, or other-service restart
occurs. The repository's writable-music Compose definition is never used.

## Files, checks, and failures

The explicit upload allowlist covers active app modules/HTML, pinned upstream
modules/license/notice, `Dockerfile`, `requirements.txt`, `requirements.lock.txt`,
and `.dockerignore`. These build inputs are backed up/hashed like app changes.
SHA256 comparison skips unchanged files. Existing originals are backed up before
upload; new modules are copied only when absent or changed. Each upload is verified.
The successful SCP/build commands remain unchanged. Other source files and
dependency changes require a deployment allowlist review.

After recreation, checks cover image ID, running state, preserved mounts/settings,
HTTP page, and folder-list API. No scans or music saves are initiated. Application
startup can update its normal `/data` job state.

Errors stop execution; earlier uploads/builds are not automatically undone.
Recreation or health-check failures need inspection; no automatic rollback occurs.
If credentials or Docker permissions are insufficient, report the requirement
instead of changing privileges. Avoid concurrent manual Portainer redeployments.

NAS read-only preflight, Compose dry-run, actual v6 recreation, and final HTTP/API
health checks have passed. The P0 deployment and isolated generated-audio storage
tests are recorded in `P0_VALIDATION.md`.

P1/P2 results and remaining limitations are in `P1_VALIDATION.md` and
`P2_VALIDATION.md`. The upload allowlist includes search orchestration, scan/resume,
preferences, and the pinned upstream modules. Runtime settings remain in the
existing data mount; deployment does not rewrite them.

Local safety tests (no network or Docker operations):

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\tests\deploy-nas.tests.ps1
node .\tests\test_gitignore.js
```

## GitHub upload boundary

`.gitignore` excludes local deployment JSON, credentials/key files, runtime
settings/job data, music, backups, and local archives. It does not scan file
contents and cannot remove already tracked files or older commits. Review
`git status --short`, `git diff`, and the intended file list before staging.
Never force-add ignored files or paste real secrets into source/examples.

By explicit owner request, `docs/CURRENT_NAS.md` and the current Stack/Compose
files record real nonsecret operating addresses/paths for private-repository
recovery. Local deployment JSON, passwords, key contents, API keys, music and
runtime data remain excluded. The existing original Git commit also contains
old NAS paths and personal domains.
History has deliberately not been rewritten: pushing the retained history also
uploads that older metadata, even after the current files are sanitized. This is
not a guarantee that every historical version is free of personal information.

## 음악 쓰기 모드 변경 — 2026-10-21

사용자 요청 및 격리된 NAS 음원 검증 후 현재 운영 음악 마운트는 `/music:rw`이다.
로컬 배포 설정의 `MusicReadOnly`는 JSON boolean `false`로 맞춘다. 문자열은 허용하지 않는다.
항목이 없는 이전 설정은 true로 처리되며 실제 모드가 다르면 배포를 중단한다.
배포는 마운트 모드를 자동 변경하지 않고 현재 승인된 설정만 보존한다.
기존 문서의 ro 설명은 전환 이전 기록이며 [전환 검증](docs/RW_MOUNT_VALIDATION.md)을 따른다.