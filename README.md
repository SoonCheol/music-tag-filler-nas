# Music Tag Filler NAS v2.0.0

음악 검색·후보 적용·태그/커버/가사 처리와 무결성 백업을 제공하는 NAS 웹 앱입니다.
이 비공개 저장소는 소스·설치 방법·운영 기록을 보관합니다.
**음악, 프로그램 data, API 키, SSH 개인키는 별도 백업해야 합니다.**

[v2.0.0 검증·배포 기록](docs/RELEASE_V2_0_0.md)

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
`search_service.py`는 검색/커버, `job_service.py`는 탐색/이어하기,
`preferences.py`는 설정/임시 커버, `app/static/index.html`은 웹 화면입니다.
원본의 MIT 코드는 `app/upstream/`에 있습니다.

현재 설치에는 루트 `Dockerfile`, `requirements.txt`, `requirements.lock.txt`,
`portainer-stack.yml`, `docker-compose.yml`을 사용합니다.
`*_1`, `*_new`, `main_new.py`, `README_1.md`는 역사적 대안이며 운영에 적용하지 않습니다.

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
