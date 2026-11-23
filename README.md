# Music Tag Filler NAS v2.0.0

음악 검색·후보 적용·태그/커버/가사 처리와 무결성 백업을 제공하는 NAS 웹 앱입니다.
이 비공개 저장소는 소스·설치 방법·운영 기록을 보관합니다.
**음악, 프로그램 data, API 키, SSH 개인키는 별도 백업해야 합니다.**

[v2.0.0 검증·배포 기록](docs/RELEASE_V2_0_0.md)

## #009 Music Assistant 검색 및 식별자 편집 (NAS 배포 전)

상단 **검색 대상**을 `MA 검색`으로 전환하고 제목·가수·앨범 가수·파일명 검색을 요청합니다. MA가 반환한 filesystem provider mapping을 실제 `/music` 파일로 확인한 결과만 기존 목록과 한 곡 태그 편집기로 연결합니다. 개별 곡은 기존 후보 재검색·수정·현재 곡 저장을 사용하며 검색 자체로는 파일이 변경되지 않습니다. MA 라이브러리 검색의 서버 측 색인 범위에 따라 파일명·앨범 가수 검색 결과가 누락될 수 있습니다.

서버 컨테이너에서 다음 **환경변수**가 필요합니다. 실제 토큰을 GitHub나 웹 브라우저에 입력·저장하지 마세요.

- `MA_API_URL`: 내부에서 접속 가능한 MA 서버 URL (예: `http://music-assistant:8095` — 실제 네트워크에 맞게 설정)
- `MA_API_TOKEN`: MA에서 발급한 장기 Bearer 토큰

설정이 없으면 `/api/ma/search`는 HTTP 503을 반환하며 기존 폴더 검색은 계속 작동합니다. 운영 Portainer 스택의 설정은 배포 전에 별도로 확인합니다. 외부에서 확인되지 않은 원격 MA 항목, 경로가 일치하지 않는 음악, 지원하지 않는 파일 형식은 편집 목록에 추가하지 않습니다.

식별자 편집을 펼치면 실제 파일에서 읽은 MusicBrainz Artist ID와 Album Artist ID를 볼 수 있으며 MusicBrainz 검색 결과를 선택하거나 UUID를 입력할 수 있습니다. 기존 ID를 교체하려면 저장 옵션의 `빈 태그만 채우기`를 해제해야 합니다. ID는 현재 곡에만 적용됩니다.

## #010 NAS 공통 웹 업데이트 (코드 구현, 별도 설치 필요)

상단 **업데이트** 메뉴에서 실제 Portainer 이미지와 검증된 최신 GHCR 빌드를 비교하고, 관리자가 **직접 업데이트를 승인**할 수 있도록 UI와 별도 NAS Update Agent를 구현했습니다. 한 Agent로 다른 NAS 앱도 앱별 설정을 추가해 재사용할 수 있습니다. 운영 앱에 Portainer/ GitHub 관리자 키나 Docker 권한을 부여하지 않으며, 기존 스택의 이미지 외 설정을 보존합니다. **Agent 설치·비공개 레지스트리 인증·NAS 배포와 실기 검증은 별도**입니다. [설치 및 보안 안내](docs/NAS_UPDATER_KO.md)를 참고하세요.

## v2.0.0 음악 미리듣기

파일 행의 재생 버튼으로 한 곡씩 듣고, 파일명 열 제목 앞의 공통 버튼으로 일시정지·이어서 재생합니다. 재생 파일이 목록에 없어도 공통 버튼으로 제어할 수 있습니다. 파일 선택·태그 편집과 독립적으로 동작하며 읽기 전용 Range 스트리밍으로 원본 음악을 변경하지 않습니다. MP3와 브라우저가 지원하는 FLAC·M4A·OGG를 지원합니다.

## 다시 설치하거나 AI에게 인계할 때

