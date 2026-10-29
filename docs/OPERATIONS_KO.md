# 개발·업데이트·장애 대응·GitHub 버전 관리

## 읽는 순서와 파일 역할

1. `README.md` → `AGENTS.md` → `docs/CURRENT_NAS.md`.
2. 최초 설치는 `docs/INSTALL_KO.md`, 데이터 복구는 `docs/BACKUP_RESTORE_KO.md`.
3. 활성 코드는 `app/main.py`, `app/storage.py`, `app/search_service.py`,
   `app/job_service.py`, `app/preferences.py`, `app/static/index.html`, `app/upstream/`이다.
4. 루트 `Dockerfile`, `requirements.txt`, `requirements.lock.txt`, `.dockerignore`,
   `portainer-stack.yml`, `docker-compose.yml`이 현재 빌드/설치 파일이다.
5. #032에서 구버전·중복 파일 9개를 작업 트리에서 제거했다. 필요하면 정리 전 커밋
   `2882cc597161b90458c3fa313726737735e4f4ca`에서 `git restore --source=2882cc597161b90458c3fa313726737735e4f4ca -- <파일 경로>`로 복구한다.
   현재 실행 대상이 아니며 과거 설정을 운영에 적용하지 않는다.
6. `FEATURE_COMPARISON.md`는 수정 전 감사, P0/P1/P2 문서는 단계별 기록이다.
   최신 UI 배치는 실제 index.html 및 CHANGELOG.md를 따른다.

## 수정 전·후 검사

기존 작업 파일을 먼저 확인한다. 이미 있던 수정 사항을 되돌리거나 임의 커밋하지 않는다.
음악을 수정하는 검증은 운영 `/music`가 아니라 생성 음원만 사용한다.

```powershell
git status --short
git diff --check
node tests/test_ui_save.js
node tests/test_p2_ui.js
node tests/test_gitignore.js
node tests/test_repository_readiness.js
powershell -NoProfile -ExecutionPolicy Bypass -File tests/deploy-nas.tests.ps1
```

Docker Desktop 또는 격리된 NAS 검증 폴더에서 Linux 테스트를 실행한다.
아래는 Windows Docker Desktop **Linux 컨테이너** 예시다.

```powershell
docker build -t music-tag-filler-validation:local .
docker run --rm --network none --read-only --tmpfs /tmp:rw,size=512m -e PYTHONDONTWRITEBYTECODE=1 --mount "type=bind,source=$PWD/tests,target=/app/tests,readonly" -w /app music-tag-filler-validation:local python -m unittest discover -s tests -p 'test_p*.py' -q
```

테스트 자체가 `/tmp`에 MUSIC_ROOT/DATA_ROOT를 지정한다. 운영 볼륨은 연결하지 않는다.
2026-10-21 기준 P0/P1/P2 Python 테스트는 55개다. 이후 테스트가 늘면 실제 수를 기록한다.
GitHub Actions는 Windows UI/배포/파일 검사와 Linux 이미지/격리 테스트만 수행한다.
NAS 키·접속·배포는 CI에 포함하지 않는다. GitHub 실행 성공 여부는 로컬 검사와 별도로 확인한다.