| 문서 | 내용 |
| --- | --- |
| [AGENTS.md](AGENTS.md) | 향후 Codex/AI의 개발·테스트·배포·Git 규칙 |
| [현재 NAS](docs/CURRENT_NAS.md) | 실제 IP·계정·경로·환경·마운트·이미지 조사값 |
| [신규 설치](docs/INSTALL_KO.md) | GitHub clone부터 Windows/새 NAS/Portainer 설치까지 |
| [업데이트·버전 관리](docs/OPERATIONS_KO.md) | 테스트·자동 배포·장애 대응·릴리스 절차 |
| [백업·복구](docs/BACKUP_RESTORE_KO.md) | data·설정·이미지·음악·키의 별도 백업 및 복원 |
| [DEPLOYMENT.md](DEPLOYMENT.md) | 배포 스크립트의 모드와 보존 검사 |
| [변경 기록](CHANGELOG.md) | Unreleased와 기존 P0/P1/P2·UI 이력 |
| [라이선스](THIRD_PARTY_NOTICES.md) | 원본 MIT와 Chromaprint/FFmpeg 고지 |
| [준비 검증 결과](docs/READINESS_REPORT.md) | 누락·보안·테스트·실행하지 않은 항목 |
| [보안 검사](docs/SECURITY_AUDIT_KO.md) | 비밀값 검사·기존 의존성 보안 공지와 후속 작업 |
| [과거 v1.0.0 등록 준비](docs/RELEASE_V1_0_0.md) | 운영 재점검·릴리스 문안·등록 전 남은 절차 |

## 활성 파일

`app/main.py`는 FastAPI, `storage.py`는 저장·백업·복원,
`lyrics_service.py`는 가사 조회/캐시/토큰, `search_service.py`는 검색/커버, `job_service.py`는 탐색/이어하기,
`preferences.py`는 설정/임시 커버, `app/static/index.html`은 웹 화면입니다.
원본의 MIT 코드는 `app/upstream/`에 있습니다.

현재 설치에는 루트 `Dockerfile`, `requirements.txt`, `requirements.lock.txt`,
`portainer-stack.yml`, `docker-compose.yml`을 사용합니다.
구버전·중복 파일 9개는 #032 정리로 작업 트리에서 제거했습니다. 필요하면 정리 전 커밋 `2882cc597161b90458c3fa313726737735e4f4ca`에서 `git restore --source=2882cc597161b90458c3fa313726737735e4f4ca -- <파일 경로>`로 복구할 수 있습니다. 현재 실행·빌드·배포에는 사용하지 않습니다.

## 기존 NAS 업데이트 명령

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -CheckOnly
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1 -PreflightOnly
# 실제 배포를 요청받은 경우에만:
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy-nas.ps1
```

주소·키 경로 등은 Git에서 제외되는 `deploy-nas.local.json`에서 읽습니다.
새 PC에서는 `deploy-nas.example.json`을 복사하여 현재 NAS 문서의 값으로 채웁니다.
신규 설치에는 먼저 컨테이너/스택을 만들어야 하므로 설치 문서를 따릅니다.

운영 음악은 사용자 요청으로 **`/music:rw`**로 전환했습니다. 실제 저장·이름 변경·되돌리기가
가능하므로 원본 백업을 유지합니다. 검증 결과는 [쓰기 마운트 검증](docs/RW_MOUNT_VALIDATION.md)을 참고하며 테스트는 격리된 생성 음원만 사용합니다.

과거 정식 이름 이전과 초기 GitHub 등록 기록은 [v1.0.0 등록 상태](docs/V1_REGISTRATION_STATUS.md)를
따릅니다. push 완료를 확인하기 전에는 GitHub만으로 최신 작업을 복구할 수 없습니다.

## 기능과 지원 형식

태그 읽기·쓰기는 MP3, FLAC, M4A, OGG(Vorbis)를 지원합니다 (`app/upstream/tags.py`의 `FORMATS`). WAV·WMA·Opus 등은 지원 목록에 포함되지 않습니다. 브라우저 미리듣기는 브라우저의 코덱 지원에 따릅니다.

- 폴더/하위 폴더 스캔, 진행 상태·취소·해시 기반 이어하기, 후보 비교 및 선택.
- 제목·가수·앨범·앨범 가수·연도·트랙·장르의 선택 저장, 빈 태그만 채우기.
- 후보/업로드 커버, 검색·직접 입력 가사, 선택적 시간 가사와 LRC.
- 파일명 직접 변경, 최초 원본 전체 바이트 백업·무결성 검사·원본 복원.

텍스트 검색은 파일의 기존 태그와 파일명에서 검색어를 만들고 후보를 점수화합니다. 기본 **통합 검색**은 iTunes와 MusicBrainz를 병렬 조회합니다. iTunes만/MusicBrainz만 모드도 있으며, **빠른 검색**은 iTunes 결과가 자동 선택 기준에 못 미칠 때 MusicBrainz를 추가합니다. 국가 기본값은 KR입니다. 음향 지문은 기본 비활성이며 선택 시 AcoustID 키와 fpcalc가 필요합니다. 커버·가사는 별도 조회 경로와 캐시를 사용합니다. 검색 결과만으로 음악에 태그를 쓰지 않으며 사용자가 저장 대상을 확인해야 합니다.

## 설치 요구사항과 격리된 Compose 설치

Windows 개발 도구는 Git·PowerShell 5.1 이상·OpenSSH이며, JS 검사는 Node.js를 사용합니다. 배포 대상은 Docker/Compose가 설치된 NAS입니다. 기존 UGREEN NAS 운영값은 현재 NAS 문서를 참고하고, 새 장비의 CPU/권한 호환성은 별도로 확인합니다. Dockerfile은 Python 3.11, FFmpeg, Chromaprint(fpcalc)와 고정 Python 의존성/제약 파일을 사용하며 Uvicorn **단일 worker**, 포트 8000으로 실행합니다. 이미지 다운로드·빌드·외부 검색에는 인터넷이 필요합니다.

아래는 **기존 스택이 없는 별도 테스트 설치**입니다. 운영 음악·data를 연결하지 않습니다. `.env.example`은 환경변수 설명용이며 기존 운영 Compose가 자동으로 적용하는 파일이 아닙니다.

```sh
# clone한 소스 루트에서, NAS/Linux Docker 호스트에서 실행
mkdir -p install-example/music install-example/data
docker build -t music-tag-filler-nas:example .
docker compose -p music-tag-filler-example -f compose.example.yml config
docker compose -p music-tag-filler-example -f compose.example.yml up -d --no-build --pull never
```

이 예시는 새 `install-example` 폴더와 호스트 포트 **18000**을 사용합니다. 테스트할 때는 생성 음원/폐기 가능한 사본만 `install-example/music`에 넣습니다. 웹 UI는 `http://<Docker호스트>:18000`입니다. 방화벽·접근 제어는 설치 환경에 맞춰 준비합니다. 기존 NAS는 **8000** 포트를 사용하며 [실제 설치 절차](docs/INSTALL_KO.md)를 따릅니다. 예시 YAML로 기존 Portainer 스택을 덮어쓰지 않습니다.

## 환경변수와 초기 설정

| 변수 | 기본값/역할 |
| --- | --- |
| `MUSIC_ROOT` | `/music`, 컨테이너 내부 음악 경로 |
| `DATA_ROOT` | `/data`, 지속 보관할 설정·작업·원본 백업 경로 |
| `TZ` | 운영 Compose는 `Asia/Seoul` 지정 |
| `SEARCH_COUNTRY` | 미지정 시 settings의 country, 없으면 KR |
| `ACOUSTID_API_KEY` | 선택 사항. 미지정 시 settings, 그다음 `/data/acoustid_key.txt` |
| `FPCALC_PATH` | 선택 사항. 미지정 시 settings의 fpcalc_path와 제공처의 실행 파일 탐색 사용 |

UI에서 국가·저장 필드·빈 태그만 채우기·커버/가사 옵션을 확인한 뒤 폴더를 선택합니다. 설치 상태는 `/api/diagnostics`, `/api/capabilities`, `/api/preferences`로 확인할 수 있습니다. UI/API 확인만으로 운영 스캔이나 저장을 실행할 필요는 없습니다. `settings.json`과 키 파일은 Git에 넣지 않습니다. 호스트 경로는 볼륨의 source이며 위 환경변수는 컨테이너 내부 경로입니다.