## 기존 NAS 업데이트

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -CheckOnly
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -PreflightOnly
# 아래는 실제 배포를 사용자가 요청한 경우에만 실행
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1
```

실제 배포는 로컬 JSON → 기존 정의/컨테이너 대조 → 변경 파일만 백업·SCP → 이미지 빌드 →
새 이미지 기본값 대조 → 기존 정의의 스냅샷으로 music-tag-filler만 재생성 → 설정/마운트/HTTP 확인 순서다.
Portainer 원본 정의를 수정하지 않는다. `-BuildOnly`는 복사/빌드까지만 수행한다.
전송 허용 목록은 활성 앱 파일과 Dockerfile·두 requirements·.dockerignore다.
새 모듈을 추가하면 전송 목록·Docker context·복구 문서·검증 목록도 갱신한다.

업데이트 전 진행 중인 스캔이 없는지 확인한다. 재시작 시 queued/scanning/cancelling은
interrupted로 복구되며 사용자가 이어하기를 선택해야 한다. 대기 중 HTTP/fpcalc는
제한 시간까지 기다릴 수 있다. 워커 수를 1보다 늘리면 메모리 작업 상태/잠금 가정이 깨질 수 있다.

## 장애 및 이전 버전으로 돌아가기

- SSH/Docker 권한·sudo 암호 문제: 중단하고 보고. `chmod 777`, 권한 확대, host-key 우회 금지.
- 빌드 실패: 기존 컨테이너는 보통 기존 이미지로 계속 실행한다. 소스 전송은 이미 끝났을 수 있다.
- 재생성/HTTP 실패: 자동 롤백은 하지 않는다. 이미지 ID·마운트·환경·로그를 먼저 확인한다.
- 이전 이미지 tar가 있으면 `docker image load -i <보관파일>`로 기존 태그를 복구할 수 있다.
  이어서 기존 스택 정의로 music-tag-filler만 재생성한다. 다른 서비스나 볼륨은 삭제하지 않는다.
- 코드로 롤백할 때는 별도 작업 폴더에 승인한 태그/커밋을 checkout하여 검증한 뒤 배포한다.
  현재 수정 사항을 `reset --hard`로 지우지 않는다. 옛 버전이 현 data 형식을 지원하는지도 확인한다.
- `job_store_error`가 있으면 기존 jobs.json을 별도 보존하고 검증된 백업을 복구한다.
  오류를 숨기기 위해 빈 jobs.json으로 덮어쓰거나 백업 무결성 검사를 제거하지 않는다.

```powershell
Invoke-RestMethod http://192.168.0.100:8000/api/diagnostics
ssh -i C:\Users\homes\.ssh\codex_nas -o BatchMode=yes hitmyhead@192.168.0.100 "docker logs --tail 100 music-tag-filler"
```

로그와 inspect 파일에는 파일명/환경값이 있을 수 있으므로 GitHub 이슈나 로그 아티팩트에 그대로 올리지 않는다.

## GitHub 버전 관리 규칙

저장소 `https://github.com/SoonCheol/music-tag-filler-nas`는 비공개로 유지한다.
아직 원격 연결·commit·push가 없다면 사용자의 별도 요청 뒤 진행한다. 기존 Git 기록은 유지한다.
`git init`, 강제 push, 기록 재작성, 기존 커밋 amend, 태그 재지정은 요청 없이 수행하지 않는다.

1. `git status`, 파일/비밀값 검사, diff, 관련 테스트를 통과시킨다.
2. 사용자가 commit을 요청한 뒤 검토한 파일만 명시적으로 stage한다. `git add -f`는 사용하지 않는다.
3. 커밋에는 동작 변경·검증을 설명하고 CHANGELOG의 Unreleased를 갱신한다.
4. 실제 배포한 커밋과 이미지 ID·테스트 결과를 릴리스 기록에 남긴다. 필요하면 승인받은
   `v6.X.Y` 태그를 만든다. 빌드 이미지 태그 `:v6`만으로 과거 버전을 식별하지 않는다.
5. push는 사용자가 요청한 원격/브랜치에만 수행한다. 비공개 여부와 인증 계정을 먼저 확인한다.
6. 저장소 외부에도 별도의 Git 백업을 유지한다. commit된 모든 참조는 `git bundle create <외부경로>.bundle --all`로
   보관할 수 있다. 미커밋 변경·음악·data·GitHub 이슈·계정 인증은 bundle에 들어가지 않는다.

GitHub의 [저장소 복제 안내](https://docs.github.com/en/repositories/creating-and-managing-repositories/duplicating-a-repository)는
추가 Git 사본을 만드는 근거다. `push --mirror`는 참조 삭제/덮어쓰기까지 전파하므로 일반 업데이트에 사용하지 않는다.

## 재현성 및 라이선스

의존성 업데이트는 `requirements.txt`와 잠금 파일을 함께 검토하고 전체 회귀를 실행한다.
31개 잠금은 현재 Linux/Python 3.11 환경 스냅샷이지 무기한 보안 업데이트 보장이 아니다.
기반 이미지·Debian 패키지까지 같은 바이트가 필요하면 이미지 tar도 별도 백업한다.
원본 MIT 고지와 패키지 라이선스는 [THIRD_PARTY_NOTICES.md](../THIRD_PARTY_NOTICES.md)를 유지한다.

## 음악 쓰기 모드 변경 — 2026-10-21

사용자 요청 및 격리된 NAS 음원 검증 후 현재 운영 음악 마운트는 `/music:rw`이다.
로컬 배포 설정의 `MusicReadOnly`는 JSON boolean `false`로 맞춘다. 문자열은 허용하지 않는다.
항목이 없는 이전 설정은 true로 처리되며 실제 모드가 다르면 배포를 중단한다.
배포는 마운트 모드를 자동 변경하지 않고 현재 승인된 설정만 보존한다.
기존 문서의 ro 설명은 전환 이전 기록이며 [전환 검증](RW_MOUNT_VALIDATION.md)을 따른다.