## 업데이트·백업·복구·오류 해결

기존 설치 업데이트는 [운영 절차](docs/OPERATIONS_KO.md)와 [배포 스크립트](DEPLOYMENT.md)를 따릅니다. 먼저 진행 중 작업과 data 형식 호환성을 확인하고 코드·이미지·data 백업을 확보합니다. 실제 배포를 요청받았을 때만 기존 배포 스크립트를 실행합니다. 이전 이미지와 스택 정의를 보존하며 자동 롤백은 수행하지 않습니다.

[백업·복구 문서](docs/BACKUP_RESTORE_KO.md)에 따라 `/data` 전체(작업별 `jobs/*.json`, `jobs_legacy.json`, settings, backups, renames, lyric-assets 포함), 음악과 sidecar, 로컬 배포 설정·키, Docker 이미지를 별도로 보관합니다. GitHub에는 소스만 있으며 음악·작업·설정·키는 복원할 수 없습니다. 복구는 빈 별도 경로에서 checksum/JSON/원본 manifest를 확인한 뒤 수행합니다. 기존 데이터나 볼륨을 삭제하는 초기화 명령을 사용하지 않습니다.

| 증상 | 확인할 내용 |
| --- | --- |
| UI 접속 불가 | 컨테이너 상태, 호스트 포트 충돌/방화벽, 포트 매핑. 예시 18000과 운영 8000 구분 |
| 음악 목록이 비어 있음 | 실제 호스트 음악 경로, `/music` 마운트, 지원 확장자, 읽기 권한 |
| 저장 불가 | 음악 볼륨 쓰기 권한·여유 공간·리비전/백업 오류. 검사 우회나 광범위 권한 변경 금지 |
| 검색 대기/빈 결과 | 인터넷·제공처 제한·검색어·국가 확인. 대량 강제 재시도 금지 |
| 지문 검색 불가 | capabilities의 키 설정 여부와 fpcalc 가용성 확인. 키 없이 텍스트 검색 가능 |
| 시작 시 작업 기록 오류 | 손상 JSON·legacy 전환 충돌·진행 작업 확인. 작업 JSON을 지우거나 빈 파일로 덮어쓰지 않음 |
| 재시작 후 가사/커버 선택 소실 | 메모리 캐시·토큰·보류 업로드는 재조회/재선택. 미저장 UI 편집은 영구 초안이 아님 |

## 주요 폴더와 AI 진입점

```text
app/main.py             FastAPI API·공유 상태·저장 오케스트레이션
app/request_models.py   API 입력 모델
app/scan_service.py     스캔 실행·병렬 검색·진행 상태
app/job_service.py      파일 수집·작업 상태·이어하기 판단
app/job_store.py        작업별 JSON의 원자적 저장·legacy 보관
app/search_service.py   검색 제공처 조합·후보·커버
app/lyrics_service.py   가사 캐시·중복 요청·검증 토큰
app/storage.py          태그 저장·최초 백업·무결성·복원
app/rename_service.py   덮어쓰기 없는 이름 변경·복구 기록
app/lyric_assets.py     LRC 기록·복구
app/preferences.py     설정·임시 커버
app/upstream/           제공처·네트워크 캐시·태그 처리 및 원본 고지
app/static/             HTML·CSS·기능별 JavaScript
tests/                 격리된 생성 데이터 검사
tools/                 개발용 점검 도구
docs/                  설치·운영·복구·구조·검증 기록
```

다른 AI는 이 README → [AGENTS.md](AGENTS.md) → 작업에 해당하는 설치/운영/구조 문서 순서로 읽습니다. 과거 검증·배포 기록은 현재 커밋의 재검증 결과를 의미하지 않습니다. 최신 업로드 범위와 미검증 사항은 [#028 인계 기록](docs/GITHUB_HANDOFF_028.md)을 참고합니다.
